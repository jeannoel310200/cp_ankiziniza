import math
import random
import secrets
import string
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from datetime import datetime , timedelta, timezone

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.email import send_email
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.bonus.service import BonusReason, BonusService
from app.modules.notification.service import NotificationService
from app.modules.relationships.repository import RelationshipRequestRepository
from app.modules.users.model import CODE_SEARCH_EXPIRES_AFTER, GenderEnum, User, UserRole
from app.modules.users.pending_model import PENDING_REGISTRATION_EXPIRES_AFTER
from app.modules.users.pending_repository import PendingRegistrationRepository
from app.modules.users.repository import UserRepository
from app.modules.users.schema import (
    PublicStatusRead,
    UserChangeEmail,
    UserChangePhone,
    UserCodeSearchRead,
    UserCreate,
    UserNameSearchRead,
    UserNewPassword,
    UserPasswordUpdate,
    UserPublicRead,
    UserRead,
    UserUpdate,
    ValidateCode,
    UserForgotPassword
)
from app.modules.wallet.service import WalletService
from app.shared.schemas.pagination import Page, PaginationParams, make_page

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_ATTEMPTS = 5
_EMAIL_CHANGE_COOLDOWN_DAYS = 30
# Même valeur aujourd'hui, mais constante distincte : le téléphone empruntait
# celle de l'email, si bien qu'ajuster le délai de l'un aurait déplacé l'autre
# sans qu'on le veuille.
_PHONE_CHANGE_COOLDOWN_DAYS = 30

# Coût en points ZO pour révéler le statut relationnel d'un utilisateur
# trouvé via recherche authentifiée (bouton "Révéler").
REVEAL_STATUS_COST_ZO = 300


def _generate_code() -> str:
    suffix = "".join(random.choices(_CODE_CHARS, k=6))
    return f"AKI-{suffix}"


def _generate_code_verify() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class UserService:
    def __init__(
        self,
        repo: UserRepository,
        bonus_service: BonusService,
        notif_service: NotificationService,
        wallet_service: WalletService,
        pending_repo: PendingRegistrationRepository,
    ):
        self.repo = repo
        self.bonus_service = bonus_service
        self.notif_service = notif_service
        self.wallet_service = wallet_service
        self.pending_repo = pending_repo

    async def generate_code_user(self):
        code_user: str | None = None
        for _ in range(_CODE_ATTEMPTS):
            candidate = _generate_code()
            if not await self.repo.get_by_code(candidate):
                code_user = candidate
                break

        if code_user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Code generation failed",
            )
        return code_user

    async def generate_code_verification(self):
        code_verification: str | None = None
        for _ in range(_CODE_ATTEMPTS):
            candidate = _generate_code_verify()
            if not await self.repo.get_by_code_verification(candidate):
                code_verification = candidate
                break

        if code_verification is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Code generation failed",
            )
        return code_verification

    async def create_user(self, data: UserCreate):
        generate = await self.generate_code_user()
        code = generate
        user = await self.repo.create(
            {
                "first_name": data.first_name,
                "last_name": data.last_name,
                "email": str(data.email),
                "phone": data.phone,
                "hashed_password": hash_password(data.password),
                "code_user": code,
                "provider": "local",
                "gender": data.gender,
            }
        )
        return user

    async def register(self, data: UserCreate) -> UserRead | None:
        """N'écrit rien tant que l'envoi de l'email n'a pas réussi : le
        compte est créé plus tard, seulement quand le bon code est soumis
        (cf. validate_code_email). Si l'envoi échoue, retourne None — le
        routeur bascule alors sur register_without_verification, qui crée
        le compte immédiatement, comportement inchangé."""
        if await self.repo.get_by_email(str(data.email)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        code_verification = await self.generate_code_verification()
        try:
            send = await self.send_an_email(data.email, code_verification)
        except Exception:
            send = False
        if not send:
            return None

        # Une inscription en attente déjà présente pour cet email (tentative
        # précédente jamais confirmée) est remplacée plutôt qu'accumulée.
        existing_pending = await self.pending_repo.get_by_email(str(data.email))
        if existing_pending:
            await self.pending_repo.delete(existing_pending)
        pending = await self.pending_repo.create(
            {
                "email": str(data.email),
                "hashed_password": hash_password(data.password),
                "first_name": data.first_name,
                "last_name": data.last_name,
                "phone": data.phone,
                "gender": data.gender,
                "code_verification": code_verification,
            }
        )
        return UserRead.model_validate(
            {
                "id": pending.id,
                "first_name": pending.first_name,
                "last_name": pending.last_name,
                "email": pending.email,
                "phone": pending.phone,
                "avatar_url": None,
                "is_verified": False,
                "role": UserRole.user,
                "code_user": None,
                "profile_views": 0,
                "created_at": pending.created_at,
                "updated_at": pending.created_at,
                "verified_after_forgot_password": False,
                "change_email_verified": False,
                "gender": pending.gender,
                "code_first_searched_at": None,
                "profile": None,
            }
        )

    async def register_without_verification(self, data: UserCreate):
        """Chemin fallback (envoi d'email échoué/désactivé) : crée le
        compte tout de suite, sans code à saisir — is_verified=True direct."""
        if await self.repo.get_by_email(str(data.email)):
            return None

        user = await self.create_user(data)
        await self.repo.update(user, {"is_verified": True})
        await self.bonus_service.award_bonus(
                user_id=user.id, reason=BonusReason.first_time
            )
        await self.repo.create_profile(
                {
                    "user_id": user.id,
                    "full_name": f"{user.first_name} {user.last_name}".strip(),
                }
            )
        # Nettoie une éventuelle inscription en attente pour le même email
        # (tentative précédente dont l'envoi avait réussi mais jamais
        # confirmée) : sans ça, son code pourrait plus tard entrer en
        # conflit avec ce compte fraîchement créé (email déjà pris).
        stale_pending = await self.pending_repo.get_by_email(str(data.email))
        if stale_pending:
            await self.pending_repo.delete(stale_pending)
        return user

    async def resend_verification_code(self, email: str) -> None:
        pending = await self.pending_repo.get_by_email(email)
        if pending is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending registration for this email",
            )
        code_verification = await self.generate_code_verification()
        try:
            send = await self.send_an_email(email, code_verification)
        except Exception:
            send = False
        if not send:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not send verification email",
            )
        await self.pending_repo.update(
            pending,
            {"code_verification": code_verification, "created_at": datetime.now(UTC)},
        )

    async def send_an_email(self, email: str, code_verification: str):
        html = f"""
        <h1>Verify Your Email</h1>
        <p>Please use the following verification code to verify your email:</p>
        <h2>{code_verification}</h2>"""

        subject = "Verify Your email"
        return await send_email([email], subject, html)

    async def email_forgot_password(self, email: str, token: str):
        settings = get_settings()
        link = f"{settings.base_url}{settings.api_v1_prefix}/users/response_email_password/{token}"
        html = f"""
        <h1>Verify your Email</h1>
        <p>Please click this <a href="{link}">link</a> to verify your email</p>
                """
        subject = "Verify Your email"
        await send_email([email], subject, html)

    async def decode_email_token(self, token: str) -> dict[str, Any]:
        email = decode_token(token)
        return email

    async def get_email_token(self, email: str) -> dict[str, Any] | None:
        token = await self.repo.get_email_token(email)
        if token is None:
            raise HTTPException("Token None")
        decode = await self.decode_email_token(token)
        return decode

    async def verify_email(self, email: str) -> User | None:
        return await self.repo.get_by_email(str(email))

    async def verify_user_id(self, user_id:str) -> User | None:
        user = await self.repo.get_by_id(str(user_id))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

    async def forgot_password(self, email: str):
        user = await self.verify_email(email)
        if user:
            token = create_access_token(str(user.id), str(user.email), str(user.role))
            await self.email_forgot_password(email, token)
            return user

    async def _code_verification_register(self, code: str):
        code_verification = await self.repo.code_verification(code)
        if not code_verification or None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Incorrect code or User not found"
            )
        return code_verification

    async def _code_verification_password(self, code: str):
        code_verification = await self.repo.get_by_code_verification(code)
        if not code_verification or None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Incorrect code"
            )
        return code_verification

    async def validate_code_email(self, data: ValidateCode) -> User:
        """Crée le vrai compte seulement maintenant, à partir de
        l'inscription en attente correspondant au code — c'est le seul
        endroit qui écrit dans `users` pour le chemin d'inscription par
        email réussi (cf. register)."""
        pending = await self.pending_repo.get_by_code(data.code)
        if pending is None or (data.email and pending.email != str(data.email)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Incorrect code or registration not found"
            )

        created_at = pending.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - created_at > PENDING_REGISTRATION_EXPIRES_AFTER:
            await self.pending_repo.delete(pending)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Code expired, please register again.",
            )

        code_user = await self.generate_code_user()
        user = await self.repo.create(
            {
                "first_name": pending.first_name,
                "last_name": pending.last_name,
                "email": pending.email,
                "phone": pending.phone,
                "hashed_password": pending.hashed_password,
                "code_user": code_user,
                "provider": "local",
                "gender": pending.gender,
                "is_verified": True,
            }
        )
        await self.pending_repo.delete(pending)
        await self.bonus_service.award_bonus(user_id=user.id, reason=BonusReason.first_time)
        await self.repo.create_profile({"user_id": user.id})
        return user


    async def new_password(self, user: User, data: UserNewPassword):
        password = await self.repo.update(user, {"hashed_password": hash_password(data.password)})
        if not password:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return password

    async def list_users(self, params: PaginationParams, q: str | None = None) -> Page[UserRead]:
        users, total = await self.repo.list(params.offset, params.limit, q=q)
        return make_page([UserRead.model_validate(u) for u in users], total, params)

    async def search_by_name(
        self, name: str, params: PaginationParams, current_id: str | UUID
    ) -> Page[UserNameSearchRead]:
        users, total = await self.repo.search_by_name(
            current_id=current_id, name=name.strip(), offset=params.offset, limit=params.limit
        )
        return make_page([UserNameSearchRead.model_validate(u) for u in users], total, params)

    async def get_suggestions(
        self,
        current_user: User,
        params: PaginationParams,
        relationship_repo: RelationshipRequestRepository,
    ) -> Page[UserNameSearchRead]:
        """Suggestions de personnes du sexe opposé (page découverte de
        l'écran recherche). Legacy comptes sans gender (pré-migration ou
        OAuth) : page vide, ni erreur ni crash — limitation connue et
        acceptée (cf. plan.md, décisions).

        Pagination avec wraparound côté serveur : ORDER BY created_at pour
        une pagination stable (pas de random(), qui casserait l'offset
        entre deux appels), et si le pool de suggestions est plus petit que
        la page demandée, on boucle sur les pages existantes plutôt que de
        renvoyer une liste vide (cf. plan.md, décisions)."""
        if current_user.gender is None:
            return make_page([], 0, params)

        opposite_gender = (
            GenderEnum.FEMALE if current_user.gender == GenderEnum.MALE else GenderEnum.MALE
        )
        exclude_ids = await relationship_repo.list_related_user_ids(current_user.id)
        exclude_ids.add(current_user.id)

        items, total = await self.repo.get_suggestions(
            current_user_id=current_user.id,
            opposite_gender=opposite_gender,
            exclude_ids=exclude_ids,
            offset=0,
            limit=params.page_size,
        )

        total_pages = max(1, math.ceil(total / params.page_size))
        effective_page = ((params.page - 1) % total_pages) + 1

        if effective_page != 1:
            offset = (effective_page - 1) * params.page_size
            items, total = await self.repo.get_suggestions(
                current_user_id=current_user.id,
                opposite_gender=opposite_gender,
                exclude_ids=exclude_ids,
                offset=offset,
                limit=params.page_size,
            )

        # make_page fige page=params.page (le compteur du client), même si
        # le serveur a en réalité servi effective_page en interne.
        return make_page([UserNameSearchRead.model_validate(u) for u in items], total, params)

    async def _apply_code_search_effects(self, user: User, searcher_id: UUID | None) -> User:
        """Effets de bord d'une recherche par code_user : le code expire 1h
        après sa première utilisation par un tiers et est alors régénéré, et
        son propriétaire reçoit un bonus. Partagé entre la recherche
        authentifiée (`get_by_code`) et la vérification publique sans compte
        (`get_public_status`, `searcher_id=None` — pas de notification
        "profil consulté" possible faute d'auteur identifiable)."""
        if user.code_first_searched_at is not None:
            elapsed = datetime.now(UTC) - user.code_first_searched_at
            if elapsed >= CODE_SEARCH_EXPIRES_AFTER:
                new_code = await self.generate_code_user()
                await self.repo.update(
                    user, {"code_user": new_code, "code_first_searched_at": None}
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Code expired, please ask for a new one",
                )

        if searcher_id is None or user.id != searcher_id:
            if searcher_id is not None:
                await self.notif_service.notify_profile_searched(user.id, searcher_id)
            await self.bonus_service.award_bonus(user_id=user.id, reason=BonusReason.code_searched)

            if user.code_first_searched_at is None:
                await self.repo.update(user, {"code_first_searched_at": datetime.now(UTC)})

        return user

    async def get_by_code(self, code: str, searcher_id: UUID) -> User:
        user = await self.repo.get_by_code(code)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user = await self._apply_code_search_effects(user, searcher_id)
        await self.repo.increment_profile_views(user.id)

        return user

    _SITUATION_LABELS: dict[str, str] = {
        "single": "Célibataire",
        "in_couple": "En couple",
        "married": "Marié(e)",
        "divorced": "Divorcé(e)",
        "widowed": "Veuf/Veuve",
    }

    def _build_status_fields(self, rel_status) -> tuple[str, bool]:
        situation = (
            self._SITUATION_LABELS.get(rel_status.status.value, rel_status.status.value)
            if rel_status
            else "Célibataire"
        )
        has_partner = (
            rel_status is not None
            and rel_status.partner_id is not None
            and rel_status.status.value in ("in_couple", "married")
        )
        return situation, has_partner

    async def get_public_status(self, code: str) -> PublicStatusRead:
        row = await self.repo.get_public_status_by_code(code)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user, rel_status = row

        user = await self._apply_code_search_effects(user, searcher_id=None)
        await self.repo.increment_profile_views(user.id)

        situation, has_partner = self._build_status_fields(rel_status)
        return PublicStatusRead(
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url or "",
            situation=situation,
            has_partner=has_partner,
        )

    async def get_code_search_result(self, user: User) -> UserCodeSearchRead:
        """Enrichit un résultat de recherche par code avec le statut
        relationnel, gratuitement — chercher par code implique déjà
        connaître le code, donc pas de facturation ni d'étape "Révéler"."""
        row = await self.repo.get_status_by_user_id(user.id)
        rel_status = row[1] if row else None
        situation, has_partner = self._build_status_fields(rel_status)
        return UserCodeSearchRead(
            **UserPublicRead.model_validate(user).model_dump(),
            situation=situation,
            has_partner=has_partner,
        )

    async def reveal_status_by_id(self, target_user_id: UUID, requester_id: UUID) -> PublicStatusRead:
        """Révélation payante depuis un résultat de recherche par nom.

        Le coût est prélevé sur le solde ZO agrégé. Les ZO issus d'une
        conversion ANK sont consommés en priorité et peuvent financer une
        récompense ANK pour la personne consultée ; les ZO de bonus ne créent
        jamais de dette ANK.
        """
        row = await self.repo.get_status_by_user_id(target_user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user, rel_status = row
        situation, has_partner = self._build_status_fields(rel_status)

        await self.bonus_service.spend_for_reveal(
            requester_id=requester_id,
            cost_zo=REVEAL_STATUS_COST_ZO,
            description="Révéler le statut relationnel",
            reward_allocations=[(user.id, 4, 120)],
            bonus_awards=[
                (user.id, 15, "Bonus standard de révélation du statut"),
                (requester_id, 15, "Bonus standard de demande de statut"),
            ],
        )

        return PublicStatusRead(
            first_name=user.first_name,
            last_name=user.last_name,
            avatar_url=user.avatar_url or "",
            situation=situation,
            has_partner=has_partner,
        )

    async def get_by_id(self, user_id: str) -> User:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def update(self, user: User, data: UserUpdate) -> User:
        changes = data.model_dump(exclude_none=True)
        return await self.repo.update(user, changes)

    async def update_user_code(self, current_user: User) -> User:
        user = await self.verify_user_id(current_user.id)
        code_user: str | None = None
        for _ in range(_CODE_ATTEMPTS):
            candidate = _generate_code()
            if not await self.repo.get_by_code(candidate):
                code_user = candidate
                break
        if code_user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Code generation failed",
            )
        new_code_user = await self.repo.update(
            user, {"code_user": code_user, "code_first_searched_at": None}
        )

        return new_code_user.code_user

    async def regenerate_expired_codes(self) -> int:
        """Régénère automatiquement le code des utilisateurs dont le code a
        été recherché par un tiers il y a plus de `CODE_SEARCH_EXPIRES_AFTER`
        et n'a jamais été régénéré depuis (ni manuellement, ni via une autre
        recherche déjà expirée). Appelée périodiquement par la tâche de fond
        démarrée dans le lifespan de l'app. Retourne le nombre de comptes mis
        à jour (utile pour les logs/tests)."""
        expired_before = datetime.now(UTC) - CODE_SEARCH_EXPIRES_AFTER
        users = await self.repo.list_with_expired_code_search(expired_before)
        for user in users:
            new_code = await self.generate_code_user()
            await self.repo.update(
                user, {"code_user": new_code, "code_first_searched_at": None}
            )
            await self.notif_service.notify_code_regenerated(user.id)
        return len(users)

    async def change_password(self, user: User, data: UserPasswordUpdate) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong current password"
            )
        await self.repo.update(user, {"hashed_password": hash_password(data.new_password)})

    async def change_email(self, current_user: User, data: UserChangeEmail) -> User:
        user = await self.verify_user_id(current_user.id)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")
        now = datetime.now(UTC)
        update_date = await self.repo.get_email_update_date(current_user.id)
        if update_date is None or (now - update_date).days >= _EMAIL_CHANGE_COOLDOWN_DAYS:
            await self.bonus_service.award_bonus(
                current_user.id,
                BonusReason.update_user_email,
            )
        user_email = await self.repo.update(
            user,
            {
                "email": data.email,
                "updated_email_date": now,
            },
        )
        return user_email

    async def change_phone(self, current_user: User, data: UserChangePhone) -> User:
        user = await self.verify_user_id(current_user.id)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")
        now = datetime.now(UTC)
        update_date = await self.repo.get_phone_update_date(current_user.id)
        if update_date is None or (now - update_date).days >= _PHONE_CHANGE_COOLDOWN_DAYS:
            await self.bonus_service.award_bonus(
                current_user.id,
                BonusReason.update_profile_phone,
            )
        updated_user = await self.repo.update(
            user,
            {
                "phone": data.phone,
                "updated_phone_date": now,
            },
        )
        return updated_user

    async def ensure_code(self, user: User) -> User:
        """Returns the user unchanged if already has a code; otherwise generates and persists one."""
        if user.code_user:
            return user
        code_user: str | None = None
        for _ in range(_CODE_ATTEMPTS):
            candidate = _generate_code()
            if not await self.repo.get_by_code(candidate):
                code_user = candidate
                break
        if code_user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Code generation failed",
            )
        return await self.repo.update(user, {"code_user": code_user})

    async def delete(self, user: User) -> None:
        await self.repo.delete(user)


# -- forgot password -- #
    async def forgot_password_with_verification(self, data: UserForgotPassword):
        user = await self.repo.get_by_email(str(data.email))
        if user is None:
            raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=" User not found "
            )
        code_verification = await self.generate_code_verification()
        try:
            send = await self.send_an_email(data.email, code_verification)
        except Exception:
            send = False
        if not send:
            return None
        token = create_access_token(str(user.id), str(user.email), str(user.role))
        await self.repo.update(
            user,
            {
                "forgot_password_token": token,
                "forgot_password_code": code_verification
            }
        )
        return user

    async def forgot_password_no_verification(self, data:UserForgotPassword):
        user = await self.repo.get_by_email(data.email)
        if user:
            await self.repo.update(
                user,
                {
                    "verified_after_forgot_password": True
                }
            )
        return user

    async def validate_code_password(self, data: ValidateCode):
        user = await self._code_verification_password(data.code)
        token = await self.repo.get_password_token(user.email)
        decode = await self.decode_email_token(token)
        now = datetime.now(UTC)
        exp = datetime.fromtimestamp(decode["exp"], tz=UTC)
        diff = exp - now
        if diff.total_seconds() > 3600:
            await self.repo.update(
                user,
                {
                    "forgot_password_token":None,
                    "forgot_password_code":None
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=" Code token invalid, please try again.",
            )
        await self.repo.update(
            user,
            {
                "forgot_password_token":None,
                "forgot_password_code":None
            }
            )
        return await self.repo.update(user,{"verified_after_forgot_password": True})

    async def change_forgot_password(self,email:str, data: UserNewPassword) -> User:
        user = await self.repo.get_by_email(email)
        if not user or None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )
        verified_column = await self.repo.verified_column(user.id)
        if verified_column is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,detail="You can't change your password"
            )
        new_password = await self.repo.update(user, {"hashed_password": hash_password(data.password)})
        return new_password
