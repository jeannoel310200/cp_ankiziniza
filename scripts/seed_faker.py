"""Génère un jeu de données de production avec Faker.

Le script ajoute un lot de données à la base par défaut. Pour repartir d'une
base vide, utiliser ``--reset`` explicitement.

Exemples :

    SEED_PASSWORD='local-only-password' \
        .venv/bin/python scripts/seed_faker.py --users 10000 --history-days 730

    SEED_PASSWORD='local-only-password' \
        .venv/bin/python scripts/seed_faker.py --users 1000 --reset --seed 42

Les volumes des tables historiques sont pilotés par ``--history-days`` et les
moyennes ``--*-per-user``. Les opérations d'insertion sont faites par lots pour
éviter de matérialiser toutes les lignes historiques en mémoire.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

from alembic.config import Config as AlembicConfig
from faker import Faker  # type: ignore[import-not-found]
from sqlalchemy import case, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command as alembic_command

# Importer Base en premier enregistre tous les modèles dans metadata.
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.modules.auth.model import RefreshSession
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
from app.modules.notification.model import Notification, NotificationType
from app.modules.profile.model import Profile
from app.modules.relationships.model import (
    RelationshipRequest,
    RelationshipRequestStatus,
    RelationshipStatus,
    RelationshipStatusEnum,
)
from app.modules.users.model import GenderEnum, User, UserRole
from app.modules.verification.model import VerificationRequest, VerificationStatus
from app.modules.wallet.model import AnkTransaction, TransactionOrigin, TransactionType, Wallet

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed_faker")

T = TypeVar("T")


@dataclass(slots=True)
class SeedConfig:
    users: int
    admins: int
    history_days: int
    batch_size: int
    seed: int
    namespace: str
    email_domain: str
    password: str | None
    profile_completion_rate: float
    oauth_rate: float
    email_verified_rate: float
    gender_rate: float
    relationship_rate: float
    requests_per_user: float
    bonus_events_per_user: float
    transactions_per_user: float
    notifications_per_user: float
    verification_rate: float
    daily_claim_rate: float
    question_answer_rate: float
    zero_wallet_rate: float
    refresh_session_rate: float
    bonus_codes: int | None
    reset: bool
    skip_migrations: bool


@dataclass(slots=True)
class SeedUser:
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    birth_date: date
    gender: GenderEnum | None
    role: UserRole
    provider: str
    created_at: datetime


@dataclass(slots=True)
class VerificationSeed:
    status: VerificationStatus
    created_at: datetime
    reviewed_by: uuid.UUID | None


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def random_datetime(rng: random.Random, start: datetime, end: datetime) -> datetime:
    seconds = max(0, int((end - start).total_seconds()))
    return start + timedelta(seconds=rng.randint(0, seconds))


def sampled_count(rng: random.Random, average: float, minimum: int = 0) -> int:
    """Approxime une moyenne tout en gardant une distribution légère."""
    if average <= 0:
        return minimum
    whole = int(average)
    count = whole + int(rng.random() < average - whole)
    # Une petite variation évite que chaque utilisateur ait exactement N lignes.
    if whole > 1 and rng.random() < 0.20:
        count += rng.choice((-1, 1))
    return max(minimum, count)


def other_user(
    rng: random.Random,
    users: list[SeedUser],
    user_id: uuid.UUID,
    positions: dict[uuid.UUID, int],
) -> uuid.UUID | None:
    if len(users) < 2:
        return None
    candidate = users[rng.randrange(len(users))].id
    if candidate == user_id:
        candidate = users[(positions[user_id] + 1) % len(users)].id
    return candidate


async def insert_batches(
    session: AsyncSession,
    model: type[T],
    rows: Iterable[dict[str, Any]],
    batch_size: int,
    label: str,
) -> int:
    """Insère un itérable par lots et retourne le nombre de lignes insérées."""
    batch: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            await session.execute(insert(model), batch)
            total += len(batch)
            batch.clear()
            if total % (batch_size * 10) == 0:
                log.info("[%s] %d lignes", label, total)
    if batch:
        await session.execute(insert(model), batch)
        total += len(batch)
    await session.commit()
    log.info("[%s] %d lignes insérées", label, total)
    return total


def build_users(
    config: SeedConfig, fake: Faker, rng: random.Random, now: datetime
) -> list[SeedUser]:
    users: list[SeedUser] = []
    local_count = max(0, config.users - config.admins)
    for index in range(config.users):
        first_name = fake.first_name()
        last_name = fake.last_name()
        role = UserRole.admin if index < config.admins else UserRole.user
        if role is UserRole.admin:
            provider = "local"
        elif rng.random() < config.oauth_rate:
            provider = "google" if rng.random() < 0.67 else "facebook"
        else:
            provider = "local"
        birth_date = fake.date_of_birth(minimum_age=18, maximum_age=70)
        gender = None
        if rng.random() < config.gender_rate:
            gender = GenderEnum.MALE if rng.random() < 0.50 else GenderEnum.FEMALE
        created_at = random_datetime(rng, now - timedelta(days=config.history_days), now)
        users.append(
            SeedUser(
                id=uuid.uuid4(),
                first_name=first_name,
                last_name=last_name,
                email=f"seed-{config.namespace}-{index}@{config.email_domain}".lower(),
                birth_date=birth_date,
                gender=gender,
                role=role,
                provider=provider,
                created_at=created_at,
            )
        )
    log.info(
        "[users] %d utilisateurs générés (%d admins, %d locaux, %d OAuth)",
        len(users),
        config.admins,
        sum(user.provider == "local" for user in users),
        sum(user.provider != "local" for user in users),
    )
    if local_count == 0 and config.password:
        log.info("[users] Aucun compte local : le mot de passe fourni ne sera pas utilisé")
    return users


def user_rows(
    users: list[SeedUser],
    config: SeedConfig,
    rng: random.Random,
    now: datetime,
    hashed_seed_password: str | None,
) -> Iterator[dict[str, Any]]:
    for index, user in enumerate(users):
        is_verified = user.role is UserRole.admin or (
            user.provider != "local" or rng.random() < config.email_verified_rate
        )
        avatar_url = None
        if rng.random() < config.profile_completion_rate:
            avatar_url = f"https://i.pravatar.cc/256?u={user.id}"
        searched_at = None
        if rng.random() < 0.15:
            searched_at = now - timedelta(minutes=rng.randint(1, 60))
        yield {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": f"+2376{rng.randint(00_000_000, 99_999_999):08d}"
            if rng.random() < 0.88
            else None,
            "avatar_url": avatar_url,
            "hashed_password": hashed_seed_password if user.provider == "local" else None,
            "provider": user.provider,
            "provider_id": None
            if user.provider == "local"
            else f"{user.provider}-{uuid.uuid4().hex}",
            "is_verified": is_verified,
            "role": user.role,
            "email_token": None,
            "code_verification": None,
            "forgot_password_token": None,
            "forgot_password_code": None,
            "verified_after_forgot_password": False,
            "change_email_verified": False,
            "code_user": f"AKI-{config.namespace.upper()}{index:08d}"[:20],
            "code_first_searched_at": searched_at,
            "updated_email_date": None,
            "updated_phone_date": None,
            "profile_views": rng.randint(0, 700),
            "using_code_user": rng.randint(0, 12),
            "gender": user.gender,
            "created_at": user.created_at,
            "updated_at": max(user.created_at, random_datetime(rng, user.created_at, now)),
        }


def verification_seeds(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> dict[uuid.UUID, VerificationSeed]:
    admins = [user for user in users if user.role is UserRole.admin]
    seeds: dict[uuid.UUID, VerificationSeed] = {}
    for user in users:
        if user.role is UserRole.admin or rng.random() >= config.verification_rate:
            continue
        roll = rng.random()
        status = (
            VerificationStatus.pending
            if not admins
            else VerificationStatus.approved
            if roll < 0.60
            else VerificationStatus.rejected
            if roll < 0.85
            else VerificationStatus.pending
        )
        created_at = random_datetime(rng, user.created_at, now)
        reviewed_by = None
        if status is not VerificationStatus.pending and admins:
            reviewed_by = rng.choice(admins).id
        seeds[user.id] = VerificationSeed(status, created_at, reviewed_by)
    return seeds


def profile_rows(
    users: list[SeedUser],
    config: SeedConfig,
    rng: random.Random,
    now: datetime,
    verifications: dict[uuid.UUID, VerificationSeed],
    assignments: dict[uuid.UUID, tuple[RelationshipStatusEnum, uuid.UUID | None]],
) -> Iterator[dict[str, Any]]:
    for user in users:
        verification = verifications.get(user.id)
        has_full_name = rng.random() < min(1.0, config.profile_completion_rate + 0.12)
        has_picture = rng.random() < config.profile_completion_rate
        has_birth_date = rng.random() < min(1.0, config.profile_completion_rate + 0.20)
        if verification:
            has_full_name = True
            has_birth_date = True
        yield {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "full_name": f"{user.first_name} {user.last_name}" if has_full_name else None,
            "profile_pictures": f"https://i.pravatar.cc/512?u={user.id}" if has_picture else None,
            "birth_date": user.birth_date if has_birth_date else None,
            "relationship_status": assignments[user.id][0].value,
            "blue_badge": bool(verification and verification.status is VerificationStatus.approved),
            "updated_full_name_date": None,
            "updated_first_name_date": None,
            "updated_last_name_date": None,
            "updated_picture_profile_date": None,
            "updated_birth_date": None,
            "created_at": user.created_at,
            "updated_at": max(user.created_at, random_datetime(rng, user.created_at, now)),
        }


def status_assignments(
    users: list[SeedUser], config: SeedConfig, rng: random.Random
) -> dict[uuid.UUID, tuple[RelationshipStatusEnum, uuid.UUID | None]]:
    assignments: dict[uuid.UUID, tuple[RelationshipStatusEnum, uuid.UUID | None]] = {}
    members = [user for user in users if user.role is UserRole.user]
    shuffled = members[:]
    rng.shuffle(shuffled)
    couple_size = min(len(shuffled), int(len(shuffled) * config.relationship_rate))
    couple_size -= couple_size % 2
    for index in range(0, couple_size, 2):
        status = (
            RelationshipStatusEnum.married
            if rng.random() < 0.35
            else RelationshipStatusEnum.in_couple
        )
        left, right = shuffled[index], shuffled[index + 1]
        assignments[left.id] = (status, right.id)
        assignments[right.id] = (status, left.id)
    for user in users:
        if user.id in assignments:
            continue
        roll = rng.random()
        status = (
            RelationshipStatusEnum.divorced
            if roll < 0.12
            else RelationshipStatusEnum.widowed
            if roll < 0.17
            else RelationshipStatusEnum.single
        )
        assignments[user.id] = (status, None)
    return assignments


def relationship_status_rows(
    users: list[SeedUser],
    assignments: dict[uuid.UUID, tuple[RelationshipStatusEnum, uuid.UUID | None]],
    now: datetime,
) -> Iterator[dict[str, Any]]:
    for user in users:
        status, partner_id = assignments[user.id]
        created_at = min(now, user.created_at + timedelta(days=1))
        yield {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "status": status,
            "partner_id": partner_id,
            "created_at": created_at,
            "updated_at": now,
        }


def relationship_request_rows(
    users: list[SeedUser],
    config: SeedConfig,
    rng: random.Random,
    now: datetime,
    events: list[tuple[uuid.UUID, uuid.UUID, RelationshipRequestStatus]],
) -> Iterator[dict[str, Any]]:
    members = [user for user in users if user.role is UserRole.user]
    if len(members) < 2:
        return
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    target_count = sampled_count(rng, len(members) * config.requests_per_user)
    attempts = 0
    generated = 0
    while generated < target_count and attempts < target_count * 10 + 10:
        attempts += 1
        requester, target = rng.sample(members, 2)
        pair = (requester.id, target.id)
        if pair in seen:
            continue
        seen.add(pair)
        roll = rng.random()
        status = (
            RelationshipRequestStatus.accepted
            if roll < 0.48
            else RelationshipRequestStatus.rejected
            if roll < 0.80
            else RelationshipRequestStatus.pending
        )
        created_at = random_datetime(rng, max(requester.created_at, target.created_at), now)
        events.append((requester.id, target.id, status))
        generated += 1
        yield {
            "id": uuid.uuid4(),
            "requester_id": requester.id,
            "target_id": target.id,
            "status": status,
            "created_at": created_at,
            "updated_at": min(now, created_at + timedelta(days=rng.randint(0, 20))),
        }


def wallet_and_transaction_rows(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]]]]:
    positions = {user.id: index for index, user in enumerate(users)}
    for user in users:
        wallet_id = uuid.uuid4()
        force_zero = rng.random() < config.zero_wallet_rate
        total = sampled_count(rng, config.transactions_per_user, minimum=1)
        balance = 0 if force_zero and total == 1 else rng.randint(150, 2200)
        initial = balance
        transactions: list[dict[str, Any]] = []
        if initial > 0:
            transactions.append(
                {
                    "id": uuid.uuid4(),
                    "wallet_id": wallet_id,
                    "amount": initial,
                    "type": TransactionType.credit,
                    "origin": TransactionOrigin.recharge,
                    "related_user_id": None,
                    "description": "Recharge initiale de simulation",
                    "created_at": user.created_at,
                    "updated_at": user.created_at,
                }
            )
        event_count = total - len(transactions)
        for event_index in range(event_count):
            wants_debit = rng.random() < 0.56 and balance > 0
            if force_zero and event_index == event_count - 1 and balance > 0:
                wants_debit = True
                amount = balance
            elif wants_debit:
                amount = rng.randint(1, max(1, min(balance, 180)))
            else:
                amount = rng.randint(10, 450)
            if wants_debit:
                balance -= amount
                origin = (
                    TransactionOrigin.transfer
                    if rng.random() < 0.30
                    else TransactionOrigin.consultation_paid
                )
                transaction_type = TransactionType.debit
                related_id = (
                    other_user(rng, users, user.id, positions)
                    if origin is TransactionOrigin.transfer
                    else None
                )
                description = (
                    "Transfert envoyé"
                    if origin is TransactionOrigin.transfer
                    else "Consultation payée"
                )
            else:
                balance += amount
                origin = (
                    TransactionOrigin.consultation_revenue
                    if rng.random() < 0.55
                    else TransactionOrigin.bonus
                )
                transaction_type = TransactionType.credit
                related_id = (
                    other_user(rng, users, user.id, positions)
                    if origin is TransactionOrigin.consultation_revenue
                    else None
                )
                description = (
                    "Revenu de consultation"
                    if origin is TransactionOrigin.consultation_revenue
                    else "Bonus converti"
                )
            created_at = random_datetime(rng, user.created_at, now)
            transactions.append(
                {
                    "id": uuid.uuid4(),
                    "wallet_id": wallet_id,
                    "amount": amount,
                    "type": transaction_type,
                    "origin": origin,
                    "related_user_id": related_id,
                    "description": description,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
        wallet = {
            "id": wallet_id,
            "user_id": user.id,
            "points": max(0, balance),
            "created_at": user.created_at,
            "updated_at": now,
        }
        yield wallet, transactions


async def seed_wallets_and_transactions(
    session: AsyncSession,
    users: list[SeedUser],
    config: SeedConfig,
    rng: random.Random,
    now: datetime,
) -> tuple[int, int]:
    wallets_count = 0
    transactions_count = 0
    wallet_rows: list[dict[str, Any]] = []
    transaction_rows: list[dict[str, Any]] = []
    for wallet, transactions in wallet_and_transaction_rows(users, config, rng, now):
        wallet_rows.append(wallet)
        transaction_rows.extend(transactions)
        if len(wallet_rows) >= config.batch_size:
            await session.execute(insert(Wallet), wallet_rows)
            await session.execute(insert(AnkTransaction), transaction_rows)
            wallets_count += len(wallet_rows)
            transactions_count += len(transaction_rows)
            wallet_rows.clear()
            transaction_rows.clear()
            await session.commit()
    if wallet_rows:
        await session.execute(insert(Wallet), wallet_rows)
        await session.execute(insert(AnkTransaction), transaction_rows)
        wallets_count += len(wallet_rows)
        transactions_count += len(transaction_rows)
        await session.commit()
    log.info(
        "[wallets] %d wallets, [transactions] %d lignes insérées", wallets_count, transactions_count
    )
    return wallets_count, transactions_count


def bonus_rule_rows(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> Iterator[dict[str, Any]]:
    reasons = [
        ("daily_check_in", "Récompense de connexion quotidienne"),
        ("daily_question", "Réponse à une question du jour"),
        ("quick_response", "Réponse rapide à une demande"),
        ("relationship_milestone", "Étape relationnelle"),
        ("usage_milestone", "Palier d'utilisation"),
        ("wallet_conversion", "Conversion de points bonus"),
    ]
    for user in users:
        balance = 0
        for _ in range(sampled_count(rng, config.bonus_events_per_user)):
            is_debit = balance > 0 and rng.random() < 0.22
            if is_debit:
                points = rng.randint(1, min(balance, 40))
                balance -= points
                transaction_type = BonusTransactionType.debit
                reason, description = "wallet_conversion", "Points bonus convertis en points wallet"
                source = BonusSource.ank_conversion
            else:
                points = rng.randint(4, 60)
                balance += points
                transaction_type = BonusTransactionType.credit
                reason, description = rng.choice(reasons)
                source = (
                    BonusSource.ank_conversion
                    if reason == "wallet_conversion"
                    else BonusSource.bonus
                )
            created_at = random_datetime(rng, user.created_at, now)
            yield {
                "id": uuid.uuid4(),
                "user_id": user.id,
                "reason": reason,
                "points": points,
                "description": description,
                "is_active": rng.random() < 0.94,
                "transaction_type": transaction_type,
                "source": source,
                "created_at": created_at,
                "updated_at": created_at,
            }


async def synchronize_zo_balances(
    session: AsyncSession, users: list[SeedUser]
) -> None:
    user_ids = [user.id for user in users]
    if not user_ids:
        return

    signed_points = case(
        (BonusRule.transaction_type == BonusTransactionType.credit, BonusRule.points),
        else_=-BonusRule.points,
    )
    result = await session.execute(
        select(
            BonusRule.user_id,
            func.coalesce(
                func.sum(
                    case((BonusRule.source == BonusSource.bonus, signed_points), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (BonusRule.source == BonusSource.ank_conversion, signed_points),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(BonusRule.user_id.in_(user_ids))
        .group_by(BonusRule.user_id)
    )
    totals = {
        user_id: (bonus_points, converted_points)
        for user_id, bonus_points, converted_points in result.all()
    }
    existing_result = await session.execute(
        select(ZoBalance).where(ZoBalance.user_id.in_(user_ids))
    )
    existing = {balance.user_id: balance for balance in existing_result.scalars()}

    for user_id in user_ids:
        bonus_points, converted_points = totals.get(user_id, (0, 0))
        bonus_points = max(0, int(bonus_points))
        converted_points = max(0, int(converted_points))
        balance = existing.get(user_id)
        if balance is None:
            session.add(
                ZoBalance(
                    user_id=user_id,
                    bonus_points=bonus_points,
                    converted_zo_points=converted_points,
                )
            )
        else:
            balance.bonus_points = bonus_points
            balance.converted_zo_points = converted_points
    await session.commit()


def bonus_code_rows(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> Iterator[dict[str, Any]]:
    count = config.bonus_codes
    if count is None:
        count = max(50, round(len(users) * 0.10))
    admins = [user for user in users if user.role is UserRole.admin]
    for index in range(count):
        is_used = rng.random() < 0.20
        expired = rng.random() < 0.18
        created_by = rng.choice(admins).id if admins and rng.random() < 0.80 else None
        created_at = random_datetime(rng, now - timedelta(days=config.history_days), now)
        used_by = rng.choice(users).id if is_used else None
        used_at = random_datetime(rng, created_at, now) if is_used else None
        expires_at = (
            now - timedelta(days=rng.randint(1, 180))
            if expired
            else now + timedelta(days=rng.randint(15, 365))
        )
        yield {
            "id": uuid.uuid4(),
            "code": f"ANK-{config.namespace.upper()}{index:08d}",
            "ank_points": rng.choice((50, 100, 150, 250, 500, 1000)),
            "expires_at": expires_at,
            "is_used": is_used,
            "used_at": used_at,
            "created_by": created_by,
            "used_by": used_by,
            "created_at": created_at,
            "updated_at": now,
        }


def question_rows(now: datetime, history_days: int) -> list[dict[str, Any]]:
    questions = [
        "Quelle habitude aimerais-tu construire cette année ?",
        "Quel lieu de ta ville recommanderais-tu à un ami ?",
        "Qu'est-ce qui te met de bonne humeur au quotidien ?",
        "Quelle qualité apprécies-tu le plus chez les autres ?",
        "Quel projet personnel te tient à cœur en ce moment ?",
        "Quel livre, film ou morceau t'a marqué récemment ?",
        "Quelle activité aimerais-tu essayer prochainement ?",
        "Quelle valeur est importante dans une relation durable ?",
        "Quel souvenir te fait sourire instantanément ?",
        "Comment préfères-tu célébrer une bonne nouvelle ?",
    ]
    return [
        {
            "id": uuid.uuid4(),
            "question_text": question,
            "is_active": True,
            "created_at": now - timedelta(days=min(history_days, 365)),
            "updated_at": now,
        }
        for question in questions
    ]


def daily_claim_rows(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> Iterator[dict[str, Any]]:
    first_day = now.date() - timedelta(days=config.history_days - 1)
    for user in users:
        streak = 0
        for offset in range(config.history_days):
            claim_date = first_day + timedelta(days=offset)
            if rng.random() < config.daily_claim_rate:
                streak += 1
                yield {
                    "id": uuid.uuid4(),
                    "user_id": user.id,
                    "claim_date": claim_date,
                    "streak_day": streak,
                    "points": min(4 + streak, 10),
                    "created_at": datetime.combine(claim_date, datetime.min.time(), tzinfo=UTC),
                    "updated_at": datetime.combine(claim_date, datetime.min.time(), tzinfo=UTC),
                }
            else:
                streak = 0


def daily_answer_rows(
    users: list[SeedUser],
    question_ids: list[uuid.UUID],
    config: SeedConfig,
    fake: Faker,
    rng: random.Random,
    now: datetime,
) -> Iterator[dict[str, Any]]:
    first_day = now.date() - timedelta(days=config.history_days - 1)
    for user in users:
        for offset in range(config.history_days):
            if rng.random() >= config.question_answer_rate:
                continue
            answer_date = first_day + timedelta(days=offset)
            answer_count = 2 if rng.random() < 0.28 and len(question_ids) > 1 else 1
            for question_id in rng.sample(question_ids, answer_count):
                created_at = datetime.combine(
                    answer_date, datetime.min.time(), tzinfo=UTC
                ) + timedelta(hours=rng.randint(7, 22), minutes=rng.randint(0, 59))
                yield {
                    "id": uuid.uuid4(),
                    "user_id": user.id,
                    "question_id": question_id,
                    "answer_date": answer_date,
                    "answer_text": fake.sentence(nb_words=rng.randint(8, 20))[:1000],
                    "points_awarded": 15,
                    "created_at": created_at,
                    "updated_at": created_at,
                }


def verification_rows(
    users: list[SeedUser],
    verifications: dict[uuid.UUID, VerificationSeed],
    rng: random.Random,
    now: datetime,
) -> Iterator[dict[str, Any]]:
    for user in users:
        verification = verifications.get(user.id)
        if not verification:
            continue
        reviewed_at = None
        admin_note = None
        if verification.status is VerificationStatus.approved:
            reviewed_at = random_datetime(rng, verification.created_at, now)
        elif verification.status is VerificationStatus.rejected:
            reviewed_at = random_datetime(rng, verification.created_at, now)
            admin_note = rng.choice(
                [
                    "La photo du document est illisible.",
                    "Les informations fournies ne correspondent pas au profil.",
                    "Merci de transmettre un document plus récent.",
                ]
            )
        yield {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "cin_photo_path": f"uploads/verification/{user.id}/cin.jpg",
            "full_name": f"{user.first_name} {user.last_name}",
            "birth_date": user.birth_date,
            "extra_info": fake_extra_info(rng),
            "status": verification.status,
            "admin_note": admin_note,
            "reviewed_by": verification.reviewed_by,
            "reviewed_at": reviewed_at,
            "created_at": verification.created_at,
        }


def fake_extra_info(rng: random.Random) -> str | None:
    return rng.choice(
        (None, None, "Document national", "Résident de longue durée", "Dossier standard")
    )


def notification_rows(
    users: list[SeedUser],
    request_events: list[tuple[uuid.UUID, uuid.UUID, RelationshipRequestStatus]],
    config: SeedConfig,
    rng: random.Random,
    now: datetime,
) -> Iterator[dict[str, Any]]:
    request_by_type: dict[NotificationType, list[tuple[uuid.UUID, uuid.UUID]]] = {
        NotificationType.friend_request_received: [
            (requester, target) for requester, target, _ in request_events
        ],
        NotificationType.friend_request_accepted: [
            (requester, target)
            for requester, target, status in request_events
            if status is RelationshipRequestStatus.accepted
        ],
        NotificationType.friend_request_rejected: [
            (requester, target)
            for requester, target, status in request_events
            if status is RelationshipRequestStatus.rejected
        ],
    }
    positions = {user.id: index for index, user in enumerate(users)}
    types = [
        NotificationType.bonus_received,
        NotificationType.profile_searched,
        NotificationType.friend_request_received,
        NotificationType.friend_request_accepted,
        NotificationType.friend_request_rejected,
        NotificationType.account_verified,
        NotificationType.verification_rejected,
        NotificationType.relationship_ended,
        NotificationType.code_regenerated,
        NotificationType.partner_viewed,
    ]
    weights = [30, 14, 12, 8, 7, 8, 4, 5, 4, 8]
    for user in users:
        for _ in range(sampled_count(rng, config.notifications_per_user)):
            notification_type = rng.choices(types, weights=weights, k=1)[0]
            from_user_id = None
            to_user_id = user.id
            matching_events = request_by_type.get(notification_type, [])
            if matching_events:
                requester_id, target_id = rng.choice(matching_events)
                to_user_id = (
                    target_id
                    if notification_type is NotificationType.friend_request_received
                    else requester_id
                )
                from_user_id = requester_id if to_user_id == target_id else target_id
            elif notification_type in {
                NotificationType.profile_searched,
                NotificationType.partner_viewed,
            }:
                from_user_id = other_user(rng, users, user.id, positions)
            message = {
                NotificationType.bonus_received: "Tu as reçu une récompense en points.",
                NotificationType.profile_searched: "Un utilisateur a consulté ton profil.",
                NotificationType.friend_request_received: "Tu as reçu une demande de relation.",
                NotificationType.friend_request_accepted: "Ta demande de relation a été acceptée.",
                NotificationType.friend_request_rejected: "Ta demande de relation a été refusée.",
                NotificationType.account_verified: "Ton compte a été vérifié.",
                NotificationType.verification_rejected: "Ta demande de vérification a été refusée.",
                NotificationType.relationship_ended: "Une relation a été clôturée.",
                NotificationType.code_regenerated: "Ton code utilisateur a été régénéré.",
                NotificationType.partner_viewed: "Ton partenaire a consulté ton profil.",
            }[notification_type]
            created_at = random_datetime(rng, user.created_at, now)
            yield {
                "id": uuid.uuid4(),
                "to_user_id": to_user_id,
                "from_user_id": from_user_id if from_user_id != to_user_id else None,
                "type": notification_type,
                "message": message,
                "is_read": rng.random() < 0.62,
                "created_at": created_at,
            }


def refresh_session_rows(
    users: list[SeedUser], config: SeedConfig, rng: random.Random, now: datetime
) -> Iterator[dict[str, Any]]:
    for user in users:
        if user.provider != "local" or rng.random() >= config.refresh_session_rate:
            continue
        created_at = random_datetime(rng, max(user.created_at, now - timedelta(days=90)), now)
        yield {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "jti": str(uuid.uuid4()),
            "expires_at": now + timedelta(days=rng.randint(1, 30)),
            "revoked": rng.random() < 0.10,
            "created_at": created_at,
        }


async def reset_database() -> None:
    log.warning("[reset] Suppression de toutes les tables applicatives...")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


async def create_schema_for_sqlite() -> None:
    """Crée le schéma local sans rejouer les migrations PostgreSQL historiques."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def run_migrations() -> None:
    log.info("[alembic] upgrade head...")
    alembic_command.upgrade(AlembicConfig("alembic.ini"), "head")
    log.info("[alembic] schema à jour")


async def run_seed(config: SeedConfig) -> None:
    now = utc_now()
    fake = Faker("fr_FR")
    fake.seed_instance(config.seed)
    rng = random.Random(config.seed)
    users = build_users(config, fake, rng, now)
    verification_map = verification_seeds(users, config, rng, now)
    assignments = status_assignments(users, config, rng)
    hashed_seed_password = hash_password(config.password) if config.password else None

    async with SessionLocal() as session:
        await insert_batches(
            session,
            User,
            user_rows(users, config, rng, now, hashed_seed_password),
            config.batch_size,
            "users",
        )
        await insert_batches(
            session,
            Profile,
            profile_rows(users, config, rng, now, verification_map, assignments),
            config.batch_size,
            "profiles",
        )
        await seed_wallets_and_transactions(session, users, config, rng, now)

        await insert_batches(
            session,
            RelationshipStatus,
            relationship_status_rows(users, assignments, now),
            config.batch_size,
            "relationship_statuses",
        )
        request_events: list[tuple[uuid.UUID, uuid.UUID, RelationshipRequestStatus]] = []
        request_rows = relationship_request_rows(users, config, rng, now, request_events)
        await insert_batches(
            session, RelationshipRequest, request_rows, config.batch_size, "relationship_requests"
        )

        await insert_batches(
            session,
            BonusRule,
            bonus_rule_rows(users, config, rng, now),
            config.batch_size,
            "bonus_rules",
        )
        await synchronize_zo_balances(session, users)
        await insert_batches(
            session,
            BonusCode,
            bonus_code_rows(users, config, rng, now),
            config.batch_size,
            "bonus_codes",
        )

        questions = question_rows(now, config.history_days)
        await insert_batches(
            session, DailyQuestion, questions, config.batch_size, "daily_questions"
        )
        question_ids = [row["id"] for row in questions]
        await insert_batches(
            session,
            DailyBonusClaim,
            daily_claim_rows(users, config, rng, now),
            config.batch_size,
            "daily_bonus_claims",
        )
        await insert_batches(
            session,
            DailyQuestionAnswer,
            daily_answer_rows(users, question_ids, config, fake, rng, now),
            config.batch_size,
            "daily_question_answers",
        )

        await insert_batches(
            session,
            VerificationRequest,
            verification_rows(users, verification_map, rng, now),
            config.batch_size,
            "verification_requests",
        )
        await insert_batches(
            session,
            Notification,
            notification_rows(users, request_events, config, rng, now),
            config.batch_size,
            "notifications",
        )
        await insert_batches(
            session,
            # Les sessions sont volontairement seedées après les tables métier,
            # comme lors d'un login réel.
            RefreshSession,
            refresh_session_rows(users, config, rng, now),
            config.batch_size,
            "refresh_sessions",
        )

    log.info(
        "Seed Faker terminé : %d utilisateurs, historique de %d jours.",
        len(users),
        config.history_days,
    )


def probability(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("doit être un nombre") from error
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("doit être compris entre 0 et 1")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("doit être strictement positif")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("doit être positif ou nul")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("doit être strictement positif")
    return parsed


def parse_args() -> SeedConfig:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--users",
        type=positive_int,
        default=1000,
        help="Nombre d'utilisateurs à ajouter (défaut: 1000)",
    )
    parser.add_argument(
        "--admins",
        type=non_negative_int,
        default=1,
        help="Nombre d'admins inclus dans --users (défaut: 1)",
    )
    parser.add_argument(
        "--history-days",
        type=positive_int,
        default=365,
        help="Nombre de jours d'historique (défaut: 365)",
    )
    parser.add_argument(
        "--batch-size", type=positive_int, default=2000, help="Taille des lots SQL (défaut: 2000)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Graine Faker et aléatoire")
    parser.add_argument(
        "--namespace",
        default=None,
        help="Préfixe unique des emails/codes (défaut: identifiant aléatoire)",
    )
    parser.add_argument(
        "--email-domain", default="seed.akizniz.app", help="Domaine des emails générés"
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SEED_PASSWORD"),
        help="Mot de passe des comptes locaux (ou SEED_PASSWORD)",
    )
    parser.add_argument("--profile-completion-rate", type=probability, default=0.82)
    parser.add_argument("--oauth-rate", type=probability, default=0.15)
    parser.add_argument("--email-verified-rate", type=probability, default=0.90)
    parser.add_argument("--gender-rate", type=probability, default=0.95)
    parser.add_argument("--relationship-rate", type=probability, default=0.34)
    parser.add_argument("--requests-per-user", type=positive_float, default=0.80)
    parser.add_argument("--bonus-events-per-user", type=positive_float, default=3.2)
    parser.add_argument("--transactions-per-user", type=positive_float, default=6.0)
    parser.add_argument("--notifications-per-user", type=positive_float, default=5.0)
    parser.add_argument("--verification-rate", type=probability, default=0.16)
    parser.add_argument("--daily-claim-rate", type=probability, default=0.42)
    parser.add_argument("--question-answer-rate", type=probability, default=0.24)
    parser.add_argument("--zero-wallet-rate", type=probability, default=0.12)
    parser.add_argument("--refresh-session-rate", type=probability, default=0.58)
    parser.add_argument("--bonus-codes", type=non_negative_int, default=None)
    parser.add_argument("--reset", action="store_true", help="Supprime les données avant le seed")
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="N'exécute pas Alembic (schema déjà installé)",
    )
    args = parser.parse_args()

    if args.admins > args.users:
        parser.error("--admins ne peut pas être supérieur à --users")
    if args.password is None and (args.users - args.admins > 0 or args.admins > 0):
        parser.error(
            "un mot de passe est requis via --password ou SEED_PASSWORD pour les comptes locaux"
        )
    if args.namespace is not None and not args.namespace.replace("-", "").isalnum():
        parser.error("--namespace ne peut contenir que des lettres, chiffres et tirets")
    namespace = args.namespace or uuid.uuid4().hex[:8]
    if len(namespace) > 8:
        parser.error("--namespace ne peut pas dépasser 8 caractères")
    return SeedConfig(
        users=args.users,
        admins=args.admins,
        history_days=args.history_days,
        batch_size=args.batch_size,
        seed=args.seed,
        namespace=namespace,
        email_domain=args.email_domain,
        password=args.password,
        profile_completion_rate=args.profile_completion_rate,
        oauth_rate=args.oauth_rate,
        email_verified_rate=args.email_verified_rate,
        gender_rate=args.gender_rate,
        relationship_rate=args.relationship_rate,
        requests_per_user=args.requests_per_user,
        bonus_events_per_user=args.bonus_events_per_user,
        transactions_per_user=args.transactions_per_user,
        notifications_per_user=args.notifications_per_user,
        verification_rate=args.verification_rate,
        daily_claim_rate=args.daily_claim_rate,
        question_answer_rate=args.question_answer_rate,
        zero_wallet_rate=args.zero_wallet_rate,
        refresh_session_rate=args.refresh_session_rate,
        bonus_codes=args.bonus_codes,
        reset=args.reset,
        skip_migrations=args.skip_migrations,
    )


def main() -> None:
    config = parse_args()
    if config.reset:
        asyncio.run(reset_database())

    database_url = get_settings().database_url
    if database_url.startswith("sqlite"):
        # Plusieurs migrations historiques utilisent des opérations DDL
        # PostgreSQL-only. Le chemin de production reste Alembic/PostgreSQL ;
        # SQLite sert ici de backend local de smoke test.
        log.info("[schema] SQLite détecté : création via SQLAlchemy metadata")
        asyncio.run(create_schema_for_sqlite())
    elif config.skip_migrations:
        log.info("[alembic] migrations ignorées (--skip-migrations)")
    else:
        run_migrations()
    asyncio.run(run_seed(config))


if __name__ == "__main__":
    main()
