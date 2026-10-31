import uuid

from fastapi import HTTPException, status

from app.modules.notification.model import NotificationType
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.schema import CreateNotification, NotificationRead, UnreadCountRead
from app.modules.notification.ssemanager.manager import notification_store
from app.modules.users.model import GenderEnum


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self.repo = repo

    # --- Générique ---
    async def create_notification(self, data: CreateNotification) -> NotificationRead:
        notif = await self.repo.create(
            to_user_id=data.to_user_id,
            type_=data.type,
            message=data.message,
            from_user_id=data.from_user_id,
        )
        read = NotificationRead.model_validate(notif)
        self._push_live(data.to_user_id, read)
        return read

    def _push_live(self, to_user_id: uuid.UUID, notif: NotificationRead) -> None:
        """Pousse la notification vers les flux SSE ouverts du destinataire
        (aucun effet si personne n'est connecté — cf. ConnectionStore)."""
        payload = notif.model_dump(mode="json")
        for queue in notification_store.get(to_user_id):
            queue.put_nowait(payload)

    # --- Méthodes dédiées par source (utilisées par les autres services) ---

    async def notify_bonus_received(
        self, user_id: uuid.UUID, points: int, reason_label: str
    ) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.bonus_received,
                message=f"Vous avez reçu {points} points bonus : {reason_label}",
            )
        )

    async def notify_ank_received(
        self,
        user_id: uuid.UUID,
        points: int,
        reason_label: str,
        from_user_id: uuid.UUID | None = None,
    ) -> None:
        if points <= 0:
            return
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                from_user_id=from_user_id,
                type=NotificationType.ank_received,
                message=f"Vous avez reçu {points} points ANK : {reason_label}",
            )
        )

    async def notify_profile_searched(self, owner_id: uuid.UUID, searcher_id: uuid.UUID) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=owner_id,
                from_user_id=searcher_id,
                type=NotificationType.profile_searched,
                message="Quelqu'un a consulté votre profil",
            )
        )

    async def notify_partner_viewed(self, owner_id: uuid.UUID, viewer_id: uuid.UUID) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=owner_id,
                from_user_id=viewer_id,
                type=NotificationType.partner_viewed,
                message="Quelqu'un a consulté l'identité de votre partenaire",
            )
        )

    async def notify_friend_request_received(
        self, target_id: uuid.UUID, requester_id: uuid.UUID, requester_name: str
    ) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=target_id,
                from_user_id=requester_id,
                type=NotificationType.friend_request_received,
                message=f"{requester_name} vous a envoyé une demande",
            )
        )

    async def notify_request_response(
        self, requester_id: uuid.UUID, responder_id: uuid.UUID, responder_name: str, accepted: bool
    ) -> None:
        notif_type = (
            NotificationType.friend_request_accepted
            if accepted
            else NotificationType.friend_request_rejected
        )
        verb = "accepté" if accepted else "refusé"
        await self.create_notification(
            CreateNotification(
                to_user_id=requester_id,
                from_user_id=responder_id,
                type=notif_type,
                message=f"{responder_name} a {verb} votre demande",
            )
        )

    async def notify_account_verified(self, user_id: uuid.UUID) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.account_verified,
                message="Votre compte a été vérifié avec succès",
            )
        )

    async def notify_verification_rejected(
        self, user_id: uuid.UUID, admin_note: str
    ) -> None:
        # Le motif est indispensable : sans lui l'utilisateur refait la même
        # demande à l'identique.
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.verification_rejected,
                message=f"Votre demande de vérification a été refusée : {admin_note}",
            )
        )

    async def notify_relationship_ended(
        self, user_id: uuid.UUID, ex_partner_id: uuid.UUID, ex_partner_name: str
    ) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                from_user_id=ex_partner_id,
                type=NotificationType.relationship_ended,
                message=f"{ex_partner_name} a mis fin à votre relation",
            )
        )

    async def notify_wallet_request_approved(
        self, user_id: uuid.UUID, amount_ank: int, gender: GenderEnum | None
    ) -> None:
        # Accord du participe passé selon le sexe (à défaut de sexe connu, on
        # retombe sur le masculin, générique en français).
        verb = "contactée" if gender == GenderEnum.FEMALE else "contacté"
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.wallet_request_approved,
                message=f"Votre retrait de {amount_ank} points ANK a été validé, vous serez {verb} pour le paiement",
            )
        )

    async def notify_wallet_request_rejected(
        self, user_id: uuid.UUID, amount_ank: int, admin_note: str
    ) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.wallet_request_rejected,
                message=f"Ta demande de retrait de {amount_ank} points ANK a été "
                f"refusée : {admin_note}",
            )
        )

    async def notify_account_deletion_cancelled(
        self, user_id: uuid.UUID, admin_note: str
    ) -> None:
        # Le motif est indispensable : sans lui l'utilisateur ne sait pas
        # pourquoi sa demande de suppression n'a pas été honorée.
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.account_deletion_cancelled,
                message=f"Votre demande de suppression de compte a été annulée : {admin_note}",
            )
        )

    async def notify_code_regenerated(self, user_id: uuid.UUID) -> None:
        await self.create_notification(
            CreateNotification(
                to_user_id=user_id,
                type=NotificationType.code_regenerated,
                message="Votre code a expiré et a été régénéré automatiquement",
            )
        )

    # --- Lecture / consultation ---

    async def get_my_notifications(self, user_id: uuid.UUID) -> list[NotificationRead]:
        notifs = await self.repo.list_by_user(user_id)
        return [NotificationRead.model_validate(n) for n in notifs]

    async def get_unread_count(self, user_id: uuid.UUID) -> UnreadCountRead:
        count = await self.repo.count_unread(user_id)
        return UnreadCountRead(count=count)

    async def mark_as_read(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationRead:
        notif = await self.repo.get_by_id(notification_id)
        if not notif or notif.to_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
            )
        updated = await self.repo.mark_as_read(notif)
        return NotificationRead.model_validate(updated)

    async def mark_all_as_read(self, user_id: uuid.UUID) -> None:
        await self.repo.mark_all_as_read(user_id)

    async def delete_notification(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        # Même contrôle que mark_as_read. On renvoie 404 plutôt que 403 pour ne
        # pas révéler l'existence de la notification d'un autre utilisateur.
        notif = await self.repo.get_by_id(notification_id)
        if not notif or notif.to_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
            )
        await self.repo.delete(notif)

    async def delete_all(self, user_id: uuid.UUID) -> None:
        await self.repo.delete_all_by_user(user_id)
