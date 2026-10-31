import uuid

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, first_name: str = "Test") -> dict:
    suffix = uuid.uuid4().hex[:8]
    email = f"{first_name.lower()}_{suffix}@example.com"
    reg = client.post(
        "/api/v1/users/register",
        json={
            "first_name": first_name,
            "last_name": f"Name{suffix}",
            "email": email,
            "password": "pass1234",
            "gender": "male",
        },
    )
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "pass1234"})
    assert login.status_code == 200
    token = login.json()["accessToken"]
    return {"id": reg.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


def test_search_by_name_excludes_code_user(client: TestClient, auth_headers: dict):
    target = _register_and_login(client, first_name="Unique")

    res = client.get("/api/v1/users/search?name=Unique", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert "first_name" in item
    assert "code_user" not in item


def test_search_by_code_returns_status_and_no_charge(client: TestClient, auth_headers: dict):
    target = _register_and_login(client, first_name="Coded")
    code_res = client.post("/api/v1/users/me/generate-code", headers=target["headers"])
    assert code_res.status_code == 200
    code = code_res.json()["code_user"]

    wallet_before = client.get("/api/v1/wallets/me", headers=auth_headers).json()

    res = client.get(f"/api/v1/users/search/code/{code}", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code_user"] == code
    assert body["situation"] == "Célibataire"
    assert body["has_partner"] is False

    wallet_after = client.get("/api/v1/wallets/me", headers=auth_headers).json()
    assert wallet_after["points"] == wallet_before["points"]


def test_reveal_status_by_id_spends_points_and_402_on_insufficient_balance(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    target = _register_and_login(client, first_name="Revealed")

    insufficient = client.post(
        f"/api/v1/users/reveal-status/{target['id']}", headers=auth_headers
    )
    assert insufficient.status_code == 402

    # Credit the searcher with ANK, then convert it to ZO.
    searcher_id = client.get("/api/v1/users/me", headers=auth_headers).json()["id"]
    credit = client.post(
        f"/api/v1/wallets/users/{searcher_id}/credit",
        params={"amount": 10, "description": "test credit"},
        headers=admin_headers,
    )
    assert credit.status_code == 200
    converted = client.post(
        "/api/v1/bonus/bonus/convert",
        json={"points": 10},
        headers=auth_headers,
    )
    assert converted.status_code == 200

    revealed = client.post(
        f"/api/v1/users/reveal-status/{target['id']}", headers=auth_headers
    )
    assert revealed.status_code == 200
    body = revealed.json()
    assert body["situation"] == "Célibataire"
    assert body["has_partner"] is False

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers).json()
    assert wallet["points"] == 0
    target_wallet = client.get("/api/v1/wallets/me", headers=target["headers"])
    assert target_wallet.status_code == 200
    assert target_wallet.json()["points"] == 4

    target_notifications = client.get(
        "/api/v1/views_notifications/notifications", headers=target["headers"]
    ).json()
    target_notification_types = {notification["type"] for notification in target_notifications}
    assert "ank_received" in target_notification_types
    assert "bonus_received" in target_notification_types


def test_reveal_status_requires_auth(client: TestClient):
    fake_id = uuid.uuid4()
    res = client.post(f"/api/v1/users/reveal-status/{fake_id}")
    assert res.status_code == 401


def test_reveal_status_old_code_route_no_longer_resolves(client: TestClient, auth_headers: dict):
    res = client.post("/api/v1/users/reveal-status/AKI-XXXXXX", headers=auth_headers)
    assert res.status_code in (400, 404, 422)
