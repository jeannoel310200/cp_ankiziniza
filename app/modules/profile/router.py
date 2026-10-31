from datetime import date

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.users.schema import UserRead,ValidateCode
from app.modules.bonus.service import BonusService
from app.modules.profile.repository import ProfileRepository
from app.modules.notification.service import NotificationService
from app.modules.users.pending_repository import PendingRegistrationRepository
from app.modules.users.repository import UserRepository
from app.modules.users.service import UserService
from app.modules.notification.repository import NotificationRepository
from app.modules.profile.schema import (
    UpdateProfile,UpdateProfileResponse,UpdateUserMail
)
from app.modules.profile.service import ProfileService
from app.modules.users.model import User
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.service import WalletService
from app.shared.dependencies.auth import get_current_user

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _profile_service(db: AsyncSession = Depends(get_db)) -> ProfileService:
    bonus_repo = BonusRepository(db)
    wallet_repo = WalletRepository(db)
    notif_repo = NotificationRepository(db)
    user_repo = UserRepository(db)
    notif_service = NotificationService(notif_repo)
    bonus_service = BonusService(bonus_repo, wallet_repo,notif_service=notif_service)
    user_service = UserService(
        repo=user_repo,
        bonus_service=bonus_service,
        notif_service=notif_service,
        wallet_service=WalletService(repo=wallet_repo),
        pending_repo=PendingRegistrationRepository(db),
    )

    return ProfileService(
        repo=ProfileRepository(db),user_service=user_service,
        user_repo=user_repo,bonus=bonus_service
    )


@router.patch(
    "/update_profile",
    response_model=UpdateProfileResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_profile(
    response: Response,
    first_name: str | None = None,
    last_name: str | None = None,
    picture: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    service: ProfileService = Depends(_profile_service),
):
    payload = UpdateProfile(
        first_name=first_name,
        last_name=last_name,
    )

    return await service.update_profile(
        current_user=current_user,
        payload=payload,
        picture=picture,
    )

@router.patch(
    "/change_email",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UserRead,
    summary="change_user_email",
)
async def change_mail(
    payload: UpdateUserMail,
    current_user=Depends(get_current_user), 
    service: ProfileService = Depends(_profile_service)):
    email_sent = await service.change_mail_with_verification(current_user,payload)
    if email_sent is None:
        user = await service.change_mail_no_verification(current_user,payload)
        return UserRead.model_validate(user)
    return UserRead.model_validate(email_sent)

#
@router.post(
    "/change_email_verification_code",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UserRead,
    summary="Verify code",
)
async def verify_code_change_email(
    data: ValidateCode,
    current_user=Depends(get_current_user),
    service: ProfileService = Depends(_profile_service)
):
    user = await service.validate_code_change_email(current_user,data)
    return UserRead.model_validate(user)

@router.delete(
    "/delete_picture",
    response_model=UpdateProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="delete profile picture",
)
async def delete_profile_picture(
    response: Response,
    current_user: User = Depends(get_current_user),
    service: ProfileService = Depends(_profile_service),
):
    return await service.delete_profile_picture(current_user)
