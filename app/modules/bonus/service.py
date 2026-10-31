import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum

from fastapi import HTTPException, status

from app.modules.bonus.model import BonusSource, BonusTransactionType
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.schema import (
    BonusBalanceRead,
    BonusConversionRequest,
    BonusConversionResult,
    BonusRead,
    PurchaseCodeCreate,
    PurchaseCodeRead,
    PurchaseWithCodeRequest,
    PurchaseWithCodeResult,
    DailyBonusStatus, DailyBonusClaimResult, DailyQuestionRead,
    DailyQuestionAnswerRequest, DailyQuestionAnswerResult, DailyQuestionItem,
    DailyQuestionsRead, AdminDailyQuestionCreate, AdminDailyQuestionUpdate,
    AdminDailyQuestionRead, AdminDailyAnswerRead,
)
from app.modules.notification.service import NotificationService
from app.modules.wallet.model import TransactionOrigin
from app.modules.wallet.repository import WalletRepository
from app.shared.schemas.pagination import Page, PaginationParams, make_page

ANK_TO_ZO_RATE = 30
BONUS_TO_WALLET_RATE = ANK_TO_ZO_RATE
_CODE_PREFIX = "ANK"
_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_RANDOM_LEN = 8
_CODE_ATTEMPTS = 10



class BonusReason(str, Enum):
    first_time = "first_time"
    quick_response = "quick_response"
    code_searched = "code_searched"
    # Prénom et nom sont éditables indépendamment (cf. ProfileService), donc
    # deux raisons distinctes plutôt qu'une seule update_profile_name : le
    # libellé doit dire lequel des deux a changé.
    update_profile_first_name = "update_profile_first_name"
    update_profile_last_name = "update_profile_last_name"
    update_user_email = "update_user_email"
    update_profile_picture = "update_profile_picture"
    update_profile_birth_date = "update_profile_birth_date"
    update_profile_phone = "update_profile_phone"
    relationship_milestone = "relationship_milestone"
    account_verified = "account_verified"
    usage_milestone = "usage_milestone"
    visite_site = "visite_site"


# Montants par raison
BONUS_POINTS: dict[BonusReason, int] = {
    BonusReason.first_time: 15,
    BonusReason.visite_site: 5,
    BonusReason.quick_response: 10,
    BonusReason.code_searched: 5,
    BonusReason.update_profile_first_name: 3,
    BonusReason.update_profile_last_name: 3,
    BonusReason.update_profile_picture: 10,
    BonusReason.update_profile_birth_date: 5,
    BonusReason.update_user_email: 10,
    BonusReason.update_profile_phone: 10,
    BonusReason.relationship_milestone: 20,
    BonusReason.account_verified: 30,
    BonusReason.usage_milestone: 10,
}

BONUS_LABELS: dict[BonusReason, str] = {
    BonusReason.first_time: "Bonus de bienvenue",
    BonusReason.visite_site: "Bonus de visite",
    BonusReason.quick_response: "Bonus pour réponse rapide (<24h)",
    BonusReason.code_searched: "Bonus pour recherche via code",
    BonusReason.update_profile_first_name: "Bonus pour la modification du prénom",
    BonusReason.update_profile_last_name: "Bonus pour la modification du nom",
    BonusReason.update_profile_picture: "Bonus pour la modification de la photo de profil",
    BonusReason.update_profile_birth_date: "Bonus pour la modification de la date de naissance",
    BonusReason.update_user_email: "Bonus pour la modification de email",
    BonusReason.update_profile_phone: "Bonus pour la modification de numéro de téléphone",
    BonusReason.relationship_milestone: "Bonus anniversaire de relation",
    BonusReason.account_verified: "Bonus vérification de compte",
    BonusReason.usage_milestone: "Bonus fidélité d'utilisation",
}


@dataclass(frozen=True)
class RevealSpendResult:
    converted_zo_used: int
    bonus_zo_used: int
    ank_rewards: dict[uuid.UUID, int]


class BonusService:
    def __init__(
        self,
        repo: BonusRepository,
        wallet_repo: WalletRepository,
        notif_service: NotificationService,
    ):
        self.repo = repo
        self.notif_service = notif_service
        self.wallet_repo = wallet_repo

    def _generate_code_value(self) -> str:
        suffix = "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_RANDOM_LEN))
        return f"{_CODE_PREFIX}-{suffix}"

    def _normalize_dt(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _to_code_read(self, code_obj) -> PurchaseCodeRead:
        now = datetime.now(UTC)
        expires_at = self._normalize_dt(code_obj.expires_at)
        is_expired = expires_at is not None and expires_at < now
        return PurchaseCodeRead(
            id=code_obj.id,
            code=code_obj.code,
            ank_points=code_obj.ank_points,
            is_used=code_obj.is_used,
            expires_at=expires_at,
            used_at=code_obj.used_at,
            created_by=code_obj.created_by,
            used_by=code_obj.used_by,
            is_expired=is_expired,
            created_at=code_obj.created_at,
        )

    async def award_bonus(self, user_id: uuid.UUID | str, reason: BonusReason) -> BonusRead:
        points = BONUS_POINTS[reason]
        label = BONUS_LABELS[reason]
        bonus = await self.repo.create(user_id, reason.value, points, label)
        await self.notif_service.notify_bonus_received(
            user_id=user_id, points=points, reason_label=label
        )
        return BonusRead.model_validate(bonus)

    async def get_my_history(self, user_id: uuid.UUID | str) -> list[BonusRead]:
        bonuses = await self.repo.list_by_user(user_id)
        return [BonusRead.model_validate(b) for b in bonuses]

    @staticmethod
    def _allocate_ank_rewards(
        converted_zo_used: int,
        reward_allocations: list[tuple[uuid.UUID, int, int]],
    ) -> dict[uuid.UUID, int]:
        """Convertit les enveloppes ZO prévues en ANK sans créer de dette.

        Chaque tuple contient le bénéficiaire, le plafond ANK et l'enveloppe
        ZO associée. Les enveloppes sont consommées dans l'ordre métier ; le
        calcul utilise ``round`` mais reste plafonné par les ZO effectivement
        consommés et par le plafond de chaque bénéficiaire.
        """
        remaining_zo = max(0, converted_zo_used)
        rewards: dict[uuid.UUID, int] = {}
        for user_id, max_ank, funding_zo in reward_allocations:
            max_ank = max(0, max_ank)
            funding_zo = max(0, funding_zo)
            if not max_ank or not funding_zo or not remaining_zo:
                continue

            funded_zo = min(remaining_zo, funding_zo)
            amount = min(
                max_ank,
                round(funded_zo / ANK_TO_ZO_RATE),
                funded_zo // ANK_TO_ZO_RATE,
            )
            if amount:
                rewards[user_id] = rewards.get(user_id, 0) + amount
            remaining_zo -= funded_zo
        return rewards

    async def spend_for_reveal(
        self,
        requester_id: uuid.UUID,
        cost_zo: int,
        description: str,
        reward_allocations: list[tuple[uuid.UUID, int, int]],
        bonus_awards: list[tuple[uuid.UUID, int, str]],
    ) -> RevealSpendResult:
        balances = await self.repo.get_points_by_source(requester_id, lock=True)
        converted_balance = max(0, balances.get(BonusSource.ank_conversion, 0))
        bonus_balance = max(0, balances.get(BonusSource.bonus, 0))
        if converted_balance + bonus_balance < cost_zo:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Insufficient ZO balance",
            )

        converted_zo_used = min(converted_balance, cost_zo)
        bonus_zo_used = cost_zo - converted_zo_used
        if converted_zo_used:
            await self.repo.create(
                requester_id,
                reason="reveal_spend",
                points=converted_zo_used,
                description=description,
                transaction_type=BonusTransactionType.debit,
                source=BonusSource.ank_conversion,
                commit=False,
            )
        if bonus_zo_used:
            await self.repo.create(
                requester_id,
                reason="reveal_spend",
                points=bonus_zo_used,
                description=description,
                transaction_type=BonusTransactionType.debit,
                source=BonusSource.bonus,
                commit=False,
            )

        ank_rewards = self._allocate_ank_rewards(
            converted_zo_used, reward_allocations
        )
        for recipient_id, amount in ank_rewards.items():
            wallet = await self.wallet_repo.get_or_create(recipient_id, commit=False)
            self.wallet_repo.flush_credit(
                wallet,
                amount,
                TransactionOrigin.transfer,
                related_user_id=requester_id,
                description=description,
            )

        if converted_zo_used:
            for recipient_id, points, label in bonus_awards:
                await self.repo.create(
                    recipient_id,
                    reason="reveal_bonus",
                    points=points,
                    description=label,
                    source=BonusSource.bonus,
                    commit=False,
                )

        await self.repo.commit()

        if converted_zo_used:
            for recipient_id, points, label in bonus_awards:
                await self.notif_service.notify_bonus_received(
                    user_id=recipient_id,
                    points=points,
                    reason_label=label,
                )

        for recipient_id, amount in ank_rewards.items():
            if amount > 0:
                await self.notif_service.notify_ank_received(
                    user_id=recipient_id,
                    points=amount,
                    reason_label=description,
                    from_user_id=requester_id,
                )

        return RevealSpendResult(
            converted_zo_used=converted_zo_used,
            bonus_zo_used=bonus_zo_used,
            ank_rewards=ank_rewards,
        )

    async def generate_purchase_code(
        self, admin_user_id: uuid.UUID, data: PurchaseCodeCreate
    ) -> PurchaseCodeRead:
        for _ in range(_CODE_ATTEMPTS):
            code_value = self._generate_code_value()
            existing = await self.repo.get_code_by_value(code_value)
            if existing is None:
                created = await self.repo.create_code(
                    code=code_value,
                    ank_points=data.ank_points,
                    created_by=admin_user_id,
                    expires_at=data.expires_at,
                )
                return self._to_code_read(created)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique ANK code",
        )

    async def list_purchase_codes(self, params: PaginationParams) -> Page[PurchaseCodeRead]:
        rows, total = await self.repo.list_codes(params.offset, params.limit)
        return make_page([self._to_code_read(row) for row in rows], total, params)

    async def purchase_with_code(
        self,
        user_id: uuid.UUID,
        data: PurchaseWithCodeRequest,
    ) -> PurchaseWithCodeResult:
        code_value = data.code.strip().upper()
        code_obj = await self.repo.get_code_by_value(code_value)
        if not code_obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")

        if code_obj.is_used:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code already used")

        now = datetime.now(UTC)
        expires_at = self._normalize_dt(code_obj.expires_at)
        if expires_at is not None and expires_at < now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired")

        wallet = await self.wallet_repo.get_or_create(user_id)
        consumed = await self.repo.consume_code(code_obj.id, user_id, now)
        if not consumed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code already used")

        self.wallet_repo.flush_credit(
            wallet,
            code_obj.ank_points,
            TransactionOrigin.bonus,
            description=f"Code redemption: {code_obj.code}",
        )
        await self.repo.commit()

        return PurchaseWithCodeResult(
            code=code_obj.code,
            credited_ank_points=code_obj.ank_points,
            wallet_points_balance=wallet.points,
        )

    async def get_my_balance(self, user_id: uuid.UUID | str) -> BonusBalanceRead:
        total = await self.repo.get_total_points(user_id)
        return BonusBalanceRead(total_points=total)

    @staticmethod
    def _daily_points(streak_day: int) -> int:
        return min(4 + streak_day, 10)

    async def daily_status(self, user_id: uuid.UUID) -> DailyBonusStatus:
        today = datetime.now(UTC).date()
        claim = await self.repo.get_daily_claim(user_id, today)
        last = await self.repo.get_last_daily_claim(user_id)
        streak = claim.streak_day if claim else 0
        if not claim and last and last.claim_date == today - timedelta(days=1):
            streak = last.streak_day
        next_streak = streak + 1 if not claim else streak
        return DailyBonusStatus(awarded_today=claim is not None, points_today=claim.points if claim else 0, streak_day=streak, next_points=self._daily_points(next_streak))

    async def daily_check_in(self, user_id: uuid.UUID) -> DailyBonusClaimResult:
        today = datetime.now(UTC).date()
        existing = await self.repo.get_daily_claim(user_id, today)
        if existing:
            balance = await self.repo.get_total_points(user_id)
            return DailyBonusClaimResult(awarded_today=True, points_today=existing.points, streak_day=existing.streak_day, next_points=existing.points, awarded_points=0, balance=balance)
        last = await self.repo.get_last_daily_claim(user_id)
        streak = last.streak_day + 1 if last and last.claim_date == today - timedelta(days=1) else 1
        points = self._daily_points(streak)
        await self.repo.create_daily_claim(user_id, today, streak, points)
        await self.repo.create(user_id, "daily_check_in", points, f"Bonus de connexion quotidienne (jour {streak})")
        await self.notif_service.notify_bonus_received(user_id, points, "Bonus de connexion quotidienne")
        balance = await self.repo.get_total_points(user_id)
        return DailyBonusClaimResult(awarded_today=True, points_today=points, streak_day=streak, next_points=self._daily_points(streak + 1), awarded_points=points, balance=balance)

    async def _today_questions(self) -> list:
        today = datetime.now(UTC).date()
        questions = await self.repo.list_active_questions()
        if not questions:
            return []
        start = today.toordinal() % len(questions)
        return [questions[(start + offset) % len(questions)] for offset in range(min(2, len(questions)))]

    async def daily_question(self, user_id: uuid.UUID) -> DailyQuestionsRead:
        today = datetime.now(UTC).date()
        questions = await self._today_questions()
        items = []
        for question in questions:
            items.append(DailyQuestionItem(id=question.id, question_text=question.question_text, answered_today=False))
        answers = await self.repo.list_daily_answers_for_user(user_id, today)
        answered_ids = {answer.question_id for answer in answers}
        items = [item.model_copy(update={"answered_today": item.id in answered_ids}) for item in items]
        return DailyQuestionsRead(questions=items, completed_today=len(answers) >= len(items) and bool(items))

    async def answer_daily_question(self, user_id: uuid.UUID, data: DailyQuestionAnswerRequest) -> DailyQuestionAnswerResult:
        today = datetime.now(UTC).date()
        questions = await self._today_questions()
        answers = await self.repo.list_daily_answers_for_user(user_id, today)
        if len(answers) >= 2:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Questions déjà terminées aujourd'hui")
        answer = data.answer.strip()
        if not answer:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La réponse ne peut pas être vide")
        # Le client envoie l'identifiant de la question pour empêcher de
        # répondre deux fois à la même question du jour.
        question_id = data.question_id
        if question_id not in {question.id for question in questions} or question_id in {a.question_id for a in answers}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Question déjà répondue ou invalide")
        await self.repo.create_daily_answer(user_id, question_id, today, answer, 15)
        await self.repo.create(user_id, "daily_question", 15, "Réponse à la question du jour")
        await self.notif_service.notify_bonus_received(user_id, 15, "Réponse à la question du jour")
        return DailyQuestionAnswerResult(awarded_points=15, balance=await self.repo.get_total_points(user_id))

    async def admin_questions(self, params: PaginationParams) -> Page[AdminDailyQuestionRead]:
        questions, total = await self.repo.list_questions(params.offset, params.limit)
        return make_page(
            [AdminDailyQuestionRead.model_validate(q) for q in questions], total, params
        )

    async def admin_create_question(self, data: AdminDailyQuestionCreate) -> AdminDailyQuestionRead:
        return AdminDailyQuestionRead.model_validate(await self.repo.create_question(data.question_text))

    async def admin_update_question(self, question_id: uuid.UUID, data: AdminDailyQuestionUpdate) -> AdminDailyQuestionRead:
        question = await self.repo.get_question(question_id)
        if not question:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question introuvable")
        if data.question_text is not None:
            question.question_text = data.question_text.strip()
        if data.is_active is not None:
            question.is_active = data.is_active
        return AdminDailyQuestionRead.model_validate(await self.repo.save_question(question))

    async def admin_delete_question(self, question_id: uuid.UUID) -> None:
        question = await self.repo.get_question(question_id)
        if not question:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question introuvable")
        question.is_active = False
        await self.repo.save_question(question)

    async def admin_answers(
        self, params: PaginationParams, answer_date: date | None = None
    ) -> Page[AdminDailyAnswerRead]:
        answers, total = await self.repo.list_daily_answers(
            params.offset, params.limit, answer_date
        )
        items = [AdminDailyAnswerRead(id=a.id, question_id=a.question_id, question_text=a.question.question_text, user_id=a.user_id, user_name=f"{a.owner.first_name} {a.owner.last_name}".strip(), user_email=a.owner.email, answer_text=a.answer_text, answer_date=a.answer_date, points_awarded=a.points_awarded, created_at=a.created_at) for a in answers]
        return make_page(items, total, params)

    async def convert_to_wallet(
        self, user_id: uuid.UUID, data: BonusConversionRequest
    ) -> BonusConversionResult:
        """Convertit des points ANK (wallet) en points ZO (bonus), au taux
        [BONUS_TO_WALLET_RATE] (1 ANK -> BONUS_TO_WALLET_RATE ZO)."""
        if data.points <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Points must be positive",
            )

        wallet = await self.wallet_repo.get_or_create(user_id)
        if wallet.points < data.points:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient wallet balance",
            )

        bonus_points_credited = data.points * BONUS_TO_WALLET_RATE

        try:
            await self.wallet_repo.debit(
                wallet,
                data.points,
                TransactionOrigin.bonus,
                description=f"Conversion de {data.points} points wallet en {bonus_points_credited} points bonus",
                commit=False,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        await self.repo.create(
            user_id,
            reason="wallet_conversion",
            points=bonus_points_credited,
            description=f"Conversion de {data.points} points wallet en {bonus_points_credited} points bonus",
            transaction_type=BonusTransactionType.credit,
            source=BonusSource.ank_conversion,
            commit=False,
        )
        await self.repo.commit()

        return BonusConversionResult(
            wallet_points_converted=data.points,
            bonus_points_credited=bonus_points_credited,
            remaining_wallet_balance=wallet.points,
        )
