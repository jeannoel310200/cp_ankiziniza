import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.schema import NotificationRead, UnreadCountRead
from app.modules.notification.service import NotificationService
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.shared.dependencies.auth import get_current_user

router = APIRouter(prefix="/views_notifications", tags=["Notifications "])


def _get_notification_service(db: AsyncSession = Depends(get_db)):
    return NotificationService(NotificationRepository(db=db))


@router.get("/notifications", response_model=list[NotificationRead])
async def list_notifications(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    return await service.get_my_notifications(current_user.id)


@router.get("/notifications/unread-count", response_model=UnreadCountRead)
async def unread_count(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    return await service.get_unread_count(current_user.id)


@router.patch("/notifications/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    return await service.mark_as_read(notification_id, current_user.id)


@router.patch("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    await service.mark_all_as_read(current_user.id)


@router.delete(
    "/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_notification(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    await service.delete_notification(notification_id, current_user.id)


# Vider le flux porte sur la collection, sans segment supplémentaire : une
# route « /notifications/all » entrerait en collision avec celle ci-dessus,
# `all` serait interprété comme un UUID et renverrait 422.
@router.delete("/notifications", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_notifications(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(_get_notification_service),
):
    await service.delete_all(current_user.id)
