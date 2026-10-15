# Persistent feedback ingestion results — implementation and verification

4 November 2026. **Implemented; 638 tests passed, zero failures/skips/errors.**
All 604 previous test case IDs retained; 34 new cases (33 against real PostgreSQL,
one retention-configuration test). Production readiness remains NOT READY because
existing supported-server, broader live-provider and operational gates remain open.
This task makes no deployment or definitive original-reviewer-compliance claim.

## Root cause and scope

The prior WebhookService worker awaited IngestionService.analyze but discarded the
returned IngestionResponse. EventStore kept only temporary in-memory status and
cleared its request on completion, then removed terminal metadata after TTL. There
was no stored original feedback/result or supported result route. The old status
endpoint correctly returned COMPLETED without exposing the discarded analysis.
Direct ingestion returned its synchronous analysis but did not persist it either.

The actual structured result from that same existing invocation now commits to
PostgreSQL. There is no reclassification on retrieval, duplicate, restart or report
formatting, and no new provider/graph/prompt. Previously discarded events/results
cannot be reconstructed or backfilled; an old delivery ID alone is insufficient.

## Files changed

Production additions:

- app/storage/feedback_models.py: normalized event metadata, validated feedback and
  result JSONB, integrity constraints and owner/delivery uniqueness.
- app/storage/postgres_event_store.py: shared-engine repository, short transactions,
  atomic idempotency/admission, SQL ownership, result validation and restart policy.
- migrations/versions/feedback_results_v1_persistent_ingestion.py: additive table/index/
  constraints, descending from t09_batch_v2; prior batch migrations untouched.

Production updates:

- app/services/webhook_service.py: durable submission/processing/finish, synchronous
  direct coordination, result retrieval, bounded queue/admission and cancellation.
- app/api/v1/ingestion.py and webhooks.py: thin async delegation, the new GET and
  direct response headers; original response bodies preserved.
- app/schemas/ingestion.py: EventResult reuses IngestionRequest/SentimentResponse;
  verifies completed/failed invariants and evidence grounding.
- app/storage/event_store.py: operation correlation ID for safe writes; historical
  ephemeral adapter retained for explicit isolated fixtures, not a DB fallback.
- app/storage/database.py, migrations/env.py: new migration head/metadata registration.
- app/main.py: default PostgreSQL event repository over the existing batch engine/
  coordinator; explicit ephemeral fixture injection; private direct-ID headers.
- app/core/config.py and exceptions.py: explicit durable retention setting and the
  safe stored INGESTION_INTERRUPTED code.

Tests: new tests/integration/test_postgres_ingestion_results.py; existing tests/
conftest.py, t06_helpers.py, t07_helpers.py and t08_helpers.py explicitly inject their
historical ephemeral adapter; API inventory adds the single authorized route.
No assertion was removed, skipped or weakened. The existing standalone reviewer
mock harness also explicitly injects the adapter and retains correct import order.
Public config/engineering/readme/API/tenant/architecture/QA documentation and
shareable Postman artifacts were updated. No dependency or private .env changes.
[Complete manifest](feedback-persistence/manifest.json).

## Database and transactions

feedback_events stores integer PK, authenticated tenant ID, delivery ID,
nullable integration ID, direct/webhook kind, nullable event type, timestamp-independent
raw-body digest, private operation correlation ID, validated original feedback JSONB,
actual SentimentResponse JSONB, state/safe error and created/updated/completed/optional
expiry timestamptz values. The feedback JSON preserves exact text, validated feedback
ID, source, business type and channel. No API key, signing secret, signature, signed
headers, provider exception, registry or principal proof is persisted.

Unique(tenant_id, delivery_id) supports owner lookup. Indexes support status recovery
and terminal expiry. Constraints enforce origin/state/outcome shape. New migration
feedback_results_v1 adds only this table/indexes/checks; existing batch rows and
migration history remain. Actual development database is at the new head; ORM vs
migrated metadata comparison returns zero differences. Repeat-to-head and v2 batch
sentinel preservation are tested. Destructive downgrades are refused.
[Sanitized schema evidence](feedback-persistence/database-verification.json).

The repository shares the existing bounded SQLAlchemy/psycopg engine and exclusive
PostgreSQL coordinator. Tenant-scoped lookup, duplicate comparison, quota counts
and insertion occur atomically under a short transaction-level advisory lock.
Input commits before webhook queue/202 or direct inference. PROCESSING commits
before the model await; no transaction is held during network inference. The exact
validated result commits before COMPLETED or a successful direct response. Writes
are fenced by tenant/delivery/operation ID and terminal outcomes are immutable.
Blocking SQL runs off the event loop. Existing parser/batch tables/services remain.

## APIs and compatibility

| Operation | Behavior |
| --- | --- |
| POST /api/v1/webhooks/feedback | Existing 202 acknowledgment for a new authenticated event; 200 DUPLICATE for identical retained bytes; no response-body change |
| POST /api/v1/ingest/feedback | Existing synchronous 200 ANALYZED body; adds X-Feedback-Delivery-Id and relative Location after durable reservation, also on controlled provider failures |
| GET /api/v1/ingest/events/{delivery_id} | Existing 200 EventStatus body unchanged, no feedback/analysis or model call |
| GET /api/v1/ingest/events/{delivery_id}/result | New route:202 EventStatus while ACCEPTED/PROCESSING,200 EventResult when COMPLETED/FAILED |

EventResult includes delivery/status, integration/event metadata, feedback using
existing IngestionRequest names (feedback_id, text, source, business_type, channel),
actual existing SentimentResponse or null, safe error and timezone-aware timestamps.
A failed event keeps original feedback but cannot contain a fabricated successful
analysis. GET revalidates stored schema/evidence and fails closed on invalid data.
Unknown/foreign IDs404, missing/invalid key401, missing events:read403. All private
responses use no-store/no-cache/nosniff/no-referrer.

[OpenAPI comparison](feedback-persistence/compatibility.json) proves every existing
path/operation remains. Exactly one path and one schema are added. The only old
operation change is documented direct-response headers; its body/schema/status and
all other old operation definitions are identical. ErrorCode gains only the safe
INGESTION_INTERRUPTED enum value. The API inventory assertion was extended rather
than weakening its security/schema checks. All20 paths are documented.

## Authentication and idempotency

Server-verified principals, not payload/model tenant fields, determine ownership.
Both GETs require events:read, and SQL predicates include tenant+delivery before
loading/returning feedback/result. HMAC integration principals cannot authenticate
business reads; they carry only ingest authority. A development key cannot read
business results. Rotation keys share ownership within the same configured tenant.

Every webhook attempt preserves original-byte HMAC, all signed headers, timestamp
validation and service-boundary reverification. Stored normalized feedback must
match signed bytes. Exact-byte digests exclude timestamps: fresh signed identical
retries deduplicate after restart without a new classifier call. Changed bytes409;
another integration in the same tenant with that delivery409; a separate tenant
can use the same ID independently. Conflicts never overwrite the first record.
Unique keys/transaction locking prevent concurrent duplicate reservation. Direct
POST generates a new server event ID per request; it does not acquire a new
caller-idempotency promise. Both ingestion paths retain the shared T01 behavior.

## Lifecycle, failure handling and retention

Existing fixed workers, bounded queue and shared model/owner budgets remain.
Completed/failed feedback/results/digests survive restart. Under the exclusive
coordinator, startup terminalizes unfinished ACCEPTED/PROCESSING as
FAILED/INGESTION_INTERRUPTED without replay. Original inputs remain retrievable.
Graceful shutdown terminalizes active/pending work with WEBHOOK_UNAVAILABLE.
Cancellation waits for in-flight commits and shields terminal writes from AnyIO
level cancellation. The first full run exposed that cleanup gap (637 passed/1
failed); it was fixed in production code and both cancellation regressions plus
the final full suite pass. [Retained failed-run evidence](feedback-persistence/cancellation-before-fix.xml).

Result-write failure never invents completion. New ingestion admission fails closed
until restart; unfinished rows are then terminalized without repeating inference.
If a provider response was received but its commit failed, that analysis is not
recoverable; the stored event truthfully reports interruption. This is an explicit
terminal-failure policy, not a durable retry queue or exactly-once guarantee.

INGESTION_RESULT_TTL_SECONDS defaults0: original inputs, outcomes and idempotency
remain indefinitely. Positive terminal expiry is explicit, must cover twice signed
timestamp skew, and removes the event/result/digest together. Active rows never
expire or evict. Existing 1800-second memory-metadata TTL does not silently delete
PostgreSQL results. Global/tenant retained-event caps now include both direct and
webhook events; exhausted history rejects new work with429 and preserves history.
Duplicates still succeed within their original retained identity. Raw feedback,
summaries and evidence are sensitive: protect DB/backups and define retention and
server/proxy logging independently. Gmail/OAuth state is unchanged and memory-only.

## Executed verification

- Initial existing focused regressions:89 passed (ingestion/signatures/workers/tenants).
- Initial PostgreSQL-focused cases:27 passed before adding further failure/lifecycle tests.
- Cancellation correction:2 focused PostgreSQL tests passed unchanged afterward.
- Final full suite:638 passed, 0 failed/skipped/errors, 45.675 seconds JUnit (45.68 console).
  All604 baseline IDs retained +34 new; integration218/security261/unit156/performance3.
  33 new cases use real PostgreSQL; one validates retention configuration.
- Existing real-PostgreSQL batch tests, MCP official in-process/subprocess stdio,
  graph/chat, Gmail mocks, ingress/HMAC, reporting and tenant regressions all pass.
- Separate-process test: one synthetic webhook completed in process1; process2
  retrieved exactly equal status/result, duplicate200/conflict409/invalid HMAC401/
  foreign404, zero new inference. [Evidence](feedback-persistence/process-restart.json).
- Real isolated PostgreSQL tests cover original Unicode/whitespace feedback,
  captured exact analysis, repeated GET, pending/processing/failed/restart outcomes,
  concurrent reservation, safe DB insert/result failures, explicit retention,
  quotas, cancellation, rotation, legacy ownership and SQL owner predicates.
- Alembic CLI upgrade on the prepared development DB succeeded; metadata matches
  ORM with zero differences. uv sync --locked --offline and uv pip check pass:
  84 resolved, all80 installed compatible; pyproject/uv.lock and MCP2.3.0 unchanged.
- All12 Postman requests/20 scripts syntax checked; four exported Web Crypto
  signing cases executed in Node and independently HMAC-verified, including exact
  duplicate bytes/modified conflict. No desktop Postman or live HTTP/Groq run.
- Python source imports pass the existing module-import suite. Ruff, mypy and
  coverage are unavailable and were not installed/run. No vulnerability scan claim.

[Final JUnit](feedback-persistence/full.xml), [summary](feedback-persistence/summary.json),
[dependency/migration commands](feedback-persistence/commands.txt),
[signer checks](feedback-persistence/postman-verification.json).

## Run and demonstrate

Use README's project-local uv/cache exports and existing private PostgreSQL URL:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

[PostgreSQL setup](../POSTGRESQL_BATCH_STORAGE.md),
[updated webhook/API contract](../WEBHOOK_INTEGRATION.md),
[exact Postman workflow](../POSTMAN_FEEDBACK_RESULTS.md),
[collection](../postman/feedback-results.postman_collection.json),
[blank-secret environment](../postman/feedback-results.postman_environment.json).
The Postman flow saves the original ID, polls status, retrieves the actual stored
analysis, checks duplicates/conflicts/authentication and compares the same response
after a manual FastAPI restart. It never asks for sentiment/analyze resubmission.

## Remaining limitations

The real available local server is PostgreSQL12.22, end-of-life; verification on a
supported server remains outstanding. One coordinator/ASGI worker only; no distributed
processing or exactly-once execution. Raw data is intentionally durable under an
explicit retention policy. Old discarded in-memory events cannot be recovered.
A result not committed because the DB failed cannot be represented as persisted
success. Restart marks unfinished work failed rather than replaying the model.

No real Groq/Google/external webhook calls, frontend, deployment, Git command/mount
change, private .env change or new dependency occurred. Batch storage is preserved;
Gmail credentials/state remain out of scope. Workspace files/current local DB are
available; cross-managed-environment replacement and production backup/restore
retention remain unverified. Prior reviewer source archives predate this feature
and are not regenerated. Live/manual Postman acceptance remains a user-run step;
production/reviewer readiness is not inferred solely from638 passing tests.
