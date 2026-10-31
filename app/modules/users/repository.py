import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # <-- À AJOUTER

from app.modules.profile.model import Profile
from app.modules.relationships.model import RelationshipStatus
from app.modules.users.model import GenderEnum, User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        normalized = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        query = select(User).where(User.id == normalized).options(selectinload(User.profile))
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()
        return user

    async def delete_user_by_email(self, email: str):
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            await self.db.delete(user)
            await self.db.commit()
            return True

        return False

    async def code_verification(self, code: str):
        result = await self.db.execute(select(User).where(User.code_verification == code))
        return result.scalar_one_or_none()

    async def get_email_token(self, email: str):
        result = await self.db.execute(select(User.email_token).where(User.email == email))
        return result.scalar_one_or_none()

    async def verified_column(self, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(select(User.verified_after_forgot_password).where(User.id==user_id))
        return result.scalar_one_or_none()

    async def get_password_token(self, email: str):
        result = await self.db.execute(select(User.forgot_password_token).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email).options(selectinload(User.profile))
        )
        return result.scalar_one_or_none()

    async def get_email_update_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(User.updated_email_date).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_phone_update_date(self, user_id: uuid.UUID) -> datetime | None:
        result = await self.db.execute(select(User.updated_phone_date).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.code_user == code.upper()).options(selectinload(User.profile))
        )
        return result.scalar_one_or_none()

    async def get_by_code_verification(self, code: str) -> User | None:
        result = await self.db.execute(select(User).where(User.forgot_password_code == code))
        return result.scalar_one_or_none()

    async def get_public_status_by_code(
        self, code: str
    ) -> tuple[User, RelationshipStatus | None] | None:
        result = await self.db.execute(
            select(User, RelationshipStatus)
            .outerjoin(RelationshipStatus, RelationshipStatus.user_id == User.id)
            .where(User.code_user == code.upper())
        )
        row = result.first()
        if row is None:
            return None
        user, rel_status = row
        return user, rel_status

    async def get_status_by_user_id(
        self, user_id: uuid.UUID
    ) -> tuple[User, RelationshipStatus | None] | None:
        result = await self.db.execute(
            select(User, RelationshipStatus)
            .outerjoin(RelationshipStatus, RelationshipStatus.user_id == User.id)
            .where(User.id == user_id)
        )
        row = result.first()
        if row is None:
            return None
        user, rel_status = row
        return user, rel_status

    async def list_with_expired_code_search(self, expired_before: datetime) -> list[User]:
        """Utilisateurs dont le code a été recherché par un tiers avant
        `expired_before` et n'a jamais été régénéré depuis — candidats à la
        régénération automatique (cf. UserService.regenerate_expired_codes)."""
        result = await self.db.execute(
            select(User).where(
                User.code_first_searched_at.is_not(None),
                User.code_first_searched_at <= expired_before,
            )
        )
        return list(result.scalars().all())

    async def increment_profile_views(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(User).where(User.id == user_id).values(profile_views=User.profile_views + 1)
        )
        await self.db.commit()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def get_number(self, user_id: uuid.UUID) -> int:
        date = await self.db.execute(select(User.using_code_user).where(User.id == user_id))
        return date.scalar_one()

    async def search_by_name(
        self, current_id: str | uuid.UUID, name: str, offset: int, limit: int
    ) -> tuple[list[User], int]:
        normalized = current_id if isinstance(current_id, uuid.UUID) else uuid.UUID(str(current_id))
        pattern = f"%{name}%"
        base_q = (
            select(User)
            .where(or_(User.first_name.ilike(pattern), User.last_name.ilike(pattern)))
            .where(User.id != normalized)
        )
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(
            base_q.options(selectinload(User.profile)).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_suggestions(
        self,
        current_user_id: uuid.UUID,
        opposite_gender: GenderEnum,
        exclude_ids: set[uuid.UUID],
        offset: int,
        limit: int,
    ) -> tuple[list[User], int]:
        """Mirroir de search_by_name (même forme total+items) pour les
        suggestions du sexe opposé, en excluant le demandeur et les ids déjà
        en relation (cf. UserService.get_suggestions)."""
        base_q = (
            select(User)
            .where(User.gender == opposite_gender)
            .where(User.id != current_user_id)
        )
        if exclude_ids:
            base_q = base_q.where(User.id.notin_(exclude_ids))
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(
            base_q.options(selectinload(User.profile))
            .order_by(User.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def list(
        self, offset: int, limit: int, q: str | None = None
    ) -> tuple[list[User], int]:
        base_q = select(User)
        if q:
            pattern = f"%{q}%"
            base_q = base_q.where(
                or_(
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(
            base_q.options(selectinload(User.profile)).offset(offset).limit(limit)
        )
        return result.scalars().all(), total  # type: ignore[return-value]

    async def create_profile(self, data: dict) -> Profile:
        profile = Profile(**data)

        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    async def create(self, data: dict) -> User:
        user = User(**data)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update(self, user: User, data: dict) -> User:
        for key, value in data.items():
            setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        await self.db.delete(user)
        await self.db.commit()

    async def get_by_provider(self, provider: str, provider_id: str):
        """Cherche un utilisateur par son lien OAuth (provider + provider_id)."""
        result = await self.db.execute(
            select(User).where(
                User.provider == provider,
                User.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()
