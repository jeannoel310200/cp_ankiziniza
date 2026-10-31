import enum
from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.shared.models.base import UUIDTimestampMixin

# Délai après lequel un code_user recherché par un tiers expire (voir
# UserService.get_by_code et UserRead.code_expires_at).
CODE_SEARCH_EXPIRES_AFTER = timedelta(hours=1)


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class GenderEnum(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class User(Base, UUIDTimestampMixin):
    __tablename__ = "users"

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=True)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.user)
    email_token: Mapped[str | None] = mapped_column(String(512),nullable=True)
    code_verification: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    forgot_password_token : Mapped[str|None] = mapped_column(String(512),nullable=True)
    forgot_password_code : Mapped[str|None] = mapped_column(String(20),nullable=True,unique=True)
    verified_after_forgot_password : Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    change_email_verified : Mapped[bool] = mapped_column(
        Boolean, nullable=False,default=False,server_default="false"
        ) 
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.user)
    code_user: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    code_first_searched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    updated_email_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_phone_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_views: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    using_code_user: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # values_callable : par défaut SQLAlchemy stocke le *nom* Python de
    # l'enum ('MALE'/'FEMALE') plutôt que sa valeur ('male'/'female'). Tous
    # les autres enums du projet (UserRole, RelationshipStatusEnum, ...) ont
    # un nom identique à leur valeur donc le problème ne s'y voit pas ; ici
    # il faut forcer explicitement l'utilisation de la valeur pour matcher
    # le contrat API ('male'/'female') et la migration Alembic.
    gender: Mapped[GenderEnum | None] = mapped_column(
        Enum(GenderEnum, values_callable=lambda obj: [e.value for e in obj], name="gender_enum"),
        nullable=True,
    )

    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
