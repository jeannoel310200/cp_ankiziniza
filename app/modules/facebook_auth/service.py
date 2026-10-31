import random
import string

import httpx
from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.security import create_access_token, create_refresh_token
from app.modules.bonus.service import BonusReason, BonusService
from app.modules.facebook_auth.schemas import FacebookAuthResponse
from app.modules.users.repository import UserRepository

_FACEBOOK_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
_FACEBOOK_USERINFO_URL = "https://graph.facebook.com/v19.0/me"

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_ATTEMPTS = 5


def _generate_code() -> str:
    suffix = "".join(random.choices(_CODE_CHARS, k=6))
    return f"AKI-{suffix}"


class FacebookAuthService:
    def __init__(self, repo: UserRepository, bonus_service: BonusService) -> None:
        self.repo = repo
        self.bonus_service = bonus_service

    async def authenticate(self, code: str) -> FacebookAuthResponse:
        user_info = await self._get_user_info_from_facebook(code)
        return await self._register_or_login(user_info)

    async def _exchange_code_for_token(self, code: str) -> str:
        async with httpx.AsyncClient() as client:
            settings = Settings()
            response = await client.get(
                _FACEBOOK_TOKEN_URL,
                params={
                    "code": code,
                    "client_id": settings.facebook_client_id,
                    "client_secret": settings.facebook_client_secret,
                    "redirect_uri": settings.facebook_redirect_uri,
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Facebook token exchange failed: {response.text}",
            )

        data = response.json()
        if "access_token" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Facebook: access_token absent dans la réponse.",
            )
        return data["access_token"]

    async def _get_user_info_from_facebook(self, code: str) -> dict:
        access_token = await self._exchange_code_for_token(code)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                _FACEBOOK_USERINFO_URL,
                params={
                    "fields": "id,email,first_name,last_name,picture",
                    "access_token": access_token,
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Facebook userinfo failed: {response.text}",
            )

        data = response.json()

        if "id" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Facebook: champ 'id' absent dans la réponse.",
            )

        return {
            "provider": "facebook",
            "provider_id": data["id"],
            "email": data.get("email"),
            "first_name": data.get("first_name") or "",
            "last_name": data.get("last_name") or "",
            "avatar_url": (data.get("picture") or {}).get("data", {}).get("url"),
        }

    async def _register_or_login(self, info: dict) -> FacebookAuthResponse:
        is_new_user = False

        user = await self.repo.get_by_provider("facebook", info["provider_id"])

        if user is None and info["email"]:
            user = await self.repo.get_by_email(info["email"])
            if user is not None:
                user = await self.repo.update(
                    user,
                    {
                        "provider": "facebook",
                        "provider_id": info["provider_id"],
                    },
                )

        if user is None:
            user = await self._create_user(info)
            is_new_user = True

        if is_new_user:
            await self.bonus_service.award_bonus(user.id, BonusReason.first_time)

        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        refresh_token = create_refresh_token(user_id=str(user.id))

        return FacebookAuthResponse(
            access_token=access_token,
            refresh_token=str(refresh_token[0]),
            is_new_user=is_new_user,
        )

    async def _create_user(self, info: dict):
        if info["email"] and await self.repo.get_by_email(info["email"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        code_user: str | None = None
        for _ in range(_CODE_ATTEMPTS):
            candidate = _generate_code()
            if not await self.repo.get_by_code(candidate):
                code_user = candidate
                break

        if code_user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Code generation failed",
            )

        return await self.repo.create(
            {
                "first_name": info["first_name"],
                "last_name": info["last_name"],
                "email": info["email"],
                "phone": None,
                "avatar_url": info["avatar_url"],
                "hashed_password": None,  # Pas de mot de passe pour OAuth
                "provider": "facebook",
                "provider_id": info["provider_id"],
                "code_user": code_user,
            }
        )
