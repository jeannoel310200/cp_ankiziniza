import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profile.model import Profile


class ProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, current_user: uuid.UUID) -> Profile | None:
        result = await self.db.execute(select(Profile).where(Profile.user_id == current_user))
        return result.scalar_one_or_none()

    async def get_first_name_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(Profile.updated_first_name_date).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_last_name_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(Profile.updated_last_name_date).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_picture_profile_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(Profile.updated_picture_profile_date).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_birth_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(Profile.updated_birth_date).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def verify_blue_badge(self, user_id:uuid.UUID) -> bool|None:
        result = await self.db.execute(select(Profile.blue_badge).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def update(self, profile: Profile, data: dict) -> Profile:
        for key, value in data.items():
            setattr(profile, key, value)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def delete(self, profile: Profile) -> None:
        await self.db.delete(profile)
        await self.db.commit()
