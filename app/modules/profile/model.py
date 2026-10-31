import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.shared.models.base import UUIDTimestampMixin

# Délai avant de pouvoir redemander un changement de nom. Défini ici plutôt que
# dans le service : le schéma UserRead en dérive `name_editable_at` pour que le
# client puisse griser le champ, et importer le service depuis le schéma
# créerait une boucle d'imports.
NAME_CHANGE_COOLDOWN = timedelta(days=60)


class Profile(Base, UUIDTimestampMixin):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str | None] = mapped_column(String(255))
    profile_pictures: Mapped[str | None] = mapped_column(String(512))
    birth_date: Mapped[date | None] = mapped_column(Date)
    relationship_status: Mapped[str | None] = mapped_column(String(200))
    blue_badge: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_full_name_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Remplacent updated_full_name_date pour l'usage courant : first_name et
    # last_name sont désormais éditables (et soumis au cooldown) indépendamment
    # l'un de l'autre. updated_full_name_date reste en base (colonne existante,
    # non supprimée) mais n'est plus alimentée.
    updated_first_name_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_last_name_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_picture_profile_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_birth_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="profile")
