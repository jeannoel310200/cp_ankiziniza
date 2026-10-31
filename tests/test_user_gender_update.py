from fastapi.testclient import TestClient


def test_update_me_can_set_gender(client: TestClient, auth_headers: dict):
    """Comptes OAuth (Google/Facebook) : gender absent à l'inscription (le
    fixture email/password en fixe un, mais l'app mobile le complète via
    PATCH /users/me après coup pour les comptes OAuth) — ici on vérifie
    juste que l'endpoint accepte bien de le (re)définir."""
    updated = client.patch(
        "/api/v1/users/me", json={"gender": "female"}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json()["gender"] == "female"

    me_again = client.get("/api/v1/users/me", headers=auth_headers)
    assert me_again.json()["gender"] == "female"


def test_update_me_without_gender_leaves_it_unchanged(
    client: TestClient, auth_headers: dict
):
    before = client.get("/api/v1/users/me", headers=auth_headers)
    gender_before = before.json()["gender"]

    updated = client.patch(
        "/api/v1/users/me", json={"first_name": "Nouveau"}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json()["gender"] == gender_before
    assert updated.json()["first_name"] == "Nouveau"
