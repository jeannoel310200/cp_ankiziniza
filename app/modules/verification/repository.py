import uuid
from sqlalchemy import func, select

from app.modules.verification.model import VerificationRequest, VerificationStatus


class VerificationRepository:
    def __init__(self, db):
        self.db = db

    async def create(self, data: dict) -> VerificationRequest:
        req = VerificationRequest(**data)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def get_latest_by_user(self, user_id: uuid.UUID) -> VerificationRequest | None:
        """Dernière demande de l'utilisateur, quel que soit son statut.

        `get_pending_by_user` ne voit que les demandes en cours : il ne permet
        pas de distinguer « jamais demandé » d'une demande rejetée, ce dont le
        client a besoin pour savoir s'il propose le bouton d'envoi.
        """
        result = await self.db.execute(
            select(VerificationRequest)
            .where(VerificationRequest.user_id == user_id)
            .order_by(VerificationRequest.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pending_by_user(self, user_id: uuid.UUID) -> VerificationRequest | None:
        result = await self.db.execute(
            select(VerificationRequest).where(
                VerificationRequest.user_id == user_id,
                VerificationRequest.status == VerificationStatus.pending,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, request_id: uuid.UUID) -> VerificationRequest | None:
        result = await self.db.execute(
            select(VerificationRequest).where(VerificationRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def list_pending(self, offset: int, limit: int) -> tuple[list[VerificationRequest], int]:
        base_q = select(VerificationRequest).where(
            VerificationRequest.status == VerificationStatus.pending
        )
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(
            base_q.order_by(VerificationRequest.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def update(self, req: VerificationRequest, data: dict) -> VerificationRequest:
        for key, value in data.items():
            setattr(req, key, value)
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req
