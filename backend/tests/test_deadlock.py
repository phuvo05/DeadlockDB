def test_deadlock_demo_observes_real_postgres_deadlock(client) -> None:
    response = client.post("/api/demo/deadlock")

    assert response.status_code == 200
    payload = response.json()
    assert payload["demo_completed"] is True
    assert payload["deadlock_detected"] is True
    assert payload["victim"] in {"T1", "T2"}
    assert any(
        transaction["sqlstate"] == "40P01"
        for transaction in payload["transactions"]
    )
    assert any(event["event"] == "DEADLOCK_DETECTED" for event in payload["events"])
    assert payload["total_balance"] == 2000
    assert payload["invariant_ok"] is True
