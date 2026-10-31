import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccountDeletionStatus(str, PyEnum):
    pending = "pending"
    deleted = "deleted"
    cancelled = "cancelled"


class AccountDeletionRequest(Base):
    __tablename__ = "account_deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # `SET NULL` (pas `CASCADE` comme verification/wallet_request) : cette
    # ligne doit survivre à la suppression du compte pour rester une trace
    # d'audit de la demande elle-même, une fois le compte effacé.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Copiés au moment de la demande : restent lisibles même après que
    # `user_id` soit passé à NULL (compte supprimé).
    email: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[AccountDeletionStatus] = mapped_column(
        Enum(AccountDeletionStatus), default=AccountDeletionStatus.pending, nullable=False
    )
    admin_note: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
