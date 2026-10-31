import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wallet.model import AnkTransaction, TransactionOrigin, TransactionType, Wallet


class WalletRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: uuid.UUID) -> Wallet | None:
        result = await self.db.execute(select(Wallet).where(Wallet.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: uuid.UUID, *, commit: bool = True) -> Wallet:
        wallet = await self.get_by_user_id(user_id)
        if wallet is None:
            wallet = Wallet(user_id=user_id, points=0)
            self.db.add(wallet)
            await self.db.flush()
            if commit:
                await self.db.commit()
                await self.db.refresh(wallet)
        return wallet

    async def list_transactions(
        self, wallet_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[AnkTransaction], int]:
        total = (
            await self.db.execute(
                select(func.count()).where(AnkTransaction.wallet_id == wallet_id)
            )
        ).scalar_one()
        result = await self.db.execute(
            select(AnkTransaction)
            .where(AnkTransaction.wallet_id == wallet_id)
            .order_by(AnkTransaction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    # --- committing variants (simple single-step operations) ---

    async def credit(
        self,
        wallet: Wallet,
        amount: int,
        origin: TransactionOrigin,
        related_user_id: uuid.UUID | None = None,
        description: str | None = None,
    ) -> AnkTransaction:
        tx = self._build_tx(wallet, amount, TransactionType.credit, origin, related_user_id, description)
        wallet.points += amount
        self.db.add(tx)
        await self.db.commit()
        await self.db.refresh(wallet)
        await self.db.refresh(tx)
        return tx

    async def debit(
        self,
        wallet: Wallet,
        amount: int,
        origin: TransactionOrigin,
        related_user_id: uuid.UUID | None = None,
        description: str | None = None,
        commit: bool = True,
    ) -> AnkTransaction:
        if wallet.points < amount:
            raise ValueError("Insufficient ANK points")
        tx = self._build_tx(wallet, amount, TransactionType.debit, origin, related_user_id, description)
        wallet.points -= amount
        self.db.add(tx)
        if commit:
            await self.db.commit()
            await self.db.refresh(wallet)
            await self.db.refresh(tx)
        else:
            await self.db.flush()
        return tx

    # --- flush-only variants (for multi-step atomic operations in consultation) ---

    def flush_credit(
        self,
        wallet: Wallet,
        amount: int,
        origin: TransactionOrigin,
        related_user_id: uuid.UUID | None = None,
        description: str | None = None,
    ) -> AnkTransaction:
        tx = self._build_tx(wallet, amount, TransactionType.credit, origin, related_user_id, description)
        wallet.points += amount
        self.db.add(tx)
        return tx

    def flush_debit(
        self,
        wallet: Wallet,
        amount: int,
        origin: TransactionOrigin,
        related_user_id: uuid.UUID | None = None,
        description: str | None = None,
    ) -> AnkTransaction:
        if wallet.points < amount:
            raise ValueError("Insufficient ANK points")
        tx = self._build_tx(wallet, amount, TransactionType.debit, origin, related_user_id, description)
        wallet.points -= amount
        self.db.add(tx)
        return tx

    # --- internal ---

    def _build_tx(
        self,
        wallet: Wallet,
        amount: int,
        tx_type: TransactionType,
        origin: TransactionOrigin,
        related_user_id: uuid.UUID | None,
        description: str | None,
    ) -> AnkTransaction:
        return AnkTransaction(
            wallet_id=wallet.id,
            amount=amount,
            type=tx_type,
            origin=origin,
            related_user_id=related_user_id,
            description=description,
        )
