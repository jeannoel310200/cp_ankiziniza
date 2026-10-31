"""Script de seed — peuple la base avec des données de test réalistes.

Usage:
    .venv/bin/python scripts/seed.py

Idempotent : ne recrée pas un utilisateur dont l'e-mail existe déjà.
"""

import asyncio
import logging

from alembic.config import Config as AlembicConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# app.db.base doit être importé en premier pour enregistrer tous les modèles
# via ses imports de fin de fichier et éviter les imports circulaires.
import app.db.base  # noqa: F401,E402
from alembic import command as alembic_command
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.relationships.model import (
    RelationshipRequest,
    RelationshipRequestStatus,
    RelationshipStatus,
    RelationshipStatusEnum,
)
from app.modules.users.model import User, UserRole
from app.modules.wallet.model import AnkTransaction, TransactionOrigin, TransactionType, Wallet

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Données fixes
# ---------------------------------------------------------------------------

SEED_PASSWORD = "Test1234!"

USERS = [
    {
        "first_name": "Alice",
        "last_name": "Mballa",
        "email": "alice@akizniz.app",
        "phone": "+237690000001",
        "role": UserRole.user,
        "points": 1500,
        "code_user": "AKI-ALICE1",
    },
    {
        "first_name": "Bob",
        "last_name": "Nkeng",
        "email": "bob@akizniz.app",
        "phone": "+237690000002",
        "role": UserRole.user,
        "points": 800,
        "code_user": "AKI-BOB001",
    },
    {
        "first_name": "Chloé",
        "last_name": "Fotso",
        "email": "chloe@akizniz.app",
        "phone": "+237690000003",
        "role": UserRole.user,
        "points": 3200,
        "code_user": "AKI-CHLOE1",
    },
    {
        "first_name": "David",
        "last_name": "Biya",
        "email": "david@akizniz.app",
        "phone": "+237690000004",
        "role": UserRole.user,
        "points": 0,
        "code_user": "AKI-DAVID1",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_or_create_user(session: AsyncSession, data: dict) -> tuple[User, bool]:
    """Retourne (user, created). Ne crée pas si l'e-mail existe déjà."""
    result = await session.execute(select(User).where(User.email == data["email"]))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False

    user = User(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        phone=data.get("phone"),
        hashed_password=hash_password(SEED_PASSWORD),
        role=data.get("role", UserRole.user),
        is_verified=True,
        # code_user=data.get("code_user"),
    )
    session.add(user)
    await session.flush()
    return user, True


async def ensure_profile(session: AsyncSession, user: User) -> None:
    from app.modules.profile.model import Profile

    result = await session.execute(select(Profile).where(Profile.user_id == user.id))
    if result.scalar_one_or_none():
        return
    session.add(Profile(user_id=user.id))


async def ensure_wallet(session: AsyncSession, user: User, points: int) -> Wallet:
    result = await session.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one_or_none()
    if wallet:
        return wallet

    wallet = Wallet(user_id=user.id, points=points)
    session.add(wallet)
    await session.flush()

    if points > 0:
        tx = AnkTransaction(
            wallet_id=wallet.id,
            amount=points,
            type=TransactionType.credit,
            origin=TransactionOrigin.recharge,
            description="Crédit initial (seed)",
        )
        session.add(tx)

    return wallet


async def ensure_relationship_status(
    session: AsyncSession, user: User, status: RelationshipStatusEnum, partner: User | None = None
) -> None:
    result = await session.execute(
        select(RelationshipStatus).where(RelationshipStatus.user_id == user.id)
    )
    if result.scalar_one_or_none():
        return
    session.add(
        RelationshipStatus(
            user_id=user.id, status=status, partner_id=partner.id if partner else None
        )
    )


async def ensure_relationship_request(
    session: AsyncSession,
    requester: User,
    target: User,
    status: RelationshipRequestStatus,
) -> None:
    result = await session.execute(
        select(RelationshipRequest).where(
            RelationshipRequest.requester_id == requester.id,
            RelationshipRequest.target_id == target.id,
        )
    )
    if result.scalar_one_or_none():
        return
    session.add(
        RelationshipRequest(
            requester_id=requester.id,
            target_id=target.id,
            status=status,
        )
    )


# ---------------------------------------------------------------------------
# Seed principal
# ---------------------------------------------------------------------------


async def seed() -> None:
    # 0. Migrations
    log.info("Alembic upgrade head...")
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    log.info("Migrations OK.")

    async with SessionLocal() as session:
        # 1. Utilisateurs
        created_users: list[User] = []
        for data in USERS:
            user, created = await get_or_create_user(session, data)
            label = "cree" if created else "existant"
            log.info("[users] %s %s — %s", user.first_name, user.last_name, label)
            created_users.append(user)
            await ensure_profile(session, user)
            log.info("[profile] %s — profil assure", user.first_name)

        await session.flush()

        alice, bob, chloe, david = created_users

        # 2. Wallets
        for user, data in zip(created_users, USERS):
            await ensure_wallet(session, user, data["points"])
            log.info("[wallet] %s — %d pts", user.first_name, data["points"])

        # 3. Statuts relationnels
        statuses = [
            (alice, RelationshipStatusEnum.in_couple, bob),
            (bob, RelationshipStatusEnum.in_couple, alice),
            (chloe, RelationshipStatusEnum.married, None),
            (david, RelationshipStatusEnum.single, None),
        ]
        for user, st, partner in statuses:
            await ensure_relationship_status(session, user, st, partner)
            log.info("[rel_status] %s — %s", user.first_name, st.value)

        # 4. Demandes de relation
        pairs = [
            (alice, bob, RelationshipRequestStatus.accepted),
            (bob, chloe, RelationshipRequestStatus.pending),
            (david, alice, RelationshipRequestStatus.rejected),
        ]
        for requester, target, st in pairs:
            await ensure_relationship_request(session, requester, target, st)
            log.info(
                "[rel_request] %s -> %s — %s",
                requester.first_name,
                target.first_name,
                st.value,
            )

        await session.commit()
        log.info("Seed termine.")


if __name__ == "__main__":
    asyncio.run(seed())
