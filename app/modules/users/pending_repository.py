from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.pending_model import PendingRegistration


class PendingRegistrationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> PendingRegistration | None:
        result = await self.db.execute(
            select(PendingRegistration).where(PendingRegistration.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> PendingRegistration | None:
        result = await self.db.execute(
            select(PendingRegistration).where(PendingRegistration.code_verification == code)
        )
        return result.scalar_one_or_none()

    async def list_expired(self, expired_before: datetime) -> list[PendingRegistration]:
        result = await self.db.execute(
            select(PendingRegistration).where(PendingRegistration.created_at <= expired_before)
        )
        return list(result.scalars().all())

    async def create(self, data: dict) -> PendingRegistration:
        pending = PendingRegistration(**data)
        self.db.add(pending)
        await self.db.commit()
        await self.db.refresh(pending)
        return pending

    async def update(self, pending: PendingRegistration, data: dict) -> PendingRegistration:
        for key, value in data.items():
            setattr(pending, key, value)
        await self.db.commit()
        await self.db.refresh(pending)
        return pending

    async def delete(self, pending: PendingRegistration) -> None:
        await self.db.delete(pending)
        await self.db.commit()
