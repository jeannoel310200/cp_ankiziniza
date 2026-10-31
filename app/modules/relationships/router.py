import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.bonus.repository import BonusRepository
from app.modules.bonus.service import BonusService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.relationships.repository import (
    RelationshipRequestRepository,
    RelationshipStatusRepository,
)
from app.modules.relationships.schema import (
    RelationshipRequestCreate,
    RelationshipRequestRead,
    RelationshipRequestRespond,
    RelationshipStatusRead,
    RelationshipStatusUpdate,
    RelationshipSummaryRead,
)
from app.modules.relationships.service import RelationshipService
from app.modules.users.repository import UserRepository
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet.service import WalletService
from app.shared.dependencies.auth import get_current_user

router = APIRouter(prefix="/relationships", tags=["Relationships"])


def _get_service(db: AsyncSession = Depends(get_db)) -> RelationshipService:
    return RelationshipService(
        status_repo=RelationshipStatusRepository(db),
        request_repo=RelationshipRequestRepository(db),
        user_repo=UserRepository(db=db),
        notification_service=NotificationService(NotificationRepository(db=db)),
        bonus_service=BonusService(
            repo=BonusRepository(db=db),
            wallet_repo=WalletRepository(db=db),
            notif_service=NotificationService(NotificationRepository(db=db)),
        ),
        wallet_service=WalletService(repo=WalletRepository(db=db)),
    )

# -- voir le nombre de relation en attente et accepté -- #
@router.get(
    "/summary",
    response_model=RelationshipSummaryRead,
    summary="Get my relationship & activity summary",
)
async def get_summary(
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.get_summary(current_user.id)


# -- voir sa propre relation
@router.get(
    "/status/me",
    response_model=RelationshipStatusRead,
    summary="Get my relationship status",
)
async def get_my_status(
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.get_my_status(current_user.id)

# -- modifier sa relation -- #
@router.put(
    "/status/me",
    response_model=RelationshipStatusRead,
    summary="Update my relationship status",
)
async def update_my_status(
    payload: RelationshipStatusUpdate,
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.update_my_status(current_user.id, payload)


# -- afficher la liste de demande que d'autres personnes lui ont envoyés -- #
@router.get(
    "/requests/incoming",
    response_model=list[RelationshipRequestRead],
    summary="List incoming relationship requests",
)
async def list_incoming(
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.list_incoming_requests(current_user.id)


# -- Affiche la liste de demandes qu'il a envoyées à d'autres
@router.get(
    "/requests/outgoing",
    response_model=list[RelationshipRequestRead],
    summary="List outgoing relationship requests",
)
async def list_outgoing(
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.list_outgoing_requests(current_user.id)

# -- envoyer la demande -- #
@router.post(
    "/requests",
    response_model=RelationshipRequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a relationship request",
)
async def send_request(
    payload: RelationshipRequestCreate,
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.send_request(current_user.id, payload)


# -- accepter la demande --
@router.patch(
    "/requests/{request_id}",
    response_model=RelationshipRequestRead,
    summary="Accept or reject a relationship request",
)
async def respond_to_request(
    request_id: uuid.UUID,
    payload: RelationshipRequestRespond,
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.respond_to_request(request_id, current_user.id, payload)


# -- rompre la rélation
@router.post("/relationships/end", response_model=RelationshipStatusRead)
async def end_relationship(
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    return await service.end_relationship(current_user.id)

# -- refuser la demande
@router.delete(
    "/requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a relationship request",
)
async def cancel_request(
    request_id: uuid.UUID,
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service),
):
    await service.cancel_request(request_id, current_user.id)


# -- voir le nom d'un utilisateur en couple avec un utilisateur (payant)
@router.post(
    "/{user_id}/reveal-partner",
    status_code=status.HTTP_200_OK,
    response_model=RelationshipStatusRead,
    summary="Reveal the identity of a user's partner if they're in a couple (authenticated, spends ZO points)",
)
async def reveal_partner(
    user_id: uuid.UUID,
    current_user=Depends(get_current_user),
    service: RelationshipService = Depends(_get_service)
) -> RelationshipStatusRead:

    return await service.reveal_partner(user_id, current_user.id)





