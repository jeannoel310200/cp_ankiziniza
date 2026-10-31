from datetime import timedelta

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.users.model import GenderEnum
from app.shared.models.base import UUIDTimestampMixin

# Délai après lequel une inscription non confirmée (code jamais saisi ou
# expiré) est purgée par le worker de fond — voir _run_code_expiry_worker.
PENDING_REGISTRATION_EXPIRES_AFTER = timedelta(hours=1)


class PendingRegistration(Base, UUIDTimestampMixin):
    """Inscription par email en attente de confirmation par code : aucun
    `User` n'existe tant que le bon code n'a pas été soumis (cf.
    UserService.register/validate_code_email). Le mot de passe est déjà
    hashé ici — jamais stocké en clair, même temporairement."""

    __tablename__ = "pending_registrations"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    code_verification: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
