import uuid

from fastapi.testclient import TestClient


def _create_user_and_token(client: TestClient) -> dict:
    suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={
            "first_name": "User",
            "last_name": suffix,
            "email": f"{suffix}@x.com",
            "password": "pass123",
            "gender": "male",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": f"{suffix}@x.com", "password": "pass123"},
    )
    token = login.json()["accessToken"]
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    return {"token": token, "id": me.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


def test_get_my_status_defaults_to_single(client: TestClient, auth_headers: dict):
    res = client.get("/api/v1/relationships/status/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "single"
    assert res.json()["partner"] is None


def test_update_my_status(client: TestClient, auth_headers: dict):
    res = client.put(
        "/api/v1/relationships/status/me",
        json={"status": "divorced"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "divorced"


def test_send_relationship_request(client: TestClient, auth_headers: dict):
    other = _create_user_and_token(client)
    res = client.post(
        "/api/v1/relationships/requests",
        json={"target_id": other["id"]},
        headers=auth_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending"
    assert body["target"]["id"] == other["id"]


def test_cannot_send_request_to_self(client: TestClient, auth_headers: dict):
    me = client.get("/api/v1/users/me", headers=auth_headers).json()
    res = client.post(
        "/api/v1/relationships/requests",
        json={"target_id": me["id"]},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_duplicate_request_rejected(client: TestClient, auth_headers: dict):
    other = _create_user_and_token(client)
    client.post(
        "/api/v1/relationships/requests",
        json={"target_id": other["id"]},
        headers=auth_headers,
    )
    res = client.post(
        "/api/v1/relationships/requests",
        json={"target_id": other["id"]},
        headers=auth_headers,
    )
    assert res.status_code == 409


def test_accept_request_links_partners(client: TestClient, auth_headers: dict):
    other = _create_user_and_token(client)

    # Send request
    req = client.post(
        "/api/v1/relationships/requests",
        json={"target_id": other["id"]},
        headers=auth_headers,
    ).json()

    # Accept from other side
    client.patch(
        f"/api/v1/relationships/requests/{req['id']}",
        json={"accept": True},
        headers=other["headers"],
    )

    # Check status of both users
    status_other = client.get(
        "/api/v1/relationships/status/me", headers=other["headers"]
    ).json()
    assert status_other["status"] == "in_couple"
    assert status_other["partner"] is not None


def test_cancel_request(client: TestClient, auth_headers: dict):
    other = _create_user_and_token(client)
    req = client.post(
        "/api/v1/relationships/requests",
        json={"target_id": other["id"]},
        headers=auth_headers,
    ).json()

    res = client.delete(
        f"/api/v1/relationships/requests/{req['id']}", headers=auth_headers
    )
    assert res.status_code == 204
    check = client.get(
        f"/api/v1/relationships/requests/{req['id']}", headers=auth_headers
    )
    assert check.status_code == 404


def test_relationships_require_auth(client: TestClient):
    assert client.get("/api/v1/relationships/status/me").status_code == 401
    assert client.get("/api/v1/relationships/requests/incoming").status_code == 401


def _make_couple(user_a_id: str, user_b_id: str) -> None:
    """Contourne la route d'acceptation de demande — cassée en tests par un
    bug préexistant sans rapport (TypeError tz-naive/aware sur SQLite,
    test_accept_request_links_partners) — en construisant directement les
    deux RelationshipStatus symétriques que produirait un accept_request
    réussi (cf. RelationshipService.respond_to_request)."""
    import asyncio

    from app.db.session import SessionLocal
    from app.modules.relationships.model import RelationshipStatusEnum
    from app.modules.relationships.repository import RelationshipStatusRepository

    async def _upsert() -> None:
        async with SessionLocal() as session:
            repo = RelationshipStatusRepository(session)
            await repo.upsert(
                uuid.UUID(user_a_id), RelationshipStatusEnum.in_couple, uuid.UUID(user_b_id)
            )
            await repo.upsert(
                uuid.UUID(user_b_id), RelationshipStatusEnum.in_couple, uuid.UUID(user_a_id)
            )

    asyncio.run(_upsert())


def test_reveal_partner_requires_auth(client: TestClient):
    fake_id = uuid.uuid4()
    res = client.post(f"/api/v1/relationships/{fake_id}/reveal-partner")
    assert res.status_code == 401


def test_reveal_partner_404_when_not_in_a_couple(client: TestClient, auth_headers: dict):
    other = _create_user_and_token(client)
    res = client.post(
        f"/api/v1/relationships/{other['id']}/reveal-partner", headers=auth_headers
    )
    assert res.status_code == 404


def test_reveal_partner_spends_points_and_notifies_owner(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    requester_id = client.get("/api/v1/users/me", headers=auth_headers).json()["id"]
    target = _create_user_and_token(client)
    partner = _create_user_and_token(client)
    _make_couple(target["id"], partner["id"])

    # Les 15 ZO de bienvenue ne suffisent pas pour payer 750 ZO.
    insufficient = client.post(
        f"/api/v1/relationships/{target['id']}/reveal-partner", headers=auth_headers
    )
    assert insufficient.status_code == 402

    credit = client.post(
        f"/api/v1/wallets/users/{requester_id}/credit",
        params={"amount": 25, "description": "test credit"},
        headers=admin_headers,
    )
    assert credit.status_code == 200
    converted = client.post(
        "/api/v1/bonus/bonus/convert",
        json={"points": 25},
        headers=auth_headers,
    )
    assert converted.status_code == 200

    res = client.post(
        f"/api/v1/relationships/{target['id']}/reveal-partner", headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["partner"]["id"] == partner["id"]

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers).json()
    assert wallet["points"] == 0

    target_wallet = client.get("/api/v1/wallets/me", headers=target["headers"])
    partner_wallet = client.get("/api/v1/wallets/me", headers=partner["headers"])
    assert target_wallet.status_code == 200
    assert partner_wallet.status_code == 200
    assert target_wallet.json()["points"] == 10
    assert partner_wallet.json()["points"] == 4

    target_notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=target["headers"]
    ).json()
    partner_notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=partner["headers"]
    ).json()
    assert "ank_received" in {notification["type"] for notification in target_notifs}
    assert "bonus_received" in {notification["type"] for notification in target_notifs}
    assert "ank_received" in {notification["type"] for notification in partner_notifs}
    assert "bonus_received" in {notification["type"] for notification in partner_notifs}

    notifs = client.get(
        "/api/v1/views_notifications/notifications", headers=target["headers"]
    ).json()
    assert any(n["type"] == "partner_viewed" for n in notifs)
