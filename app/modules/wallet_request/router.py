import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet_request.repository import WalletRequestRepository
from app.modules.wallet_request.schema import (
    WalletRequestAdminRead,
    WalletRequestCreate,
    WalletRequestReject,
    WalletRequestRead,
)
from app.modules.wallet_request.service import WalletRequestService
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/wallet-requests", tags=["wallet requests"])


def get_wallet_request_service(db: AsyncSession = Depends(get_db)) -> WalletRequestService:
    return WalletRequestService(
        repo=WalletRequestRepository(db=db),
        wallet_repo=WalletRepository(db=db),
        user_repo=UserRepository(db),
        notif_service=NotificationService(NotificationRepository(db=db)),
    )


@router.post(
    "/request", response_model=WalletRequestRead, status_code=status.HTTP_201_CREATED
)
async def request_wallet_transaction(
    data: WalletRequestCreate,
    current_user: User = Depends(get_current_user),
    service: WalletRequestService = Depends(get_wallet_request_service),
):
    return await service.request_transaction(current_user.id, data)


@router.get("/me", response_model=list[WalletRequestRead])
async def my_wallet_requests(
    current_user: User = Depends(get_current_user),
    service: WalletRequestService = Depends(get_wallet_request_service),
):
    return await service.list_my_requests(current_user.id)


@router.get("/admin/pending", response_model=Page[WalletRequestAdminRead])
async def list_pending_wallet_requests(
    params: PaginationParams = Depends(),
    admin: User = Depends(require_admin),
    service: WalletRequestService = Depends(get_wallet_request_service),
):
    return await service.list_pending(params)


@router.patch("/admin/{request_id}/approve", response_model=WalletRequestRead)
async def approve_wallet_request(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: WalletRequestService = Depends(get_wallet_request_service),
):
    return await service.approve(request_id, admin.id)


@router.patch("/admin/{request_id}/reject", response_model=WalletRequestRead)
async def reject_wallet_request(
    request_id: uuid.UUID,
    data: WalletRequestReject,
    admin: User = Depends(require_admin),
    service: WalletRequestService = Depends(get_wallet_request_service),
):
    return await service.reject(request_id, admin.id, data.admin_note)
