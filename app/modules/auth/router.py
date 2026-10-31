from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.auth.repository import RefreshSessionRepository
from app.modules.auth.schema import (
    AuthTokens,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
)
from app.modules.auth.service import AuthService
from app.modules.users.repository import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), RefreshSessionRepository(db))


@router.post(
    "/login",
    response_model=AuthTokens,
    summary="Login",
    description="Authenticate with email/password and return access + refresh tokens.",
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: LoginRequest,
    service: AuthService = Depends(_get_service),
):
    return await service.login(form_data)


# Debut de teste
@router.post(
    "/docs/login",
    include_in_schema=False,  # <-- Masque cette route de la documentation pour qu'elle reste "anonyme"
)
async def swagger_login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(_get_service),
):
    # 1. On adapte le formulaire de Swagger pour votre service
    payload = LoginRequest(email=form_data.username, password=form_data.password)

    # 2. On appelle votre service existant
    tokens = await service.login(payload)

    # 3. On renvoie STRICTEMENT le format standard attendu par le cadenas Swagger
    return {
        "access_token": tokens.accessToken,  # On extrait l'access token de votre modèle
        "token_type": "bearer",
    }


# Fin de teste


@router.post(
    "/refresh",
    response_model=AuthTokens,
    summary="Refresh tokens",
    description="Rotate refresh session and return new access + refresh tokens.",
)
async def refresh(payload: RefreshRequest, service: AuthService = Depends(_get_service)):
    return await service.refresh(payload)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    description="Revoke the provided refresh token server-side.",
)
async def logout(payload: LogoutRequest, service: AuthService = Depends(_get_service)):
    return await service.logout(payload)
