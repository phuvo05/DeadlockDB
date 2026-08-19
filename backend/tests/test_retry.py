def test_retry_replays_deadlock_victim_and_eventually_commits(client) -> None:
    response = client.post("/api/demo/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deadlock_detected"] is True
    assert all(transaction["status"] == "COMMITTED" for transaction in payload["transactions"])
    assert any(
        transaction["deadlock_victim"] and transaction["attempts"] >= 2
        for transaction in payload["transactions"]
    )
    assert max(transaction["attempts"] for transaction in payload["transactions"]) <= 3
    assert [event["event"] for event in payload["events"]].count("RETRY_STARTED") >= 1
    assert payload["total_balance"] == 2000
    assert payload["invariant_ok"] is True
