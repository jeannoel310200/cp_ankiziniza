from urllib.parse import urlencode

# app/modules/facebook_auth/router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deep_link import build_error_redirect, build_success_redirect
from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.service import BonusService
from app.modules.facebook_auth.schemas import (
    FacebookAuthResponse,
    FacebookCallbackRequest,
)
from app.modules.facebook_auth.service import FacebookAuthService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository

router = APIRouter(prefix="/facebook-auth", tags=["Facebook Auth"])


def _get_service(db: AsyncSession = Depends(get_db)) -> FacebookAuthService:
    return FacebookAuthService(
        UserRepository(db),
        BonusService(
            BonusRepository(db),
            WalletRepository(db),
            NotificationService(NotificationRepository(db)),
        ),
    )


@router.get("/callback")
async def facebook_callback(
    code: str = Query(...),
    service: FacebookAuthService = Depends(_get_service),
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


@router.get(
    "/login",
    summary="Connexion Facebook — redirection navigateur",
    description="Redirige l'utilisateur vers Facebook pour qu'il se connecte.",
)
async def facebook_login() -> RedirectResponse:
    settings = Settings()
    params = {
        "client_id": settings.facebook_client_id,
        "redirect_uri": settings.facebook_redirect_uri,
        "response_type": "code",
        "scope": "email,public_profile",
    }
    facebook_url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
    return RedirectResponse(url=facebook_url)


@router.post(
    "/login",
    response_model=FacebookAuthResponse,
    summary="Connexion Facebook — SPA / mobile",
    description='Le frontend envoie { "code": "XXXX" } en JSON.',
)
async def facebook_login_spa(
    payload: FacebookCallbackRequest,
    service: FacebookAuthService = Depends(_get_service),
) -> FacebookAuthResponse:
    return await service.authenticate(payload.code)
