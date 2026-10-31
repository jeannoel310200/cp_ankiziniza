from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.model import RefreshSession


class RefreshSessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: UUID, jti: str, expires_at: datetime) -> RefreshSession:
        session = RefreshSession(
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_by_jti(self, jti: str) -> RefreshSession | None:
        result = await self.db.execute(
            select(RefreshSession).where(RefreshSession.jti == jti)
        )
        return result.scalar_one_or_none()

    async def revoke(self, jti: str) -> None:
        session = await self.get_by_jti(jti)
        if session:
            session.revoked = True
            await self.db.commit()
