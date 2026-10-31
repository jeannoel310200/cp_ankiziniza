from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deep_link import build_error_redirect, build_success_redirect
from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.service import BonusService
from app.modules.google_auth.schema import (
    GoogleAuthResponse,
    GoogleCallbackRequest,
)
from app.modules.google_auth.service import GoogleAuthService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository

router = APIRouter(prefix="/google-auth", tags=["Google Auth"])


def _get_service(db: AsyncSession = Depends(get_db)) -> GoogleAuthService:
    return GoogleAuthService(
        UserRepository(db),
        BonusService(
            BonusRepository(db),
            WalletRepository(db),
            NotificationService(NotificationRepository(db)),
        ),
    )


@router.get(
    "/login",
    summary="Connexion Google — redirection navigateur",
    description="Redirige l'utilisateur vers Google pour qu'il se connecte.",
)
async def google_login() -> RedirectResponse:
    settings = Settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    google_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=google_url)


@router.get("/callback")
async def google_callback(
    code: str = Query(...),
    service: GoogleAuthService = Depends(_get_service),
):
    try:
        result = await service.authenticate(code)
    except HTTPException as exc:
        return RedirectResponse(url=build_error_redirect(exc.detail))

    redirect_url = build_success_redirect(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        is_new_user=result.is_new_user,
    )
    return RedirectResponse(url=redirect_url)


@router.post(
    "/login",
    response_model=GoogleAuthResponse,
    summary="Connexion Google — SPA / mobile",
    description='Le frontend envoie { "code": "XXXX" } en JSON.',
)
async def google_login_spa(
    payload: GoogleCallbackRequest,
    service: GoogleAuthService = Depends(_get_service),
) -> GoogleAuthResponse:
    return await service.authenticate(payload.code)
