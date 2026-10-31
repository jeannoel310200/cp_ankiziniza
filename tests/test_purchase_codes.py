from datetime import UTC, datetime, timedelta
from collections.abc import Generator
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.shared.dependencies.auth import require_admin


@pytest.fixture
def admin_override(client: TestClient, auth_headers: dict) -> Generator[dict[str, str], None, None]:
    me = client.get("/api/v1/users/me", headers=auth_headers)
    assert me.status_code == 200
    current_user_id = UUID(me.json()["id"])
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=current_user_id)
    try:
        yield auth_headers
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_generate_purchase_code_requires_admin(client: TestClient, auth_headers: dict):
    res = client.post(
        "/api/v1/bonus/purchase-codes",
        json={"ank_points": 120},
        headers=auth_headers,
    )
    assert res.status_code == 403


def test_admin_can_generate_and_list_purchase_codes(client: TestClient, admin_override: dict):
    exp = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    create = client.post(
        "/api/v1/bonus/purchase-codes",
        json={"ank_points": 75, "expires_at": exp},
        headers=admin_override,
    )
    assert create.status_code == 200
    created = create.json()
    assert created["code"].startswith("ANK-")
    assert created["ank_points"] == 75
    assert created["is_used"] is False
    assert created["is_expired"] is False
    assert created["expires_at"] is not None

    listing = client.get("/api/v1/bonus/purchase-codes", headers=admin_override)
    assert listing.status_code == 200
    codes = listing.json()["items"]
    assert any(c["code"] == created["code"] for c in codes)


def test_user_can_purchase_with_code_and_get_ank_points(
    client: TestClient,
    admin_override: dict,
    auth_headers: dict,
):
    create = client.post(
        "/api/v1/bonus/purchase-codes",
        json={"ank_points": 50},
        headers=admin_override,
    )
    assert create.status_code == 200
    code = create.json()["code"]

    redeem = client.post(
        "/api/v1/bonus/purchase-with-code",
        json={"code": code},
        headers=auth_headers,
    )
    assert redeem.status_code == 200
    body = redeem.json()
    assert body["code"] == code
    assert body["credited_ank_points"] == 50
    assert body["wallet_points_balance"] == 50

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.status_code == 200
    assert wallet.json()["points"] == 50

    reuse = client.post(
        "/api/v1/bonus/purchase-with-code",
        json={"code": code},
        headers=auth_headers,
    )
    assert reuse.status_code == 409


def test_purchase_with_expired_code(client: TestClient, admin_override: dict, auth_headers: dict):
    expired_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    create = client.post(
        "/api/v1/bonus/purchase-codes",
        json={"ank_points": 20, "expires_at": expired_at},
        headers=admin_override,
    )
    assert create.status_code == 200
    code = create.json()["code"]

    redeem = client.post(
        "/api/v1/bonus/purchase-with-code",
        json={"code": code},
        headers=auth_headers,
    )
    assert redeem.status_code == 400
