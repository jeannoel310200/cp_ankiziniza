import uuid

from sqlalchemy import func, select

from app.modules.account_deletion.model import AccountDeletionRequest, AccountDeletionStatus


class AccountDeletionRepository:
    def __init__(self, db):
        self.db = db

    async def create(self, data: dict) -> AccountDeletionRequest:
        req = AccountDeletionRequest(**data)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def get_latest_by_user_id(self, user_id: uuid.UUID) -> AccountDeletionRequest | None:
        """Dernière demande de l'utilisateur, quel que soit son statut —
        distingue « jamais demandé » d'une demande annulée (cf.
        VerificationRepository.get_latest_by_user, même raisonnement)."""
        result = await self.db.execute(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.user_id == user_id)
            .order_by(AccountDeletionRequest.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pending_by_user_id(self, user_id: uuid.UUID) -> AccountDeletionRequest | None:
        result = await self.db.execute(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id,
                AccountDeletionRequest.status == AccountDeletionStatus.pending,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, request_id: uuid.UUID) -> AccountDeletionRequest | None:
        result = await self.db.execute(
            select(AccountDeletionRequest).where(AccountDeletionRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def list_pending(
        self, offset: int, limit: int
    ) -> tuple[list[AccountDeletionRequest], int]:
        base_q = select(AccountDeletionRequest).where(
            AccountDeletionRequest.status == AccountDeletionStatus.pending
        )
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(
            base_q.order_by(AccountDeletionRequest.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def update(self, req: AccountDeletionRequest, data: dict) -> AccountDeletionRequest:
        for key, value in data.items():
            setattr(req, key, value)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req
