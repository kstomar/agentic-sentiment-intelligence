# T07 completion report

2 November 2026, Asia/Calcutta. **T07 complete in the documented single-process
business API scope. QA-001 RESOLVED. Full release: NOT READY. T08 not started.**

## A. Implementation

Added a bounded private API-credential/integration registry, immutable authenticated
principals and a small explicit permission policy. Every protected REST request
uses verified identity; owned batch/event operations also enforce it in services
and stores. Added tenant quotas while retaining T06 global controls. No account
CRUD, user login, OAuth, billing, database, Gmail, frontend, deployment, provider
client, sentiment prompt, additional graph or remote MCP transport was introduced.

## B. Authentication

TENANT_CREDENTIALS_JSON maps validated key IDs and independently generated secrets
to configured businesses. Optional permissions restrict the seven normal operation
scopes; omitted permissions grant those normal scopes, never another owner's data.
WEBHOOK_INTEGRATIONS_JSON binds unique integrations/secrets to configured businesses.
Registries reject malformed/oversized arrays, duplicate JSON properties/IDs/secrets,
ambiguous ownership, unknown integration owners and unsafe global headroom.

At most 32 businesses,128API credentials, eight credentials per business and 128
integrations are supported. Each registry is at most 64 KiB UTF-8. New secrets are
43–128URL-safe characters generated from at least 32 random bytes; shape checks
cannot prove entropy. API authentication compares fixed-size credential hashes in
constant time across the bounded registry. HMAC uses existing compare_digest.
Secrets/proofs never appear in HTTP/MCP responses or configuration diagnostics;
SecretStr masking also protects structured Pydantic root-error inputs.

Legacy APP_API_KEY and single-webhook settings own only reserved development.
Existing nonproduction setups without a registry preserve compatibility; with a
business registry, explicit DEVELOPMENT_AUTH_ENABLED=true is required to retain
legacy access. Production always disables legacy authentication, even if true.
It is never a superuser. No real credentials/.env configuration were created or
changed. [Complete configuration and rotation guide](../TENANT_ISOLATION.md).

## C. Trusted principal

Principal is immutable and contains configured tenant/credential/permissions plus
private authentication proof. Sensitive service/store operations validate proof
and claims against their authoritative registry. Request body, business_type,
CSV cells, review IDs, query/header hints and model results cannot issue authority.
Middleware authenticates/authorizes before REST body intake and binds task-local
context. Routes explicitly pass principals to owned-resource methods; workers bind
saved verified context. Missing authority401, missing permission403, foreign or
unknown owned resource404, tenant quota429. Direct Python callers require verified
principal/context; production has no default identity. Global store maintenance is
private, and inspection maps authorize/filter owners. All in-process Python code
and configuration operators remain trusted; no adversarial-code sandbox is claimed.

## D. Batch isolation

Creation records the verified owner before scheduling. Status, report, paginated
results and download authorize in both service and store before exposing objects
or derived data. Foreign and unknown valid IDs return the same code/message404.
Rotation credentials for one tenant share ownership and quota; another business
cannot access any of those resources. An occupied caller-owned store cannot be
rebound to an authority that fails to validate saved owners. Reservations survive
HTTP cancellation until parsing actually ends, then raw text is wiped. Existing
job processing, evidence/report validation, terminal TTL, expiry and shutdown
cleanup are preserved. Raw feedback remains temporary, with no database added.

## E. Webhook isolation

Original-byte HMAC continues to sign integration.timestamp.delivery. plus body.
Server registry verification selects the integration secret and tenant; payload
identity claims reject rather than confer privileges. Public worker admission
revalidates typed signed context/raw bytes before reservation, preventing a modified
delivery object from transplanting a previously authenticated principal.

Status/storage key is tenant+delivery; idempotency additionally verifies integration
and exact-body digest, excluding timestamp. Same integration/ID/bytes returns 200
DUPLICATE; changed bytes409. A second integration in one tenant colliding with a
retained ID returns 409 WEBHOOK_DELIVERY_COLLISION, even for identical bytes, without
overwriting/claiming the original. Separate businesses can reuse IDs independently.
Every retry authenticates before lookup; reservation remains atomic and bounded.
Status returns only state/safe error code, never feedback or analysis. Existing
fixed workers, deadlines, timestamp/retention window, terminal expiry and cleanup
remain. No exactly-once, restart-durable or distributed claim is made.

## F. Resource controls

Global defaults remain:4 MiB JSON,16 KiB webhook,2 MiB file+64 KiB multipart envelope;
16 active protected requests,120 admissions/minute,15s body reads; three batch jobs,
two batch model permits,20 retained jobs; four shared REST model operations; two
webhook workers,20 pending events,100 retained reservations. Existing provider/graph
retry/deadline bounds and separate MCP two-call limit remain.

Business defaults:4 active requests,60 admissions/minute, one investigation, two
model operations, one active/five retained batch jobs, five pending/one active/
twenty retained webhook events. Effective limits leave global headroom; batch
active limits also leave another business's batch model permit. Rotating credentials
share tenant counters. Fixed workers skip owners already at worker quota, avoiding
head-of-line occupation of every worker by one owner. No unlimited queues exist.

Only verified tenant identity keys quota state. Active counters remove idle keys;
rolling windows are bounded/expire lazily; retained quotas expire with stores.
Cancellation/deadline paths release counters, including delayed parse completion.
Before full HMAC, webhook body reads use global caps only: invalid signatures
cannot charge tenant/model/queue quotas. These are single-instance application
controls, not transport-wide DoS protection or guaranteed simultaneous service for
all businesses. Shared provider-imposed limits differ from tenant/global429.

## G. Security verification

Actual Alpha/Beta credentials test owner success and foreign denial for all four
batch reads, HTTP and direct store/service boundaries, owned status, reused delivery
IDs, same-tenant integration collisions and signature tampering. Tests reject
forged principals, wrong-registry proofs, missing permissions, request-selected
identity, invalid configuration and legacy production fallback. Rotation/revocation,
concurrent owners, atomic duplicate admission, per-tenant/global quota headroom,
rate/retention expiry, body/provider timeouts and cancellation/cleanup are covered.

QA-001 root cause was shared-key authentication without a principal/owner and
unscoped resource lookup. The implemented server identity, owner predicates and
service-boundary checks now resolve that demonstrated business API finding. This
does not certify database, user-level, remote-MCP, infrastructure or distributed
isolation. [Detailed security review](SECURITY_REVIEW.md).

## H. Full regression result

**447 collected,447 passed,0 failed,0 skipped,0 errors;11.461 seconds (console 11.46 s),
exit 0. All 330 baseline case IDs retained;117 new T07 cases.**

Integration116; security214; unit114; existing bounded mock benchmarks3.
Baseline assertions were not weakened/skipped. Direct-call fixtures now authenticate;
webhook fixtures supply signed context/new status signatures; the original 5 ms-skew
sweeper freezes wall time while monotonic expiry continues. New missing-context
cases ensure these fixture adaptations do not create a production fallback.

Existing FastAPI import/startup, T01 strict/Pydantic/evidence behavior, all four
LangGraph actions, both chat modes, CSV/XLSX/reports, T06 limits/HMAC/workers and
official MCP in-process/stdio checks pass. New MCP tests preserve two stateless
tools and reject tenant_id arguments without registry disclosure. All inference
was mocked/network-blocked. No additional real Groq or external webhook request.
The three existing mock benchmarks are not live performance/load testing.

Use README's local uv exports, then:

```bash
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' WEBHOOK_SHARED_SECRET='' WEBHOOK_INTEGRATION_ID='' uv run --locked --offline pytest -q
uv sync --locked --offline
uv pip check
```

Python 3.12.16 / uv 0.13.6 / official MCP 2.3.0. Offline sync77resolved packages;
all 73 installed packages compatible. No dependency file/version changed. Coverage,
Ruff, mypy and advisory scanning were not added/run. [JUnit](t07-full.xml),
[actual console](t07-pytest-output.txt), [summary](t07-summary.json),
[dependency evidence](t07-dependency-checks.txt).

## I. Compatibility

Twelve existing paths, request parameters/bodies, success schemas/defaults,
auth-scheme names and old declared responses are preserved by actual OpenAPI
comparison. Added three ErrorCode values: AUTHORIZATION_FAILED,
TENANT_CAPACITY_EXCEEDED, WEBHOOK_DELIVERY_COLLISION;403 declarations on ten REST
operations; updated security description/event-status summary. Auth-unconfigured
message now recommends server credentials generally. No body tenant field exists.
The approved T06 4 MiB JSON 413 policy remains unchanged.

Configuration now governs business credentials/permissions/quotas. Production
rejects legacy fallback; registry-mode compatibility requires explicit opt-in.
These are intentional security behavior changes. Direct Python owned methods now
need a verified Principal/context, and webhook admission takes typed signed context,
not a bare integration string. Existing development API behavior remains functional.
[Machine comparison](t07-compatibility.json).

Sentiment service, prompt/schema, actual LangGraph definition and MCP implementation
are unchanged by hash comparison. T07 only wraps policy/accounting around their
existing call boundaries. No tenant data is added to LLM prompts. Configuration
rotation/revocation requires restart, losing all in-memory data; overlap credentials
share ownership semantics but do not make data restart-durable.

## J. Limits

Business credentials, not per-user login/accounts. In-memory single-process state,
no database persistence or row-security system, no distributed authorization/rate
limiter, no durable/exactly-once work. Independent ASGI/MCP processes have independent
state. Local MCP remains launcher-authorized stateless analysis; future tenant MCP
must obtain trusted host/launcher identity outside model/tool arguments. No remote
transport or owned lookups were added. Global pre-HMAC/transport limits cannot
promise full host/network DoS protection. Python/configuration operators are trusted.

## K. Release and next milestone

**QA-001 RESOLVED in scoped business API/service/store implementation.** No original
scoped HIGH security finding remains open; QA-003/T06 and QA-005 remain resolved.
This is not a claim that the whole project has no security flaws. Wider live/model
acceptance (QA-004), operational/Git handoff (QA-006), Gmail inclusion/deferral
(QA-007) and optional assurance (QA-009) remain unresolved.

Prior single synthetic live T01 request remains VERIFIED: openai/gpt-oss-20b,
HTTP 200, native strict/Pydantic/evidence pass, 1.4903 s,1,371 tokens. T07 made zero live
calls. No real business registry was deployed, no Gmail/frontend/database created,
no Git command/mount modification, deployment or T08 work occurred. Files are
available now; managed-session/container restart retention is unverified.

**Full release NOT READY. T07 complete. T08 may begin when separately authorized.**
[Current release decision](RELEASE_READINESS_REPORT.md),
[retained T06 history](history/pre-t07/KNOWN_ISSUES.md).

## Files changed

Complete machine inventory: [t07-manifest.json](t07-manifest.json). No Git command
was used to produce it. Original findings/contracts/source inventories are retained
under history/pre-t07; original audit, QA-005, T06 and live evidence remain.

### New production

- app/core/tenant_auth.py

### Modified production

- app/api/v1/batch.py
- app/api/v1/chat.py
- app/api/v1/ingestion.py
- app/api/v1/investigation.py
- app/api/v1/sentiment.py
- app/api/v1/webhooks.py
- app/core/config.py
- app/core/exceptions.py
- app/core/ingress_limits.py
- app/core/processing_limits.py
- app/core/security.py
- app/core/webhook_security.py
- app/main.py
- app/services/batch_service.py
- app/services/investigation_service.py
- app/services/webhook_service.py
- app/storage/event_store.py
- app/storage/job_store.py

### New tests

- tests/security/test_batch_tenant_isolation.py
- tests/security/test_tenant_api_regressions.py
- tests/security/test_tenant_auth.py
- tests/security/test_tenant_quotas.py
- tests/security/test_webhook_tenant_isolation.py
- tests/t07_helpers.py

### Adapted baseline test setup/call sites

- tests/conftest.py
- tests/security/test_ingress_limits.py
- tests/unit/test_webhook_workers.py

### Updated documentation/configuration

- README.md
- AGENTS.md
- .env.example
- docs/README.md
- docs/AGENTIC_PATTERNS.md
- docs/WEBHOOK_INTEGRATION.md
- docs/MCP_INTEGRATION.md
- docs/qa/PROJECT_AUDIT_REPORT.md
- docs/qa/TEST_EXECUTION_REPORT.md
- docs/qa/SECURITY_REVIEW.md
- docs/qa/API_CONTRACT_REPORT.md
- docs/qa/RELEASE_READINESS_REPORT.md
- docs/qa/KNOWN_ISSUES.md
- docs/qa/AGENTIC_PATTERN_VERIFICATION.md

### New documentation

- docs/TENANT_ISOLATION.md
- docs/qa/T07_IMPLEMENTATION_REPORT.md

### Updated QA artifacts

- docs/qa/openapi.json
- docs/qa/benchmark_results.json
- docs/qa/audit_summary.json
- docs/qa/console-summary.txt
- docs/qa/source_inventory.json
- docs/qa/documentation_links.json

### New QA evidence

- docs/qa/t07-full.xml
- docs/qa/t07-pytest-output.txt
- docs/qa/t07-dependency-checks.txt
- docs/qa/t07-compatibility.json
- docs/qa/t07-summary.json
- docs/qa/t07-manifest.json

### Historical copies

- docs/qa/history/pre-t07/AGENTIC_PATTERN_VERIFICATION.md
- docs/qa/history/pre-t07/API_CONTRACT_REPORT.md
- docs/qa/history/pre-t07/KNOWN_ISSUES.md
- docs/qa/history/pre-t07/PROJECT_AUDIT_REPORT.md
- docs/qa/history/pre-t07/RELEASE_READINESS_REPORT.md
- docs/qa/history/pre-t07/SECURITY_REVIEW.md
- docs/qa/history/pre-t07/TEST_EXECUTION_REPORT.md
- docs/qa/history/pre-t07/audit_summary.json
- docs/qa/history/pre-t07/console-summary.txt
- docs/qa/history/pre-t07/openapi.json
- docs/qa/history/pre-t07/source_inventory.json
