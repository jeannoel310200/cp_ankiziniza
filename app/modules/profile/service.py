import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.security import create_access_token
from app.core.storage import get_storage
from app.modules.bonus.service import BonusReason, BonusService
from app.modules.profile.model import NAME_CHANGE_COOLDOWN, Profile
from app.modules.profile.repository import ProfileRepository
from app.modules.profile.schema import UpdateProfile, UpdateProfileResponse, UpdateUserMail
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.modules.users.schema import ValidateCode
from app.modules.users.service import UserService

_NAME_CHANGE_COOLDOWN_DAYS = NAME_CHANGE_COOLDOWN.days
_PICTURE_PROFILE_CHANGE_COOLDOWN_DAYS = 7
# Aligné sur le délai du parcours jumeau /users/update_user_email.
_EMAIL_CHANGE_COOLDOWN_DAYS = 30
# Préfixe URL public des photos de profil (route interne de l'API qui sert le
# contenu depuis le stockage configuré).
_AVATAR_URL_PREFIX = "/api/uploads/avatar"
_BASE_URL = get_settings().base_url


def _storage():
    return get_storage()


class ProfileService:
    def __init__(
        self,
        repo: ProfileRepository,
        user_service:UserService,
        user_repo:UserRepository,
        bonus: BonusService,
    ):
        self.repo = repo 
        self.user_service = user_service
        self.user_repo = user_repo
        self.bonus = bonus


    async def update_profile(
            self,
            current_user: User,
            payload: UpdateProfile,
            picture: UploadFile | None,
        ):
        profile = await self.repo.get_by_id(current_user.id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found",
            )

        if payload.first_name is not None:
            await self.update_first_name(current_user, profile, payload.first_name)

        if payload.last_name is not None:
            await self.update_last_name(current_user, profile, payload.last_name)

        if picture is not None:
            await self.update_profile_picture(profile, picture)

        profile = await self.repo.get_by_id(profile.user_id)
        return await self._to_response(current_user.id, profile)

    async def _to_response(self, user_id, profile: Profile | None) -> UpdateProfileResponse:
        user = await self.user_repo.get_by_id(user_id)
        return UpdateProfileResponse(
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
            profile_pictures=profile.profile_pictures if profile else None,
        )

    # first_name et last_name sont éditables (et soumis au cooldown de
    # NAME_CHANGE_COOLDOWN) indépendamment l'un de l'autre : d'où les deux
    # méthodes quasi identiques ci-dessous plutôt qu'une seule sur full_name.
    async def update_first_name(self, current_user: User, profile: Profile, first_name: str) -> None:
        update_date = await self.repo.get_first_name_date(current_user.id)
        now = datetime.now(UTC)

        if update_date is not None:
            # SQLite (tests) ne conserve pas le fuseau, contrairement à
            # Postgres : sans normaliser, la soustraction lève TypeError.
            if update_date.tzinfo is None:
                update_date = update_date.replace(tzinfo=UTC)
            diff = now - update_date
            if diff.days < _NAME_CHANGE_COOLDOWN_DAYS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You can edit your first name in {_NAME_CHANGE_COOLDOWN_DAYS - diff.days} days",
                )
        blue_badge = await self.repo.verify_blue_badge(current_user.id)
        if blue_badge is True:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail="""You cannot change your name because
                your account is already verified."""
            )
        user = await self.user_repo.get_by_id(current_user.id)
        if user:
            await self.user_repo.update(user, {"first_name": first_name})
        await self.repo.update(profile, {"updated_first_name_date": now})
        await self.bonus.award_bonus(current_user.id, BonusReason.update_profile_first_name)

    async def update_last_name(self, current_user: User, profile: Profile, last_name: str) -> None:
        update_date = await self.repo.get_last_name_date(current_user.id)
        now = datetime.now(UTC)

        if update_date is not None:
            if update_date.tzinfo is None:
                update_date = update_date.replace(tzinfo=UTC)
            diff = now - update_date
            if diff.days < _NAME_CHANGE_COOLDOWN_DAYS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You can edit your last name in {_NAME_CHANGE_COOLDOWN_DAYS - diff.days} days",
                )
        blue_badge = await self.repo.verify_blue_badge(current_user.id)
        if blue_badge is True:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail="""You cannot change your name because
                your account is already verified."""
            )
        user = await self.user_repo.get_by_id(current_user.id)
        if user:
            await self.user_repo.update(user, {"last_name": last_name})
        await self.repo.update(profile, {"updated_last_name_date": now})
        await self.bonus.award_bonus(current_user.id, BonusReason.update_profile_last_name)

    async def update_profile_picture(self, profile:Profile, picture: UploadFile):
        ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
        extension = picture.filename.split(".")[-1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Unauthorized format")

        file_name = f"{uuid.uuid4()}.{extension}"
        content = await picture.read()

        storage = _storage()
        storage_key = f"uploads/avatar/{profile.user_id}/{file_name}"
        await storage.save_bytes(storage_key, content, picture.content_type or "image/png")

        base_url = _BASE_URL
        # L'URL est servie par la route interne `/api/uploads/avatar/...` qui
        # lit le contenu depuis le stockage configuré (disque local en
        # développement, RustFS S3 en production).
        url = f"{base_url}{_AVATAR_URL_PREFIX}/{profile.user_id}/{file_name}"

        now = datetime.now(UTC)

        update_date = await self.repo.get_picture_profile_date(profile.user_id)

        if update_date is None or (
            now - update_date).days >= _PICTURE_PROFILE_CHANGE_COOLDOWN_DAYS:
            await self.bonus.award_bonus(
                profile.user_id,
                BonusReason.update_profile_picture,
            )
        picture_profile = await self.repo.update(
            profile,
            {
            "profile_pictures": url,
            "updated_picture_profile_date": now,
        },
        )
        # `profiles.profile_pictures` et `users.avatar_url` sont deux colonnes
        # distinctes : les clients (mobile, recherche, statut public) lisent
        # `avatar_url`. Sans cette synchro, la photo est bien enregistrée mais
        # jamais visible.
        await self._sync_user_avatar(profile.user_id, url)

        return picture_profile

    async def _sync_user_avatar(self, user_id, url: str | None):
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return
        # À la suppression (url=None), ne vider que si la valeur actuelle
        # désigne un fichier que nous hébergeons. Un compte Google/Facebook
        # porte l'URL du fournisseur (cf. google_auth/service.py), qu'aucune
        # reconnexion ne réécrit : l'effacer la perdrait définitivement.
        if url is None and not self._is_self_hosted_avatar(user.avatar_url):
            return
        await self.user_repo.update(user, {"avatar_url": url})

    @staticmethod
    def _is_self_hosted_avatar(url: str | None) -> bool:
        # `uploads/picture` couvre les enregistrements antérieurs au
        # déplacement des avatars vers `uploads/avatar`.
        return bool(url) and (_AVATAR_URL_PREFIX in url or "uploads/picture" in url)
        

    async def delete_profile_picture(self,current_user: User):
        profile = await self.repo.get_by_id(current_user.id)
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    
        # Aucune suppression d'objet, ni en local ni dans RustFS : le bucket
        # est versionné, l'ancien avatar reste disponible dans l'historique.
        # On ne fait que détacher la référence dans la base.

        updated = await self.repo.update(profile, {"profile_pictures": None})
        await self._sync_user_avatar(profile.user_id, None)
        return await self._to_response(current_user.id, updated)


    async def change_mail_with_verification(self,current_user:User,data: UpdateUserMail):
        user = await self.user_service.verify_user_id(str(current_user.id))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=" User not found "
            )
        email = await self.user_service.verify_email(data.email)
        if email:
            raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
                )
        code_verification = await self.user_service.generate_code_verification()
        try:
            send = await self.user_service.send_an_email(data.email, code_verification)
        except Exception:
            send = False
        if not send:
            return None
        token = create_access_token(str(current_user.id), str(data.email), str(current_user.role))
        await self.user_repo.update(
            user, 
            {
                "email_token": token,
                "code_verification": code_verification
            }
        )
        return user
    
    async def change_mail_no_verification(
        self,
        current_user: User,
        data: UpdateUserMail
    ):
        user = await self.user_service.verify_email(data.email)

        if user:
            raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

        now = datetime.now(UTC)
        eligible = await self._email_bonus_eligible(current_user.id, now)
        updated = await self.repo.update(
            current_user,
            {
            "email": data.email,
            "change_email_verified": True,
            "updated_email_date": now
            }
        )
        if eligible:
            await self.bonus.award_bonus(current_user.id, BonusReason.update_user_email)
        return updated

    async def _email_bonus_eligible(self, user_id, now: datetime) -> bool:
        """Le bonus n'est dû qu'une fois par période. À évaluer AVANT l'écriture,
        qui écrase `updated_email_date`. Renseigner cette date est indispensable :
        ce parcours ne l'écrivait pas, donc le délai ne se déclenchait jamais et
        les points étaient farmables en enchaînant les changements d'email."""
        last = await self.user_repo.get_email_update_date(user_id)
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (now - last).days >= _EMAIL_CHANGE_COOLDOWN_DAYS

    async def validate_code_change_email(self,current_user:User,data: ValidateCode):
        user = await self.user_service._code_verification_register(data.code)
        token = await self.user_repo.get_email_token(current_user.email)
        decode = await self.user_service.decode_email_token(token)
        now = datetime.now(UTC)
        exp = datetime.fromtimestamp(decode["exp"], tz=UTC)
        diff = exp - now
        if diff.total_seconds() > 3600:
            await self.repo.update(
                user,
                {
                    "email_token":None,
                    "code_verification":None
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=" Code token invalid, please try again.",
            )
        eligible = await self._email_bonus_eligible(user.id, now)
        updated = await self.repo.update(
            user,
            {
                "email":decode["email"],
                "change_email_verified":True,
                "email_token":None,
                "code_verification":None,
                "updated_email_date":now
            }
        )
        # Les deux branches (avec et sans code) changent réellement l'email :
        # sans ça, toucher le bonus dépendrait du succès de l'envoi du mail.
        if eligible:
            await self.bonus.award_bonus(user.id, BonusReason.update_user_email)
        return updated
        
