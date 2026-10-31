import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.modules.notification.service import NotificationService
from app.modules.users.repository import UserRepository
from app.modules.wallet.model import TransactionOrigin
from app.modules.wallet.repository import WalletRepository
from app.modules.wallet_request.model import WalletRequestStatus
from app.modules.wallet_request.repository import WalletRequestRepository
from app.modules.wallet_request.schema import (
    WalletRequestAdminRead,
    WalletRequestCreate,
    WalletRequestRead,
)
from app.shared.schemas.pagination import Page, PaginationParams, make_page

# En dessous de ce solde, un retrait n'est pas proposé (cf. palier de retrait
# 1 ANK = 550 Ar
MIN_WITHDRAWAL_ANK = 100
_DEFAULT_MOTIF = "Retrait de points ANK"


class WalletRequestService:
    def __init__(
        self,
        repo: WalletRequestRepository,
        wallet_repo: WalletRepository,
        user_repo: UserRepository,
        notif_service: NotificationService,
    ):
        self.repo = repo
        self.wallet_repo = wallet_repo
        self.user_repo = user_repo
        self.notif_service = notif_service

    async def request_transaction(
        self, user_id: uuid.UUID, data: WalletRequestCreate
    ) -> WalletRequestRead:
        wallet = await self.wallet_repo.get_or_create(user_id)
        if wallet.points < MIN_WITHDRAWAL_ANK:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum {MIN_WITHDRAWAL_ANK} ANK balance required to request a withdrawal",
            )
        if data.amount_ank > wallet.points:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient wallet balance",
            )

        motif = (data.motif or "").strip() or _DEFAULT_MOTIF
        req = await self.repo.create(
            {
                "user_id": user_id,
                "motif": motif,
                "phone": data.phone.strip(),
                "amount_ank": data.amount_ank,
            }
        )
        return WalletRequestRead.model_validate(req)

    async def list_my_requests(self, user_id: uuid.UUID) -> list[WalletRequestRead]:
        reqs = await self.repo.list_by_user(user_id)
        return [WalletRequestRead.model_validate(r) for r in reqs]

    async def list_pending(self, params: PaginationParams) -> Page[WalletRequestAdminRead]:
        rows, total = await self.repo.list_pending(params.offset, params.limit)
        items = [
            WalletRequestAdminRead(
                id=req.id,
                user_id=req.user_id,
                user_name=f"{user.first_name} {user.last_name}".strip(),
                user_email=user.email,
                motif=req.motif,
                phone=req.phone,
                amount_ank=req.amount_ank,
                status=req.status,
                admin_note=req.admin_note,
                reviewed_at=req.reviewed_at,
                created_at=req.created_at,
            )
            for req, user in rows
        ]
        return make_page(items, total, params)

    async def approve(self, request_id: uuid.UUID, admin_id: uuid.UUID) -> WalletRequestRead:
        """Un retrait : approuver DÉBITE le wallet (l'admin paie l'utilisateur
        en argent hors de l'app) — ce n'est pas un rechargement."""
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != WalletRequestStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending wallet request not found",
            )

        wallet = await self.wallet_repo.get_or_create(req.user_id)
        try:
            await self.wallet_repo.debit(
                wallet,
                req.amount_ank,
                TransactionOrigin.withdrawal,
                description=f"Retrait de {req.amount_ank} points ANK approuvé",
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        updated = await self.repo.update(
            req,
            {
                "status": WalletRequestStatus.approved,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )

        user = await self.user_repo.get_by_id(req.user_id)
        await self.notif_service.notify_wallet_request_approved(
            req.user_id, req.amount_ank, user.gender if user else None
        )

        return WalletRequestRead.model_validate(updated)

    async def reject(
        self, request_id: uuid.UUID, admin_id: uuid.UUID, admin_note: str
    ) -> WalletRequestRead:
        req = await self.repo.get_by_id(request_id)
        if not req or req.status != WalletRequestStatus.pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending wallet request not found",
            )

        updated = await self.repo.update(
            req,
            {
                "status": WalletRequestStatus.rejected,
                "admin_note": admin_note,
                "reviewed_by": admin_id,
                "reviewed_at": datetime.now(UTC),
            },
        )

        # Refus notifié in-app (et poussé en direct par SSE), pas par email —
        # un email peut se perdre ou finir en spam, la notification in-app
        # est ce que l'utilisateur voit réellement dans l'app.
        await self.notif_service.notify_wallet_request_rejected(
            req.user_id, req.amount_ank, admin_note
        )

        return WalletRequestRead.model_validate(updated)
