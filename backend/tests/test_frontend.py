def test_root_serves_deadlock_lab_controls(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for control_id in (
        "trigger-deadlock",
        "safe-ordering",
        "retry-demo",
        "reset-database",
        "timeline",
        "result",
    ):
        assert f'id="{control_id}"' in response.text
