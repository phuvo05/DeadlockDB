def test_bloom_filter_demo_returns_typed_deterministic_result(client) -> None:
    response = client.post("/api/demo/bloom-filter")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "bloom-filter"
    assert payload["demo_completed"] is True
    assert payload["bit_size"] == 1024
    assert payload["hash_count"] == 4
    assert payload["inserted_items"]
    assert payload["applications"]
    assert {event["event"] for event in payload["events"]} >= {
        "RUN_STARTED",
        "ITEMS_INSERTED",
        "MEMBERSHIP_CHECKED",
        "RUN_FINISHED",
    }
    assert all(event["run_id"] == payload["run_id"] for event in payload["events"])


def test_bloom_filter_interpretation_is_safe(client) -> None:
    payload = client.post("/api/demo/bloom-filter").json()

    for check in payload["checks"]:
        if check["maybe_present"]:
            assert check["interpretation"] == "POSSIBLY_PRESENT"
        else:
            assert check["interpretation"] == "DEFINITELY_ABSENT"


def test_bloom_filter_demo_has_deterministic_content(client) -> None:
    first = client.post("/api/demo/bloom-filter").json()
    second = client.post("/api/demo/bloom-filter").json()

    for payload in (first, second):
        payload.pop("run_id")
        payload.pop("duration_ms")
        for event in payload["events"]:
            event.pop("run_id")
            event.pop("timestamp")
            event.pop("elapsed_ms")

    assert first == second
