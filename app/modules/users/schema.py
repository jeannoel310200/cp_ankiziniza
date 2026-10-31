from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, computed_field

from app.modules.profile.model import NAME_CHANGE_COOLDOWN
from app.modules.users.model import CODE_SEARCH_EXPIRES_AFTER, GenderEnum, UserRole


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = Field(default=None, max_length=30)
    gender: GenderEnum


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=512)
    # Absent pour les comptes créés par OAuth (Google/Facebook ne le
    # fournissent pas) — l'app mobile le complète après coup.
    gender: GenderEnum | None = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    first_name: str
    last_name: str
    email: str
    phone: str | None
    avatar_url: str | None
    is_verified: bool
    role: UserRole
    code_user: str | None
    profile_views: int
    created_at: datetime
    updated_at: datetime
    verified_after_forgot_password:bool
    change_email_verified:bool
    gender: GenderEnum | None

    # Champ brut utilisé uniquement pour calculer code_expires_at ci-dessous ;
    # jamais exposé tel quel dans la réponse (exclude=True).
    code_first_searched_at: datetime | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def code_expires_at(self) -> datetime | None:
        if self.code_first_searched_at is None:
            return None
        return self.code_first_searched_at + CODE_SEARCH_EXPIRES_AFTER

    # Relation ORM brute, utilisée uniquement pour lire blue_badge ci-dessous ;
    # jamais exposée telle quelle (exclude=True). Nécessite que la requête
    # ait fait un selectinload(User.profile) (cf. UserRepository).
    profile: Any = Field(default=None, exclude=True)

    @computed_field
    @property
    def is_badge_verified(self) -> bool:
        """Badge bleu "compte vérifié" (KYC) — distinct de is_verified
        (email). Stocké sur Profile.blue_badge, pas sur User."""
        return bool(self.profile and self.profile.blue_badge)

    @computed_field
    @property
    def has_custom_avatar(self) -> bool:
        """Photo réellement envoyée par l'utilisateur (Profile.profile_pictures),
        par opposition à un avatar hérité de Google/Facebook. avatar_url ne
        permet pas de trancher : elle est renseignée dans les deux cas. Le
        client s'en sert pour ne proposer « Supprimer » que s'il y a quelque
        chose à supprimer."""
        return bool(self.profile and self.profile.profile_pictures)

    @computed_field
    @property
    def first_name_editable_at(self) -> datetime | None:
        """Date à partir de laquelle le prénom pourra être modifié de nouveau.
        None = modifiable maintenant (jamais changé). Permet au client de
        griser le champ au lieu d'exposer l'utilisateur à un 400.
        Indépendant du verrou définitif du badge bleu, lisible via
        is_badge_verified, et indépendant du cooldown du nom de famille
        (cf. last_name_editable_at) : les deux champs s'éditent séparément."""
        changed_at = getattr(self.profile, "updated_first_name_date", None)
        if changed_at is None:
            return None
        return changed_at + NAME_CHANGE_COOLDOWN

    @computed_field
    @property
    def last_name_editable_at(self) -> datetime | None:
        """Symétrique de first_name_editable_at, pour le nom de famille."""
        changed_at = getattr(self.profile, "updated_last_name_date", None)
        if changed_at is None:
            return None
        return changed_at + NAME_CHANGE_COOLDOWN


class UserPublicRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    first_name: str
    last_name: str
    avatar_url: str | None
    is_verified: bool
    code_user: str | None
    gender: GenderEnum | None

    profile: Any = Field(default=None, exclude=True)

    @computed_field
    @property
    def is_badge_verified(self) -> bool:
        return bool(self.profile and self.profile.blue_badge)


class UserNameSearchRead(BaseModel):
    """Résultat de /users/search (par nom) : comme UserPublicRead mais
    SANS code_user — le code ANK d'un tiers ne doit jamais être exposé via
    une recherche par nom, seule une recherche par code (où le chercheur
    connaît déjà le code) y donne droit."""
    model_config = {"from_attributes": True}

    id: UUID
    first_name: str
    last_name: str
    avatar_url: str | None
    is_verified: bool
    gender: GenderEnum | None

    profile: Any = Field(default=None, exclude=True)

    @computed_field
    @property
    def is_badge_verified(self) -> bool:
        return bool(self.profile and self.profile.blue_badge)


class UserCodeSearchRead(UserPublicRead):
    """Résultat de /users/search/code/{code} : mêmes champs que
    UserPublicRead (code_user inclus) plus le statut relationnel, révélé
    gratuitement puisque la recherche par code implique déjà de connaître
    le code."""

    situation: str
    has_partner: bool = False


class PublicStatusRead(BaseModel):
    model_config = {"from_attributes": True}
    first_name: str
    last_name: str
    avatar_url: str|None
    situation: str
    has_partner: bool = False

class UserForgotPassword(BaseModel):
    email : EmailStr

class UserNewPassword(BaseModel):
    password : str

class UserNewCode(BaseModel):
    code_user : str

class ValidateCode(BaseModel):
    code : str
    # Envoyé par le mobile depuis l'écran de vérification d'inscription,
    # utilisé uniquement pour affiner la recherche de l'inscription en
    # attente (cf. UserService.validate_code_email) ; ignoré des autres
    # usages de ce schéma (mot de passe oublié, changement d'email).
    email: EmailStr | None = None

class UserResendCode(BaseModel):
    email: EmailStr

class UserChangeEmail(BaseModel):
    email: EmailStr

class UserChangePhone(BaseModel):
    phone : str = Field(min_length=10, max_length=30)


