import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WalletRequestStatus(str, PyEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class WalletRequest(Base):
    __tablename__ = "wallet_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    motif: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    amount_ank: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[WalletRequestStatus] = mapped_column(
        Enum(WalletRequestStatus), default=WalletRequestStatus.pending, nullable=False
    )
    admin_note: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
