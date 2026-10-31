import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.schema import AnkTransactionRead, SpendRequest, WalletRead
from app.modules.wallet.service import WalletService
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/wallets", tags=["wallets"])


def _service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(WalletRepository(db))


@router.get("/me", response_model=WalletRead)
async def get_my_wallet(
    current_user=Depends(get_current_user),
    svc: WalletService = Depends(_service),
):
    return await svc.get_my_wallet(current_user.id)


@router.get("/me/transactions", response_model=Page[AnkTransactionRead])
async def get_my_transactions(
    current_user=Depends(get_current_user),
    params: PaginationParams = Depends(),
    svc: WalletService = Depends(_service),
):
    return await svc.get_my_transactions(current_user.id, params)


@router.post("/me/spend", response_model=WalletRead, status_code=200)
async def spend_my_wallet(
    body: SpendRequest,
    current_user=Depends(get_current_user),
    svc: WalletService = Depends(_service),
):
    return await svc.spend(current_user.id, body.amount, body.reason)


@router.post("/users/{user_id}/credit", response_model=WalletRead, status_code=200)
async def admin_credit_wallet(
    user_id: uuid.UUID,
    amount: int,
    description: str | None = None,
    _=Depends(require_admin),
    svc: WalletService = Depends(_service),
):
    return await svc.admin_credit(user_id, amount, description)
