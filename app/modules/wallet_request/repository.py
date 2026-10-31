import uuid

from sqlalchemy import func, select

from app.modules.users.model import User
from app.modules.wallet_request.model import WalletRequest, WalletRequestStatus


class WalletRequestRepository:
    def __init__(self, db):
        self.db = db

    async def create(self, data: dict) -> WalletRequest:
        req = WalletRequest(**data)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def get_by_id(self, request_id: uuid.UUID) -> WalletRequest | None:
        result = await self.db.execute(
            select(WalletRequest).where(WalletRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[WalletRequest]:
        result = await self.db.execute(
            select(WalletRequest)
            .where(WalletRequest.user_id == user_id)
            .order_by(WalletRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending(
        self, offset: int, limit: int
    ) -> tuple[list[tuple[WalletRequest, User]], int]:
        """Jointe à User (pas de relationship() déclarée sur WalletRequest,
        même approche que UserRepository.get_public_status_by_code) : la
        liste admin a besoin du nom/email du demandeur, pas juste son id."""
        filter_clause = WalletRequest.status == WalletRequestStatus.pending
        total_result = await self.db.execute(
            select(func.count()).select_from(WalletRequest).where(filter_clause)
        )
        total = total_result.scalar_one()
        result = await self.db.execute(
            select(WalletRequest, User)
            .join(User, User.id == WalletRequest.user_id)
            .where(filter_clause)
            .order_by(WalletRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all()), total

    async def update(self, req: WalletRequest, data: dict) -> WalletRequest:
        for key, value in data.items():
            setattr(req, key, value)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req
