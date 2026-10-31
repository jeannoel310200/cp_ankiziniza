"""Production bootstrap helpers (idempotent)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.profile.model import Profile
from app.modules.users.model import User, UserRole

logger = logging.getLogger(__name__)

# Identifiants de repli, utilises quand ADMIN_EMAIL / ADMIN_PASSWORD ne sont
# pas fournis, afin qu'un administrateur existe toujours.
#
# ATTENTION : ces identifiants sont en clair dans le depot et s'appliquent
# aussi en production. Quiconque les connait obtient la suppression de
# comptes, le credit de points, la validation des verifications et l'acces
# aux pieces d'identite. Definir ADMIN_EMAIL et ADMIN_PASSWORD dans le .env
# de production desactive ce repli.
_FALLBACK_ADMIN_EMAIL = "shan@ankiziniza.app"
_FALLBACK_ADMIN_PASSWORD = "password"


async def ensure_admin_user1(session: AsyncSession) -> None:
    """Create the bootstrap admin user if missing.

    Uses ADMIN_EMAIL / ADMIN_PASSWORD when provided, otherwise falls back to
    the built-in credentials above so an administrator always exists.
    Idempotent: does nothing if a user with the same email already exists.
    """
    settings = get_settings()
    email = (settings.admin_email or "").strip().lower()
    password = (settings.admin_password or "").strip()

    if not email or not password:
        email = email or _FALLBACK_ADMIN_EMAIL
        password = password or _FALLBACK_ADMIN_PASSWORD
        logger.warning(
            "ADMIN_EMAIL ou ADMIN_PASSWORD absent : utilisation des "
            "identifiants de repli (%s). A remplacer par des identifiants "
            "dedies en production.",
            email,
        )

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        return

    admin = User(
        # ADMIN_USERNAME sert de nom affiche : la variable existait mais
        # n'etait lue nulle part, ce qui la rendait trompeuse.
        first_name=(settings.admin_username or "Admin").strip() or "Admin",
        last_name="Akiziniza",
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.admin,
    )

    session.add(admin)
    await session.flush()

    profile = Profile(user_id=admin.id)
    session.add(profile)

    await session.commit()
    logger.info("Bootstrap admin user and profile created: %s", email)
