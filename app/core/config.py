import os
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.getenv("ENV_FILE", ".env"), extra="ignore")

    app_name: str | None = "APIs TEST"
    environment: str | None = "development"
    api_v1_prefix: str | None = "/myapi/v1"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mydb"

    jwt_secret_key: str | None = None  # Reste requis (indispensable pour la sécurité)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4173",
    ]

    auto_create_tables: bool = False
    base_url: str = "http://localhost:8000"

    admin_username: str | None = "admin"
    admin_email: str | None = None
    admin_password: str | None = None

    # ---- OAUTH FACEBOOK (Optionnels désormais) ----
    facebook_client_id: str | None = None
    facebook_client_secret: str | None = None
    facebook_redirect_uri: str | None = (
        "https://ankiziniza.holy-dev.mg/api/v1/facebook-auth/callback"
    )

    # ---- OAUTH GOOGLE (Optionnels désormais) ----
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = "https://ankiziniza.holy-dev.mg/api/v1/google-auth/callback"

    # ---- CONFIGURATION MAIL (Optionnels désormais) ----
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str | None = None
    mail_port: int | None = None
    # Le serveur de prod utilise MAIL_HOST plutôt que MAIL_SERVER.
    mail_server: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIL_SERVER", "MAIL_HOST"),
    )
    mail_from_name: str | None = "My API"
    mail_starttls: bool | None = None
    mail_ssl_tls: bool | None = None
    use_credentials: bool | None = None
    validate_certs: bool | None = None

    enable_mail_notification: bool = True

    # ---- STOCKAGE OBJETS (RustFS S3) ----
    # `local` : uniquement pour le développement/tests (écrit dans uploads/).
    # `s3`    : production, aucune écriture de fichier locale.
    storage_driver: str = "local"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"  # valeur requise par l'API S3, ignorée par RustFS
    s3_use_path_style: bool = True
    # Préfixe/clé de chaque type de contenu dans le bucket.
    s3_avatar_prefix: str = "uploads/avatar"
    s3_verification_prefix: str = "uploads/verification"

    @field_validator("*", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("mail_from", mode="after")
    @classmethod
    def default_mail_from_to_username(cls, value, info):
        # En prod, seul un nom d'affichage (MAIL_FROM_NAME) est configuré,
        # sans adresse MAIL_FROM dédiée — on retombe sur le compte SMTP
        # authentifié, qui est de toute façon la seule adresse autorisée
        # comme expéditeur par la plupart des fournisseurs SMTP.
        if value is None:
            return info.data.get("mail_username")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
