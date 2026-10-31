import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.wallet_request.model import WalletRequestStatus


class WalletRequestCreate(BaseModel):
    # Le mobile ne collecte plus de motif (le contexte "retrait" suffit) —
    # le service en assigne un générique quand absent (cf. service.py).
    motif: str | None = Field(default=None, max_length=1000)
    phone: str = Field(min_length=1, max_length=32)
    amount_ank: int = Field(gt=0)


class WalletRequestRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    motif: str
    phone: str
    amount_ank: int
    status: WalletRequestStatus
    admin_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WalletRequestReject(BaseModel):
    admin_note: str = Field(min_length=1)


class WalletRequestAdminRead(WalletRequestRead):
    """Variante admin de WalletRequestRead avec l'identité du demandeur —
    sans ça la liste admin n'affiche qu'un user_id opaque."""

    user_name: str
    user_email: str
