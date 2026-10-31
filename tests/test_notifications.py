import uuid

from fastapi.testclient import TestClient

_BASE = "/api/v1/views_notifications/notifications"


def _list(client: TestClient, headers: dict) -> list[dict]:
    res = client.get(_BASE, headers=headers)
    assert res.status_code == 200
    return res.json()


def _unread_count(client: TestClient, headers: dict) -> int:
    res = client.get(f"{_BASE}/unread-count", headers=headers)
    assert res.status_code == 200
    return res.json()["count"]


def _register_other_user(client: TestClient) -> dict:
    """Second compte, pour vérifier qu'on ne peut pas toucher aux
    notifications d'autrui. La fixture auth_headers en fabrique un seul."""
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


def test_registration_creates_a_notification(client: TestClient, auth_headers: dict):
    """Le bonus de bienvenue génère une notification : c'est ce qui donne aux
    tests suivants une notification à supprimer, sans écrire en base."""
    assert len(_list(client, auth_headers)) >= 1


def test_delete_one_notification(client: TestClient, auth_headers: dict):
    notif = _list(client, auth_headers)[0]

    assert client.delete(f"{_BASE}/{notif['id']}", headers=auth_headers).status_code == 204

    remaining = [n["id"] for n in _list(client, auth_headers)]
    assert notif["id"] not in remaining


def test_delete_unknown_notification_is_404(client: TestClient, auth_headers: dict):
    res = client.delete(f"{_BASE}/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404


def test_cannot_delete_another_users_notification(
    client: TestClient, auth_headers: dict
):
    """Sans contrôle d'appartenance, un UUID devine permettrait de supprimer
    les notifications de n'importe qui."""
    victim_notif = _list(client, auth_headers)[0]
    attacker = _register_other_user(client)

    res = client.delete(f"{_BASE}/{victim_notif['id']}", headers=attacker)
    assert res.status_code == 404

    # La notification de la victime est toujours là.
    assert victim_notif["id"] in [n["id"] for n in _list(client, auth_headers)]


def test_delete_all_notifications(client: TestClient, auth_headers: dict):
    assert len(_list(client, auth_headers)) >= 1

    assert client.delete(_BASE, headers=auth_headers).status_code == 204

    assert _list(client, auth_headers) == []
    assert _unread_count(client, auth_headers) == 0


def test_delete_all_leaves_other_users_untouched(
    client: TestClient, auth_headers: dict
):
    other = _register_other_user(client)
    assert len(_list(client, other)) >= 1

    assert client.delete(_BASE, headers=auth_headers).status_code == 204

    assert len(_list(client, other)) >= 1


def test_unread_count_drops_after_deleting_an_unread_notification(
    client: TestClient, auth_headers: dict
):
    before = _unread_count(client, auth_headers)
    assert before >= 1

    unread = next(n for n in _list(client, auth_headers) if n["is_read"] is False)
    assert client.delete(f"{_BASE}/{unread['id']}", headers=auth_headers).status_code == 204

    assert _unread_count(client, auth_headers) == before - 1
