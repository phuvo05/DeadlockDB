# Bloom Filter Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a deterministic Bloom Filter demo endpoint, pure-Python service, frontend view, tests, and documentation to the PostgreSQL Deadlock Lab.

**Architecture:** The Bloom Filter is an in-memory service with a 1024-bit `bytearray`, four deterministic double-hash probes, and no database dependency. FastAPI exposes `POST /api/demo/bloom-filter` through the existing process-local demo guard; the vanilla JavaScript UI renders Bloom-specific results without changing account balances or deadlock result semantics.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, HTML, CSS, Vanilla JavaScript, Python standard-library `hashlib` and `math`.

**Spec:** `docs/superpowers/specs/2026-08-19-bloom-filter-demo-design.md`

## Global Constraints

- Keep the feature deterministic: `bit_size=1024`, `hash_count=4`, UTF-8 values, no random seed.
- Use a `bytearray`; do not add Redis, Kafka, an ORM, or an external Bloom Filter package.
- Use double hashing with `position_i = (hash_a + i * hash_b) % bit_size`, with a non-zero second hash step.
- Never claim that `maybe_present=True` proves membership; only `False` means definitely absent.
- Keep the demo fixed-data and in-memory; do not accept arbitrary request payloads or persist filter state.
- Run the endpoint under the existing `demo_lock` and preserve existing deadlock/account routes.
- Add typed Pydantic response models and keep SQL/database behavior untouched.
- Follow TDD: each production behavior must have a failing test before implementation.
- Use parameterized/escaped output patterns already present in the repository; never expose secrets.

---

### Task 1: Bloom Filter core service

**Files:**
- Create: `backend/app/services/bloom_filter.py`
- Create: `backend/tests/test_bloom_filter_service.py`

**Interfaces:**
- `BloomFilter(bit_size: int = 1024, hash_count: int = 4)` constructs an empty filter.
- `BloomFilter.add(value: str) -> None` sets all probe bits and increments the inserted-item count once per call.
- `BloomFilter.might_contain(value: str) -> bool` returns whether all probe bits are set.
- `BloomFilter.estimated_false_positive_rate() -> float` returns `(1 - exp(-k*n/m)) ** k`.
- Read-only properties expose `bit_size`, `hash_count`, and `inserted_count`.

- [ ] **Step 1: Write failing service tests**

Add tests with concrete behavior:

```python
from app.services.bloom_filter import BloomFilter


def test_new_filter_definitely_excludes_unknown_value() -> None:
    bloom = BloomFilter()

    assert bloom.might_contain("unknown@example.com") is False


def test_inserted_values_never_have_false_negatives() -> None:
    bloom = BloomFilter()
    values = ["alice@example.com", "https://example.com/article/1", "user:1001"]

    for value in values:
        bloom.add(value)

    assert all(bloom.might_contain(value) for value in values)
    assert bloom.inserted_count == len(values)


def test_false_positive_rate_is_bounded_and_grows_with_insertions() -> None:
    small = BloomFilter()
    large = BloomFilter()
    for value in [f"item:{index}" for index in range(20)]:
        large.add(value)

    assert 0 <= small.estimated_false_positive_rate() <= 1
    assert 0 <= large.estimated_false_positive_rate() <= 1
    assert large.estimated_false_positive_rate() > small.estimated_false_positive_rate()


def test_invalid_filter_parameters_are_rejected() -> None:
    for kwargs in ({"bit_size": 0}, {"hash_count": 0}):
        try:
            BloomFilter(**kwargs)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run the service tests and verify the expected RED state**

Run:

```text
docker compose exec -T backend python -m pytest tests/test_bloom_filter_service.py -q
```

Expected: collection fails because `app.services.bloom_filter` does not exist.

- [ ] **Step 3: Implement the minimal Bloom Filter**

Implement the class with a private `bytearray` and helpers equivalent to:

```python
def _positions(self, value: str) -> list[int]:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    secondary = hashlib.sha1(value.encode("utf-8")).digest()
    hash_a = int.from_bytes(digest[:8], "big")
    hash_b = int.from_bytes(secondary[:8], "big") or 1
    return [
        (hash_a + index * hash_b) % self._bit_size
        for index in range(self._hash_count)
    ]
```

Set/read a bit using `byte_index = position // 8` and `mask = 1 << (position % 8)`. Validate positive integer parameters. Track `inserted_count` per `add()` call; the fixed demo will not add duplicate values.

- [ ] **Step 4: Run the service tests and verify GREEN**

Run the same command. Expected: all service tests pass with no warnings.

- [ ] **Step 5: Commit the service and tests**

```text
git add backend/app/services/bloom_filter.py backend/tests/test_bloom_filter_service.py
git commit -m "feat: add deterministic bloom filter service"
```

### Task 2: Bloom Filter response models and demo orchestration

**Files:**
- Create: `backend/app/services/bloom_demo.py`
- Create: `backend/tests/test_bloom_demo.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/demo.py`
- Modify: `backend/app/services/timeline.py`

**Interfaces:**
- `BloomCheckResult` contains `value`, `inserted`, `maybe_present`, and `interpretation`.
- `BloomFilterResponse` contains `run_id`, `mode="bloom-filter"`, `demo_completed`, filter parameters, inserted items, checks, estimated false-positive rate, applications, events, and duration.
- `run_bloom_filter_demo() -> BloomFilterResponse` is deterministic and does not call `get_connection()`.
- `POST /api/demo/bloom-filter` returns the typed response through the existing demo guard.

- [ ] **Step 1: Write failing service/API tests**

Add tests that assert the full route contract:

```python
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
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run:

```text
docker compose exec -T backend python -m pytest tests/test_bloom_demo.py -q
```

Expected: import/route failures because the response models, service, and route do not exist.

- [ ] **Step 3: Add typed response models**

In `schemas.py`, add `BloomCheckResult` and `BloomFilterResponse` exactly as specified. Keep `DemoResponse.mode` unchanged for the existing three routes; use `BloomFilterResponse` for the new route.

- [ ] **Step 4: Implement fixed demo orchestration**

In `bloom_demo.py`, define fixed constants:

```python
INSERTED_ITEMS = (
    "alice@example.com",
    "bob@example.com",
    "https://example.com/articles/1",
    "content:sha256:demo-001",
    "user:1001",
)
CHECK_ITEMS = (
    ("alice@example.com", True),
    ("https://example.com/articles/1", True),
    ("carol@example.com", False),
    ("content:sha256:unknown", False),
)
APPLICATIONS = (
    "Cache/database lookup guard",
    "Email or URL duplicate detection",
    "Rate-limit and abuse pre-check",
)
```

Create a new `run_id`, a `Timeline`, and a `BloomFilter`; add all inserted items, record `ITEMS_INSERTED`, evaluate every check, record `MEMBERSHIP_CHECKED`, and finish with `RUN_FINISHED`. Use the filter result—not the expected sample label—to set `maybe_present`; use the expected label only to expose the educational ground truth. Interpret `False` as `DEFINITELY_ABSENT` and `True` as `POSSIBLY_PRESENT`. Return elapsed milliseconds and the formula-based estimated rate.

- [ ] **Step 5: Include the run ID in timeline events**

Update `Timeline.add()` so every event dictionary contains `run_id=self.run_id`. Existing deadlock responses may gain this additive field; do not change event names or existing route behavior.

- [ ] **Step 6: Add the route through the existing guard**

Import `BloomFilterResponse` and `run_bloom_filter_demo` in `api/demo.py`. Widen `_run_demo` to return `DemoResponse | BloomFilterResponse`, then add:

```python
@router.post("/bloom-filter", response_model=BloomFilterResponse)
async def bloom_filter_demo() -> BloomFilterResponse:
    return await _run_demo(run_bloom_filter_demo)
```

Because the service is synchronous in nature but the endpoint contract is async, keep the orchestration function async for consistency and avoid adding thread-pool complexity.

- [ ] **Step 7: Run targeted tests and verify GREEN**

Run:

```text
docker compose exec -T backend python -m pytest tests/test_bloom_filter_service.py tests/test_bloom_demo.py -q
```

Expected: all Bloom Filter tests pass and no existing database state is modified.

- [ ] **Step 8: Commit the API and orchestration**

```text
git add backend/app/services/bloom_demo.py backend/app/services/timeline.py backend/app/models/schemas.py backend/app/api/demo.py backend/tests/test_bloom_demo.py
git commit -m "feat: expose bloom filter demo endpoint"
```

### Task 3: Frontend Bloom Filter experience

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `backend/tests/test_frontend.py`

**Interfaces:**
- New button ID: `bloom-filter-demo` with `data-mode="bloom-filter"`.
- Existing loading, disable, error, and run ID behavior remains shared.
- Bloom mode renders parameters, checks, estimated rate, and applications in `#result-content`.

- [ ] **Step 1: Extend the frontend smoke test first**

Add `bloom-filter-demo` to the existing control ID list and assert the response HTML contains `Bloom Filter` and `data-mode="bloom-filter"`.

- [ ] **Step 2: Run the frontend test and verify RED**

Run:

```text
docker compose exec -T backend python -m pytest tests/test_frontend.py -q
```

Expected: failure because the new button and copy are absent.

- [ ] **Step 3: Add the control and result markup**

Add a fourth scenario button in `frontend/index.html` with a short description such as `Fast membership pre-check`. Keep the existing controls and reset button unchanged.

- [ ] **Step 4: Render Bloom-specific response data**

In `app.js`, branch in `renderResult(payload)` before deadlock-specific fields when `payload.mode === "bloom-filter"`. Render all server-provided values through `escapeHtml()`, format the rate as a percentage, show each check’s safe interpretation, and list the application examples. Set the result badge to a neutral educational state such as `Probabilistic lookup`.

Update `updateBalances()` so it only changes the account invariant status when `payload.invariant_ok` is present; a Bloom response must not rewrite deadlock/account balances or show a false invariant state.

- [ ] **Step 5: Add focused Bloom styles**

Add small styles for filter metrics, membership check rows, and `POSSIBLY_PRESENT`/`DEFINITELY_ABSENT` labels. Reuse the existing panel, metric, and status color vocabulary; do not introduce a frontend framework.

- [ ] **Step 6: Run frontend tests and JavaScript syntax validation**

Run:

```text
docker compose exec -T backend python -m pytest tests/test_frontend.py -q
node --check frontend/app.js
```

Expected: both pass.

- [ ] **Step 7: Commit the frontend**

```text
git add frontend/index.html frontend/app.js frontend/styles.css backend/tests/test_frontend.py
git commit -m "feat: add bloom filter demo UI"
```

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `backend/tests/test_bloom_demo.py` if verification exposes a contract gap

- [ ] **Step 1: Document the endpoint and algorithm**

Add a `Bloom Filter demo` section to README covering the curl command, bit-array/hash flow, safe interpretation of results, no-false-negative guarantee, possible false positives, and the four application examples. Include a compact trade-off table and explicitly state that the demo does not persist data or replace the source-of-truth lookup.

- [ ] **Step 2: Run the complete automated verification**

Run:

```text
docker compose config --quiet
docker compose exec -T backend python -m pytest -q
node --check frontend/app.js
git diff --check
```

Expected: Compose parses, all tests pass, JavaScript syntax is valid, and no whitespace errors are reported.

- [ ] **Step 3: Exercise the live endpoint**

Run:

```text
Invoke-RestMethod -Method Post http://localhost:8000/api/demo/bloom-filter | ConvertTo-Json -Depth 8
```

Verify `mode=bloom-filter`, `demo_completed=true`, required events, safe interpretations, applications, and no account balance changes before/after the request.

- [ ] **Step 4: Manually verify the UI**

Open `http://localhost:8000`, click `Bloom Filter demo`, confirm controls disable while running, the result panel shows all checks/applications, the timeline includes the Bloom events, and account balances remain unchanged.

- [ ] **Step 5: Review repository state and commit documentation**

Run:

```text
git status --short --branch
git log --oneline -6
```

Commit the README change:

```text
git add README.md
git commit -m "docs: explain bloom filter applications"
```

- [ ] **Step 6: Final handoff**

Report the endpoint, test command and result, final commit hashes, and any residual scope limitation. Push the current branch only after all verification steps pass and the user has requested the push.
