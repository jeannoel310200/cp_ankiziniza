import uuid
from enum import Enum

from fastapi import HTTPException, status

from app.modules.wallet.model import TransactionOrigin
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.schema import AnkTransactionRead, WalletRead
from app.shared.schemas.pagination import Page, PaginationParams, make_page


class BonusReason(str, Enum):
    quick_response = "quick_response"
    code_searched = "code_searched"
    relationship_milestone = "relationship_milestone"
    account_verified = "account_verified"
    usage_milestone = "usage_milestone"


BONUS_POINTS: dict[BonusReason, int] = {
    BonusReason.quick_response: 100,
    BonusReason.code_searched: 5,
    BonusReason.relationship_milestone: 20,
    BonusReason.account_verified: 15,
    BonusReason.usage_milestone: 5,
}

BONUS_LABELS: dict[BonusReason, str] = {
    BonusReason.quick_response: "Bonus pour réponse rapide (<24h)",
    BonusReason.code_searched: "Bonus pour recherche via code",
    BonusReason.relationship_milestone: "Bonus anniversaire de relation",
    BonusReason.account_verified: "Bonus vérification de compte",
    BonusReason.usage_milestone: "Bonus fidélité d'utilisation",
}


class WalletService:
    def __init__(self, repo: WalletRepository):
        self.repo = repo

    async def get_my_wallet(self, user_id: uuid.UUID) -> WalletRead:
        wallet = await self.repo.get_or_create(user_id)
        return WalletRead.model_validate(wallet)

    async def get_my_transactions(
        self, user_id: uuid.UUID, params: PaginationParams
    ) -> Page[AnkTransactionRead]:
        wallet = await self.repo.get_or_create(user_id)
        txs, total = await self.repo.list_transactions(wallet.id, params.offset, params.limit)
        return make_page([AnkTransactionRead.model_validate(t) for t in txs], total, params)

    async def admin_credit(
        self,
        user_id: uuid.UUID,
        amount: int,
        description: str | None = None,
    ) -> WalletRead:
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be positive",
            )
        wallet = await self.repo.get_or_create(user_id)
        await self.repo.credit(
            wallet,
            amount,
            TransactionOrigin.recharge,
            description=description,
        )
        return WalletRead.model_validate(wallet)

    async def spend(
        self,
        user_id: uuid.UUID,
        amount: int,
        reason: str,
    ) -> WalletRead:
        wallet = await self.repo.get_or_create(user_id)
        try:
            await self.repo.debit(
                wallet,
                amount,
                TransactionOrigin.consultation_paid,
                description=reason,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Solde ANK insuffisant",
            )
        return WalletRead.model_validate(wallet)

    async def award_bonus(
        self,
        user_id: uuid.UUID,
        reason: BonusReason,
        related_user_id: uuid.UUID | None = None,
    ) -> WalletRead:
        wallet = await self.repo.get_or_create(user_id)
        await self.repo.credit(
            wallet,
            BONUS_POINTS[reason],
            TransactionOrigin.bonus,
            description=BONUS_LABELS[reason],
            related_user_id=related_user_id,
        )
        return WalletRead.model_validate(wallet)
