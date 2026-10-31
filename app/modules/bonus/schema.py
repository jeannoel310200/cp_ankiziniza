import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class BonusRead(BaseModel):
    id: uuid.UUID
    reason: str
    points: int
    description: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BonusBalanceRead(BaseModel):
    total_points: int


class BonusConversionRequest(BaseModel):
    points: int  # nombre de points ANK (wallet) à convertir en ZO (bonus)


class BonusConversionResult(BaseModel):
    wallet_points_converted: int
    bonus_points_credited: int
    remaining_wallet_balance: int


class PurchaseCodeCreate(BaseModel):
    ank_points: int = Field(gt=0)
    expires_at: datetime | None = None


class PurchaseCodeRead(BaseModel):
    id: uuid.UUID
    code: str
    ank_points: int
    is_used: bool
    expires_at: datetime | None
    used_at: datetime | None
    created_by: uuid.UUID | None
    used_by: uuid.UUID | None
    is_expired: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseWithCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class PurchaseWithCodeResult(BaseModel):
    code: str
    credited_ank_points: int
    wallet_points_balance: int


class DailyBonusStatus(BaseModel):
    awarded_today: bool
    points_today: int
    streak_day: int
    next_points: int


class DailyBonusClaimResult(DailyBonusStatus):
    awarded_points: int
    balance: int


class DailyQuestionRead(BaseModel):
    id: uuid.UUID
    question_text: str
    answered_today: bool


class DailyQuestionItem(BaseModel):
    id: uuid.UUID
    question_text: str
    answered_today: bool


class DailyQuestionsRead(BaseModel):
    questions: list[DailyQuestionItem]
    completed_today: bool


class AdminDailyQuestionCreate(BaseModel):
    question_text: str = Field(min_length=1, max_length=512)


class AdminDailyQuestionUpdate(BaseModel):
    question_text: str | None = Field(default=None, min_length=1, max_length=512)
    is_active: bool | None = None


class AdminDailyQuestionRead(BaseModel):
    id: uuid.UUID
    question_text: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AdminDailyAnswerRead(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question_text: str
    user_id: uuid.UUID
    user_name: str
    user_email: str
    answer_text: str
    answer_date: date
    points_awarded: int
    created_at: datetime


class DailyQuestionAnswerRequest(BaseModel):
    question_id: uuid.UUID
    answer: str = Field(min_length=1, max_length=1000)


class DailyQuestionAnswerResult(BaseModel):
    awarded_points: int
    balance: int
