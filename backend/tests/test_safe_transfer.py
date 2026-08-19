def test_safe_ordering_commits_both_transfers_without_deadlock(client) -> None:
    response = client.post("/api/demo/safe-ordering")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deadlock_detected"] is False
    assert [transaction["status"] for transaction in payload["transactions"]] == [
        "COMMITTED",
        "COMMITTED",
    ]
    assert [(account["id"], account["balance"]) for account in payload["balances"]] == [
        (1, 1100),
        (2, 900),
    ]
    assert payload["total_balance"] == 2000
    assert payload["invariant_ok"] is True
    assert any(event["event"] == "LOCK_WAITING" for event in payload["events"])
