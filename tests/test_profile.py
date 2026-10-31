import base64
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient

# Toutes les routes de /profiles partagent la dépendance _profile_service.
# Si son graphe de dépendances ne se résout pas (ex: un service construit avec
# un argument manquant), FastAPI échoue AVANT le corps du handler et toutes les
# routes du module renvoient 500. Ces tests couvrent ce câblage, pas seulement
# le métier de chaque route.

# PNG 1x1 valide : l'endpoint filtre sur l'extension du nom de fichier, mais on
# envoie un vrai PNG pour que le test reste honnête si une validation du contenu
# est ajoutée plus tard.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _me(client: TestClient, headers: dict) -> dict:
    res = client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    return res.json()


def _upload_avatar(client: TestClient, headers: dict):
    return client.patch(
        "/api/v1/profiles/update_profile",
        files={"picture": ("avatar.png", _PNG_1X1, "image/png")},
        headers=headers,
    )


def _cleanup(user_id: str) -> None:
    shutil.rmtree(Path("uploads/avatar") / user_id, ignore_errors=True)


def _bonus_balance(client: TestClient, headers: dict) -> int:
    res = client.get("/api/v1/bonus/balance", headers=headers)
    assert res.status_code == 200
    return res.json()["total_points"]


def _change_email(client: TestClient, headers: dict) -> str:
    """Change l'email via le parcours utilisé par l'app mobile. L'envoi de mail
    est désactivé en test (MAIL_* vides), donc on retombe sur la branche sans
    vérification par code."""
    new_email = f"new_{uuid.uuid4().hex[:8]}@example.com"
    res = client.patch(
        "/api/v1/profiles/change_email",
        json={"email": new_email},
        headers=headers,
    )
    assert res.status_code == 202
    return new_email


def test_update_profile_first_and_last_name(client: TestClient, auth_headers: dict):
    res = client.patch(
        "/api/v1/profiles/update_profile",
        params={"first_name": "Nouveau", "last_name": "Nom"},
        headers=auth_headers,
    )
    assert res.status_code == 202

    me = _me(client, auth_headers)
    assert me["first_name"] == "Nouveau"
    assert me["last_name"] == "Nom"


def test_bonus_label_names_the_field_that_actually_changed(
    client: TestClient, auth_headers: dict
):
    """Le libellé du bonus doit dire « prénom » quand c'est le prénom qui a
    changé, et « nom » quand c'est le nom — pas un message générique commun
    aux deux."""
    assert client.patch(
        "/api/v1/profiles/update_profile",
        params={"first_name": "Annah"},
        headers=auth_headers,
    ).status_code == 202
    assert client.patch(
        "/api/v1/profiles/update_profile",
        params={"last_name": "Rakoto"},
        headers=auth_headers,
    ).status_code == 202

    history = client.get("/api/v1/bonus/history", headers=auth_headers)
    assert history.status_code == 200
    descriptions = [b["description"] for b in history.json()]

    first_name_bonus = next(d for d in descriptions if "prénom" in d)
    assert "prénom" in first_name_bonus

    last_name_bonus = next(
        d for d in descriptions if "nom" in d and "prénom" not in d
    )
    assert "nom" in last_name_bonus


def test_first_name_cooldown_is_independent_from_last_name(
    client: TestClient, auth_headers: dict
):
    """first_name et last_name sont éditables indépendamment : verrouiller
    l'un ne doit pas bloquer l'autre."""
    assert client.patch(
        "/api/v1/profiles/update_profile",
        params={"first_name": "Annah"},
        headers=auth_headers,
    ).status_code == 202

    blocked = client.patch(
        "/api/v1/profiles/update_profile",
        params={"first_name": "Marie"},
        headers=auth_headers,
    )
    assert blocked.status_code == 400

    still_allowed = client.patch(
        "/api/v1/profiles/update_profile",
        params={"last_name": "Rakoto"},
        headers=auth_headers,
    )
    assert still_allowed.status_code == 202


def test_change_email_dependency_resolves(client: TestClient, auth_headers: dict):
    res = client.patch(
        "/api/v1/profiles/change_email",
        json={"email": f"new_{uuid.uuid4().hex[:8]}@example.com"},
        headers=auth_headers,
    )
    assert res.status_code != 500


def test_delete_picture_dependency_resolves(client: TestClient, auth_headers: dict):
    res = client.delete("/api/v1/profiles/delete_picture", headers=auth_headers)
    assert res.status_code != 500


def test_upload_avatar_exposes_url_on_users_me(client: TestClient, auth_headers: dict):
    """L'app mobile lit `avatar_url` sur /users/me. La photo est enregistrée sur
    la table profils : sans synchronisation, l'avatar reste invisible."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _upload_avatar(client, auth_headers).status_code == 202

        avatar_url = _me(client, auth_headers)["avatar_url"]
        assert avatar_url is not None
        assert "/api/uploads/avatar/" in avatar_url
    finally:
        _cleanup(user_id)


def test_uploaded_avatar_is_actually_served(client: TestClient, auth_headers: dict):
    """L'URL renvoyée doit être téléchargeable, sinon l'app affiche un avatar
    vide sans la moindre erreur explicite."""
    user_id = _me(client, auth_headers)["id"]
    try:
        _upload_avatar(client, auth_headers)
        avatar_url = _me(client, auth_headers)["avatar_url"]

        served = client.get(urlparse(avatar_url).path)
        assert served.status_code == 200
        assert served.content == _PNG_1X1
    finally:
        _cleanup(user_id)


def test_verification_uploads_are_not_publicly_served(client: TestClient):
    """`uploads/verification/` contient les pièces d'identité : monter tout
    `uploads/` les publierait. Seul `uploads/avatar/` doit être exposé."""
    verification_dir = Path("uploads/verification")
    verification_dir.mkdir(parents=True, exist_ok=True)
    secret = verification_dir / f"cin_{uuid.uuid4().hex[:8]}.png"
    secret.write_bytes(_PNG_1X1)
    try:
        res = client.get(f"/api/uploads/verification/{secret.name}")
        assert res.status_code != 200
    finally:
        secret.unlink(missing_ok=True)


def test_delete_picture_keeps_external_provider_avatar(
    client: TestClient, auth_headers: dict
):
    """Un compte Google/Facebook a une `avatar_url` distante et aucune photo
    locale. L'app affiche le bouton « Supprimer » dès que `avatarUrl` est non
    vide : le presser ne doit pas détruire l'avatar du fournisseur, qu'aucune
    reconnexion ne restaure (google_auth/service.py ne remet à jour que
    provider/provider_id)."""
    google_avatar = "https://lh3.googleusercontent.com/a/fake-avatar"
    assert client.patch(
        "/api/v1/users/me",
        json={"avatar_url": google_avatar},
        headers=auth_headers,
    ).status_code == 200

    assert client.delete(
        "/api/v1/profiles/delete_picture", headers=auth_headers
    ).status_code == 200

    assert _me(client, auth_headers)["avatar_url"] == google_avatar


def test_delete_picture_clears_avatar_url(client: TestClient, auth_headers: dict):
    user_id = _me(client, auth_headers)["id"]
    try:
        _upload_avatar(client, auth_headers)
        assert _me(client, auth_headers)["avatar_url"] is not None

        assert client.delete(
            "/api/v1/profiles/delete_picture", headers=auth_headers
        ).status_code == 200
        assert _me(client, auth_headers)["avatar_url"] is None
    finally:
        _cleanup(user_id)


def test_has_custom_avatar_reflects_local_photo_only(
    client: TestClient, auth_headers: dict
):
    """L'app doit distinguer une photo envoyée par l'utilisateur d'un avatar
    hérité de Google/Facebook, pour ne proposer « Supprimer » que dans le
    premier cas. `avatar_url` ne suffit pas : elle est renseignée dans les deux."""
    user_id = _me(client, auth_headers)["id"]
    try:
        assert _me(client, auth_headers)["has_custom_avatar"] is False

        # Avatar externe (cas Google) : toujours pas de photo locale.
        client.patch(
            "/api/v1/users/me",
            json={"avatar_url": "https://lh3.googleusercontent.com/a/fake"},
            headers=auth_headers,
        )
        me = _me(client, auth_headers)
        assert me["avatar_url"] is not None
        assert me["has_custom_avatar"] is False

        _upload_avatar(client, auth_headers)
        assert _me(client, auth_headers)["has_custom_avatar"] is True

        client.delete("/api/v1/profiles/delete_picture", headers=auth_headers)
        assert _me(client, auth_headers)["has_custom_avatar"] is False
    finally:
        _cleanup(user_id)


def test_name_editable_at_is_exposed_after_rename(
    client: TestClient, auth_headers: dict
):
    """Chaque champ du nom est bloqué 60 jours indépendamment côté serveur.
    L'app a besoin de sa propre date pour griser le champ correspondant au
    lieu de laisser l'utilisateur se prendre un 400."""
    me = _me(client, auth_headers)
    assert me["first_name_editable_at"] is None
    assert me["last_name_editable_at"] is None

    assert client.patch(
        "/api/v1/profiles/update_profile",
        params={"first_name": "Annah"},
        headers=auth_headers,
    ).status_code == 202

    me = _me(client, auth_headers)
    first_editable_at = me["first_name_editable_at"]
    assert first_editable_at is not None
    # Changer le prénom ne doit pas verrouiller le nom de famille.
    assert me["last_name_editable_at"] is None

    # SQLite (utilisé en test) ne conserve pas le fuseau, contrairement à
    # Postgres : on normalise avant de comparer.
    parsed = datetime.fromisoformat(first_editable_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    assert parsed > datetime.now(UTC)


def test_change_email_awards_bonus_once_within_cooldown(
    client: TestClient, auth_headers: dict
):
    """Changer d'email depuis l'app doit créditer des points, et le délai doit
    empêcher de farmer en enchaînant les changements."""
    before = _bonus_balance(client, auth_headers)

    _change_email(client, auth_headers)
    after_first = _bonus_balance(client, auth_headers)
    assert after_first > before

    _change_email(client, auth_headers)
    assert _bonus_balance(client, auth_headers) == after_first
