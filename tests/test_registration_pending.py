import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.users.pending_model import PendingRegistration


async def _fake_send_email_success(recipients, subject, body) -> bool:
    return True


@pytest.fixture
def mail_succeeds(monkeypatch):
    """Simule un envoi d'email réussi sans réseau réel, pour exercer le
    chemin succès de UserService.register (par défaut en test, l'envoi
    échoue toujours faute de config SMTP réelle — cf. tests/conftest.py —
    ce qui exerce systématiquement le fallback, jamais ce chemin)."""
    monkeypatch.setattr("app.modules.users.service.send_email", _fake_send_email_success)


def _register(client: TestClient, email: str) -> dict:
    res = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Jean",
            "last_name": "Dupont",
            "email": email,
            "password": "password1",
            "gender": "male",
        },
    )
    assert res.status_code == 201
    return res.json()


def _login(client: TestClient, email: str) -> int:
    res = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password1"}
    )
    return res.status_code


def _pending_code(email: str) -> str:
    # Import différé : fresh_db (autouse) réassigne app.db.session.SessionLocal
    # à chaque test, un import en tête de fichier figerait l'ancienne
    # référence (vraie base Postgres au lieu du sqlite jetable du test).
    from app.db.session import SessionLocal

    async def _get() -> str:
        async with SessionLocal() as session:
            result = await session.execute(
                select(PendingRegistration).where(PendingRegistration.email == email)
            )
            return result.scalar_one().code_verification

    return asyncio.run(_get())


def test_register_does_not_create_account_until_code_is_validated(
    client: TestClient, mail_succeeds
):
    email = "pending_success@example.com"
    body = _register(client, email)
    assert body["is_verified"] is False

    # Aucun compte n'existe tant que le code n'est pas soumis : le login
    # échoue (pas "Invalid credentials" par mauvais mot de passe, mais parce
    # qu'il n'y a personne à cette adresse).
    assert _login(client, email) == 401


def test_correct_code_creates_the_account(client: TestClient, mail_succeeds):
    email = "pending_correct_code@example.com"
    body = _register(client, email)
    code = _pending_code(email)

    verified = client.post(
        "/api/v1/users/verification_code", json={"code": code, "email": email}
    )
    assert verified.status_code == 202
    assert verified.json()["is_verified"] is True
    assert verified.json()["id"] != body["id"]  # id "pending" jeté, vrai id créé ici

    assert _login(client, email) == 200


def test_wrong_code_does_not_create_an_account(client: TestClient, mail_succeeds):
    email = "pending_wrong_code@example.com"
    _register(client, email)

    verified = client.post(
        "/api/v1/users/verification_code", json={"code": "000000", "email": email}
    )
    assert verified.status_code == 404
    assert _login(client, email) == 401


def test_resend_verification_code_regenerates_and_still_validates(
    client: TestClient, mail_succeeds
):
    email = "pending_resend@example.com"
    _register(client, email)

    resent = client.post(
        "/api/v1/users/resend_verification_code", json={"email": email}
    )
    assert resent.status_code == 204

    code = _pending_code(email)
    verified = client.post(
        "/api/v1/users/verification_code", json={"code": code, "email": email}
    )
    assert verified.status_code == 202
    assert _login(client, email) == 200


def test_resend_verification_code_404_when_nothing_pending(client: TestClient):
    res = client.post(
        "/api/v1/users/resend_verification_code",
        json={"email": "never_registered@example.com"},
    )
    assert res.status_code == 404


def test_register_fallback_path_unchanged_when_mail_fails(client: TestClient):
    """Sans mail_succeeds, l'envoi échoue (config SMTP absente en test,
    cf. conftest.py) : comportement inchangé, compte créé immédiatement."""
    email = "fallback_unchanged@example.com"
    body = _register(client, email)
    assert body["is_verified"] is True
    assert _login(client, email) == 200
