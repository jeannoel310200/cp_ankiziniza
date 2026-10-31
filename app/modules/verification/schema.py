import uuid
from datetime import date, datetime

from app.modules.verification.model import VerificationStatus
from pydantic import BaseModel, ConfigDict


class VerificationRequestRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    birth_date: date
    extra_info: str | None
    status: VerificationStatus
    admin_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class VerificationReject(BaseModel):
    admin_note: str
