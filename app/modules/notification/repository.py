import uuid

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update

from app.modules.notification.model import Notification


class NotificationRepository:
    def __init__(self, db):
        self.db = db

    async def create(
        self,
        to_user_id: uuid.UUID,
        type_: str,
        message: str,
        from_user_id: uuid.UUID | None = None,
    ) -> Notification:
        notif = Notification(
            to_user_id=to_user_id, type=type_, message=message, from_user_id=from_user_id
        )
        self.db.add(notif)
        await self.db.commit()
        await self.db.refresh(notif)
        return notif

    async def list_by_user(
        self, user_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        result = await self.db.execute(
            select(Notification)
            .where(Notification.to_user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    async def mark_as_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_all_as_read(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Notification)
            .where(Notification.to_user_id == user_id, Notification.is_read == False)  # noqa: E712
            .values(is_read=True)
        )
        await self.db.commit()

    async def delete(self, notification: Notification) -> None:
        await self.db.delete(notification)
        await self.db.commit()

    async def delete_all_by_user(self, user_id: uuid.UUID) -> None:
        # Le filtre sur to_user_id porte la sécurité : aucune notification
        # d'un autre utilisateur ne peut être atteinte.
        await self.db.execute(
            sql_delete(Notification).where(Notification.to_user_id == user_id)
        )
        await self.db.commit()

    async def count_unread(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.to_user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
        return result.scalar_one()
