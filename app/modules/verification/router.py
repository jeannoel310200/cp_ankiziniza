import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.service import BonusService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.profile.repository import ProfileRepository
from app.modules.users.model import User
from app.modules.verification.repository import VerificationRepository
from app.modules.verification.schema import VerificationReject, VerificationRequestRead
from app.modules.verification.service import VerificationService
from app.modules.wallet.repository import WalletRepository
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/verification", tags=["verification"])


def get_verification_service(db: AsyncSession = Depends(get_db)) -> VerificationService:
    return VerificationService(
        repo=VerificationRepository(db=db),
        profile_repo=ProfileRepository(db=db),
        bonus_service=BonusService(
            repo=BonusRepository(db),
            notif_service=NotificationService(NotificationRepository(db=db)),
            wallet_repo=WalletRepository(db=db),
        ),
        notif_service=NotificationService(NotificationRepository(db=db)),
    )


@router.post(
    "/request", response_model=VerificationRequestRead, status_code=status.HTTP_201_CREATED
)
async def request_verification(
    full_name: str = Form(...),
    birth_date: date = Form(...),
    cin_photo: UploadFile = File(...),
    extra_info: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
):
    return await service.request_verification(
        user_id=current_user.id,
        full_name=full_name,
        birth_date=birth_date,
        cin_photo=cin_photo,
        extra_info=extra_info,
    )


@router.get("/me", response_model=VerificationRequestRead | None)
async def my_verification_request(
    current_user: User = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
):
    """Dernière demande de l'utilisateur courant, `null` s'il n'en a jamais
    faite. Le client s'en sert pour savoir s'il propose le bouton d'envoi :
    sans cette information il ne peut que deviner, et provoque un 409.
    """
    return await service.get_my_latest(current_user.id)


@router.get("/admin/pending", response_model=Page[VerificationRequestRead])
async def list_pending_verifications(
    params: PaginationParams = Depends(),
    admin: User = Depends(require_admin),
    service: VerificationService = Depends(get_verification_service),
):
    return await service.list_pending(params)


@router.get("/admin/{request_id}/photo")
async def get_verification_photo(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: VerificationService = Depends(get_verification_service),
):
    """Pièce d'identité envoyée par l'utilisateur — réservée aux admins.
    Le contenu est lu depuis le stockage configuré (RustFS S3 en production) :
    `uploads/verification` n'est jamais monté en statique (cf. app/main.py)."""
    content, content_type = await service.read_photo(request_id)
    return Response(
        content=content,
        media_type=content_type,
    )


@router.patch("/admin/{request_id}/approve", response_model=VerificationRequestRead)
async def approve_verification(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: VerificationService = Depends(get_verification_service),
):
    return await service.approve(request_id, admin.id)


@router.patch("/admin/{request_id}/reject", response_model=VerificationRequestRead)
async def reject_verification(
    request_id: uuid.UUID,
    data: VerificationReject,
    admin: User = Depends(require_admin),
    service: VerificationService = Depends(get_verification_service),
):
    return await service.reject(request_id, admin.id, data.admin_note)
