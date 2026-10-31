import base64
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

_BASE = "/api/v1/verification"
_NOTIFS = "/api/v1/views_notifications/notifications"

# Même PNG 1x1 que tests/test_profile.py : la demande exige un fichier.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _me(client: TestClient, headers: dict) -> dict:
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    return res.json()


def _request_verification(client: TestClient, headers: dict):
    return client.post(
        f"{_BASE}/request",
        data={"full_name": "Annah Marie", "birth_date": "1998-04-12"},
        files={"cin_photo": ("cin.png", _PNG_1X1, "image/png")},
        headers=headers,
    )


def _my_verification(client: TestClient, headers: dict):
    return client.get(f"{_BASE}/me", headers=headers)


def _register_other_user(client: TestClient) -> dict:
    suffix = uuid.uuid4().hex[:8]
    email = f"other_{suffix}@example.com"
    assert client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Autre",
            "last_name": "Compte",
            "email": email,
            "password": "password1",
            "gender": "female",
        },
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _cleanup(user_id: str) -> None:
    shutil.rmtree(Path("uploads/verification") / user_id, ignore_errors=True)


def test_no_request_yet_is_reported_as_such(client: TestClient, auth_headers: dict):
    """L'app doit pouvoir distinguer « jamais demandé » d'une demande en cours,
    sinon elle affiche le bouton d'envoi à tort."""
    res = _my_verification(client, auth_headers)
    assert res.status_code in (200, 204)
    if res.status_code == 200:
        assert res.json() is None


def test_pending_request_is_visible_after_restart(
    client: TestClient, auth_headers: dict
):
    """Le cœur du bug : cet état ne vivait que dans la mémoire de l'app, donc
    au redémarrage le bouton réapparaissait et l'envoi partait pour rien."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201

        res = _my_verification(client, auth_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "pending"
    finally:
        _cleanup(user_id)


def test_second_request_is_refused(client: TestClient, auth_headers: dict):
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201
        assert _request_verification(client, auth_headers).status_code == 409
    finally:
        _cleanup(user_id)


def test_my_verification_does_not_leak_another_users_request(
    client: TestClient, auth_headers: dict
):
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201

        other = _register_other_user(client)
        res = _my_verification(client, other)
        assert res.status_code in (200, 204)
        if res.status_code == 200:
            assert res.json() is None
    finally:
        _cleanup(user_id)


def test_rejection_is_notified_and_lets_the_user_retry(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    """Sans notification, l'utilisateur ne sait pas pourquoi sa demande a été
    refusée : il la refait à l'identique."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201

        pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
        assert pending.status_code == 200
        request_id = next(r["id"] for r in pending.json()["items"] if r["user_id"] == user_id)

        note = "Photo de la pièce d'identité illisible"
        rejected = client.patch(
            f"{_BASE}/admin/{request_id}/reject",
            json={"admin_note": note},
            headers=admin_headers,
        )
        assert rejected.status_code == 200

        mine = _my_verification(client, auth_headers)
        assert mine.status_code == 200
        assert mine.json()["status"] == "rejected"
        assert mine.json()["admin_note"] == note

        # La notification doit porter le motif.
        notifs = client.get(_NOTIFS, headers=auth_headers)
        assert notifs.status_code == 200
        rejection = [
            n for n in notifs.json() if n["type"] == "verification_rejected"
        ]
        assert len(rejection) == 1
        assert note in rejection[0]["message"]

        # Le serveur ne bloque que les demandes pending : une nouvelle passe.
        assert _request_verification(client, auth_headers).status_code == 201
    finally:
        _cleanup(user_id)


def test_admin_can_view_verification_photo(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    """L'admin doit pouvoir voir la pièce d'identité envoyée, pas juste le
    nom/date de naissance déclaratifs."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201

        pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
        request_id = next(r["id"] for r in pending.json()["items"] if r["user_id"] == user_id)

        photo = client.get(f"{_BASE}/admin/{request_id}/photo", headers=admin_headers)
        assert photo.status_code == 200
        assert photo.content == _PNG_1X1
    finally:
        _cleanup(user_id)


def test_verification_photo_is_not_accessible_without_admin(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    """`uploads/verification` n'étant pas monté en statique, cette route est
    le seul accès à la pièce d'identité : elle ne doit jamais être ouverte à
    un compte non-admin, même authentifié."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _request_verification(client, auth_headers).status_code == 201

        pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
        request_id = next(r["id"] for r in pending.json()["items"] if r["user_id"] == user_id)

        as_owner = client.get(f"{_BASE}/admin/{request_id}/photo", headers=auth_headers)
        assert as_owner.status_code == 403

        anonymous = client.get(f"{_BASE}/admin/{request_id}/photo")
        assert anonymous.status_code == 401
    finally:
        _cleanup(user_id)
