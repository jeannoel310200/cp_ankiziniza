import base64
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

_MIN_WITHDRAWAL_ANK = 100_000
# Même PNG 1x1 que tests/test_verification.py : la demande exige un fichier.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _me(client: TestClient, headers: dict) -> dict:
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    return res.json()


def _register(client: TestClient) -> dict:
    suffix = uuid.uuid4().hex[:8]
    email = f"victim_{suffix}@example.com"
    register = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Victime",
            "last_name": "Test",
            "email": email,
            "password": "password1",
            "gender": "male",
        },
    )
    assert register.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password1"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def test_admin_can_delete_a_user_who_left_traces_everywhere(
    client: TestClient, admin_headers: dict
):
    """Reproduction du crash de prod : un admin qui supprime un utilisateur
    ayant déjà été émetteur d'une notification, propriétaire d'une demande
    de retrait ou d'une demande de vérification se heurtait à un
    ForeignKeyViolationError (`notifications_from_user_id_fkey` et
    équivalents) faute d'`ondelete` sur ces colonnes."""
    victim_headers = _register(client)
    victim = _me(client, victim_headers)

    # L'admin bootstrap n'a pas de code_user par défaut : on le génère avant
    # de pouvoir le rechercher.
    gen_code = client.post("/api/v1/users/me/generate-code", headers=admin_headers)
    assert gen_code.status_code == 200
    admin_code = gen_code.json()["code_user"]

    # Émetteur d'une notification (recherche du code de l'admin) :
    # notifications.from_user_id = victim.id.
    searched = client.get(
        f"/api/v1/users/search/code/{admin_code}", headers=victim_headers
    )
    assert searched.status_code == 200

    # Propriétaire d'une demande de retrait : wallet_requests.user_id = victim.id.
    credit = client.post(
        f"/api/v1/wallets/users/{victim['id']}/credit",
        params={"amount": _MIN_WITHDRAWAL_ANK, "description": "Test top-up"},
        headers=admin_headers,
    )
    assert credit.status_code == 200
    wallet_request = client.post(
        "/api/v1/wallet-requests/request",
        json={"phone": "0341234567", "amount_ank": _MIN_WITHDRAWAL_ANK},
        headers=victim_headers,
    )
    assert wallet_request.status_code == 201

    # Propriétaire d'une demande de vérification : verification_requests.user_id = victim.id.
    verification_request = client.post(
        "/api/v1/verification/request",
        data={"full_name": "Victime Test", "birth_date": "1998-04-12"},
        files={"cin_photo": ("cin.png", _PNG_1X1, "image/png")},
        headers=victim_headers,
    )
    assert verification_request.status_code == 201
    shutil.rmtree(Path("uploads/verification") / victim["id"], ignore_errors=True)

    deleted = client.delete(f"/api/v1/users/{victim['id']}", headers=admin_headers)
    assert deleted.status_code == 204

    # La notification survit côté admin, avec l'émetteur mis à NULL plutôt
    # que de bloquer la suppression.
    notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=admin_headers
    )
    assert notifs.status_code == 200
    match = next(n for n in notifs.json() if n["type"] == "profile_searched")
    assert match["from_user_id"] is None

    # L'utilisateur n'existe plus.
    again = client.delete(f"/api/v1/users/{victim['id']}", headers=admin_headers)
    assert again.status_code == 404
