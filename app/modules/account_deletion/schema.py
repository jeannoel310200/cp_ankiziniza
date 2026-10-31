import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.account_deletion.model import AccountDeletionStatus


class AccountDeletionCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AccountDeletionRequestRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    email: str
    full_name: str
    reason: str | None
    status: AccountDeletionStatus
    admin_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AccountDeletionCancel(BaseModel):
    admin_note: str = Field(min_length=1)
