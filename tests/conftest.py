import os
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "adminpass123"
os.environ["MAIL_USERNAME"] = ""
os.environ["MAIL_PASSWORD"] = ""
os.environ["MAIL_FROM"] = ""
os.environ["MAIL_SERVER"] = ""

import app.db.session as _session_module  # noqa: E402
import app.main as _main_module  # noqa: E402
from app.core.limiter import limiter  # noqa: E402
from app.main import app  # noqa: E402


def _use_db(db_url: str) -> None:
    new_engine = create_async_engine(db_url)

    @event.listens_for(new_engine.sync_engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
        # SQLite n'applique pas les FK par défaut : sans ça, les tests ne
        # détecteraient jamais une contrainte FK manquante/mal configurée
        # (ex: ondelete absent), contrairement à Postgres en prod.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    new_session_local = async_sessionmaker(
        bind=new_engine, class_=AsyncSession, expire_on_commit=False
    )

    _session_module.engine = new_engine
    _session_module.SessionLocal = new_session_local

    # app.main fait `from app.db.session import SessionLocal, engine` : il tient
    # donc ses propres références. Remplacer les deux, sinon le lifecycle crée
    # les tables dans SQLite (engine remplacé) mais exécute le bootstrap de
    # l'admin et le worker de fond sur la base d'origine — d'où un admin absent
    # des tests et des erreurs de connexion asyncpg en arrière-plan.
    _main_module.engine = new_engine
    _main_module.SessionLocal = new_session_local


@pytest.fixture(autouse=True)
def fresh_db(tmp_path) -> Generator[None, None, None]:
    db_file = tmp_path / f"{uuid.uuid4().hex}.db"
    _use_db(f"sqlite+aiosqlite:///{db_file}")
    limiter.reset()
    yield


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    register = client.post(
        "/api/v1/users/register",
        json={
            "first_name": "Test",
            "last_name": "User",
            "email": f"user_{suffix}@example.com",
            "password": "password1",
            "gender": "male",
        },
    )
    assert register.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": f"user_{suffix}@example.com", "password": "password1"},
    )
    assert login.status_code == 200
    token = login.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]},
    )
    assert login.status_code == 200
    token = login.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}
