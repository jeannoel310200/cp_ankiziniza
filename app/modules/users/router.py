from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.service import BonusService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.relationships.repository import RelationshipRequestRepository
from app.modules.users.pending_repository import PendingRegistrationRepository
from app.modules.users.repository import UserRepository
from app.modules.users.schema import (
    PublicStatusRead,
    UserChangeEmail,
    UserChangePhone,
    UserCodeSearchRead,
    UserCreate,
    UserForgotPassword,
    UserNameSearchRead,
    UserNewCode,
    UserNewPassword,
    UserPasswordUpdate,
    UserPublicRead,
    UserRead,
    UserResendCode,
    UserUpdate,
    ValidateCode,
)
from app.modules.users.service import UserService
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.service import WalletService
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/users", tags=["users"])


def _get_service(db: AsyncSession = Depends(get_db)) -> UserService:

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


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: UserCreate, service: UserService = Depends(_get_service)):
    email_sent = await service.register(payload)
    if email_sent is None:
        user = await service.register_without_verification(payload)
        return UserRead.model_validate(user)
    return UserRead.model_validate(email_sent)


@router.post(
    "/verification_code",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UserRead,
    summary="Verify email",
)
async def verify_code_email(
    data: ValidateCode,
    service: UserService = Depends(_get_service)):
    user = await service.validate_code_email(data)
    return UserRead.model_validate(user)


@router.post(
    "/resend_verification_code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Resend the registration verification code",
)
async def resend_verification_code(
    payload: UserResendCode, service: UserService = Depends(_get_service)
):
    await service.resend_verification_code(str(payload.email))


# -- forgot password APIs -- #
@router.post(
    "/forgot_password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UserRead,
    summary="user forgot his password",
)
async def forgot_password(payload: UserForgotPassword, service: UserService = Depends(_get_service)):
    email_sent = await service.forgot_password_with_verification(payload)
    if email_sent is None:
        user = await service.forgot_password_no_verification(payload)
        return UserRead.model_validate(user)
    return UserRead.model_validate(email_sent)

#
@router.post(
    "/forgot_password_verification_code",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UserRead,
    summary="Verify code",
)
async def verify_code_forgot_password(
    data: ValidateCode,
    service: UserService = Depends(_get_service)
):
    user = await service.validate_code_password(data)
    return UserRead.model_validate(user)

@router.patch(
    "/change_forgot_password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Change forgot password",
    response_model=UserRead
)
async def change_password(
    payload: UserNewPassword,
    email:str,
    service: UserService = Depends(_get_service),
):
    new_password = await service.change_forgot_password(email, payload)
    return UserRead.model_validate(new_password)


# -- Change Password -- #
@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change current user password",
)
async def change_password(
    payload: UserPasswordUpdate,
    current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    await service.change_password(current_user, payload)


# -- Userself -- #
@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user profile",
)
async def get_me(current_user=Depends(get_current_user)):
    return UserRead.model_validate(current_user)


# -- Update user -- #
@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update current user profile",
)
async def update_me(
    payload: UserUpdate,
    current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    user = await service.update(current_user, payload)
    return UserRead.model_validate(user)

# -- generate code user -- #
@router.post(
    "/me/generate-code",
    response_model=UserRead,
    summary="Generate (or return existing) code_user for current user",
)
async def generate_my_code(
    current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    user = await service.ensure_code(current_user)
    return UserRead.model_validate(user)


@router.patch("/change_code_user", summary="update current code_user", response_model=UserNewCode)
async def update_user_code(
    current_user=Depends(get_current_user), service: UserService = Depends(_get_service)
):
    new_code = await service.update_user_code(current_user)
    return UserNewCode(code_user=new_code)


@router.get(
    "/search",
    response_model=Page[UserNameSearchRead],
    summary="Search users by name (authenticated)",
)
async def search_users(
    name: str = Query(min_length=2),
    params: PaginationParams = Depends(),
    _current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    return await service.search_by_name(current_id=_current_user.id, params=params, name=name)


@router.get(
    "/suggestions",
    response_model=Page[UserNameSearchRead],
    summary="Get opposite-gender suggestions for the current user (authenticated)",
)
async def get_suggestions(
    # Le mobile appelle toujours cette route avec page_size=10 explicite ;
    # on ne redéfinit pas le défaut de PaginationParams (20, partagé avec
    # les autres routes de listing) pour ne pas les affecter.
    params: PaginationParams = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: UserService = Depends(_get_service),
):
    relationship_repo = RelationshipRequestRepository(db)
    return await service.get_suggestions(current_user, params, relationship_repo)


@router.get(
    "/search/code/{code}",
    response_model=UserCodeSearchRead,
    summary="Get user by code, including relationship status (authenticated, free)",
)
@limiter.limit("30/minute")
async def get_by_code(
    request: Request,
    code: str,
    _current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    user = await service.get_by_code(code, searcher_id=_current_user.id)
    return await service.get_code_search_result(user)


@router.get(
    "/public-status/{code}",
    response_model=PublicStatusRead,
    summary="Get public relationship status by user code (public)",
)
@limiter.limit("20/minute")
async def get_public_status(
    request: Request,
    code: str,
    service: UserService = Depends(_get_service),
):
    user = await service.get_public_status(code)
    return PublicStatusRead.model_validate(user)


@router.post(
    "/reveal-status/{user_id}",
    response_model=PublicStatusRead,
    summary="Reveal relationship status of a name-search result (authenticated, spends ZO points)",
)
async def reveal_status(
    user_id: UUID,
    current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    return await service.reveal_status_by_id(user_id, current_user.id)


# --- change mail --
@router.patch("/update_user_email", response_model=UserRead, summary="update user email")
async def update_user_email(
    request: Request,
    payload: UserChangeEmail,
    _current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    user = await service.change_email(_current_user, payload)
    return UserRead.model_validate(user)


# --- change phone --
@router.patch("/update_user_phone", response_model=UserRead, summary="update user phone")
async def update_user_phone(
    request: Request,
    payload: UserChangePhone,
    _current_user=Depends(get_current_user),
    service: UserService = Depends(_get_service),
):
    user = await service.change_phone(_current_user, payload)
    return UserRead.model_validate(user)


# --- Admin routes ---


@router.get(
    "",
    response_model=Page[UserRead],
    summary="List all users (admin only)",
    dependencies=[Depends(require_admin)],
)
async def list_users(
    params: PaginationParams = Depends(),
    q: str | None = Query(None, description="Search by first name, last name or email"),
    service: UserService = Depends(_get_service),
):
    return await service.list_users(params, q=q)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get user by ID (admin only)",
    dependencies=[Depends(require_admin)],
)
async def get_user(user_id: str, service: UserService = Depends(_get_service)):
    user = await service.get_by_id(user_id)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user (admin only)",
    dependencies=[Depends(require_admin)],
)
async def delete_user(user_id: str, service: UserService = Depends(_get_service)):
    user = await service.get_by_id(user_id)
    await service.delete(user)
