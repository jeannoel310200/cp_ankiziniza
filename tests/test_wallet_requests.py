import uuid

from fastapi.testclient import TestClient


_BASE = "/api/v1/wallet-requests"
_MIN_BALANCE = 100_000


def _me(client: TestClient, headers: dict) -> dict:
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    return res.json()


def _register_headers(client: TestClient, gender: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"user_{suffix}@example.com"
    register = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": email,
            "password": "password1",
            "gender": gender,
        },
    )
    assert register.status_code == 201

    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password1"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _credit_wallet(client: TestClient, admin_headers: dict, user_id: str, amount: int) -> None:
    res = client.post(
        f"/api/v1/wallets/users/{user_id}/credit",
        params={"amount": amount, "description": "Test top-up"},
        headers=admin_headers,
    )
    assert res.status_code == 200


def _spend_wallet(client: TestClient, headers: dict, amount: int) -> None:
    res = client.post(
        "/api/v1/wallets/me/spend",
        json={"amount": amount, "reason": "Test spend"},
        headers=headers,
    )
    assert res.status_code == 200


def _request_transaction(client: TestClient, headers: dict, amount_ank: int) -> dict:
    res = client.post(
        f"{_BASE}/request",
        json={"phone": "0341234567", "amount_ank": amount_ank},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()


def test_request_requires_minimum_wallet_balance(client: TestClient, auth_headers: dict):
    res = client.post(
        f"{_BASE}/request",
        json={"phone": "0341234567", "amount_ank": _MIN_BALANCE},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_request_transaction_is_pending_with_default_motif(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], _MIN_BALANCE + 50_000)

    created = _request_transaction(client, auth_headers, amount_ank=_MIN_BALANCE)
    assert created["status"] == "pending"
    assert created["amount_ank"] == _MIN_BALANCE
    assert created["phone"] == "0341234567"
    # Le mobile n'envoie plus de motif : le serveur en assigne un générique.
    assert created["motif"]


def test_admin_pending_list_includes_requester_identity_and_pagination(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], _MIN_BALANCE)
    _request_transaction(client, auth_headers, amount_ank=_MIN_BALANCE)

    pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
    assert pending.status_code == 200
    body = pending.json()
    assert body["total"] >= 1
    assert body["page"] == 1
    match = next(r for r in body["items"] if r["user_id"] == user["id"])
    assert match["user_email"] == user["email"]
    assert match["amount_ank"] == _MIN_BALANCE


def test_approve_debits_wallet_and_notifies(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], _MIN_BALANCE + 50_000)
    _request_transaction(client, auth_headers, amount_ank=_MIN_BALANCE)

    pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
    request_id = next(
        r["id"] for r in pending.json()["items"] if r["user_id"] == user["id"]
    )

    approved = client.patch(f"{_BASE}/admin/{request_id}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.status_code == 200
    assert wallet.json()["points"] == 50_000

    notifs = client.get("/api/v1/views_notifications/notifications", headers=auth_headers)
    assert notifs.status_code == 200
    matches = [n for n in notifs.json() if n["type"] == "wallet_request_approved"]
    assert len(matches) == 1
    assert str(_MIN_BALANCE) in matches[0]["message"]

    # Une demande déjà traitée ne peut plus être approuvée deux fois.
    again = client.patch(f"{_BASE}/admin/{request_id}/approve", headers=admin_headers)
    assert again.status_code == 404


def test_approve_notification_uses_gender_appropriate_verb(
    client: TestClient, admin_headers: dict
):
    male_headers = _register_headers(client, "male")
    male_user = _me(client, male_headers)
    _credit_wallet(client, admin_headers, male_user["id"], _MIN_BALANCE)
    _request_transaction(client, male_headers, amount_ank=_MIN_BALANCE)

    female_headers = _register_headers(client, "female")
    female_user = _me(client, female_headers)
    _credit_wallet(client, admin_headers, female_user["id"], _MIN_BALANCE)
    _request_transaction(client, female_headers, amount_ank=_MIN_BALANCE)

    pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers).json()["items"]
    male_request_id = next(r["id"] for r in pending if r["user_id"] == male_user["id"])
    female_request_id = next(r["id"] for r in pending if r["user_id"] == female_user["id"])

    client.patch(f"{_BASE}/admin/{male_request_id}/approve", headers=admin_headers)
    client.patch(f"{_BASE}/admin/{female_request_id}/approve", headers=admin_headers)

    male_notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=male_headers
    ).json()
    male_message = next(
        n["message"] for n in male_notifs if n["type"] == "wallet_request_approved"
    )
    assert "vous serez contacté " in male_message
    assert "contactée" not in male_message

    female_notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=female_headers
    ).json()
    female_message = next(
        n["message"] for n in female_notifs if n["type"] == "wallet_request_approved"
    )
    assert "vous serez contactée " in female_message


def test_approve_fails_if_balance_dropped_below_request_since_submission(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], _MIN_BALANCE)
    _request_transaction(client, auth_headers, amount_ank=_MIN_BALANCE)

    # Le solde baisse après la soumission de la demande (dépense ailleurs
    # dans l'app) : l'admin ne peut plus l'approuver tel quel.
    _spend_wallet(client, auth_headers, 1)

    pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
    request_id = next(
        r["id"] for r in pending.json()["items"] if r["user_id"] == user["id"]
    )

    approved = client.patch(f"{_BASE}/admin/{request_id}/approve", headers=admin_headers)
    assert approved.status_code == 400

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.json()["points"] == _MIN_BALANCE - 1

    still_pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
    assert any(r["id"] == request_id for r in still_pending.json()["items"])


def test_reject_requires_note_and_does_not_debit_wallet(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], _MIN_BALANCE)
    _request_transaction(client, auth_headers, amount_ank=_MIN_BALANCE)

    pending = client.get(f"{_BASE}/admin/pending", headers=admin_headers)
    request_id = next(
        r["id"] for r in pending.json()["items"] if r["user_id"] == user["id"]
    )

    missing_note = client.patch(
        f"{_BASE}/admin/{request_id}/reject", json={"admin_note": ""}, headers=admin_headers
    )
    assert missing_note.status_code == 400

    note = "Numéro de téléphone invalide"
    rejected = client.patch(
        f"{_BASE}/admin/{request_id}/reject",
        json={"admin_note": note},
        headers=admin_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["admin_note"] == note

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.status_code == 200
    assert wallet.json()["points"] == _MIN_BALANCE

    # Le refus notifie in-app (pas d'email) : l'utilisateur doit voir le
    # motif directement dans l'app.
    notifs = client.get("/api/v1/views_notifications/notifications", headers=auth_headers)
    assert notifs.status_code == 200
    matches = [n for n in notifs.json() if n["type"] == "wallet_request_rejected"]
    assert len(matches) == 1
    assert str(_MIN_BALANCE) in matches[0]["message"]
    assert note in matches[0]["message"]
