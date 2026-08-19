# Bloom Filter Demo Design

**Date:** 2026-08-19

## Goal

Add a deterministic Bloom Filter learning path to the existing PostgreSQL Deadlock Lab. The new path demonstrates probabilistic membership checks and common application patterns without adding a database, cache, or third-party dependency.

## Scope

The feature includes one backend endpoint, a pure-Python Bloom Filter service, typed response models, a frontend control/result view, integration/unit tests, and README documentation.

The demo uses a fixed sample dataset so each run is repeatable. It does not persist filter state, accept arbitrary user input, or replace a production cache/rate limiter.

## Architecture

```text
Browser
  │ POST /api/demo/bloom-filter
  ▼
FastAPI
  ├── Bloom Filter demo endpoint
  ├── Pure-Python BloomFilter service
  └── Typed response model
        │ no database dependency
        ▼
In-memory bit array + deterministic hash positions
```

The service owns the algorithm. The API layer owns orchestration and response serialization. The frontend renders the result in the existing result/timeline surfaces and keeps the deadlock demos unchanged.

## Bloom Filter algorithm

Implement `BloomFilter` in `backend/app/services/bloom_filter.py` with:

- `bit_size = 1024`.
- `hash_count = 4`.
- A `bytearray` bit array.
- Double hashing derived from deterministic standard-library digests:
  `position_i = (hash_a + i * hash_b) % bit_size`.
- `add(value: str) -> None`.
- `might_contain(value: str) -> bool`.
- `estimated_false_positive_rate() -> float`, using:
  `(1 - exp(-k * n / m)) ** k`.

The second hash step must never be zero. Values are encoded as UTF-8. No random seed is used, so the same input produces the same bit positions across runs.

The public explanation must state the central guarantee precisely:

- `False`: the value is definitely absent from the inserted set.
- `True`: the value may be present; a false positive is possible.
- Inserted values must never become false negatives.

## Demo endpoint

Add:

```text
POST /api/demo/bloom-filter
```

The endpoint runs under the existing process-local demo guard so a Bloom Filter run cannot overlap another demo. It does not open a PostgreSQL connection and must remain fast and deterministic.

The fixed inserted sample includes values from several realistic domains, such as:

- user/email existence checks;
- URL or content deduplication;
- cache/database lookup avoidance;
- rate-limit or abuse pre-check keys.

The fixed checks include both inserted values and known-absent values. The response must expose whether each value was inserted, the Bloom Filter result, and the safe interpretation (`POSSIBLY_PRESENT` or `DEFINITELY_ABSENT`).

## API response contract

Add typed models in `backend/app/models/schemas.py`:

```python
class BloomCheckResult(BaseModel):
    value: str
    inserted: bool
    maybe_present: bool
    interpretation: Literal["POSSIBLY_PRESENT", "DEFINITELY_ABSENT"]


class BloomFilterResponse(BaseModel):
    run_id: str
    mode: Literal["bloom-filter"]
    demo_completed: bool
    bit_size: int
    hash_count: int
    inserted_items: list[str]
    checks: list[BloomCheckResult]
    estimated_false_positive_rate: float
    applications: list[str]
    events: list[dict[str, Any]]
    duration_ms: float
```

The event list uses the existing timeline shape and includes at least `RUN_STARTED`, `ITEMS_INSERTED`, `MEMBERSHIP_CHECKED`, and `RUN_FINISHED`. Events must identify the run and must not include secrets; the sample values are non-sensitive educational data.

## Frontend behavior

Add a `Bloom Filter demo` button to the existing scenario controls. It uses the same loading/disable/error behavior as the PostgreSQL scenarios.

When the response mode is `bloom-filter`, render:

- filter parameters (`1024` bits, `4` hash functions);
- inserted item count;
- estimated false-positive rate;
- every membership check with its safe interpretation;
- a short explanation of why `maybe_present` is not proof of existence;
- the application examples listed by the backend.

The Bloom Filter result must not overwrite the account balances or display the deadlock-specific victim/SQLSTATE summary.

## Error handling

- Unexpected Bloom Filter execution failures use the existing generic `500` mapping.
- Existing deadlock/account error behavior remains unchanged.
- The endpoint must not silently fall back to a database lookup: this demo is intentionally in-memory.

## Testing

Tests must prove behavior, not implementation details:

- A newly constructed filter reports an unknown value as `False`.
- Every inserted value reports `True` (no false negative).
- The filter returns the documented safe interpretations.
- The estimated false-positive rate is within `[0, 1]` and increases as the inserted count grows for fixed parameters.
- `POST /api/demo/bloom-filter` returns `200`, the expected mode, populated checks/applications, required event types, and a completed response.
- The frontend smoke test checks for the new control and Bloom Filter result path.

## Documentation

README must document:

- the endpoint and sample command;
- how the bit array and multiple hashes work;
- the no-false-negative/possible-false-positive guarantee;
- why production code still needs a source-of-truth lookup after `maybe_present`;
- applications: cache/database guard, deduplication, URL/email existence checks, and rate-limit pre-checks;
- trade-offs: memory efficiency and speed versus deletion/false positives.

## Non-goals

- No Redis, Kafka, ORM, external Bloom Filter package, persistence, deletion support, or arbitrary request payload.
- No claim that the demo is a production-ready distributed rate limiter or cache.
