import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(str, PyEnum):
    bonus_received = "bonus_received"
    ank_received = "ank_received"
    profile_searched = "profile_searched"
    friend_request_received = "friend_request_received"
    friend_request_accepted = "friend_request_accepted"
    friend_request_rejected = "friend_request_rejected"
    account_verified = "account_verified"
    verification_rejected = "verification_rejected"
    relationship_ended = "relationship_ended"
    code_regenerated = "code_regenerated"
    partner_viewed = "partner_viewed"
    wallet_request_approved = "wallet_request_approved"
    wallet_request_rejected = "wallet_request_rejected"
    account_deletion_cancelled = "account_deletion_cancelled"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # destinataire (obligatoire)
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # émetteur (optionnel : un bonus n'a pas d'expéditeur humain, une recherche/demande oui)
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
