from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.schema import (
    BonusBalanceRead,
    BonusConversionRequest,
    BonusConversionResult,
    BonusRead,
    PurchaseCodeCreate,
    PurchaseCodeRead,
    PurchaseWithCodeRequest,
    PurchaseWithCodeResult,
    DailyBonusStatus, DailyBonusClaimResult, DailyQuestionRead,
    DailyQuestionAnswerRequest, DailyQuestionAnswerResult,
    DailyQuestionsRead, AdminDailyQuestionCreate, AdminDailyQuestionUpdate,
    AdminDailyQuestionRead, AdminDailyAnswerRead,
)
from app.modules.bonus.service import BonusService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.users.model import User
from app.modules.wallet.repository import WalletRepository
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/bonus", tags=["Point zo"])


def get_bonus_service(db: AsyncSession = Depends(get_db)) -> BonusService:
    return BonusService(
        BonusRepository(db),
        WalletRepository(db),
        NotificationService(NotificationRepository(db=db)),
    )


@router.get("/balance", response_model=BonusBalanceRead)
async def get_bonus_balance(
    current_user: User = Depends(get_current_user),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.get_my_balance(current_user.id)


@router.get("/history", response_model=list[BonusRead])
async def get_bonus_history(
    current_user: User = Depends(get_current_user),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.get_my_history(current_user.id)


@router.get("/daily/status", response_model=DailyBonusStatus)
async def get_daily_status(current_user: User = Depends(get_current_user), service: BonusService = Depends(get_bonus_service)):
    return await service.daily_status(current_user.id)


@router.post("/daily/check-in", response_model=DailyBonusClaimResult)
async def daily_check_in(current_user: User = Depends(get_current_user), service: BonusService = Depends(get_bonus_service)):
    return await service.daily_check_in(current_user.id)


@router.get("/daily-question", response_model=DailyQuestionsRead)
async def get_daily_question(current_user: User = Depends(get_current_user), service: BonusService = Depends(get_bonus_service)):
    return await service.daily_question(current_user.id)


@router.post("/daily-question/answer", response_model=DailyQuestionAnswerResult)
async def answer_daily_question(data: DailyQuestionAnswerRequest, current_user: User = Depends(get_current_user), service: BonusService = Depends(get_bonus_service)):
    return await service.answer_daily_question(current_user.id, data)


@router.get("/admin/daily-questions", response_model=Page[AdminDailyQuestionRead])
async def admin_list_daily_questions(params: PaginationParams = Depends(), _: User = Depends(require_admin), service: BonusService = Depends(get_bonus_service)):
    return await service.admin_questions(params)


@router.post("/admin/daily-questions", response_model=AdminDailyQuestionRead, status_code=status.HTTP_201_CREATED)
async def admin_create_daily_question(data: AdminDailyQuestionCreate, _: User = Depends(require_admin), service: BonusService = Depends(get_bonus_service)):
    return await service.admin_create_question(data)


@router.patch("/admin/daily-questions/{question_id}", response_model=AdminDailyQuestionRead)
async def admin_update_daily_question(question_id: UUID, data: AdminDailyQuestionUpdate, _: User = Depends(require_admin), service: BonusService = Depends(get_bonus_service)):
    return await service.admin_update_question(question_id, data)


@router.delete("/admin/daily-questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_daily_question(question_id: UUID, _: User = Depends(require_admin), service: BonusService = Depends(get_bonus_service)):
    await service.admin_delete_question(question_id)


@router.get("/admin/daily-answers", response_model=Page[AdminDailyAnswerRead])
async def admin_list_daily_answers(answer_date: date | None = None, params: PaginationParams = Depends(), _: User = Depends(require_admin), service: BonusService = Depends(get_bonus_service)):
    return await service.admin_answers(params, answer_date)


@router.post(
    "/bonus/convert",
    response_model=BonusConversionResult,
    summary="Convert wallet (ANK) points into bonus (ZO) points",
)
async def convert_wallet_to_bonus(
    data: BonusConversionRequest,
    current_user: User = Depends(get_current_user),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.convert_to_wallet(current_user.id, data)


@router.post("/purchase-codes", response_model=PurchaseCodeRead)
async def generate_purchase_code(
    data: PurchaseCodeCreate,
    current_user: User = Depends(require_admin),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.generate_purchase_code(current_user.id, data)


@router.get("/purchase-codes", response_model=Page[PurchaseCodeRead])
async def list_purchase_codes(
    params: PaginationParams = Depends(),
    _: User = Depends(require_admin),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.list_purchase_codes(params)


@router.post("/purchase-with-code", response_model=PurchaseWithCodeResult)
async def purchase_with_code(
    data: PurchaseWithCodeRequest,
    current_user: User = Depends(get_current_user),
    service: BonusService = Depends(get_bonus_service),
):
    return await service.purchase_with_code(current_user.id, data)
