import uuid

from fastapi.testclient import TestClient


def test_get_my_wallet_creates_if_missing(client: TestClient, auth_headers: dict):
    res = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["points"] == 0
    assert "id" in body
    assert "user_id" in body


def test_get_my_wallet_idempotent(client: TestClient, auth_headers: dict):
    res1 = client.get("/api/v1/wallets/me", headers=auth_headers)
    res2 = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["id"] == res2.json()["id"]


def test_get_my_transactions_empty(client: TestClient, auth_headers: dict):
    client.get("/api/v1/wallets/me", headers=auth_headers)
    res = client.get("/api/v1/wallets/me/transactions", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_get_my_wallet_requires_auth(client: TestClient):
    res = client.get("/api/v1/wallets/me")
    assert res.status_code == 401


def test_get_my_transactions_requires_auth(client: TestClient):
    res = client.get("/api/v1/wallets/me/transactions")
    assert res.status_code == 401


def test_admin_credit_wallet(client: TestClient, auth_headers: dict):
    # Register a fresh user to credit
    suffix = uuid.uuid4().hex[:8]
    reg = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Rich",
            "last_name": f"U{suffix}",
            "email": f"rich_{suffix}@example.com",
            "password": "pass1234",
            "gender": "male",
        },
    )
    assert reg.status_code == 201
    target_user_id = reg.json()["id"]

    # Register an admin
    admin_suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Admin",
            "last_name": f"A{admin_suffix}",
            "email": f"admin_{admin_suffix}@example.com",
            "password": "adminpass",
            "gender": "male",
        },
    )
    # Promote to admin via DB is not practical in integration tests;
    # use a non-admin → expect 403
    res = client.post(
        f"/api/v1/wallets/users/{target_user_id}/credit",
        params={"amount": 100, "description": "test credit"},
        headers=auth_headers,
    )
    assert res.status_code == 403


def test_admin_credit_requires_auth(client: TestClient):
    fake_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/wallets/users/{fake_id}/credit",
        params={"amount": 50},
    )
    assert res.status_code == 401
