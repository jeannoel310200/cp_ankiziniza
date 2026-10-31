import uuid

from fastapi.testclient import TestClient

from app.modules.relationships.model import RelationshipRequest, RelationshipRequestStatus
from app.modules.users.model import User


def _register(client: TestClient, suffix: str | None = None, gender: str = "male") -> dict:
    s = suffix or uuid.uuid4().hex[:8]
    res = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Jean",
            "last_name": "Dupont",
            "email": f"u_{s}@x.com",
            "password": "pass123",
            "gender": gender,
        },
    )
    return res


def _register_and_login(client: TestClient, gender: str) -> dict:
    """Inscrit + connecte un utilisateur d'un genre donné, retourne id/headers.
    Utilisé par les tests de suggestions qui ont besoin de contrôler
    précisément le genre de plusieurs comptes."""
    suffix = uuid.uuid4().hex[:8]
    email = f"sugg_{gender}_{suffix}@x.com"
    reg = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Sugg",
            "last_name": suffix,
            "email": email,
            "password": "pass123",
            "gender": gender,
        },
    )
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "pass123"})
    assert login.status_code == 200
    token = login.json()["accessToken"]
    return {"id": reg.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


def test_register(client: TestClient):
    res = _register(client)
    assert res.status_code == 201
    body = res.json()
    assert body["first_name"] == "Jean"
    assert body["last_name"] == "Dupont"
    assert body["role"] == "user"
    assert "hashed_password" not in body


def test_register_gender_persisted(client: TestClient):
    res = _register(client, gender="male")
    assert res.status_code == 201
    assert res.json()["gender"] == "male"


def test_register_missing_gender(client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    res = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Jean",
            "last_name": "Dupont",
            "email": f"u_{suffix}@x.com",
            "password": "pass123",
        },
    )
    # RequestValidationError est converti en 400 par le handler global de
    # l'app (cf. app/main.py::_validation_handler), pas 422 par défaut.
    assert res.status_code == 400


def test_legacy_user_without_gender(client: TestClient):
    """Une ligne pré-migration (gender NULL en base) doit rester lisible
    sans erreur : la colonne gender est nullable au niveau DB, seul
    UserCreate l'exige à l'inscription."""
    import asyncio

    from app.db.session import SessionLocal

    async def _insert() -> User:
        async with SessionLocal() as session:
            user = User(
                first_name="Legacy",
                last_name="User",
                email=f"legacy_{uuid.uuid4().hex[:8]}@x.com",
                hashed_password="x",
                provider="local",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    user = asyncio.run(_insert())
    assert user.gender is None


def test_register_duplicate_email(client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    _register(client, suffix)
    res = _register(client, suffix)
    assert res.status_code == 409


def test_get_me(client: TestClient, auth_headers: dict):
    res = client.get("/api/v1/users/me", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert "email" in body
    assert "first_name" in body


def test_get_me_unauthenticated(client: TestClient):
    res = client.get("/api/v1/users/me")
    assert res.status_code == 401


def test_update_me(client: TestClient, auth_headers: dict):
    res = client.patch(
        "/api/v1/users/me",
        json={"first_name": "Marie"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Marie"


def test_search_users_requires_auth(client: TestClient):
    res = client.get("/api/v1/users/search?name=Jean")
    assert res.status_code == 401


def test_search_users(client: TestClient, auth_headers: dict):
    suffix = uuid.uuid4().hex[:8]
    client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Unique",
            "last_name": f"Name{suffix}",
            "email": f"unique_{suffix}@x.com",
            "password": "pass123",
            "gender": "female",
        },
    )
    res = client.get(f"/api/v1/users/search?name=Unique", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert "first_name" in body["items"][0]
    assert "is_verified" in body["items"][0]
    assert "email" not in body["items"][0]
    assert "code_user" not in body["items"][0]


def test_list_users_requires_admin(client: TestClient, auth_headers: dict):
    res = client.get("/api/v1/users", headers=auth_headers)
    assert res.status_code == 403


def test_register_invalid_payload(client: TestClient):
    res = client.post("/api/v1/users/register", json={"email": "not-an-email", "password": "p"})
    assert res.status_code == 400


def test_suggestions_requires_auth(client: TestClient):
    res = client.get("/api/v1/users/suggestions")
    assert res.status_code == 401


def test_suggestions_returns_only_opposite_gender(client: TestClient):
    requester = _register_and_login(client, "male")
    female_1 = _register_and_login(client, "female")
    female_2 = _register_and_login(client, "female")
    _register_and_login(client, "male")  # same-gender noise, must not appear

    res = client.get(
        "/api/v1/users/suggestions?page=1&page_size=10", headers=requester["headers"]
    )
    assert res.status_code == 200
    body = res.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {female_1["id"], female_2["id"]}
    assert requester["id"] not in ids
    assert "code_user" not in body["items"][0]


def test_suggestions_small_pool_wraparound(client: TestClient):
    requester = _register_and_login(client, "male")
    female_1 = _register_and_login(client, "female")
    female_2 = _register_and_login(client, "female")

    page_1 = client.get(
        "/api/v1/users/suggestions?page=1&page_size=10", headers=requester["headers"]
    )
    assert page_1.status_code == 200
    page_1_ids = [item["id"] for item in page_1.json()["items"]]
    assert set(page_1_ids) == {female_1["id"], female_2["id"]}

    page_3 = client.get(
        "/api/v1/users/suggestions?page=3&page_size=10", headers=requester["headers"]
    )
    assert page_3.status_code == 200
    body = page_3.json()
    assert [item["id"] for item in body["items"]] == page_1_ids
    # make_page renvoie toujours le compteur de page du client, pas la page
    # interne réellement servie.
    assert body["page"] == 3


def test_suggestions_excludes_existing_relation(client: TestClient):
    import asyncio

    from app.db.session import SessionLocal

    requester = _register_and_login(client, "male")
    female_related = _register_and_login(client, "female")
    female_unrelated = _register_and_login(client, "female")

    async def _insert_accepted_request() -> None:
        async with SessionLocal() as session:
            req = RelationshipRequest(
                requester_id=uuid.UUID(requester["id"]),
                target_id=uuid.UUID(female_related["id"]),
                status=RelationshipRequestStatus.accepted,
            )
            session.add(req)
            await session.commit()

    asyncio.run(_insert_accepted_request())

    res = client.get(
        "/api/v1/users/suggestions?page=1&page_size=10", headers=requester["headers"]
    )
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["items"]}
    assert female_related["id"] not in ids
    assert female_unrelated["id"] in ids


def test_suggestions_null_gender_requester_returns_empty(client: TestClient):
    import asyncio

    from app.db.session import SessionLocal

    _register_and_login(client, "female")  # would otherwise be a valid suggestion

    async def _insert_legacy_user() -> User:
        async with SessionLocal() as session:
            user = User(
                first_name="Legacy",
                last_name="NoGender",
                email=f"legacy_sugg_{uuid.uuid4().hex[:8]}@x.com",
                hashed_password="x",
                provider="local",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    legacy_user = asyncio.run(_insert_legacy_user())

    from app.core.security import create_access_token

    token = create_access_token(str(legacy_user.id), legacy_user.email, legacy_user.role.value)
    res = client.get(
        "/api/v1/users/suggestions", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["items"] == []
