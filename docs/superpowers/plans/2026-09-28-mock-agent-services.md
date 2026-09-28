# Mock Agent Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one locally runnable FastAPI Mock that exposes OAuth2-style SSO, personnel, and leave workflows through HTTP and MCP for repeatable Agent integration tests.

**Architecture:** One ASGI process owns four modules (`auth`, `people`, `leave`, `mcp`). HTTP and MCP adapters call the same service functions. MySQL persists personnel and leave records; Redis stores short-lived, revocable opaque tokens.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic, SQLAlchemy 2 async, Alembic, asyncmy, redis-py asyncio, pwdlib with Argon2, official Python MCP SDK, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-28-mock-agent-services-design.md`

## Global Constraints

- This is a local, controlled-test Mock; OAuth2 `password` grant is allowed only for this purpose and must be documented as unsuitable for real SSO.
- Use `leave` naming throughout: HTTP collection `/leaves`, path parameter `leave_id`, MCP tools `create_leave`, `list_leaves`, `get_leave`, `update_leave`, `decide_leave`, `withdraw_leave`.
- A single FastAPI application exposes `/docs`, `/openapi.json`, and Streamable HTTP `/mcp`; no web UI.
- Seed about 12 stable users across at least three departments with employee, manager, HR, and admin roles. Explicit CLI reset restores deterministic people and sample leaves.
- Access tokens expire after 30 minutes, refresh tokens after 7 days; refresh rotates the token and logout revokes the entire session.
- Store timezone-aware API times as UTC. `days` is caller-supplied positive decimal; no calendar calculation.
- Test the common flows with focused tests and a smoke script; avoid a large unit-test matrix.

## Review Focus

1. A replayed refresh token must fail with `invalid_grant` after rotation; pinned by Task 3's refresh test.
2. A user who knows an invisible leave ID must receive `404`, not record details; pinned by Task 4's ACL test and Task 5's HTTP test.
3. Naive timestamps and an end time before the start must be rejected before persistence; pinned by Task 4's validation test.
4. An applicant selected as their own approver must be rejected; pinned by Task 4's creation test.
5. A terminal leave must reject further modification, decision, or withdrawal with `409`; pinned by Task 4's transition test.

---

## File Map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.env.example` | Python dependencies and local configuration contract |
| `src/mockfastapi/config.py`, `db.py`, `cache.py`, `app.py` | Settings, MySQL/Redis connections, ASGI composition and readiness |
| `alembic.ini`, `alembic/env.py`, `alembic/versions/*.py` | Schema migrations |
| `src/mockfastapi/people/{models,schemas,service,seed,http}.py` | People schema, directory, stable fixtures and HTTP adapter |
| `src/mockfastapi/auth/{schemas,service,http}.py` | Token lifecycle, principal lookup and OAuth HTTP adapter |
| `src/mockfastapi/leave/{models,schemas,service,http}.py` | Leave state, ACL and HTTP adapter |
| `src/mockfastapi/mcp_server.py` | MCP tools and request Bearer extraction |
| `src/mockfastapi/cli.py` | Seed and explicit reset commands |
| `tests/conftest.py`, `tests/test_*.py` | Focused integration fixtures and behavior checks |
| `docs/mcp.md`, `README.md` | Tool contract, setup, debugging, background run and smoke examples |

### Task 1: Runnable app and dependency readiness

**Files:** Create `pyproject.toml`, `uv.lock`, `.env.example`, `src/mockfastapi/{__init__,config,db,cache,app}.py`, `tests/{conftest,test_bootstrap}.py`.

**Interfaces:** Produce `Settings` in `config.py`; `get_session() -> AsyncIterator[AsyncSession]` in `db.py`; `get_redis() -> Redis` in `cache.py`; `create_app() -> FastAPI` in `app.py`. Later tasks use these interfaces. Defaults target `127.0.0.1:3306` and `127.0.0.1:6379`, with credentials supplied by `.env`.

- [ ] **Step 1: Write `test_readiness_reports_mysql_and_redis` in `tests/test_bootstrap.py`.** With local test DB and Redis configured, assert `GET /health/ready` returns `200` and both dependencies report ready. Keep test settings isolated from development data.
- [ ] **Step 2: Run `uv run pytest tests/test_bootstrap.py -v`.** Expect failure because the app and route do not exist.
- [ ] **Step 3: Implement the named interfaces and readiness endpoint.** Add Python 3.12 constraint, dependencies, `.env.example`, and a `uv.lock`. The endpoint pings both dependencies and returns `503` with a stable error body if either fails.
- [ ] **Step 4: Run `uv run pytest tests/test_bootstrap.py -v` and `uv run python -c "from mockfastapi.app import create_app; print(create_app().title)"`.** Expect pass and application title.
- [ ] **Step 5: Commit** with `git add pyproject.toml uv.lock .env.example src/mockfastapi tests` and `git commit -m "feat: bootstrap mock service"`.

### Task 2: Schema, personnel and deterministic reset

**Files:** Create `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`, `src/mockfastapi/people/{models,schemas,service,seed}.py`, `src/mockfastapi/leave/models.py`, `src/mockfastapi/cli.py`, `tests/test_seed.py`.

**Interfaces:** Produce `Person` and `Leave` SQLAlchemy models; `PersonOut`; `async list_people(session: AsyncSession, *, limit: int, offset: int) -> list[Person]`, `async get_person(session: AsyncSession, person_id: int) -> Person | None`; `async seed(session: AsyncSession, *, reset: bool, redis: Redis) -> None`. `python -m mockfastapi.cli seed` adds missing fixtures; `python -m mockfastapi.cli reset` deletes Mock data and tokens, then restores fixed fixtures. Stable numeric IDs identify seeded people and sample leaves.

- [ ] **Step 1: Write `test_seed_is_idempotent_and_reset_restores_fixed_records` in `tests/test_seed.py`.** Assert about 12 users, at least three departments and all four roles; run seed twice with unchanged counts; create an extra leave, reset, and assert it is gone while fixture IDs and four sample statuses are restored.
- [ ] **Step 2: Run `uv run pytest tests/test_seed.py -v`.** Expect failure for missing models and CLI.
- [ ] **Step 3: Implement models, first Alembic migration, seed data and CLI.** Person has stable `id`, `username`, `name`, `department`, `level`, `role`, password hash; Leave has all spec fields. Reset deletes in transaction order and clears only this app's Redis key prefix.
- [ ] **Step 4: Run `uv run alembic upgrade head` and `uv run pytest tests/test_seed.py -v`.** Expect migration and test pass.
- [ ] **Step 5: Commit** with `git add alembic.ini alembic src/mockfastapi/people src/mockfastapi/leave/models.py src/mockfastapi/cli.py tests/test_seed.py` and `git commit -m "feat: add personnel fixtures and reset"`.

### Task 3: OAuth token lifecycle and identity

**Files:** Create `src/mockfastapi/auth/{__init__,schemas,service,http}.py`, `tests/test_auth.py`; modify `src/mockfastapi/app.py`, `src/mockfastapi/config.py`.

**Interfaces:** Produce `Principal(id: int, username: str, role: str)` and `TokenPair(access_token: str, refresh_token: str, expires_in: int)` in `schemas.py`. Service functions are `authenticate_client(client_id: str, client_secret: str, settings: Settings) -> None`, `async issue_password_tokens(session: AsyncSession, redis: Redis, username: str, password: str) -> TokenPair`, `async refresh_tokens(redis: Redis, refresh_token: str) -> TokenPair`, `async principal_for_access(redis: Redis, token: str) -> Principal`, `async revoke_token(redis: Redis, token: str) -> None`, `async logout(redis: Redis, token: str) -> None`, and `async introspect(redis: Redis, token: str) -> dict[str, bool | int | str]`. Both HTTP and MCP authenticate the configured test client before password, refresh, revoke or introspection operations. Map invalid grants and credentials to explicit domain exceptions. HTTP routes: `/oauth/token`, `/oauth/revoke`, `/oauth/introspect`, `/auth/me`, `/auth/logout`.

- [ ] **Step 1: Write `test_password_refresh_replay_logout` and `test_client_and_user_credentials` in `tests/test_auth.py`.** Assert form token response has Bearer and `expires_in=1800`; refresh returns a new pair, old refresh fails `invalid_grant` even when two refreshes race; logout makes new access invalid; wrong client or user credentials fail without issuing tokens.
- [ ] **Step 2: Run `uv run pytest tests/test_auth.py -v`.** Expect failure for missing routes.
- [ ] **Step 3: Implement schemas, Redis session/token mapping, Argon2 password verification, Basic client authentication and OAuth HTTP routes.** Use a Redis transaction or Lua script for atomic refresh-token consumption so concurrent replay cannot mint two pairs. Set Redis TTLs to 30 minutes and 7 days; return stable `code` and `message` for business errors.
- [ ] **Step 4: Run `uv run pytest tests/test_auth.py -v`.** Expect all auth tests pass.
- [ ] **Step 5: Commit** with `git add src/mockfastapi/auth src/mockfastapi/app.py src/mockfastapi/config.py tests/test_auth.py` and `git commit -m "feat: implement mock OAuth token lifecycle"`.

### Task 4: Leave service rules

**Files:** Create `src/mockfastapi/leave/{__init__,schemas,service}.py`, `tests/test_leave_service.py`.

**Interfaces:** Produce `LeaveCreate`, `LeavePatch`, `LeaveDecision`, `LeaveOut` Pydantic schemas. Service functions are `async create_leave(session: AsyncSession, actor: Principal, data: LeaveCreate) -> Leave`, `async list_leaves(session: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[Leave]`, `async get_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave`, `async update_leave(session: AsyncSession, actor: Principal, leave_id: int, data: LeavePatch) -> Leave`, `async decide_leave(session: AsyncSession, actor: Principal, leave_id: int, data: LeaveDecision) -> Leave`, `async withdraw_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave`. Shared domain exceptions represent invalid input, forbidden action, hidden/not-found record and state conflict.

- [ ] **Step 1: Write focused service tests.** `test_create_rejects_self_approver_and_invalid_time` checks self-approval, naive time and reversed interval; `test_visibility_and_approver_acl` checks only applicant/assigned approver/admin see a leave and invisible ID produces not-found; `test_terminal_transitions_conflict` checks repeat update, decision and withdrawal after terminal state.
- [ ] **Step 2: Run `uv run pytest tests/test_leave_service.py -v`.** Expect failure for missing service.
- [ ] **Step 3: Implement schemas, validation, ACL and state transitions.** Applicant comes from `Principal`; approver must be manager or HR; `days > 0`; UTC persistence; `pending` is the only mutable state. Use one database transaction per mutation.
- [ ] **Step 4: Run `uv run pytest tests/test_leave_service.py -v`.** Expect all leave service tests pass.
- [ ] **Step 5: Commit** with `git add src/mockfastapi/leave tests/test_leave_service.py` and `git commit -m "feat: implement leave workflow rules"`.

### Task 5: People and leave HTTP API

**Files:** Create `src/mockfastapi/people/http.py`, `src/mockfastapi/leave/http.py`, `tests/test_http_flows.py`; modify `src/mockfastapi/app.py`.

**Interfaces:** HTTP routes match the spec exactly: `GET /people`, `GET /people/{person_id}`, `POST /leaves`, `GET /leaves`, `GET /leaves/{leave_id}`, `PATCH /leaves/{leave_id}`, `POST /leaves/{leave_id}/decision`, `POST /leaves/{leave_id}/withdraw`. All use Task 3 `principal_for_access` and Task 4 service methods. Paginate people and leaves with `limit`/`offset`; filter leaves by `status`.

- [ ] **Step 1: Write `test_http_create_update_decide_and_visibility` in `tests/test_http_flows.py`.** Log in applicant and approver, create then update, reject approval by unrelated user, approve as assigned approver, check invisible detail `404`, and check `/openapi.json` lists every path.
- [ ] **Step 2: Run `uv run pytest tests/test_http_flows.py -v`.** Expect failure for missing routes.
- [ ] **Step 3: Implement thin HTTP adapters and shared exception mapping.** Distinguish `401`, `403`, `404`, `409`, `422`; keep errors stable as `code`, `message`, optional `details`. Never read `applicant_id` from creation payload.
- [ ] **Step 4: Run `uv run pytest tests/test_http_flows.py -v`.** Expect pass.
- [ ] **Step 5: Commit** with `git add src/mockfastapi/people/http.py src/mockfastapi/leave/http.py src/mockfastapi/app.py tests/test_http_flows.py` and `git commit -m "feat: expose people and leave HTTP API"`.

### Task 6: MCP parity

**Files:** Create `src/mockfastapi/mcp_server.py`, `tests/test_mcp_flows.py`, `docs/mcp.md`; modify `src/mockfastapi/app.py`.

**Interfaces:** Mount Streamable HTTP at `/mcp`. Tools: `sso_login`, `sso_refresh`, `sso_logout`, `sso_validate`, `list_people`, `get_person`, `create_leave`, `list_leaves`, `get_leave`, `update_leave`, `decide_leave`, `withdraw_leave`. `sso_login` and `sso_refresh` accept client credentials as parameters; protected tools read Bearer from MCP request headers and call Tasks 2–4 service functions.

- [ ] **Step 1: Write `test_mcp_login_leave_and_acl` in `tests/test_mcp_flows.py`.** Use the official MCP client over Streamable HTTP: discover tools, log in, create as applicant, try an unauthorized decision, decide as approver, then compare the result with HTTP detail. Assert auth and business errors carry the same codes.
- [ ] **Step 2: Run `uv run pytest tests/test_mcp_flows.py -v`.** Expect failure because `/mcp` is absent.
- [ ] **Step 3: Implement MCP server, mount and lifespan integration, plus `docs/mcp.md`.** Keep tools thin; put request-header extraction and exception translation in one place. Document tool inputs, outputs, errors and a minimal client example.
- [ ] **Step 4: Run `uv run pytest tests/test_mcp_flows.py -v`.** Expect pass through a live local ASGI server.
- [ ] **Step 5: Commit** with `git add src/mockfastapi/mcp_server.py src/mockfastapi/app.py docs/mcp.md tests/test_mcp_flows.py` and `git commit -m "feat: expose mock services through MCP"`.

### Task 7: Operator README and final smoke run

**Files:** Modify `README.md`; create `scripts/smoke.py`.

**Interfaces:** `uv run python scripts/smoke.py` performs the common HTTP and MCP flow against the running service and exits nonzero on failure. README covers configuration, Docker dependencies, migration, seed/reset, foreground debug, PowerShell hidden background run with log files, Swagger, MCP, test users, and the test-only OAuth password-grant limitation.

- [ ] **Step 1: Write `scripts/smoke.py` with explicit assertions for login, people lookup, create/update/decision, withdrawal, refresh/logout and one MCP call.** The script uses a fresh reset fixture and a running service.
- [ ] **Step 2: Run migration, `python -m mockfastapi.cli reset`, start the service, then run `uv run python scripts/smoke.py`.** Expect all assertions to pass; repair any integration mismatch before continuing.
- [ ] **Step 3: Write README commands and examples from the commands just verified.** Ensure PowerShell background instructions use `Start-Process -WindowStyle Hidden` with stdout/stderr log paths.
- [ ] **Step 4: Run `uv run pytest -v`, `uv run python scripts/smoke.py`, and `git diff --check`.** Expect all tests and the end-to-end smoke flow to pass; record any environment limitation truthfully.
- [ ] **Step 5: Commit** with `git add README.md scripts/smoke.py` and `git commit -m "docs: add runbook and smoke flow"`.

## Handoff

Read the approved spec and this plan before implementation. Execute tasks in order, keep each task's red/green check and commit, then perform one whole-branch review before declaring the Mock ready.
