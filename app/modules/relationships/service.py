import uuid
from datetime import UTC, datetime, timedelta
import asyncio

from fastapi import HTTPException, status

from app.modules.bonus.service import BonusReason, BonusService
from app.modules.notification.service import NotificationService
from app.modules.relationships.model import (
    RelationshipRequestStatus,
    RelationshipStatusEnum,
)
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
from app.modules.users.schema import UserPublicRead
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.modules.wallet.service import WalletService


def _display_name(user: User) -> str:
    """Nom affiché dans les notifications. `Profile.full_name` peut être
    vide pour les comptes créés avant son initialisation à l'inscription —
    on retombe alors sur first_name/last_name plutôt que d'afficher "None"."""
    full_name = user.profile.full_name if user.profile else None
    return full_name or f"{user.first_name} {user.last_name}".strip()


# Coût en points ZO pour révéler l'identité du/de la partenaire d'un
# utilisateur trouvé en recherche.
REVEAL_PARTNER_COST_ZO = 750


class RelationshipService:
    def __init__(
        self,
        status_repo: RelationshipStatusRepository,
        request_repo: RelationshipRequestRepository,
        user_repo: UserRepository,
        notification_service: NotificationService,
        bonus_service: BonusService,
        wallet_service: WalletService,
    ):
        self.status_repo = status_repo
        self.request_repo = request_repo
        self.user_repo = user_repo
        self.notification_service = notification_service
        self.bonus_service = bonus_service
        self.wallet_service = wallet_service

    async def get_my_status(self, user_id: uuid.UUID) -> RelationshipStatusRead:
        record = await self.status_repo.get_by_user_id(user_id)
        if not record:
            record = await self.status_repo.upsert(user_id, RelationshipStatusEnum.single, None)
        return RelationshipStatusRead.model_validate(record)

    async def end_relationship(self, user_id: uuid.UUID) -> RelationshipStatusRead:
        current = await self.status_repo.get_by_user_id(user_id)
        if not current or current.status not in (
            RelationshipStatusEnum.in_couple,
            RelationshipStatusEnum.married,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are not currently in a relationship",
            )

        partner_id = current.partner_id

        updated = await self.status_repo.upsert(user_id, RelationshipStatusEnum.single, None)
        if partner_id:
            await self.status_repo.upsert(partner_id, RelationshipStatusEnum.single, None)

            user = await self.user_repo.get_by_id(user_id)
            await self.notification_service.notify_relationship_ended(
                partner_id, user_id, _display_name(user)
            )

        return RelationshipStatusRead.model_validate(updated)

    async def update_my_status(
        self, user_id: uuid.UUID, data: RelationshipStatusUpdate
    ) -> RelationshipStatusRead:
        current = await self.status_repo.get_by_user_id(user_id)
        partner_id = None
        if data.status in (
            RelationshipStatusEnum.in_couple,
            RelationshipStatusEnum.married,
        ):
            if current:
                partner_id = current.partner_id
        record = await self.status_repo.upsert(user_id, data.status, partner_id)
        return RelationshipStatusRead.model_validate(record)

    async def list_incoming_requests(self, user_id: uuid.UUID) -> list[RelationshipRequestRead]:
        requests = await self.request_repo.list_incoming(user_id)
        return [RelationshipRequestRead.model_validate(r) for r in requests]

    async def list_outgoing_requests(self, user_id: uuid.UUID) -> list[RelationshipRequestRead]:
        requests = await self.request_repo.list_outgoing(user_id)
        return [RelationshipRequestRead.model_validate(r) for r in requests]

    async def send_request(
        self, requester_id: uuid.UUID, data: RelationshipRequestCreate
    ) -> RelationshipRequestRead:
        if requester_id == data.target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send a request to yourself",
            )
        target = await self.user_repo.get_by_id(data.target_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        existing = await self.request_repo.get_existing(requester_id, data.target_id)
        if existing and existing.status == RelationshipRequestStatus.pending:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already sent")

        req = await self.request_repo.create(requester_id, data.target_id)

        # AJouter une notification
        if req:
            user = await self.user_repo.get_by_id(requester_id)
            await self.notification_service.notify_friend_request_received(
                data.target_id, requester_id, _display_name(user)
            )
        return RelationshipRequestRead.model_validate(req)

    async def respond_to_request(
        self,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        data: RelationshipRequestRespond,
    ) -> RelationshipRequestRead:
        req = await self.request_repo.get_by_id(request_id)
        if not req or req.target_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if req.status != RelationshipRequestStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Request already processed"
            )

        new_status = (
            RelationshipRequestStatus.accepted
            if data.accept
            else RelationshipRequestStatus.rejected
        )
        req = await self.request_repo.update_status(req, new_status)

        if data.accept:
            await self.status_repo.upsert(
                req.requester_id, RelationshipStatusEnum.in_couple, user_id
            )
            await self.status_repo.upsert(
                user_id, RelationshipStatusEnum.in_couple, req.requester_id
            )

            # AJouter notification

        responder = await self.user_repo.get_by_id(user_id)
        await self.notification_service.notify_request_response(
            req.requester_id, user_id, _display_name(responder), accepted=data.accept
        )

        response_delay = datetime.now(UTC) - req.created_at
        if response_delay <= timedelta(hours=24):
            await self.bonus_service.award_bonus(user_id=user_id, reason=BonusReason.quick_response)

        return RelationshipRequestRead.model_validate(req)

    async def cancel_request(self, request_id: uuid.UUID, user_id: uuid.UUID) -> None:
        req = await self.request_repo.get_by_id(request_id)
        if not req or req.requester_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if req.status != RelationshipRequestStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot cancel a processed request",
            )
        await self.request_repo.delete(req)

    async def get_summary(self, user_id: uuid.UUID) -> RelationshipSummaryRead:
        status_record = await self.status_repo.get_by_user_id(user_id)
        status_val = status_record.status if status_record else RelationshipStatusEnum.single
        pending = await self.request_repo.count_incoming_pending(user_id)
        accepted = await self.request_repo.count_accepted(user_id)
        user = await self.user_repo.get_by_id(user_id)
        pv = user.profile_views if user else 0
        return RelationshipSummaryRead(
            status=status_val,
            pending_incoming=pending,
            accepted_count=accepted,
            profile_views=pv,
        )



    async def get_relationship_count(
        self, 
        user_id: uuid.UUID, 
        current_user: uuid.UUID
    ) -> int:
        
        visitor_exists_task = await self.user_repo.get_by_id(current_user)
        user_exists_task = await self.user_repo.get_by_id(user_id)
        count_task = await self.request_repo.count_accepted(user_id)
        
        if not visitor_exists_task:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Visitor account not found"
            )
            
        if not user_exists_task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found"
            )
        
        return count_task

    async def reveal_partner(
        self, user_id: uuid.UUID,
        requester_id: uuid.UUID
    ) -> RelationshipStatusRead:
        """Révèle le/la partenaire d'un utilisateur trouvé en recherche.

        Le coût est de 750 ZO. Les ZO issus d'une conversion ANK sont
        consommés en priorité et financent proportionnellement les ANK versés
        à la personne consultée et à son/sa partenaire, sans jamais créer de
        dette ANK.
        """
        requester = await self.user_repo.get_by_id(requester_id)
        target = await self.user_repo.get_by_id(user_id)

        if not requester:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Visitor account not found"
            )

        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        relationship = await self.request_repo.get_current_relationship(user_id)

        if (
            relationship is None
            or relationship.status not in (
                RelationshipStatusEnum.in_couple, RelationshipStatusEnum.married
            )
            or relationship.partner_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This user has no partner to reveal",
            )

        real_partner = relationship.partner if relationship.user_id == user_id else relationship.user

        await self.bonus_service.spend_for_reveal(
            requester_id=requester_id,
            cost_zo=REVEAL_PARTNER_COST_ZO,
            description="Voir le partenaire",
            reward_allocations=[
                (user_id, 10, 300),
                (real_partner.id, 4, 120),
            ],
            bonus_awards=[
                (user_id, 25, "Bonus standard de révélation du couple"),
                (real_partner.id, 10, "Bonus standard du partenaire consulté"),
            ],
        )

        if requester_id != user_id:
            await self.notification_service.notify_partner_viewed(user_id, requester_id)

        return RelationshipStatusRead(
                id=relationship.id,
                status=relationship.status,
                partner=UserPublicRead.model_validate(real_partner),
                created_at=relationship.created_at,
                updated_at=relationship.updated_at,
            )




        
