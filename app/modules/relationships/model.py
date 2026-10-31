import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.shared.models.base import UUIDTimestampMixin


class RelationshipStatusEnum(str, enum.Enum):
    single = "single"
    in_couple = "in_couple"
    married = "married"
    divorced = "divorced"
    widowed = "widowed"


class RelationshipRequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class RelationshipStatus(Base, UUIDTimestampMixin):
    __tablename__ = "relationship_statuses"

    
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    status: Mapped[RelationshipStatusEnum] = mapped_column(
        Enum(RelationshipStatusEnum),
        nullable=False,
        default=RelationshipStatusEnum.single,
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    partner = relationship("User", foreign_keys=[partner_id], lazy="selectin")

    # Empêche de créer deux fois la même relation exacte
    __table_args__ = (
        UniqueConstraint('user_id', 'partner_id', name='_user_partner_uc'),
    )


class RelationshipRequest(Base, UUIDTimestampMixin):
    __tablename__ = "relationship_requests"

    __table_args__ = (
        UniqueConstraint("requester_id", "target_id", name="uq_relationship_request"),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RelationshipRequestStatus] = mapped_column(
        Enum(RelationshipRequestStatus),
        nullable=False,
        default=RelationshipRequestStatus.pending,
    )

    requester = relationship("User", foreign_keys=[requester_id], lazy="selectin")
    target = relationship("User", foreign_keys=[target_id], lazy="selectin")
