import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.shared.models.base import UUIDTimestampMixin


class TransactionType(str, enum.Enum):
    credit = "credit"
    debit = "debit"


class TransactionOrigin(str, enum.Enum):
    recharge = "recharge"
    consultation_paid = "consultation_paid"
    consultation_revenue = "consultation_revenue"
    transfer = "transfer"
    bonus = "bonus"
    withdrawal = "withdrawal"


class Wallet(Base, UUIDTimestampMixin):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("points >= 0", name="ck_wallets_points_nonneg"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    transactions: Mapped[list["AnkTransaction"]] = relationship(
        "AnkTransaction", back_populates="wallet", lazy="selectin"
    )


class AnkTransaction(Base, UUIDTimestampMixin):
    __tablename__ = "ank_transactions"

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    origin: Mapped[TransactionOrigin] = mapped_column(
        Enum(TransactionOrigin), nullable=False
    )
    related_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="transactions")
