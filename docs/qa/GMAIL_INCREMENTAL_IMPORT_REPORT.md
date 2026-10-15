# Persistent incremental Gmail imports — implementation and verification

6 November 2026. **Implemented; 739 automated tests passed.** This report covers
persistent message-tracking metadata and selection-time deduplication. It does not
claim live verification of this new behavior or production readiness.

## Behavior and design

Previously, selection filled its limit before checking an expiring in-memory
reservation. Repeated imports could select the same prefix, and restart lost all
message history. Selection now batch-checks and reserves eligible message IDs in
PostgreSQL before counting them toward `max_messages`. It starts from the beginning
on each import, follows validated pages, and skips successful identities without
another Gmail body fetch or inference call. No persistent page cursor is necessary.

The existing default PostgreSQL engine/coordinator hosts `gmail_message_tracking`.
Migration **gmail_incremental_v1** follows **feedback_results_v1**. The unique key is
`tenant_id + mailbox_key + message_id`; mailbox_key is SHA256 of the normalized,
Google getProfile-verified mailbox. The table stores only identity, state, attempt,
claim, job-reference, safe error and timestamp metadata. No OAuth secrets/tokens,
email body, plaintext mailbox, subject, sender or sentiment analysis is stored.
Mailbox hashing is pseudonymization, not anonymization.

Short transactions atomically reserve work, begin attempts, commit outcomes and
release claims. SQL lookups include verified tenant/mailbox before loading rows;
page-level lookups avoid per-ID queries. Unique constraints, row locks, fenced
random tokens and an admission advisory lock protect overlapping claims. No SQL
transaction remains open during Google/Groq network operations. Existing principal,
connection/version, ownership, MIME, provider, scope and model-budget checks remain.

Successful metadata remains indefinitely across job expiry, disconnect and process
restart. Failed processing retries only on another explicit import after cooldown:
default **60 seconds**, at most **3 logical attempts** across jobs/restarts. Unstarted
reservations do not spend attempts. Expired crash claims recover subject to fencing,
lease, cooldown and attempt limits. Current local active jobs cannot be stolen.
Normal claims cover the bounded job plus cancellation headroom (default 200 seconds).
A lost uncommitted provider result can require repeat work; this is not exactly-once
external execution. There is no scheduler or unlimited automatic retry.

## API and configuration

All 20 OpenAPI paths, operation definitions, original required fields and original
property schemas are unchanged. Only six defaulted GmailJobStatus properties were
added: `scanned_messages`, `previously_processed_messages`, `deferred_messages`,
`scan_exhausted`, `scan_limit_reached`, `capacity_limit_reached`.

Existing outcome counters still describe this job's selected records. Previously
successful IDs now appear in selection counters rather than duplicate outcome rows.
Page limits are distinguishable from listing exhaustion. Capacity exhaustion reports
its explicit flag and existing GMAIL_CAPACITY_EXCEEDED code; admitted rows can still
finish. Unexpected HTTP 204 remains an error, never a successful empty mailbox.

Default tracking capacities increase to 10,000 global / 1,000 per tenant. These
include failed/pending records and never evict successful history. Existing private
overrides remain effective; no private .env was edited. Normal message cap 20,
page cap 5, tenant retained-job cap 5 and job deadline 120 seconds remain. The exact
1,000-message profile explicitly sets message cap 100, pages 10, tenant retained
jobs 12 and deadline 600 seconds. See the [configuration and Postman guide](../GMAIL_INCREMENTAL_IMPORTS.md).

## Files

Created:

- app/storage/gmail_message_store.py — shared claim/retry policy and explicit test adapter.
- app/storage/gmail_message_models.py — constrained SQLAlchemy metadata model.
- app/storage/postgres_gmail_message_store.py — PostgreSQL claim repository.
- migrations/versions/gmail_incremental_v1_message_tracking.py — additive migration.
- tests/integration/test_postgres_gmail_incremental.py — 21 real PostgreSQL cases.
- docs/GMAIL_INCREMENTAL_IMPORTS.md — operation, configuration and Postman instructions.
- docs/qa/GMAIL_INCREMENTAL_IMPORT_REPORT.md — this report.

Production files modified:

- app/services/gmail_service.py — selection, off-loop database operations, bounded processing and cleanup.
- app/storage/gmail_store.py — remove old memory dedup, retain OAuth/jobs/results, add status counters.
- app/main.py — default PostgreSQL message store and explicit test injection.
- app/core/config.py — tracking capacity and bounded retry settings.
- app/schemas/gmail.py — six additive status properties.
- app/storage/database.py and migrations/env.py — expected revision and model registration.

Existing fixtures/regressions updated:

- tests/conftest.py, tests/t06_helpers.py, tests/t07_helpers.py, tests/t08_helpers.py.
- tests/integration/test_gmail_import.py and tests/unit/test_gmail_lifecycle.py.
- tests/integration/test_gmail_provider_responses.py and test_gmail_messages_transport.py.
- tests/integration/test_postgres_ingestion_results.py.
- docs/reviewer/verify_workflows.py.

Fixtures explicitly inject memory tracking when isolating unrelated behaviors.
Intentional assertion changes reflect selection-time filtering, retention through
job TTL/disconnect and the new migration head. The malformed oversized provider-page
fixture now exceeds the actual server page size; response validation was not removed.
All 718 previous collected test identities remain present and pass. Prior migration
files, dependency files, Google HTTP implementation, OAuth route, tenant authorization,
MIME decoder, shared T01 service and LangGraph implementation are unchanged.

Documentation/configuration modified: .env.example, README.md, AGENTS.md,
docs/GMAIL_INTEGRATION.md, docs/README.md and docs/POSTGRESQL_BATCH_STORAGE.md.
Local evidence is under `.local/qa/gmail-incremental-*` (ignored temporary artifacts).
No Git operation or credential/configuration disclosure occurred.

## Actual verification

Python 3.12.16, uv 0.13.6; SQLAlchemy 2.0.55, Alembic 1.20.1, psycopg 3.3.7,
official MCP SDK 2.3.0. No dependency changes; locked offline sync and compatibility
check passed. Ruff/mypy/coverage were not installed or claimed.

| Check | Actual result |
| --- | --- |
| Relevant existing Gmail/security/transport suite | 206 passed in 14.47 seconds |
| Final complete pytest suite | **739 passed in 123.43 seconds; 0 failed/errors/skipped** |
| Existing test identity comparison | All 718 retained; 21 new PostgreSQL cases |
| 250-message incremental acceptance | 100 / 100 / 50 / 0; exactly 250 distinct model calls |
| 1,000-message configured profile | Ten jobs of 100, then 0; exactly 1,000 distinct model calls |
| Application recreation against same PostgreSQL | Old successes skipped, one new ID processed; old job returns 404 |
| Retry and crash recovery | Cooldown, bounded attempts across restart, reserved/processing lease recovery verified |
| Overlap and fencing | Disjoint selection, one winner for concurrent claims, stale writer rejected |
| Security and mailbox isolation | Separate tenants/mailboxes, rotation, foreign job denial, invalid connection rejected |
| Resource and provider cases | Page limits, repeated IDs, malformed page, timeout, disconnect, quota and rollback tested |
| Shared regression suite | OAuth, HTTP 204/transport, MIME, T01–T08, MCP stdio, graph, batches, ingestion/results pass |
| Applied development migration | gmail_incremental_v1; 15 columns, unique identity, retry/expiry indexes and 5 checks |
| Alembic/model metadata comparison | Zero differences against actual PostgreSQL schema |
| API compatibility | All 20 paths identical; six defaulted status additions only |

Database tests used the isolated project-local **PostgreSQL 12.22** server and a
dedicated `_test` database with separate temporary schemas. It is end-of-life;
verification on a supported PostgreSQL release remains necessary before production.
The separate system cluster was untouched. Google and Groq were mocked and real
network access blocked. No new live Gmail/OAuth/Groq request was made. The user's
previous live import success is context, not a live test of this feature.

After README's project-local shell exports, reproduce the full suite against the
prepared isolated test server:

```bash
T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket" \
  GROQ_API_KEY='' APP_API_KEY='' \
  uv run --locked --offline pytest -q --junitxml=.local/qa/gmail-incremental-full.xml
```

For only the new database cases, use the same environment and replace the pytest
arguments with `pytest -q tests/integration/test_postgres_gmail_incremental.py`.
Tests require PostgreSQL: without T09_TEST_DATABASE_URL the database cases skip;
that is not the configuration used for the reported complete run.

With the existing private PostgreSQL DATABASE_URL and application credentials:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv pip check --python .venv/bin/python
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## Remaining limitations

- OAuth connections, mailbox ownership reservations, job status and sentiment
  results remain process-local and expire under existing policy. Reauthorize after
  restart; old result URLs can return 404. This feature persists dedup metadata only.
- Pre-upgrade successful RAM-only history cannot be backfilled automatically.
  Protection begins with identities committed to this ledger.
- One advisory-locked application coordinator / one Uvicorn worker remains required.
  SQL coordination does not introduce distributed application support.
- Scanning restarts from the beginning within bounded pages/current label/search
  window. A prefix larger than the scan budget can hide later new mail; flags expose
  that limitation. No permanent page-token checkpoint or unbounded scan was added.
- Tracking/job quotas remain finite. At 1,000 tenant identities, a new identity
  requires deliberate capacity adjustment; history is never silently evicted.
- At-least-once uncommitted external work, bounded parked failures, no scheduler,
  and RAM-only job outcomes are deliberate documented boundaries.
- Actual new-feature live import, supported-server verification, backup restoration
  and whole-environment cross-session retention were not established by these tests.

The requested incremental/durable dedup feature is implemented and locally verified.
No deployment or unrelated next milestone was started.
