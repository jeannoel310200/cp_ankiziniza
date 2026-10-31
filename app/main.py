import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import get_settings
from app.core.etag import ETagMiddleware
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.core.storage import get_storage
from app.db.base import Base
from app.db.bootstrap import ensure_admin_user1
from app.db.session import SessionLocal, engine
from app.modules.account_deletion.router import public_router as account_deletion_public_router
from app.modules.account_deletion.router import router as account_deletion_router
from app.modules.auth.router import router as auth_router
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.router import router as bonus_router
from app.modules.bonus.service import BonusService
from app.modules.facebook_auth.router import router as facebook_router
from app.modules.google_auth.router import router as google_router
from app.modules.legal.router import router as legal_router
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.router import router as notification_router
from app.modules.notification.service import NotificationService
from app.modules.notification.ssemanager.router import router as notification_sse_router
from app.modules.profile.router import router as profile_router
from app.modules.relationships.router import router as relationships_router
from app.modules.users.pending_model import PENDING_REGISTRATION_EXPIRES_AFTER
from app.modules.users.pending_repository import PendingRegistrationRepository
from app.modules.users.repository import UserRepository
from app.modules.users.router import router as users_router
from app.modules.users.service import UserService
from app.modules.verification.router import router as verification_router
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.router import router as wallet_router
from app.modules.wallet.service import WalletService
from app.modules.wallet_request.router import router as wallet_request_router

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)

_CODE_EXPIRY_CHECK_INTERVAL_SECONDS = 300


def _build_user_service(db) -> UserService:
    return UserService(
        repo=UserRepository(db),
        bonus_service=BonusService(
            repo=BonusRepository(db=db),
            wallet_repo=WalletRepository(db=db),
            notif_service=NotificationService(NotificationRepository(db=db)),
        ),
        notif_service=NotificationService(NotificationRepository(db=db)),
        wallet_service=WalletService(repo=WalletRepository(db=db)),
        pending_repo=PendingRegistrationRepository(db),
    )


async def _purge_expired_pending_registrations(db) -> int:
    """Supprime les inscriptions en attente (code jamais saisi ou saisi trop
    tard) dont le délai (PENDING_REGISTRATION_EXPIRES_AFTER) est dépassé —
    sans ça la table grossirait indéfiniment avec des inscriptions jamais
    confirmées (cf. UserService.register / validate_code_email)."""
    repo = PendingRegistrationRepository(db)
    expired_before = datetime.now(UTC) - PENDING_REGISTRATION_EXPIRES_AFTER
    expired = await repo.list_expired(expired_before)
    for pending in expired:
        await repo.delete(pending)
    return len(expired)


async def _run_code_expiry_worker() -> None:
    """Tâche de fond : régénère périodiquement le code des utilisateurs dont
    le délai d'expiration (cf. CODE_SEARCH_EXPIRES_AFTER) est dépassé, sans
    attendre qu'un tiers retente une recherche (cf. UserService.regenerate_expired_codes).
    Purge aussi les inscriptions en attente expirées (cf.
    _purge_expired_pending_registrations)."""
    while True:
        try:
            async with SessionLocal() as session:
                count = await _build_user_service(session).regenerate_expired_codes()
                if count:
                    logger.info("code_expiry_worker: %d code(s) régénéré(s)", count)
        except Exception:
            logger.exception("code_expiry_worker: échec d'un cycle")
        try:
            async with SessionLocal() as session:
                purged = await _purge_expired_pending_registrations(session)
                if purged:
                    logger.info(
                        "code_expiry_worker: %d inscription(s) en attente expirée(s) purgée(s)",
                        purged,
                    )
        except Exception:
            logger.exception("code_expiry_worker: échec de la purge des inscriptions en attente")
        await asyncio.sleep(_CODE_EXPIRY_CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        try:
            await ensure_admin_user1(session)
        except Exception:
            # Journalise : sans cela, un echec ici laisse demarrer l'app sans
            # administrateur, et toutes les routes admin repondent 403 sans
            # que rien n'indique pourquoi.
            logger.exception("Echec de creation de l'administrateur au demarrage")
            await session.rollback()

    worker_task = asyncio.create_task(_run_code_expiry_worker())

    yield

    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/myapi/docs" if settings.environment == "development" else None,
    redoc_url="/myapi/redoc" if settings.environment == "development" else None,
    openapi_url="/myapi/openapi.json" if settings.environment == "development" else None,
)

app.state.limiter = limiter


_AVATAR_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _avatar_media_type(file_path: str) -> str:
    extension = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "png"
    return _AVATAR_CONTENT_TYPES.get(extension, "application/octet-stream")

# Photos de profil servies par l'API, depuis le stockage configuré :
# - local (développement/tests) : lecture de `uploads/avatar` ;
# - RustFS S3 (production) : lecture du bucket, aucun fichier local.
# `uploads/verification/` (pièces d'identité) n'est jamais exposé ici :
# seul l'accès admin via /verification/admin/{id}/photo est autorisé.


@app.get("/api/uploads/avatar/{file_path:path}")
async def serve_avatar(file_path: str):
    try:
        content = await get_storage().read_bytes(f"uploads/avatar/{file_path}")
    except Exception:
        raise HTTPException(status_code=404, detail="Not found") from None
    return Response(
        content=content,
        media_type=_avatar_media_type(file_path),
    )


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"message": "Too many requests"})


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"message": "Invalid request payload"})


@app.exception_handler(HTTPException)
async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


# Middleware stack (innermost -> outermost)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(ETagMiddleware)
app.add_middleware(GZipMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(legal_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(facebook_router, prefix=settings.api_v1_prefix)
app.include_router(google_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)
app.include_router(profile_router, prefix=settings.api_v1_prefix)
app.include_router(relationships_router, prefix=settings.api_v1_prefix)
app.include_router(wallet_router, prefix=settings.api_v1_prefix)
app.include_router(bonus_router, prefix=settings.api_v1_prefix)

# Notification routers
app.include_router(notification_router, prefix=settings.api_v1_prefix)
app.include_router(notification_sse_router, prefix=settings.api_v1_prefix)

# Vérification de compte (KYC)
app.include_router(verification_router, prefix=settings.api_v1_prefix)

# Demandes de transaction (achat manuel de points ANK)
app.include_router(wallet_request_router, prefix=settings.api_v1_prefix)

# Demande de suppression de compte : endpoints authentifié/admin, et
# formulaire public (URL Play Console Data safety) — les deux sous /api/v1,
# seul préfixe que le reverse proxy route vers ce service (la racine du
# domaine sert l'app web admin, cf. web-v2/nginx.conf).
app.include_router(account_deletion_router, prefix=settings.api_v1_prefix)
app.include_router(account_deletion_public_router, prefix=settings.api_v1_prefix)
