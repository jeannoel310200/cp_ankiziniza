from __future__ import annotations

import uuid
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.account_deletion.repository import AccountDeletionRepository
from app.modules.account_deletion.schema import (
    AccountDeletionCancel,
    AccountDeletionCreate,
    AccountDeletionRequestRead,
)
from app.modules.account_deletion.service import AccountDeletionRequestError, AccountDeletionService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.service import NotificationService
from app.modules.users.model import User
from app.modules.users.repository import UserRepository
from app.shared.dependencies.auth import get_current_user, require_admin
from app.shared.schemas.pagination import Page, PaginationParams

router = APIRouter(prefix="/account-deletion", tags=["account deletion"])
public_router = APIRouter(tags=["account deletion public"])

_TEMPLATE_DIR = Path(__file__).with_name("templates")
_LAYOUT_TEMPLATE = (_TEMPLATE_DIR / "layout.html").read_text(encoding="utf-8")
_FORM_TEMPLATE = (_TEMPLATE_DIR / "form.html").read_text(encoding="utf-8")
_SUCCESS_TEMPLATE = (_TEMPLATE_DIR / "success.html").read_text(encoding="utf-8")


def get_account_deletion_service(db: AsyncSession = Depends(get_db)) -> AccountDeletionService:
    return AccountDeletionService(
        repo=AccountDeletionRepository(db=db),
        user_repo=UserRepository(db),
        notif_service=NotificationService(NotificationRepository(db=db)),
    )


# --- Authenticated (mobile) + admin routes, JSON, sous /api/v1 ---


@router.post(
    "/request", response_model=AccountDeletionRequestRead, status_code=status.HTTP_201_CREATED
)
async def request_account_deletion(
    data: AccountDeletionCreate,
    current_user: User = Depends(get_current_user),
    service: AccountDeletionService = Depends(get_account_deletion_service),
):
    return await service.request_deletion_authenticated(current_user, data.reason)


@router.get("/me", response_model=AccountDeletionRequestRead | None)
async def my_account_deletion_request(
    current_user: User = Depends(get_current_user),
    service: AccountDeletionService = Depends(get_account_deletion_service),
):
    return await service.get_my_latest(current_user.id)


@router.get("/admin/pending", response_model=Page[AccountDeletionRequestRead])
async def list_pending_account_deletions(
    params: PaginationParams = Depends(),
    admin: User = Depends(require_admin),
    service: AccountDeletionService = Depends(get_account_deletion_service),
):
    return await service.list_pending(params)


@router.patch("/admin/{request_id}/delete", response_model=AccountDeletionRequestRead)
async def delete_account_from_request(
    request_id: uuid.UUID,
    admin: User = Depends(require_admin),
    service: AccountDeletionService = Depends(get_account_deletion_service),
):
    return await service.delete_account(request_id, admin.id)


@router.patch("/admin/{request_id}/cancel", response_model=AccountDeletionRequestRead)
async def cancel_account_deletion(
    request_id: uuid.UUID,
    data: AccountDeletionCancel,
    admin: User = Depends(require_admin),
    service: AccountDeletionService = Depends(get_account_deletion_service),
):
    return await service.cancel(request_id, admin.id, data.admin_note)


# --- Public (no auth), HTML, à la racine du domaine ---
# URL Google Play Console (Data safety > Delete account) :
# https://ankiziniza.holy-dev.mg/api/v1/delete-account
# (pas à la racine du domaine : le reverse proxy ne route que /api/v1 vers ce
# service, la racine sert l'app web admin — cf. web-v2/nginx.conf).


def _render(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
    return rendered


def _document(title: str, body: str) -> HTMLResponse:
    settings = get_settings()
    application_name = escape(settings.app_name or "Akiziniza")
    contact = escape(settings.mail_from or "le support de l'application")
    document = _render(
        _LAYOUT_TEMPLATE,
        {
            "title": escape(f"{title} - {application_name}"),
            "application_name": application_name,
            "body": body,
            "contact": contact,
        },
    )
    return HTMLResponse(content=document)


def _form_page(
    *, banner: str = "", email_value: str = "", code_value: str = "", reason_value: str = ""
) -> HTMLResponse:
    settings = get_settings()
    body = _render(
        _FORM_TEMPLATE,
        {
            "application_name": escape(settings.app_name or "Akiziniza"),
            "banner": banner,
            "email_value": escape(email_value),
            "code_value": escape(code_value),
            "reason_value": escape(reason_value),
        },
    )
    return _document("Suppression de compte", body)


@public_router.get(
    "/delete-account",
    response_class=HTMLResponse,
    summary="Formulaire de demande de suppression de compte",
    description="Page publique (sans authentification) permettant de demander la "
    "suppression d'un compte — URL à renseigner dans la Play Console.",
)
async def delete_account_form() -> HTMLResponse:
    return _form_page()


@public_router.post(
    "/delete-account",
    response_class=HTMLResponse,
    include_in_schema=False,
)
@limiter.limit("5/minute")
async def submit_delete_account_request(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    reason: str | None = Form(None),
    service: AccountDeletionService = Depends(get_account_deletion_service),
) -> HTMLResponse:
    try:
        await service.request_deletion_public(email, code, reason)
    except AccountDeletionRequestError as exc:
        return _form_page(
            banner=f'<div class="error-banner">{escape(str(exc))}</div>',
            email_value=email,
            code_value=code,
            reason_value=reason or "",
        )

    settings = get_settings()
    body = _render(
        _SUCCESS_TEMPLATE,
        {
            "application_name": escape(settings.app_name or "Akiziniza"),
            "email_value": escape(email),
        },
    )
    return _document("Demande envoyée", body)
