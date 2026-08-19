# PostgreSQL Deadlock Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a Dockerized FastAPI/PostgreSQL lab that demonstrates real row-lock deadlocks, prevention by lock ordering, and bounded deadlock retry.

**Architecture:** FastAPI serves a Vanilla JavaScript UI and uses raw psycopg 3 async SQL. Each concurrent transaction receives its own PostgreSQL connection; an in-memory timeline records events and a fresh connection verifies final balances.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, psycopg 3, PostgreSQL 16, Docker Compose, pytest, HTML, CSS, Vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-19-postgresql-deadlock-lab-design.md`

## Global Constraints

- Use raw parameterized SQL; do not add an ORM.
- Use PostgreSQL, not SQLite, for concurrency integration tests.
- Use two independent PostgreSQL connections for concurrent transactions.
- Use `asyncio.Event` synchronization to establish the deadlock ordering; timing is not the deadlock mechanism.
- Catch real SQLSTATE `40P01` and do not assume the victim identity.
- Retry only deadlock victims, with a maximum of three attempts and bounded exponential backoff plus jitter.
- Keep the frontend to HTML, CSS, and Vanilla JavaScript served by FastAPI.
- Preserve the invariant `SUM(accounts.balance) == 2000` after every successful demo.
- Never log `DATABASE_URL` or database credentials.

## File Map

- `docker-compose.yml`: PostgreSQL and backend services, healthcheck, volume, and environment.
- `.env.example`, `.gitignore`: local configuration and repository hygiene.
- `postgres/init.sql`: accounts table and initial seed rows.
- `backend/Dockerfile`, `backend/requirements.txt`: runtime image and dependencies.
- `backend/app/config.py`: typed environment configuration.
- `backend/app/database.py`: one-shot async connection factory and connection cleanup helpers.
- `backend/app/models/schemas.py`: Pydantic request/response models.
- `backend/app/services/timeline.py`: run event collector and structured logging.
- `backend/app/services/transfer.py`: parameterized row-lock transfer and invariant queries.
- `backend/app/services/deadlock_demo.py`: deadlock, safe-ordering, retry orchestration.
- `backend/app/api/accounts.py`: health, accounts, reset, and debug endpoints.
- `backend/app/api/demo.py`: demo endpoints and demo guard.
- `backend/app/main.py`: FastAPI application and static frontend serving.
- `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`: educational UI.
- `backend/tests/conftest.py`: real database test setup and reset fixture.
- `backend/tests/test_accounts.py`: health, initial-state, and reset tests.
- `backend/tests/test_deadlock.py`: real deadlock and SQLSTATE tests.
- `backend/tests/test_safe_transfer.py`: safe ordering test.
- `backend/tests/test_retry.py`: bounded retry test.
- `README.md`: zero-to-running instructions, diagrams, production lessons, and troubleshooting.

### Task 1: Repository and Docker scaffold

**Files:** Create the Compose, environment, ignore, Dockerfile, requirements, and initial SQL files listed above.

**Interfaces:** Compose exposes backend on `localhost:8000`, PostgreSQL internally as `postgres:5432`, and injects `DATABASE_URL` into the backend.

- [ ] Write a smoke test expectation in `backend/tests/test_accounts.py` for `/api/health` and initial accounts before implementation files exist.
- [ ] Run the test collection command and confirm the expected import/configuration failure rather than a false pass.
- [ ] Create the minimal Docker/runtime scaffold and `init.sql` with the `accounts` table and two seed rows.
- [ ] Add FastAPI/psycopg/pytest/httpx dependencies without ORM packages.
- [ ] Run `docker compose config` and confirm the Compose file parses.

### Task 2: Database helpers, schemas, timeline, and account APIs

**Files:** Create `backend/app/config.py`, `database.py`, `models/schemas.py`, `services/timeline.py`, `api/accounts.py`, `main.py`; update the smoke tests.

**Interfaces:** `get_connection()`, `read_accounts()`, `reset_accounts()`, `verify_invariant()`, and typed API response models.

- [ ] Add tests for initial account payload, total balance, reset behavior, and health response.
- [ ] Run those tests against the Compose PostgreSQL service and confirm they fail because the API is not implemented.
- [ ] Implement typed settings from `DATABASE_URL`, one-shot `AsyncConnection` creation, and explicit transaction cleanup.
- [ ] Implement parameterized account reads, reset update, sum/invariant verification, and health/debug queries.
- [ ] Implement the event collector with ISO timestamp, transaction ID, event type, message, elapsed milliseconds, and structured stdout logging.
- [ ] Run the account test file and confirm it passes.

### Task 3: Single transfer transaction

**Files:** Create/update `backend/app/services/transfer.py`, schemas, and transfer-focused tests.

**Interfaces:** `transfer_once(connection, transaction_id, source_id, destination_id, amount, lock_order)` performs `BEGIN`, locks both rows, validates balance, updates both accounts, and commits or rolls back.

- [ ] Add a test that a valid A→B transfer changes balances by the requested amount and preserves the sum.
- [ ] Run it and confirm failure before the helper exists.
- [ ] Implement the smallest raw-SQL transfer helper with `SELECT ... FOR UPDATE`, balance validation, parameter binding, and rollback on all exceptions.
- [ ] Add insufficient-balance handling with a clear application error and rollback.
- [ ] Run the transfer tests and confirm they pass.

### Task 4: Deterministic real deadlock

**Files:** Create/update `backend/app/services/deadlock_demo.py`, `backend/app/api/demo.py`, `backend/app/models/schemas.py`, and `backend/tests/test_deadlock.py`.

**Interfaces:** `run_deadlock_demo()` returns a typed run result containing transaction outcomes, timeline, victim, SQLSTATE, balances, invariant, and duration.

- [ ] Add an integration test asserting `deadlock_detected is true`, at least one `sqlstate == "40P01"`, and no fixed victim identity.
- [ ] Run the test and confirm it fails because the demo endpoint is absent.
- [ ] Implement two coroutines with separate async connections, explicit `BEGIN`, first-row events, `asyncio.Event` barriers, opposite second-row locks, and a bounded orchestration timeout.
- [ ] Catch `psycopg.errors.DeadlockDetected`, record `40P01`, rollback the victim, and let the survivor complete.
- [ ] Query final balances using a fresh connection and return the invariant result.
- [ ] Run the deadlock integration test repeatedly and confirm a real 40P01 is observed without assuming T1/T2.

### Task 5: Safe ordering and retry modes

**Files:** Update `backend/app/services/deadlock_demo.py`, `backend/app/api/demo.py`, `backend/tests/test_safe_transfer.py`, and `backend/tests/test_retry.py`.

**Interfaces:** `run_safe_ordering_demo()` and `run_retry_demo()` return the same run-result shape as the deadlock mode.

- [ ] Add failing tests for both safe transfers committing with A=1100/B=900 and for retry ending with both logical transfers committed within three attempts.
- [ ] Run the tests and confirm they fail before the modes exist.
- [ ] Implement ascending account-ID lock ordering and a small visualization hold only in safe mode so the timeline shows contention.
- [ ] Implement retry of the entire victim transfer after rollback using bounded exponential backoff and 50–100ms random jitter.
- [ ] Ensure non-40P01 database errors are not retried and all connections leave failed transactions through rollback/close.
- [ ] Run both test files repeatedly and confirm they pass.

### Task 6: Frontend and error handling

**Files:** Create `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`; update `main.py` and API error mapping.

**Interfaces:** `/` serves the static lab UI; JSON API errors provide human-readable messages and suitable HTTP status codes.

- [ ] Add a browser smoke expectation for all four buttons and the timeline/result containers.
- [ ] Implement the layout, status cards, timeline rendering, mode explanation copy, loading state, button disabling, and error display.
- [ ] Serve the frontend from FastAPI without a separate frontend container.
- [ ] Map database unavailable to 503, active demo to 409, insufficient balance to 400, and unexpected failures to 500 while keeping expected deadlock demos at 200.
- [ ] Run the container and manually exercise reset, deadlock, safe ordering, and retry through the UI.

### Task 7: README, full verification, commit, and push

**Files:** Create/update `README.md`; update any files exposed by verification failures.

**Interfaces:** README supports a zero-to-running user and documents exactly what each command verifies.

- [ ] Document architecture, request flow, schema, real deadlock sequence, safe ordering, retry, production lessons, troubleshooting, logs, and `docker compose down -v`.
- [ ] Run `docker compose up --build -d` and verify PostgreSQL health and `/api/health`.
- [ ] Run the complete pytest suite inside the backend container.
- [ ] Exercise all API modes, reset, and direct SQL invariant verification against PostgreSQL.
- [ ] Run a final diff/status audit, scan for credentials, and confirm no forbidden frameworks or services were added.
- [ ] Commit the complete project on `codex/postgresql-deadlock-lab` with a descriptive message.
- [ ] Push that branch to `origin` and report the exact remote result.
