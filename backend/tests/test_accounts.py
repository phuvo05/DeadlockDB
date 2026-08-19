from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_reports_connected_database() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_accounts_start_with_two_balances_and_total_2000() -> None:
    response = client.get("/api/accounts")

    assert response.status_code == 200
    payload = response.json()
    assert [(account["id"], account["balance"]) for account in payload["accounts"]] == [
        (1, 1000),
        (2, 1000),
    ]
    assert payload["total_balance"] == 2000
