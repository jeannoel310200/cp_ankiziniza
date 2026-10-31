import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.relationships.model import (
    RelationshipRequest,
    RelationshipRequestStatus,
    RelationshipStatus,
    RelationshipStatusEnum,
)


class RelationshipStatusRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: uuid.UUID) -> RelationshipStatus | None:
        result = await self.db.execute(
            select(RelationshipStatus).where(RelationshipStatus.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: uuid.UUID,
        status: RelationshipStatusEnum,
        partner_id: uuid.UUID | None,
    ) -> RelationshipStatus:
        existing = await self.get_by_user_id(user_id)
        if existing:
            existing.status = status
            existing.partner_id = partner_id
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        record = RelationshipStatus(user_id=user_id, status=status, partner_id=partner_id)
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record


class RelationshipRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, request_id: uuid.UUID) -> RelationshipRequest | None:
        result = await self.db.execute(
            select(RelationshipRequest).where(RelationshipRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def get_existing(
        self, requester_id: uuid.UUID, target_id: uuid.UUID
    ) -> RelationshipRequest | None:
        result = await self.db.execute(
            select(RelationshipRequest).where(
                RelationshipRequest.requester_id == requester_id,
                RelationshipRequest.target_id == target_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_incoming(self, user_id: uuid.UUID) -> list[RelationshipRequest]:
        result = await self.db.execute(
            select(RelationshipRequest).where(
                RelationshipRequest.target_id == user_id,
                RelationshipRequest.status == RelationshipRequestStatus.pending,
            )
        )
        return list(result.scalars().all())

    async def list_outgoing(self, user_id: uuid.UUID) -> list[RelationshipRequest]:
        result = await self.db.execute(
            select(RelationshipRequest).where(
                RelationshipRequest.requester_id == user_id,
                RelationshipRequest.status == RelationshipRequestStatus.pending,
            )
        )
        return list(result.scalars().all())

    async def create(
        self, requester_id: uuid.UUID, target_id: uuid.UUID
    ) -> RelationshipRequest:
        req = RelationshipRequest(requester_id=requester_id, target_id=target_id)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def update_status(
        self, request: RelationshipRequest, new_status: RelationshipRequestStatus
    ) -> RelationshipRequest:
        request.status = new_status
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def delete(self, request: RelationshipRequest) -> None:
        await self.db.delete(request)
        await self.db.commit()

    async def count_incoming_pending(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(RelationshipRequest).where(
                RelationshipRequest.target_id == user_id,
                RelationshipRequest.status == RelationshipRequestStatus.pending,
            )
        )
        return result.scalar_one()

    async def count_accepted(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(RelationshipRequest).where(
                RelationshipRequest.status == RelationshipRequestStatus.accepted,
                or_(
                    RelationshipRequest.requester_id == user_id,
                    RelationshipRequest.target_id == user_id,
                ),
            )
        )
        return result.scalar_one()

    async def list_related_user_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """IDs des utilisateurs déjà en relation (pending ou accepted) avec
        user_id, dans un sens comme dans l'autre. Utilisé pour exclure des
        suggestions quelqu'un déjà sollicité ou déjà accepté (cf.
        UserService.get_suggestions)."""
        result = await self.db.execute(
            select(RelationshipRequest.requester_id, RelationshipRequest.target_id).where(
                or_(
                    RelationshipRequest.requester_id == user_id,
                    RelationshipRequest.target_id == user_id,
                ),
                RelationshipRequest.status.in_(
                    [RelationshipRequestStatus.pending, RelationshipRequestStatus.accepted]
                ),
            )
        )
        related_ids: set[uuid.UUID] = set()
        for requester_id, target_id in result.all():
            related_ids.add(target_id if requester_id == user_id else requester_id)
        return related_ids


    async def get_current_relationship(self, user_id: uuid.UUID) -> RelationshipStatus:
        result = await self.db.execute(
            select(RelationshipStatus).where(
                RelationshipStatus.user_id == user_id,  
            )
        )
        return result.scalars().first()

