import enum as PyEnum
import uuid
from datetime import date, datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.shared.models.base import UUIDTimestampMixin


class BonusTransactionType(str, PyEnum):
    credit = "credit"
    debit = "debit"


class BonusSource(str, PyEnum):
    bonus = "bonus"
    ank_conversion = "ank_conversion"


class ZoBalance(Base, UUIDTimestampMixin):
    __tablename__ = "zo_balances"
    __table_args__ = (
        CheckConstraint("bonus_points >= 0", name="ck_zo_balances_bonus_nonneg"),
        CheckConstraint(
            "converted_zo_points >= 0",
            name="ck_zo_balances_converted_nonneg",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    bonus_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    converted_zo_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class BonusRule(Base, UUIDTimestampMixin):
    __tablename__ = "bonus_rules"
    __table_args__ = (CheckConstraint("points >= 0", name="ck_bonus_rules_points_nonneg"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    transaction_type: Mapped[BonusTransactionType] = mapped_column(
        Enum(BonusTransactionType),
        nullable=False,
        default=BonusTransactionType.credit,
        server_default="credit",
    )
    source: Mapped[BonusSource] = mapped_column(
        String(32),
        nullable=False,
        default=BonusSource.bonus,
        server_default="bonus",
    )

    owner = relationship("User", foreign_keys=[user_id], lazy="selectin")


class BonusCode(Base, UUIDTimestampMixin):
    __tablename__ = "bonus_codes"
    __table_args__ = (CheckConstraint("ank_points > 0", name="ck_bonus_codes_ank_points_pos"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    ank_points: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    used_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    creator = relationship("User", foreign_keys=[created_by], lazy="selectin")
    redeemer = relationship("User", foreign_keys=[used_by], lazy="selectin")


class DailyBonusClaim(Base, UUIDTimestampMixin):
    __tablename__ = "daily_bonus_claims"
    __table_args__ = (UniqueConstraint("user_id", "claim_date", name="uq_daily_bonus_user_date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak_day: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)


class DailyQuestion(Base, UUIDTimestampMixin):
    __tablename__ = "daily_questions"

    question_text: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    answers = relationship("DailyQuestionAnswer", back_populates="question", lazy="selectin")


class DailyQuestionAnswer(Base, UUIDTimestampMixin):
    __tablename__ = "daily_question_answers"
    __table_args__ = (UniqueConstraint("user_id", "answer_date", "question_id", name="uq_daily_question_user_date_question"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("daily_questions.id", ondelete="CASCADE"), nullable=False)
    answer_date: Mapped[date] = mapped_column(Date, nullable=False)
    answer_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    question = relationship("DailyQuestion", back_populates="answers", lazy="selectin")
    owner = relationship("User", foreign_keys=[user_id], lazy="selectin")
