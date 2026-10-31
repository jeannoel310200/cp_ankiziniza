import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.modules.account_deletion.model import AccountDeletionStatus
from app.modules.account_deletion.repository import AccountDeletionRepository
from app.modules.account_deletion.schema import AccountDeletionRequestRead
from app.modules.notification.service import NotificationService
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.shared.schemas.pagination import Page, PaginationParams, make_page


class AccountDeletionRequestError(Exception):
    """Erreur métier du formulaire public (email inconnu, code invalide,
    demande déjà en cours). Volontairement distincte d'HTTPException : le
    router public répond en HTML (ré-affiche le formulaire avec le message),
    pas en JSON."""


class AccountDeletionService:
    def __init__(
        self,
        repo: AccountDeletionRepository,
        user_repo: UserRepository,
        notif_service: NotificationService,
    ):
        self.repo = repo
        self.user_repo = user_repo
        self.notif_service = notif_service

    async def _create(self, user: User, reason: str | None) -> AccountDeletionRequestRead:
        existing = await self.repo.get_pending_by_user_id(user.id)
        if existing:
            raise AccountDeletionRequestError(
                "Une demande de suppression est déjà en cours pour ce compte."
            )
        req = await self.repo.create(
            {
                "user_id": user.id,
                "email": user.email,
                "full_name": f"{user.first_name} {user.last_name}".strip(),
                "reason": reason,
            }
        )
        return AccountDeletionRequestRead.model_validate(req)

    async def request_deletion_authenticated(
        self, user: User, reason: str | None
    ) -> AccountDeletionRequestRead:
        try:
            return await self._create(user, reason)
        except AccountDeletionRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

    async def request_deletion_public(
        self, email: str, code: str, reason: str | None
    ) -> AccountDeletionRequestRead:
        user = await self.user_repo.get_by_email(email.strip())
        if not user or not user.code_user or user.code_user != code.strip().upper():
            raise AccountDeletionRequestError(
                "Aucun compte ne correspond à cet email et ce code personnel."
            )
        return await self._create(user, reason)

    async def get_my_latest(self, user_id: uuid.UUID) -> AccountDeletionRequestRead | None:
        req = await self.repo.get_latest_by_user_id(user_id)
        return AccountDeletionRequestRead.model_validate(req) if req else None

    async def list_pending(self, params: PaginationParams) -> Page[AccountDeletionRequestRead]:
        reqs, total = await self.repo.list_pending(params.offset, params.limit)
        return make_page(
            [AccountDeletionRequestRead.model_validate(r) for r in reqs], total, params
        )

    async def delete_account(
        self, request_id: uuid.UUID, admin_id: uuid.UUID
    ) -> AccountDeletionRequestRead:
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != AccountDeletionStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending account deletion request not found",
            )

        if req.user_id:
            user = await self.user_repo.get_by_id(req.user_id)
            if user:
                await self.user_repo.delete(user)

        updated = await self.repo.update(
            req,
            {
                "status": AccountDeletionStatus.deleted,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )
        return AccountDeletionRequestRead.model_validate(updated)

    async def cancel(
        self, request_id: uuid.UUID, admin_id: uuid.UUID, admin_note: str
    ) -> AccountDeletionRequestRead:
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != AccountDeletionStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending account deletion request not found",
            )

        updated = await self.repo.update(
            req,
            {
                "status": AccountDeletionStatus.cancelled,
                "admin_note": admin_note,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )

        if req.user_id:
            await self.notif_service.notify_account_deletion_cancelled(req.user_id, admin_note)

        return AccountDeletionRequestRead.model_validate(updated)
