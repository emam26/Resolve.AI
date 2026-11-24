from fastapi.testclient import TestClient

from backend.app.api import create_app


class _UnreadyCommerceRepository:
    def database_ready(self) -> bool:
        return False

    def order_for_customer(self, public_order_id: str, customer_id: str | None):
        del public_order_id, customer_id
        return None


def test_healthcheck_is_public_and_does_not_expose_dependencies() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "database" not in response.text


def test_local_development_keeps_public_api_docs_available() -> None:
    client = TestClient(create_app())

    assert client.get("/docs").status_code == 200


def test_readiness_reports_database_status_without_sensitive_details(
    monkeypatch,
) -> None:
    client = TestClient(create_app())
    assert client.get("/readyz").json() == {"status": "ready"}

    monkeypatch.setattr(client.app.state.service, "database_ready", lambda: False)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "sqlite" not in response.text.lower()


def test_readiness_fails_when_configured_commerce_database_is_unavailable() -> None:
    client = TestClient(
        create_app(commerce_repository=_UnreadyCommerceRepository())
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "commerce" not in response.text.lower()


def test_unexpected_errors_return_a_sanitized_structured_response(monkeypatch) -> None:
    client = TestClient(create_app())

    def explode(token):
        del token
        raise RuntimeError("database password=must-not-leak")

    monkeypatch.setattr(client.app.state.service, "actor_for_session", explode)
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An internal server error occurred.",
            "details": {},
        }
    }
    assert "must-not-leak" not in response.text
