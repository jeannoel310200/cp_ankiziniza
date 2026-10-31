from fastapi.testclient import TestClient


def test_terms_endpoint_returns_public_html(client: TestClient):
    response = client.get("/api/v1/legal/terms")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Conditions d'utilisation" in response.text
    assert "points ANK" in response.text
    assert "peuvent varier" in response.text
    assert "application/json" not in response.headers["content-type"]


def test_privacy_endpoint_returns_public_html(client: TestClient):
    response = client.get("/api/v1/legal/privacy")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Politique de confidentialité" in response.text
    assert "photo de CIN" in response.text
    assert "profil" in response.text
