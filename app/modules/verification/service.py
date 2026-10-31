import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException, UploadFile, status

from app.core.storage import get_storage
from app.modules.bonus.service import BonusReason, BonusService
from app.modules.notification.service import NotificationService
from app.modules.profile.repository import ProfileRepository
from app.modules.verification.model import VerificationStatus
from app.modules.verification.repository import VerificationRepository
from app.modules.verification.schema import VerificationRequestRead
from app.shared.schemas.pagination import Page, PaginationParams, make_page

_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".png"
    suffix = filename.rsplit(".", 1)[-1].lower()
    return f".{suffix}" if suffix in _EXTENSIONS else ".png"


def _guess_content_type(key: str) -> str:
    extension = _extension(key)
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(extension, "application/octet-stream")


class VerificationService:
    def __init__(
        self,
        repo: VerificationRepository,
        profile_repo: ProfileRepository,
        bonus_service: BonusService,
        notif_service: NotificationService,
    ):
        self.repo = repo
        self.profile_repo = profile_repo
        self.bonus_service = bonus_service
        self.notif_service = notif_service

    async def request_verification(
        self,
        user_id: uuid.UUID,
        full_name: str,
        birth_date: date,
        cin_photo: UploadFile,
        extra_info: str | None = None,
    ) -> VerificationRequestRead:
        existing = await self.repo.get_pending_by_user(user_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A verification request is already pending",
            )

        cin_key = f"uploads/verification/{user_id}/{uuid.uuid4()}{_extension(cin_photo.filename)}"
        content = await cin_photo.read()
        await get_storage().save_bytes(
            cin_key, content, cin_photo.content_type or "image/jpeg"
        )

        req = await self.repo.create(
            {
                "user_id": user_id,
                "full_name": full_name,
                "birth_date": birth_date,
                "cin_photo_path": cin_key,
                "extra_info": extra_info,
            }
        )
        return VerificationRequestRead.model_validate(req)

    async def get_my_latest(self, user_id: uuid.UUID) -> VerificationRequestRead | None:
        """Dernière demande de l'utilisateur, ou None s'il n'en a jamais faite."""
        req = await self.repo.get_latest_by_user(user_id)
        return VerificationRequestRead.model_validate(req) if req else None

    async def list_pending(self, params: PaginationParams) -> Page[VerificationRequestRead]:
        reqs, total = await self.repo.list_pending(params.offset, params.limit)
        return make_page(
            [VerificationRequestRead.model_validate(r) for r in reqs], total, params
        )

    async def get_photo_path(self, request_id: uuid.UUID) -> str:
        """Clé de stockage (ou chemin local) de la pièce d'identité envoyée
        par l'utilisateur. Réservé à l'admin (cf. router.py, require_admin) :
        `uploads/verification` n'est jamais monté en statique (voir
        app/main.py) pour ne pas exposer les pièces d'identité."""
        req = await self.repo.get_by_id(request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification request not found",
            )
        return req.cin_photo_path

    async def read_photo(self, request_id: uuid.UUID) -> tuple[bytes, str]:
        """Contenu binaire et type MIME de la pièce d'identité."""
        key = await self.get_photo_path(request_id)
        return await get_storage().read_bytes(key), _guess_content_type(key)

    async def approve(self, request_id: uuid.UUID, admin_id: uuid.UUID) -> VerificationRequestRead:
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != VerificationStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending verification request not found",
            )

        updated = await self.repo.update(
            req,
            {
                "status": VerificationStatus.approved,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )

        # Badge bleu (identité vérifiée par un admin) — distinct de
        # User.is_verified qui ne concerne que la vérification de l'email.
        profile = await self.profile_repo.get_by_id(req.user_id)
        if profile:
            await self.profile_repo.update(profile, {"blue_badge": True})

        await self.bonus_service.award_bonus(
            user_id=req.user_id, reason=BonusReason.account_verified
        )
        await self.notif_service.notify_account_verified(req.user_id)

        return VerificationRequestRead.model_validate(updated)

    async def reject(
        self, request_id: uuid.UUID, admin_id: uuid.UUID, admin_note: str
    ) -> VerificationRequestRead:
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != VerificationStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending verification request not found",
            )

        updated = await self.repo.update(
            req,
            {
                "status": VerificationStatus.rejected,
                "admin_note": admin_note,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )

        # Symétrique de `approve`, qui notifie déjà : sans ça le motif reste en
        # base et l'utilisateur ne sait jamais pourquoi sa demande a échoué.
        await self.notif_service.notify_verification_rejected(req.user_id, admin_note)

        return VerificationRequestRead.model_validate(updated)
