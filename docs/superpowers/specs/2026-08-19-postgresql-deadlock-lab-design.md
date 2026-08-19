# PostgreSQL Deadlock Lab Design

**Date:** 2026-08-19

## Goal

Build a small educational FastAPI application that lets a learner observe real PostgreSQL transactions, row locks, lock waits, deadlock detection, consistent lock ordering, and bounded deadlock retry.

## Architecture

```text
Browser
  │ HTTP/JSON
  ▼
FastAPI
  ├── Accounts/reset API
  ├── Demo orchestration
  ├── Timeline collection
  └── Retry policy
        │ psycopg 3 AsyncConnection
        ▼
PostgreSQL
  └── accounts
```

The frontend is static HTML/CSS/Vanilla JavaScript served by FastAPI. A demo opens two independent PostgreSQL connections, one per concurrent transaction. No ORM, message broker, cache, frontend framework, or global mutable database connection is used.

The backend uses one process-local demo guard because this is a single-container educational application. A second demo request returns `409` while another demo is active.

## Database

Only the following table is needed:

```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    balance INTEGER NOT NULL,
    CHECK (balance >= 0)
);
```

Initial rows are Account A (`id=1`, `balance=1000`) and Account B (`id=2`, `balance=1000`). `postgres/init.sql` creates and seeds the table. `/api/reset` explicitly restores both balances without deleting the Docker volume.

Run history and events remain in memory for the request. This keeps the learning path focused on PostgreSQL locking rather than audit schema design.

## Deadlock mode

Two coroutines use separate `AsyncConnection` instances:

```text
T1: BEGIN → lock A → wait until T2 locked B → request B
T2: BEGIN → lock B → wait until T1 locked A → request A
```

`asyncio.Event` objects signal that each first row lock has been acquired before either transaction requests its second row. This makes the circular wait deterministic without using a sleep as the deadlock mechanism.

The second `SELECT ... FOR UPDATE` creates the real PostgreSQL wait cycle. The backend catches `psycopg.errors.DeadlockDetected`, records SQLSTATE `40P01`, explicitly rolls back the victim connection, and lets the surviving transaction finish. The code derives the victim from the observed error and never assumes T1 or T2 is selected.

## Safe ordering mode

Both transfers lock account IDs in ascending order, regardless of transfer direction:

```python
first_id = min(source_id, destination_id)
second_id = max(source_id, destination_id)
```

The timeline records the second transaction requesting the already-held lower row and then acquiring it after the first transaction commits. This demonstrates normal lock contention without a circular dependency. A short visualization hold may be used in this mode only to make the wait observable; synchronization, not timing, establishes the deadlock mode.

## Retry mode

The first attempt uses the same unsafe ordering and can produce `40P01`. The victim rolls back, waits with exponential backoff plus 50–100ms jitter, and retries the entire logical transfer. Retries are limited to three attempts and only apply to `40P01`; all other errors fail immediately after rollback.

The final logical result is both transfers committed, with A=`1100`, B=`900`, and total=`2000`. The response preserves the fact that one transaction was initially a deadlock victim and later committed on retry.

## API contract

```text
GET  /api/health
GET  /api/accounts
POST /api/reset
POST /api/demo/deadlock
POST /api/demo/safe-ordering
POST /api/demo/retry
GET  /api/debug/db
```

Demo responses contain `run_id`, `mode`, transaction results, event timeline, final balances, `deadlock_detected`, optional `victim`, `duration_ms`, `total_balance`, and `invariant_ok`.

Expected outcomes:

| Mode | Deadlock | Final logical result |
|---|---:|---|
| Deadlock | `true` | one transfer committed, one rolled back |
| Safe ordering | `false` | both committed, A=1100, B=900 |
| Retry | initially `true` | both committed after bounded retry, A=1100, B=900 |

## Timeline

Each event contains an ISO timestamp, transaction ID, event type, message, and elapsed milliseconds. Events include `BEGIN`, `LOCK_REQUESTED`, `LOCK_ACQUIRED`, `LOCK_WAITING`, `DEADLOCK_DETECTED`, `ROLLBACK`, `RETRY_STARTED`, `RETRY_SCHEDULED`, `UPDATE_EXECUTED`, and `COMMIT`.

## Frontend

The UI shows both balances, total/invariant status, four action buttons, transaction statuses, SQLSTATE/victim information, an event timeline, and a short “What happened?” explanation for each mode. Buttons are disabled during a request and errors are mapped to human-readable messages.

## Testing

Integration tests run against the PostgreSQL service in Docker. SQLite and mocked database concurrency are not used. Tests cover initial state, reset, real SQLSTATE `40P01`, victim-independent assertions, safe ordering, bounded retry, and the total-balance invariant.

## Production lessons included in README

The README explains consistent lock ordering as prevention, `40P01` rollback/backoff/retry as recovery, short critical sections, avoiding external calls while holding locks, indexing to reduce transaction duration, monitoring deadlocks/lock waits/latency, and a symptom-to-root-cause troubleshooting flow.

## Assumptions

- PostgreSQL 16 is used for a stable local demo image.
- Development credentials are supplied through Compose and are not production secrets.
- A single backend process is sufficient; horizontal scaling is outside this educational scope.
- The database critical section contains only validation and account updates.
