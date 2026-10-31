import uuid

from fastapi.testclient import TestClient


def test_login_success(client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={"first_name": "Test", "last_name": f"U{suffix}", "email": f"u_{suffix}@x.com", "password": "pass123", "gender": "male"},
    )
    res = client.post(
        "/api/v1/auth/login",
        json={"email": f"u_{suffix}@x.com", "password": "pass123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "accessToken" in body
    assert "refreshToken" in body


def test_login_wrong_password(client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={"first_name": "Test", "last_name": f"U{suffix}", "email": f"u_{suffix}@x.com", "password": "pass123", "gender": "male"},
    )
    res = client.post(
        "/api/v1/auth/login",
        json={"email": f"u_{suffix}@x.com", "password": "wrong"},
    )
    assert res.status_code == 401


def test_login_unknown_user(client: TestClient):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@x.com", "password": "pass123"},
    )
    assert res.status_code == 401


def test_refresh_and_logout(client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={"first_name": "Test", "last_name": f"U{suffix}", "email": f"u_{suffix}@x.com", "password": "pass123", "gender": "male"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": f"u_{suffix}@x.com", "password": "pass123"},
    )
    refresh_token = login_res.json()["refreshToken"]

    refresh_res = client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert refresh_res.status_code == 200
    assert "accessToken" in refresh_res.json()

    # Old token is revoked after rotation
    old_refresh_res = client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert old_refresh_res.status_code == 401

    new_refresh_token = refresh_res.json()["refreshToken"]
    logout_res = client.post("/api/v1/auth/logout", json={"refreshToken": new_refresh_token})
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True


def test_rate_limit_login(client: TestClient):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "p"})
    res = client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "p"})
    assert res.status_code == 429
