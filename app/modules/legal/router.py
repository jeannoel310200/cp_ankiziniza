"""Endpoints publics pour les documents légaux de l'application."""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import get_settings

router = APIRouter(prefix="/legal", tags=["legal"])
_TEMPLATE_DIR = Path(__file__).with_name("templates")
_LAYOUT_TEMPLATE = (_TEMPLATE_DIR / "layout.html").read_text(encoding="utf-8")
_TERMS_TEMPLATE = (_TEMPLATE_DIR / "terms.html").read_text(encoding="utf-8")
_PRIVACY_TEMPLATE = (_TEMPLATE_DIR / "privacy.html").read_text(encoding="utf-8")
_CHILD_SAFETY_TEMPLATE = (_TEMPLATE_DIR / "child_safety.html").read_text(encoding="utf-8")


def _render(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
    return rendered


def _legal_url(document: str) -> str:
    prefix = (get_settings().api_v1_prefix or "/api/v1").rstrip("/")
    return f"{prefix}/legal/{document}"


def _document(title: str, intro: str, body: str) -> HTMLResponse:
    settings = get_settings()
    application_name = escape(settings.app_name or "Akiziniza")
    contact = escape(settings.mail_from or "le support de l'application")
    document = _render(
        _LAYOUT_TEMPLATE,
        {
            "title": escape(f"{title} - {application_name}"),
            "application_name": application_name,
            "effective_date": date.today().strftime("%d/%m/%Y"),
            "intro": escape(intro),
            "body": body,
            "contact": contact,
        },
    )
    return HTMLResponse(
        content=document,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get(
    "/terms",
    response_class=HTMLResponse,
    summary="Conditions d'utilisation",
    description="Document public des conditions d'utilisation d'Akiziniza.",
)
async def terms_of_use() -> HTMLResponse:
    body = _render(_TERMS_TEMPLATE, {"privacy_url": escape(_legal_url("privacy"))})
    return _document(
        "Conditions d'utilisation",
        (
            "Veuillez lire ces règles avant de créer un compte ou d'utiliser les "
            "fonctionnalités sociales et de points ANK."
        ),
        body,
    )


@router.get(
    "/privacy",
    response_class=HTMLResponse,
    summary="Politique de confidentialité",
    description="Document public sur la collecte et l'utilisation des données Akiziniza.",
)
async def privacy_policy() -> HTMLResponse:
    return _document(
        "Politique de confidentialité",
        (
            "Cette politique explique quelles données Akiziniza traite, pourquoi elles sont "
            "nécessaires et comment exercer vos droits."
        ),
        _PRIVACY_TEMPLATE,
    )


@router.get(
    "/child-safety-standards",
    response_class=HTMLResponse,
    summary="Normes liées à la sécurité des enfants",
    description="Normes publiques de sécurité des enfants et procédure de signalement d'Ankizin'iza.",
)
async def child_safety_standards() -> HTMLResponse:
    return _document(
        "Normes liées à la sécurité des enfants",
        (
            "Ankizin'iza applique une politique de tolérance zéro envers toute exploitation "
            "ou tout abus sexuel visant des mineurs (CSAE)."
        ),
        _CHILD_SAFETY_TEMPLATE,
    )
