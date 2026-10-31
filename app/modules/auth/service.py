from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.modules.auth.repository import RefreshSessionRepository
from app.modules.auth.schema import (
    AuthTokens,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
)
from app.modules.users.repository import UserRepository


class AuthService:
    def __init__(self, user_repo: UserRepository, session_repo: RefreshSessionRepository):
        self.user_repo = user_repo
        self.session_repo = session_repo

    async def login(self, payload: LoginRequest) -> AuthTokens:
        user = await self.user_repo.get_by_email(str(payload.email))
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        settings = get_settings()
        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        refresh_token, jti = create_refresh_token(user_id=str(user.id))
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        await self.session_repo.create(user.id, jti, expires_at)

        return AuthTokens(accessToken=access_token, refreshToken=refresh_token)

    async def refresh(self, payload: RefreshRequest) -> AuthTokens:
        token_data = decode_token(payload.refreshToken)
        if not token_data or "jti" not in token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        session = await self.session_repo.get_by_jti(token_data["jti"])
        if not session or session.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token revoked or not found",
            )

        now = datetime.now(UTC)
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired",
            )

        await self.session_repo.revoke(token_data["jti"])

        user = await self.user_repo.get_by_id(token_data["sub"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        settings = get_settings()
        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        refresh_token, jti = create_refresh_token(user_id=str(user.id))
        new_expires_at = now + timedelta(days=settings.refresh_token_expire_days)
        await self.session_repo.create(user.id, jti, new_expires_at)

        return AuthTokens(accessToken=access_token, refreshToken=refresh_token)

    async def logout(self, payload: LogoutRequest) -> LogoutResponse:
        token_data = decode_token(payload.refreshToken)
        if token_data and "jti" in token_data:
            await self.session_repo.revoke(token_data["jti"])
        return LogoutResponse()
