import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.wallet.model import TransactionOrigin, TransactionType


class SpendRequest(BaseModel):
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=255)


class WalletRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    points: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnkTransactionRead(BaseModel):
    id: uuid.UUID
    wallet_id: uuid.UUID
    amount: int
    type: TransactionType
    origin: TransactionOrigin
    related_user_id: uuid.UUID | None
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
