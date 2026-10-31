import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bonus.model import (
    BonusCode,
    BonusRule,
    BonusSource,
    BonusTransactionType,
    DailyBonusClaim,
    DailyQuestion,
    DailyQuestionAnswer,
    ZoBalance,
)


class BonusRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # app/modules/bonus/repository.py

    async def create(
        self,
        user_id: uuid.UUID | str,
        reason: str,
        points: int,
        description: str | None = None,
        transaction_type: BonusTransactionType = BonusTransactionType.credit,
        source: BonusSource = BonusSource.bonus,
        commit: bool = True,
    ) -> BonusRule:
        if points < 0:
            raise ValueError(
                "points must always be positive; use transaction_type to indicate debit"
            )

        normalized_user_id = (
            user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        )
        balance = await self._get_or_create_zo_balance(
            normalized_user_id, lock=True
        )
        delta = points if transaction_type == BonusTransactionType.credit else -points
        if source == BonusSource.ank_conversion:
            balance.converted_zo_points += delta
        else:
            balance.bonus_points += delta

        bonus = BonusRule(
            user_id=normalized_user_id,
            reason=reason,
            points=points,
            description=description,
            transaction_type=transaction_type,
            source=source,
        )
        self.db.add(bonus)
        if commit:
            await self.db.commit()
            await self.db.refresh(bonus)
        else:
            await self.db.flush()
        return bonus

    async def _get_zo_balance(
        self, user_id: uuid.UUID, *, lock: bool = False
    ) -> ZoBalance | None:
        query = select(ZoBalance).where(ZoBalance.user_id == user_id)
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _get_or_create_zo_balance(
        self, user_id: uuid.UUID, *, lock: bool = False
    ) -> ZoBalance:
        balance = await self._get_zo_balance(user_id, lock=lock)
        if balance is None:
            balance = ZoBalance(user_id=user_id)
            self.db.add(balance)
            await self.db.flush()
        return balance

    async def list_by_user(self, user_id: uuid.UUID | str) -> list[BonusRule]:
        result = await self.db.execute(
            select(BonusRule)
            .where(BonusRule.user_id == user_id)
            .order_by(BonusRule.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_points_by_source(
        self, user_id: uuid.UUID | str, *, lock: bool = False
    ) -> dict[BonusSource, int]:
        normalized_user_id = (
            user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        )
        balance = await self._get_zo_balance(normalized_user_id, lock=lock)
        if balance is None:
            return {
                BonusSource.bonus: 0,
                BonusSource.ank_conversion: 0,
            }
        return {
            BonusSource.bonus: balance.bonus_points,
            BonusSource.ank_conversion: balance.converted_zo_points,
        }

    async def get_total_points(self, user_id: uuid.UUID | str) -> int:
        balances = await self.get_points_by_source(user_id)
        return sum(balances.values())

    async def get_code_by_value(self, code: str) -> BonusCode | None:
        result = await self.db.execute(select(BonusCode).where(BonusCode.code == code))
        return result.scalar_one_or_none()

    async def list_codes(self, offset: int, limit: int) -> tuple[list[BonusCode], int]:
        base_q = select(BonusCode).order_by(BonusCode.created_at.desc())
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(base_q.offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def consume_code(self, code_id: uuid.UUID, used_by: uuid.UUID, used_at: datetime) -> bool:
        result = await self.db.execute(
            update(BonusCode)
            .where(BonusCode.id == code_id, BonusCode.is_used.is_(False))
            .values(is_used=True, used_by=used_by, used_at=used_at)
        )
        return result.rowcount == 1

    async def create_code(
        self,
        code: str,
        ank_points: int,
        created_by: uuid.UUID,
        expires_at: datetime | None = None,
    ) -> BonusCode:
        bonus_code = BonusCode(
            code=code,
            ank_points=ank_points,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.db.add(bonus_code)
        await self.db.commit()
        await self.db.refresh(bonus_code)
        return bonus_code

    async def commit(self) -> None:
        await self.db.commit()

    async def get_daily_claim(self, user_id: uuid.UUID, claim_date: date) -> DailyBonusClaim | None:
        result = await self.db.execute(select(DailyBonusClaim).where(DailyBonusClaim.user_id == user_id, DailyBonusClaim.claim_date == claim_date))
        return result.scalar_one_or_none()

    async def get_last_daily_claim(self, user_id: uuid.UUID) -> DailyBonusClaim | None:
        result = await self.db.execute(select(DailyBonusClaim).where(DailyBonusClaim.user_id == user_id).order_by(DailyBonusClaim.claim_date.desc()).limit(1))
        return result.scalar_one_or_none()

    async def create_daily_claim(self, user_id: uuid.UUID, claim_date: date, streak_day: int, points: int) -> DailyBonusClaim:
        claim = DailyBonusClaim(user_id=user_id, claim_date=claim_date, streak_day=streak_day, points=points)
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def get_question_for_date(self, day: date) -> DailyQuestion | None:
        questions = await self.list_active_questions()
        return questions[day.toordinal() % len(questions)] if questions else None

    async def list_active_questions(self) -> list[DailyQuestion]:
        result = await self.db.execute(select(DailyQuestion).where(DailyQuestion.is_active.is_(True)).order_by(DailyQuestion.created_at, DailyQuestion.id))
        return list(result.scalars().all())

    async def list_questions(self, offset: int, limit: int) -> tuple[list[DailyQuestion], int]:
        base_q = select(DailyQuestion).order_by(DailyQuestion.created_at.desc())
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(base_q.offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def get_question(self, question_id: uuid.UUID) -> DailyQuestion | None:
        result = await self.db.execute(select(DailyQuestion).where(DailyQuestion.id == question_id))
        return result.scalar_one_or_none()

    async def create_question(self, question_text: str) -> DailyQuestion:
        question = DailyQuestion(question_text=question_text.strip())
        self.db.add(question)
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def save_question(self, question: DailyQuestion) -> DailyQuestion:
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def get_daily_answer(self, user_id: uuid.UUID, answer_date: date) -> DailyQuestionAnswer | None:
        result = await self.db.execute(select(DailyQuestionAnswer).where(DailyQuestionAnswer.user_id == user_id, DailyQuestionAnswer.answer_date == answer_date))
        return result.scalar_one_or_none()

    async def create_daily_answer(self, user_id: uuid.UUID, question_id: uuid.UUID, answer_date: date, answer_text: str, points: int) -> DailyQuestionAnswer:
        answer = DailyQuestionAnswer(user_id=user_id, question_id=question_id, answer_date=answer_date, answer_text=answer_text, points_awarded=points)
        self.db.add(answer)
        await self.db.flush()
        return answer

    async def list_daily_answers(
        self, offset: int, limit: int, answer_date: date | None = None
    ) -> tuple[list[DailyQuestionAnswer], int]:
        base_q = select(DailyQuestionAnswer).order_by(DailyQuestionAnswer.created_at.desc())
        if answer_date:
            base_q = base_q.where(DailyQuestionAnswer.answer_date == answer_date)
        total_result = await self.db.execute(select(func.count()).select_from(base_q.subquery()))
        total = total_result.scalar_one()
        result = await self.db.execute(base_q.offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def list_daily_answers_for_user(self, user_id: uuid.UUID, answer_date: date) -> list[DailyQuestionAnswer]:
        result = await self.db.execute(select(DailyQuestionAnswer).where(DailyQuestionAnswer.user_id == user_id, DailyQuestionAnswer.answer_date == answer_date))
        return list(result.scalars().all())
