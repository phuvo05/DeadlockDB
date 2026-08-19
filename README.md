# PostgreSQL Deadlock Lab

Một demo nhỏ để nhìn thấy transaction, row lock, lock wait, deadlock detection và hai cách xử lý deadlock trong production:

- Prevention: consistent lock ordering.
- Recovery: catch SQLSTATE 40P01, rollback, backoff và retry toàn bộ transaction.

Stack: FastAPI, psycopg 3, PostgreSQL 16, Docker Compose, pytest, HTML/CSS/Vanilla JavaScript.

## Architecture

    Browser
      │ HTTP/JSON
      ▼
    FastAPI backend :8000
      │ psycopg 3 / PostgreSQL protocol
      ▼
    PostgreSQL :5432 (internal Compose network)
      └── accounts

Request flow:

    Browser
      ↓ POST /api/demo/deadlock
    FastAPI creates run_id + timeline
      ↓
    Two independent AsyncConnection objects
      ↓
    BEGIN
      ↓
    SELECT ... FOR UPDATE
      ↓
    Row lock / lock wait / circular wait
      ↓
    PostgreSQL deadlock detector
      ↓
    One transaction receives SQLSTATE 40P01
      ↓
    ROLLBACK victim, finish survivor
      ↓
    Fresh connection verifies balances and invariant

Transaction concurrency only exists when T1 and T2 use independent PostgreSQL sessions. Running both logical transactions on one connection would not reproduce this deadlock.

## Database schema

    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        balance INTEGER NOT NULL,
        CHECK (balance >= 0)
    );

Initial state:

    Account A: id=1, balance=1000
    Account B: id=2, balance=1000
    Total: 2000

Runs and timeline events are kept in memory because this is an educational demo. The database contains only the accounts table.

## Run from zero

### 1. Check prerequisites

Required:

- Docker Desktop with the Linux container engine running.
- Port 8000 available on localhost.

Verify Docker:

    docker --version
    docker compose version

If Docker says that dockerDesktopLinuxEngine is unavailable, start Docker Desktop and wait until its engine is ready.

### 2. Start the project

    docker compose up --build

This builds the FastAPI image, starts PostgreSQL, waits for pg_isready, and starts the backend at localhost:8000.

Expected output includes:

    postgres ... healthy
    backend ... Uvicorn running on http://0.0.0.0:8000

Open [http://localhost:8000](http://localhost:8000).

Background mode:

    docker compose up --build -d

### 3. Verify health

Linux/macOS:

    curl http://localhost:8000/api/health

PowerShell:

    Invoke-RestMethod http://localhost:8000/api/health | ConvertTo-Json

Expected:

    {"status":"ok","database":"connected"}

If the response is Database unavailable:

    docker compose ps
    docker compose logs postgres
    docker compose logs backend

### 4. Inspect accounts

    curl http://localhost:8000/api/accounts

Expected:

    {
      "accounts": [
        {"id": 1, "name": "Account A", "balance": 1000},
        {"id": 2, "name": "Account B", "balance": 1000}
      ],
      "total_balance": 2000,
      "invariant_ok": true
    }

### 5. Reset the demo state

    curl -X POST http://localhost:8000/api/reset

Reset restores both balances without deleting the named Docker volume. Expected result: both balances are 1000 and total_balance is 2000.

### 6. Run the demos

From the UI, click one button at a time. Or call:

    curl -X POST http://localhost:8000/api/demo/deadlock
    curl -X POST http://localhost:8000/api/demo/safe-ordering
    curl -X POST http://localhost:8000/api/demo/retry
    curl -X POST http://localhost:8000/api/demo/bloom-filter

The UI disables buttons while a run is active. The backend also rejects overlapping runs with HTTP 409.

## Deadlock mode

The two transfers are:

    T1: Account A → Account B, amount=100
    T2: Account B → Account A, amount=200

The first lock order is intentionally opposite:

    T1                              T2

    BEGIN                           BEGIN
    LOCK Account A                  LOCK Account B

    WAIT until T2 owns B            WAIT until T1 owns A

    REQUEST Account B               REQUEST Account A
            │                               │
            └──────── circular wait ────────┘

                  PostgreSQL
                       ↓
                 deadlock detector
                       ↓
                  abort one transaction
                       ↓
                    SQLSTATE 40P01

asyncio.Event signals establish that both first locks exist before either second lock is requested. The deadlock itself is produced by real PostgreSQL SELECT ... FOR UPDATE, not a fake Python exception.

PostgreSQL chooses the victim. Do not assume T1 or T2 is always aborted.

Expected response properties:

- deadlock_detected = true.
- victim = T1 or T2.
- At least one transaction has sqlstate = 40P01.
- One transaction COMMITTED.
- One transaction ROLLED_BACK and is the deadlock victim.
- total_balance = 2000.
- invariant_ok = true.

The final individual balances depend on the victim:

- If T1 commits: A=900, B=1100.
- If T2 commits: A=1200, B=800.

The total remains 2000 in both cases.

## Safe lock ordering mode

Both transactions always lock lower account IDs first:

    T1                              T2

    LOCK 1                          REQUEST LOCK 1
    LOCK 2                          WAIT for 1
    UPDATE
    COMMIT
    release locks
                                    ACQUIRE 1
                                    LOCK 2
                                    UPDATE
                                    COMMIT

There may be a lock wait, but there is no circular dependency:

    Lock wait != Deadlock

Expected final state:

    A = 1100
    B = 900
    Total = 2000

## Deadlock retry mode

The first attempt intentionally uses the unsafe order. After PostgreSQL aborts a victim:

    attempt 1
      ↓
    SQLSTATE 40P01
      ↓
    ROLLBACK
      ↓
    exponential backoff + 50–100ms random jitter
      ↓
    retry attempt 2
      ↓
    repeat the entire transaction
      ↓
    COMMIT

Retry is bounded by MAX_ATTEMPTS = 3. There is no infinite retry loop, and non-deadlock errors are not retried.

Expected final state:

    both logical transfers COMMITTED
    A = 1100
    B = 900
    Total = 2000

The response still marks the initially selected transaction as deadlock_victim=true and preserves its original SQLSTATE 40P01.

## Bloom Filter demo

Bloom Filter mode is an in-memory, deterministic demonstration of probabilistic membership checks. It does not use PostgreSQL, Redis, or a persistent data structure.

Run it with:

    curl -X POST http://localhost:8000/api/demo/bloom-filter

The demo inserts five sample values into a 1024-bit array and checks each value against four deterministic hash positions. Double hashing derives the positions from two standard-library digests:

    position_i = (hash_a + i * hash_b) % bit_size

The response shows the inserted ground truth separately from the Bloom Filter result:

- `maybe_present=false` means the value is definitely absent from the inserted set.
- `maybe_present=true` means the value is possibly present. A false positive is possible, so this is not proof of membership.
- Inserted values must never produce a false negative.

Common applications include:

- avoiding an unnecessary cache or database lookup when a key is definitely absent;
- checking whether an email, URL, content hash, or event has probably been seen before;
- filtering duplicate work in ingestion and crawling pipelines;
- performing a cheap rate-limit or abuse pre-check before a more expensive source-of-truth lookup.

| Trade-off | Bloom Filter behavior |
| --- | --- |
| Memory and lookup cost | Compact bit array and constant-time checks |
| False negatives | Not allowed for correctly inserted values |
| False positives | Possible and increase as the filter fills |
| Deletion | Not supported by this basic filter |
| Source of truth | Still required after `maybe_present=true` |

The sample filter is rebuilt for every request. A production system would size the filter for its expected item count and error rate, choose an appropriate lifecycle, and keep the authoritative lookup behind every possible positive result.

## API reference

    GET  /api/health
    GET  /api/accounts
    POST /api/reset
    POST /api/demo/deadlock
    POST /api/demo/safe-ordering
    POST /api/demo/retry
    POST /api/demo/bloom-filter
    GET  /api/debug/db

Deadlock demo responses contain:

    run_id
    mode
    demo_completed
    deadlock_detected
    victim
    transactions
    events
    balances
    total_balance
    invariant_ok
    duration_ms

An event contains an ISO timestamp, transaction ID, event type, message, and elapsed milliseconds.

The Bloom Filter response uses the common `run_id`, `mode`, `demo_completed`, `events`, and `duration_ms` fields plus `bit_size`, `hash_count`, `inserted_items`, `checks`, `estimated_false_positive_rate`, and `applications`. It intentionally has no transaction, victim, balance, or SQLSTATE fields.

## PostgreSQL inspection

Open psql inside the database container:

    docker compose exec postgres psql -U postgres -d deadlock_demo

Verify rows:

    SELECT * FROM accounts ORDER BY id;
    SELECT SUM(balance) AS total_balance FROM accounts;

Expected invariant:

    total_balance
    -------------
    2000

The optional debug endpoint exposes only PostgreSQL version, database name, and current connection count. It does not expose credentials.

## Tests

Tests use the PostgreSQL service; SQLite is not suitable for reproducing these PostgreSQL deadlock semantics.

Run the full suite:

    docker compose exec backend python -m pytest -q

Expected output currently includes:

    16 passed

The suite covers application startup, frontend assets, health, initial state, reset, a real parameterized transfer, real deadlock SQLSTATE 40P01, victim-independent assertions, safe ordering, bounded retry, Bloom Filter membership semantics, the Bloom Filter API contract, and the final invariant.

## Logs

    docker compose logs -f backend

Useful fields include:

    run_id=...
    transaction=T1
    event=LOCK_ACQUIRED
    account_id=1
    elapsed_ms=...

Deadlock logs include sqlstate=40P01. Database passwords are never logged.

## Production lessons

### Consistent lock ordering

Always acquire shared resources in a deterministic order. If every transfer locks account IDs from low to high, opposing directions can wait, but cannot form a cycle.

### Short transactions

Do not hold database locks while calling an external service:

    Bad:
    BEGIN → lock row → call OpenAI for 5 seconds → COMMIT

Prefer:

    external work → BEGIN → short DB critical section → COMMIT

### Retry deadlock victims

For SQLSTATE 40P01:

    rollback → backoff → retry the whole transaction

Retry only bounded, retry-safe operations. Do not retry an arbitrary operation forever.

### Indexing and transaction duration

Slow queries increase transaction duration, which increases lock duration and contention. Proper indexes reduce the time rows remain locked, although indexes do not replace correct lock ordering.

### Monitoring

Production systems should monitor deadlock count, lock-wait time, transaction duration, slow queries, database latency, and connection-pool usage.

## Troubleshooting

### Symptom: API returns SQLSTATE 40P01

Possible cause: concurrent transactions acquired shared rows in different orders.

Verify:

    docker compose logs backend
    curl -X POST http://localhost:8000/api/demo/deadlock

Root cause: circular wait.

Fix: use consistent lock ordering. Add bounded 40P01 retry for resilience.

Verify after fix:

    curl -X POST http://localhost:8000/api/demo/safe-ordering

The safe response should report deadlock_detected=false, both transactions committed, and invariant_ok=true.

Production prevention: keep transactions short, order locks consistently, monitor deadlocks and lock waits.

### Symptom: API returns Database unavailable

Possible causes:

- PostgreSQL is still starting.
- Docker engine is not running.
- Database volume contains invalid local state.
- DATABASE_URL is wrong.

Verify:

    docker compose ps
    docker compose logs postgres
    docker compose exec postgres pg_isready -U postgres -d deadlock_demo

Root cause: backend cannot establish a PostgreSQL connection.

Fix: wait for healthy status or restart Compose. If local data is disposable, use the full reset below.

### Symptom: UI loads but balances do not appear

Possible causes:

- Backend is unavailable.
- Browser loaded stale assets.
- API returned an error.

Verify:

    curl http://localhost:8000/api/health
    curl http://localhost:8000/api/accounts

Fix: inspect the browser error toast and backend logs, then reload the page.

### Symptom: deadlock demo hangs

Possible causes:

- PostgreSQL is not reachable.
- An application synchronization event was not signaled.
- A previous container process is still running.

Verify:

    docker compose ps
    docker compose logs --tail=100 backend

The backend has a bounded orchestration timeout and should return an error rather than wait forever.

### Symptom: database schema does not match the code

postgres/init.sql runs automatically only when a PostgreSQL volume is initialized. /api/reset resets balances but does not recreate schema.

For a completely clean local environment:

    docker compose down -v
    docker compose up --build

Warning: -v deletes the named postgres_data volume and therefore deletes local database data.

## Stop and full reset

Stop containers but preserve database data:

    docker compose down

Expected: containers and network are removed; the named volume remains.

Delete the local database volume too:

    docker compose down -v

Expected: the next docker compose up --build initializes PostgreSQL from postgres/init.sql again.
