from fastapi.testclient import TestClient


def _me(client: TestClient, headers: dict) -> dict:
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    return res.json()


def _credit_wallet(client: TestClient, admin_headers: dict, user_id: str, amount: int) -> None:
    res = client.post(
        f"/api/v1/wallets/users/{user_id}/credit",
        params={"amount": amount, "description": "Test top-up"},
        headers=admin_headers,
    )
    assert res.status_code == 200


def test_convert_wallet_ank_to_bonus_zo(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], 20)
    # Un compte fraîchement inscrit a déjà un bonus de bienvenue (15 ZO) : on
    # part du solde réel plutôt que de supposer zéro.
    starting_balance = client.get("/api/v1/bonus/balance", headers=auth_headers).json()[
        "total_points"
    ]

    convert = client.post(
        "/api/v1/bonus/bonus/convert", json={"points": 5}, headers=auth_headers
    )
    assert convert.status_code == 200
    body = convert.json()
    assert body["wallet_points_converted"] == 5
    assert body["bonus_points_credited"] == 150
    assert body["remaining_wallet_balance"] == 15

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.json()["points"] == 15

    balance = client.get("/api/v1/bonus/balance", headers=auth_headers)
    assert balance.json()["total_points"] == starting_balance + 150


def test_convert_fails_with_insufficient_wallet_balance(
    client: TestClient, auth_headers: dict, admin_headers: dict
):
    user = _me(client, auth_headers)
    _credit_wallet(client, admin_headers, user["id"], 3)

    convert = client.post(
        "/api/v1/bonus/bonus/convert", json={"points": 10}, headers=auth_headers
    )
    assert convert.status_code == 400

    wallet = client.get("/api/v1/wallets/me", headers=auth_headers)
    assert wallet.json()["points"] == 3
