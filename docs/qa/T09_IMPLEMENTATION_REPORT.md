# T09 — PostgreSQL persistence and reliable batch processing

3 November 2026. **Implemented and verified against real PostgreSQL with mocked inference.**
604 tests passed, 0 failed/skipped/errors, 28.462 seconds. All 571 previous test case
IDs remain, plus 33 PostgreSQL cases. Production release remains **NOT READY**;
local task completion does not establish modern-server, live-provider or deployment readiness.

## Root cause and correction

The production JobStore previously held jobs/results in a Python dictionary and
cleared it on application shutdown. A process restart, development reload, or the
original 1,800-second terminal TTL could remove the uploaded job. The subsequent
owner-scoped download then correctly returned BATCH_JOB_NOT_FOUND. There was no
durable data from which to recover it. This explains the failure mechanisms; the
specific historical four-review job cannot be forensically recovered or attributed
to a particular one without retained execution evidence.

FastAPI and BatchService now default to PostgresJobStore, using PostgreSQL only,
SQLAlchemy 2.x, psycopg 3 and explicit Alembic migrations. No SQLite prototype or
fallback exists. The old JobStore remains only as an explicitly injected ephemeral
adapter for historical isolated tests/demos. No original raw upload file or filename
is retained; necessary parsed pending text is persisted for recovery.

## Architecture and table definitions

[ORM definitions](../../app/storage/batch_models.py),
[live schema/index/check evidence](t09-postgres-verification.json),
[detailed architecture](../BATCH_PERSISTENCE.md).

| Table | Durable fields and integrity |
| --- | --- |
| batch_jobs | Integer PK; unique existing 32-hex public ID; authenticated tenant; explicit business_type/source; JSONB column-mapping options; PENDING/RUNNING/terminal status; total/valid/invalid/skipped/processed/success/failed counters; error; timezone-aware created/updated/started/completed/optional-expiry timestamps |
| batch_records | Integer PK; cascading job FK; unique job+feedback ID and job+position; original row/date/date status/validation error; necessary pending raw text; status/attempt/error; sentiment/category/urgency/summary/next step; JSONB aspects/evidence; fenced claim token/deadline; update timestamp |

Checks reconcile counters, terminal outcomes and claim shape. Indexes support
owner+public-ID reads, status recovery, expiry and ordered per-job record claims.
Reports are reconstructed through the unchanged ReportingService from validated
persisted outcomes; no redundant report snapshot or retrieval inference is added.

Upload parses/validates under the existing limits, then commits job and all rows
in one transaction **before scheduling or HTTP 202**. A DB failure rolls back,
returns sanitized BATCH_UNAVAILABLE and releases the admission reservation. Each
record claim and attempted marker commit separately. Validated results, raw-input
clearing and parent counter updates commit atomically. Pending rows are never
projected as successful results. Queries and commits run off the event loop;
no SQL transaction or row lock remains open while awaiting inference.

The engine uses a four-connection pool with no overflow, five-second connect/pool/
statement limits and a three-second lock limit. A separate idle advisory-lock
connection enforces one application coordinator. Loss of that connection fails
closed until restart. Startup requires the migration head; it does not create
unversioned tables. An absent DATABASE_URL leaves batch unavailable; a configured
unreachable/incorrect database, missing migration or second coordinator fails closed.

## Migrations and actual PostgreSQL environment

- t09_batch_v1 creates the normalized tables, constraints and indexes.
- t09_batch_v2 adds explicit business/source columns, backfills them from options,
  removes the redundant option keys and strengthens outcome checks.
- Both migrations applied to the project development database. Fresh isolated
  schemas and repeated upgrade-to-head passed in real PostgreSQL tests. Destructive
  downgrades are refused. No automatic unrelated-data changes or system-cluster changes.
- Actual server: PostgreSQL **12.22**, separate ignored project-local cluster;
  TCP disabled, private 0700 Unix socket, non-superuser application role and separate
  development/test databases. No system Python or system PostgreSQL cluster changes.
- PostgreSQL 12 is end-of-life. Only this available version was verified; supported
  modern PostgreSQL acceptance is required before production. See the
  [official support policy](https://www.postgresql.org/support/versioning/).

Installed/locked: SQLAlchemy 2.0.55, Alembic 1.20.1, psycopg/psycopg-binary 3.3.7;
Python 3.12.16, uv 0.13.6, official MCP 2.3.0 unchanged. The lock resolves 84 packages
and compatibility checks cover all 80 installed distributions.
[Dependency output](t09-dependency-checks.txt), [versions](t09-summary.json).

## Restart recovery and retention

Startup and bounded maintenance recover unfinished work using the **current**
verified registry principal with batch:create. Removed/read-only owners remain
paused, count toward quotas and are not impersonated from stored tenant strings.
Rotation keys for the same tenant share ownership. One task per job is scheduled;
terminal jobs cannot be reopened by stale recovery snapshots.

Atomic claims use parent locking and FOR UPDATE SKIP LOCKED, expiring leases and
fencing tokens. Committed SUCCESS/FAILED records are skipped. Graceful shutdown
waits for database writes/cancellation, releases owned claims and clears only RAM
copies. Hard-crash claims wait for expiry (Groq operation timeout + 15 seconds).
Successful outcomes survive a later write failure; recovery resumes the remaining
rows. A provider response received but not committed can require another call:
**at-least-once external execution, no exactly-once or distributed guarantee**.

Default BATCH_JOB_TTL_SECONDS=0 retains terminal jobs indefinitely. Positive seconds
explicitly opt into cascading deletion based on completion. Existing private .env
values such as 1800 remain explicit overrides; set 0 to adopt indefinite retention.
Retained-job quotas still bound admission and return 429 instead of evicting history.
Pending input and durable derived summaries/quotes are sensitive. Protect database
access/backups and set an intentional retention policy. Gmail/OAuth/webhook state
remains in memory. App restart persistence is verified; managed environment/container
replacement and production backup/restore durability remain unverified.

## Executed tests and compatibility

[Full JUnit](t09-full.xml), [console output](t09-pytest-output.txt),
[baseline/OpenAPI comparison](t09-compatibility.json),
[separate-process restart evidence](t09-process-restart.json).

| Verification | Actual result |
| --- | --- |
| Complete suite | 604 passed; 0 failed, skipped or errors; 28.462 seconds |
| Baseline preservation | All 571 prior case IDs retained; original QA-005 assertion retained |
| New PostgreSQL integration cases | 33 executed against dedicated *_test database; fresh random migrated schema per case; no SQLite |
| Separate-process restart | Four synthetic rows persisted across clean exit and a fresh Python interpreter; same ID/resources/pagination/download; zero retrieval calls; foreign tenant 404 |
| CSV/XLSX restart | Same public ID, exact status/report/results/download JSON before and after app recreation; pagination retained; zero retrieval model calls |
| 100-row interruption | 40 committed results preserved; only remaining 60 analyzed after restart |
| Crash/claims/fencing | Expired claim recovery; unexpired claim wait; concurrent claim winner; stale writer rejected; duplicate job scheduling prevented |
| Failure/retention | Partial/fatal/timeout outcomes; insert rollback; later result-write failure recovery; indefinite default; explicit TTL cascade; retained quotas |
| Tenant security | Foreign/unknown four-read endpoints return 404; SQL owner predicate before child reads; permissions/rotation/current-owner recovery; create-only worker cannot read |
| Existing features | T01 strict schemas, all graph routes/chat, report/parser, ingress/HMAC, registry quotas, Gmail mocks, MCP in-process and subprocess stdio pass |
| API compatibility | Entire OpenAPI document exactly equal, all 19 paths; request/status/schema/pagination/download contracts unchanged |
| Dependencies | Locked offline sync and uv pip check pass; MCP pin retained |

Historical unit fixtures now explicitly inject the old ephemeral store; those tests
are not presented as PostgreSQL evidence. A separate default-PostgreSQL composition
case verifies shared stateless, graph, chat, direct-ingestion, webhook and mocked
Gmail behavior together with durable batch processing. All providers were mocked;
no new live Groq, Google or external webhook requests were performed. Coverage,
Ruff, mypy and vulnerability scanning were not run or newly installed.

## Setup, startup and Postman handoff

Full commands for starting/creating the isolated local server, role/databases,
private external-server passwords and backup/restore:
[POSTGRESQL_BATCH_STORAGE.md](../POSTGRESQL_BATCH_STORAGE.md).
After README's project-local uv exports, use the prepared development database:

```bash
export DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_dev?host=$PWD/.local/postgres-t09-socket"
export BATCH_JOB_TTL_SECONDS=0
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Use one worker. A private older SQLite DATABASE_URL must be replaced/overridden;
the real .env was deliberately not edited. PostgreSQL must be running first.
[Exact Postman procedure](../POSTMAN_BATCH_PERSISTENCE.md): upload the provided
four synthetic rows, save original job ID and response JSON, retrieve all resources,
restart FastAPI with the same database/tenant, compare those same resources and
download, then verify a second tenant receives 404. Manual Postman/live inference
was not performed during T09. Previously lost in-memory IDs cannot be recovered.

## Files changed and remaining limitations

[Complete file manifest](t09-manifest.json). Production changes are limited to
main composition, settings, thin batch route offloading, BatchService orchestration,
new PostgreSQL model/engine/repository modules, and old store docstrings. Dependencies,
migrations, meaningful PostgreSQL tests, fixture injection and documentation support
these changes. Existing sentiment schema/prompts/provider, graph, reporting/parser,
MCP, Gmail, webhook and tenant-registry implementations remain unchanged.

No Git command, mount change, real .env edit, frontend, Redis/Celery, live provider
call or deployment was made. Current files are available; persistence across app
restart is proven, cross-container workspace retention is not. The historical
reviewer source archive remains pre-T09 and has not been regenerated. Existing live
Google/policy, broader provider and operational handoff gaps remain open. Definitive
reviewer compliance still needs the original assignment; deployment is not inferred
as a reviewer requirement. T09 is complete within the verified local scope; stop
here without starting another milestone.
