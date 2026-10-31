import random
import string

import httpx
from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.security import create_access_token, create_refresh_token
from app.modules.bonus.service import BonusReason, BonusService
from app.modules.google_auth.schema import GoogleAuthResponse
from app.modules.users.repository import UserRepository

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_ATTEMPTS = 5


def _generate_code() -> str:
    suffix = "".join(random.choices(_CODE_CHARS, k=6))
    return f"AKI-{suffix}"


class GoogleAuthService:
    def __init__(self, repo: UserRepository, bonus_service: BonusService) -> None:
        self.repo = repo
        self.bonus_service = bonus_service

    async def authenticate(self, code: str) -> GoogleAuthResponse:
        user_info = await self._get_user_info_from_google(code)
        return await self._register_or_login(user_info)

    async def _exchange_code_for_token(self, code: str) -> str:
        """
        POST vers Google avec le code d'autorisation.
        Google répond avec un access_token.
        """
        async with httpx.AsyncClient() as client:
            settings = Settings()
            response = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Google token exchange failed: {response.text}",
            )

        data = response.json()
        if "access_token" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google: access_token absent dans la réponse.",
            )
        return data["access_token"]

    async def _get_user_info_from_google(self, code: str) -> dict:
        access_token = await self._exchange_code_for_token(code)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Google userinfo failed: {response.text}",
            )

        data = response.json()

        if "sub" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google: champ 'sub' absent dans la réponse.",
            )

        return {
            "provider": "google",
            "provider_id": data["sub"],
            "email": data.get("email"),
            "first_name": data.get("given_name") or "",
            "last_name": data.get("family_name") or "",
            "avatar_url": data.get("picture"),
        }

    async def _register_or_login(self, info: dict) -> GoogleAuthResponse:
        is_new_user = False
        user = await self.repo.get_by_provider("google", info["provider_id"])

        if user is None and info["email"]:
            user = await self.repo.get_by_email(info["email"])
            if user is not None:
                user = await self.repo.update(
                    user,
                    {
                        "provider": "google",
                        "provider_id": info["provider_id"],
                    },
                )

        if user is None:
            # Cas 3 : nouveau compte
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

        return GoogleAuthResponse(
            access_token=str(access_token),
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
                "hashed_password": None,
                "provider": "google",
                "provider_id": info["provider_id"],
                "code_user": code_user,
            }
        )
