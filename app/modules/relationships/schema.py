from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.relationships.model import RelationshipRequestStatus, RelationshipStatusEnum
from app.modules.users.schema import UserPublicRead


class RelationshipStatusRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
#    user_id: UUID
    status: RelationshipStatusEnum
    partner: UserPublicRead | None = None
    created_at: datetime
    updated_at: datetime


class RelationshipStatusUpdate(BaseModel):
    status: RelationshipStatusEnum


class RelationshipRequestCreate(BaseModel):
    target_id: UUID


class RelationshipRequestRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    requester: UserPublicRead
    target: UserPublicRead
    status: RelationshipRequestStatus
    created_at: datetime
    updated_at: datetime


class RelationshipRequestRespond(BaseModel):
    accept: bool


class RelationshipSummaryRead(BaseModel):
    status: RelationshipStatusEnum
    pending_incoming: int
    accepted_count: int
    profile_views: int
