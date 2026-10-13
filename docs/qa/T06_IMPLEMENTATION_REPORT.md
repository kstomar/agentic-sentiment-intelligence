# T06 completion report

2 November 2026. **T06 complete for its single-process development scope.**
Release decision: **NOT READY**. T07 can begin as a separately authorized milestone;
no T07 work was performed.

## Implementation and endpoints

| Method/path | Authentication | Behavior |
| --- | --- | --- |
| POST /api/v1/ingest/feedback | Existing X-API-Key | Validates/normalizes external metadata, delegates to T01, returns 200 ANALYZED with existing SentimentResponse |
| POST /api/v1/webhooks/feedback | HMAC-SHA256 signed headers, no X-API-Key | Validates original bytes, event and capacity; returns 202 ACCEPTED or 200 DUPLICATE; conflict 409 |
| GET /api/v1/ingest/events/{delivery_id} | Existing X-API-Key; development/admin | Returns state and controlled error_code only; unknown/expired 404 |

REST routes and fixed webhook workers use the same transport-independent
IngestionService and application-owned SentimentService. The existing classifier,
prompt, Groq client factory, strict-output schema, evidence checks and bounded
retry/timeout policy are reused. No new graph, classifier, prompt, provider client,
MCP tool, persistent database or queue framework was added. No frontend, Gmail,
vendor adapter or multi-business feature was implemented.

## Webhook security and lifecycle

Canonical signed bytes are UTF8(integration_id + '.' + timestamp + '.' +
delivery_id + '.') followed by the exact raw body. Signature format is
sha256=lowercase-hex; verification uses hmac.compare_digest. All four headers
are required once, IDs are restricted ASCII, and both past/future timestamps
must be within 300 seconds by default. Missing configuration fails closed 503.
The configured integration and verified headers provide integration identity;
payload business_type/control fields cannot confer ownership or privileges.

Reservation identity is authenticated integration+delivery. SHA256 of the exact
body, excluding timestamp, permits fresh signed retries without duplicate calls.
Same bytes return 200 DUPLICATE; different bytes return 409; every retry must pass
HMAC/time checks. Check/reserve/queue admission has no await point, making it
atomic on the application's one event loop. Full retained capacity rejects new
work rather than evicting active reservations.

Two fixed workers consume 20 pending events. Retained active/terminal reservations
are capped at 100, with a 60-second event deadline and 1,800-second terminal TTL.
Retention must cover twice timestamp tolerance, including future-dated deliveries.
202 is local admission/scheduling only; it does not imply provider success.
Required local provider configuration is checked without a live network probe.
Provider/capacity/timeout failures become FAILED with safe codes. Results are
validated then discarded. Raw feedback is released immediately on termination;
metadata expires via lazy/periodic cleanup. Shutdown cancels workers, drains the
queue and clears records. Status never exposes analysis or raw feedback.

The queue/store are single-process, nondurable and not distributed. Reload/restart
loses deliveries and deduplication. A still-valid request may execute again after
restart. There is no exactly-once claim. Run one ASGI worker.

## Resource remediation and compatibility

Shared ASGI admission authenticates REST before body read/parse, checks actual
incoming/chunked bytes and replays the original bytes without reserialization.
HMAC verification occurs before JSON parsing. Default protected JSON cap:
**4,194,304 bytes**. Separate webhook cap: 16,384 bytes. Multipart remains 2 MiB per
file with 64 KiB additional envelope allowance. Upload intake is bounded at 3
concurrent requests before multipart parsing, separate from the existing job cap.

The user explicitly approved the **intentional compatibility change**: formerly
accepted JSON above 4 MiB, including whitespace-heavy bodies, now returns 413.
Existing valid 2 MiB padded JSON and Unicode within the byte cap still pass.
Spoofed Content-Length cannot bypass actual-byte checks. Excessively declared
or malformed length can reject early.

Global single-instance defaults are 16 active protected requests, 120 admissions per
rolling minute, 15-second body reads and 4 shared model operations. Excess work
fails immediately 429; read deadlines return 408. The classifier and selector
share one budget across REST, graph/chat, batch and webhook consumers, including
bounded retries. Existing batch limits and separate MCP two-active-tool admission
remain. There is no unlimited model waiting queue or per-event task creation.
Independent MCP/ASGI processes have separate counters. Per-business fair quotas
and proxy/header/connection/TLS/host limits remain future work.

OpenAPI now has 12 operations, adding the three routes, HMAC security, new models,
additive ErrorCode values and 408/413 error declarations. Existing request/success
schemas, operation fields, defaults, allowlists and prior responses match the
original audited contract. The comparison was checked against the preserved
original OpenAPI, not inferred solely from tests. Batch source validation/QA-005
is unchanged; only router error documentation changed. MCP source and protocol
contracts are unchanged. No dependency file/version was modified.

## Executed verification

Final command, after README's local uv exports:

```bash
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q --junitxml=docs/qa/t06-full.xml
uv sync --locked --offline
uv pip check
```

**330 collected, 330 passed, 0 failed, 0 skipped, 0 errors; 8.894 seconds (console 8.89 s).**
All 220 baseline cases remain, plus 110 new T06 cases. Existing route-inventory
expectations were extended for authorized routes/HMAC; no behavioral assertions
were weakened or skipped. QA-005's original failing test remains unchanged and
passes. Focused T06/inventory run: 100 passed in 2.72 seconds before final additions.

| Area | Passed |
| --- | --- |
| Integration | 116 |
| Security | 97 |
| Unit | 114 |
| Existing local mock benchmarks | 3 |

New tests cover valid/invalid direct ingestion and T01 reuse, HMAC/tampering/
headers/time boundaries, payload controls, duplicate/conflict/concurrent retry,
configuration failure, queue/retained/worker capacity, state/deadline/failure,
expiry and cleanup, cancellation and shutdown, byte boundaries/Unicode/chunks/
misleading lengths, actual multipart file/envelope limits, global admission/rate
and shared model-budget release. Existing FastAPI startup/import, strict adapter,
Pydantic evidence, all four LangGraph actions, CSV/XLSX/report and official MCP
in-process/stdio regressions pass. Network guards and mock inference were active;
test credentials were explicitly blank. No new live Groq or external webhook
request was made. Local benchmark outputs are not provider performance testing.

Python 3.12.16 / uv 0.13.6 / official MCP 2.3.0. Offline sync resolved 77 locked
packages and checked 73 installed packages; uv pip check reports all compatible.
Coverage, Ruff, mypy and advisory scanning were not installed/run.

Evidence: [JUnit](t06-full.xml), [summary](t06-summary.json),
[compatibility](t06-compatibility.json), [OpenAPI](openapi.json),
[dependency checks](t06-dependency-checks.txt), [test report](TEST_EXECUTION_REPORT.md).

## Pattern mapping

| Pattern | Actual files | Scope |
| --- | --- | --- |
| Multi-Platform Webhook Triggers | api/v1/webhooks.py; core/webhook_security.py; services/ingestion_service.py, webhook_service.py; storage/event_store.py | Generic authenticated trigger, normalization, duplicates, bounded asynchronous work and truthful ack; no vendor/durable/distributed claim |
| Dual-Use Tool Design | services/ingestion_service.py and existing sentiment_service.py; direct route/workers | Same T01 logic across adapters, no duplicate model setup/prompt |
| LLM-Friendly API Design | schemas/ingestion.py; api/v1/ingestion.py, webhooks.py; core/exceptions.py | Typed versioned inputs/results, separate auth, predictable errors/status and documented limits |
| Structured Output Specification | Existing sentiment schemas/factory plus ingestion result validation | Native strict output and exact evidence checks retained; no fallback |

Full references and limits are in [pattern mapping](../AGENTIC_PATTERNS.md) and
[QA pattern verification](AGENTIC_PATTERN_VERIFICATION.md).

## All files changed

Complete machine-readable list, including historical copies:
[t06-manifest.json](t06-manifest.json). Git was not used to obtain this inventory.

New production files:

- app/api/v1/ingestion.py
- app/api/v1/webhooks.py
- app/core/ingress_limits.py
- app/core/processing_limits.py
- app/core/webhook_security.py
- app/schemas/ingestion.py
- app/services/ingestion_service.py
- app/services/webhook_service.py
- app/storage/event_store.py

Modified production files:

- app/main.py
- app/core/config.py
- app/core/exceptions.py
- app/core/security.py
- app/services/sentiment_service.py
- app/services/investigation_service.py
- app/agents/action_selector.py
- app/api/v1/sentiment.py
- app/api/v1/investigation.py
- app/api/v1/chat.py
- app/api/v1/batch.py (additive 408 documentation only)

Tests:

- tests/integration/test_api_contracts.py (modified endpoint inventory/security)
- tests/integration/test_ingestion_api.py (new)
- tests/security/test_webhook_security.py (new)
- tests/security/test_ingress_limits.py (new)
- tests/unit/test_webhook_workers.py (new)
- tests/t06_helpers.py (new synthetic-only helpers)

Documentation/configuration:

- .env.example (empty secret/integration placeholders and limits)
- README.md
- AGENTS.md
- docs/README.md
- docs/AGENTIC_PATTERNS.md
- docs/WEBHOOK_INTEGRATION.md (new, signing/POST standard-library example)
- docs/qa/PROJECT_AUDIT_REPORT.md
- docs/qa/TEST_EXECUTION_REPORT.md
- docs/qa/SECURITY_REVIEW.md
- docs/qa/AGENTIC_PATTERN_VERIFICATION.md
- docs/qa/API_CONTRACT_REPORT.md
- docs/qa/RELEASE_READINESS_REPORT.md
- docs/qa/KNOWN_ISSUES.md
- docs/qa/T06_IMPLEMENTATION_REPORT.md (this new report)

QA artifacts updated: docs/qa/openapi.json, benchmark_results.json,
source_inventory.json, audit_summary.json, console-summary.txt and
documentation_links.json. New evidence: docs/qa/t06-full.xml,
t06-compatibility.json, t06-summary.json, t06-manifest.json and
t06-dependency-checks.txt. New history files under docs/qa/history/pre-t06/:
PROJECT_AUDIT_REPORT.md, TEST_EXECUTION_REPORT.md, SECURITY_REVIEW.md,
AGENTIC_PATTERN_VERIFICATION.md, API_CONTRACT_REPORT.md,
RELEASE_READINESS_REPORT.md, KNOWN_ISSUES.md, audit_summary.json and
console-summary.txt. Original-audit, QA-005 and live verification evidence remain.

## Release assessment and next milestone

QA-002 feature gap and QA-003 demonstrated ingress/resource defect are resolved
within the stated development scope. QA-005 remains resolved; QA-008 current
scope documentation is updated. **QA-001 missing tenant ownership remains HIGH**:
shared-key batch access and admin event status are not business authorization.
T07 should introduce trusted principal/business context, configured integration
ownership, service/store authorization, cross-business negative tests, revocation
and per-business quotas. This work has not begun.

The prior one-case live T01 result remains VERIFIED: configured
openai/gpt-oss-20b, HTTP 200, strict schema/Pydantic/evidence pass, 1.4903 seconds,
1,371 tokens. T06 made zero additional requests. Live webhook/HTTP/graph/MCP/batch
and broad accuracy/security acceptance remain unverified. See the unchanged
[prior live report](LIVE_GROQ_VERIFICATION_REPORT.md).

Git mount remains untouched and unavailable; no Git command, deployment or
repository bypass occurred. Production TLS/proxy/resource/recovery handoff,
Gmail inclusion/deferral and optional assurance gates remain outstanding. Files
are present/readable now; persistence across managed-session/container restart
is unverified. In-memory event/job state intentionally does not survive restart.

**Release: NOT READY. T06 complete. T07 may begin when separately authorized.**
