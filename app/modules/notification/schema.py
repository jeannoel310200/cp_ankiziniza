import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.notification.model import NotificationType


class CreateNotification(BaseModel):
    to_user_id: uuid.UUID
    type: NotificationType
    message: str
    from_user_id: uuid.UUID | None = None


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: NotificationType
    message: str
    from_user_id: uuid.UUID | None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UnreadCountRead(BaseModel):
    count: int
