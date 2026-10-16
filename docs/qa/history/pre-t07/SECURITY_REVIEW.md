# Security review — T06

Date: 2 November 2026. **One unresolved HIGH security finding: QA-001 tenant
ownership.** QA-003's demonstrated application ingress/resource defects are
resolved within the single-process scope. No demonstrated CRITICAL finding;
this is scoped code review and automated local evidence, not exhaustive testing.
[Pre-T06 findings](../pre-t06/SECURITY_REVIEW.md) and
[original review](../original-audit/SECURITY_REVIEW.md) remain preserved.

## QA-001 — Missing tenant ownership: HIGH, OPEN (T07)

Sensitive lookup endpoints: GET /api/v1/batch/jobs/{job_id} and its /report,
/results, /download variants. Files: app/api/v1/batch.py,
app/services/batch_service.py, app/storage/job_store.py, app/core/security.py.
Any holder of the shared key can read known job IDs, evidence and derived data;
the retained characterization test demonstrates this. Job opacity and TTL are
not ownership. The new GET /api/v1/ingest/events/{delivery_id} similarly grants
shared-key development/admin visibility into the configured integration's state,
though it deliberately exposes no analysis/raw feedback. Affected new files:
app/api/v1/ingestion.py, app/services/webhook_service.py, app/storage/event_store.py.

Write/cost entry points POST /api/v1/sentiment/analyze, /agent/investigate, /chat,
/batch/upload, /ingest/feedback have no distinct principals or per-business quotas.
The webhook has verified integration identity and HMAC but no mapping from an
integration to a real business principal. Business_type is only a hint. REST
and stdio authority are different; local MCP trusts its launcher and exposes no
job/event lookup. No T06 route adds caller-selected privileged ownership fields.

Minimal T07 design: authenticate distinct revocable credentials into immutable
principal/business context; map server-owned integration credentials to that
context; pass it through services/storage; key every reservation/job/query by
trusted owner; authorize create and read boundaries, not merely route filters;
use consistent inaccessible/unknown 404; add cross-principal REST/service/HMAC
negative tests and per-principal bounded rate/model/retention accounting. Define
local MCP authority explicitly before exposing tenant data. Keep development
single-key mode explicit. No such identity system was implemented in T06.

## QA-003 — Ingress/resource controls: RESOLVED for single-instance T06

Affected POST endpoints: sentiment/analyze, agent/investigate, chat,
batch/upload, ingest/feedback, webhooks/feedback. Protected batch/event GET
operations also share global request admission/rate controls. Files:
app/core/ingress_limits.py, processing_limits.py, security.py, config.py,
exceptions.py; app/main.py; app/services/sentiment_service.py,
investigation_service.py; app/agents/action_selector.py; new webhook service/store.

Previously field lengths allowed unlimited whole JSON bytes; direct calls lacked
shared model admission; multipart body parsing preceded route authentication and
job reservation. Impact: aggregate memory/parser/provider cost consumption across
interfaces despite per-job limits. An accepted >2 MiB padded body demonstrated
the gap without attempting a real DoS.

Implemented and tested:

- Early REST key verification reuses constant-time existing validation. Untrusted
  upload bodies are rejected before read/parse. Duplicate key headers reject.
- Shared ASGI actual-byte cap: approved 4 MiB JSON, separate 16 KiB webhook,
  unchanged 2 MiB file plus 64 KiB multipart envelope. Original bytes are replayed;
  HMAC is verified before JSON parsing. Length spoofing cannot bypass byte counts.
- Sixteen active protected HTTP requests, three concurrent upload intakes, bounded
  120-admission rolling-minute deque, 15-second body-read timeout. Fail-fast 429/
  408/413 errors have safe existing envelopes. Cancellation releases capacity.
- Four shared REST model operations across T01 and action selection, including
  direct/chat/graph/batch/webhook paths. No unbounded model waiting queue; budget
  covers bounded service retries. Existing three batch jobs/two batch permits,
  request-scoped graph/record/time limits and MCP two-active-tool cap remain.
- Webhook fixed two workers, 20 pending, 100 retained, processing deadline 60 s,
  temporary raw data, terminal TTL 1800 s, cancellation/cleanup, no active eviction.

The user explicitly approved 4,194,304-byte JSON 413 behavior as an intentional
compatibility change. The historical >2 MiB test is retained as a compatibility
check under that cap, **not** evidence of a remaining unbounded body policy.
New tests exercise the actual cap and all protected JSON interfaces. Full suite:
330 passed; see [tests](../../TEST_EXECUTION_REPORT.md).

Remaining deployment/T07 work: per-business quotas/fairness require trusted
identity; app limits are per-instance, not a distributed or host-wide DoS policy.
Verify proxy/header/connection/TLS limits, process/memory quotas, representative
capacity, observability, reverse-proxy path handling and production configuration
before deployment. Docs/health remain outside protected-request rate admission.
A holder of valid shared credentials can consume the global budget. Multiple
ASGI/MCP processes have independent counters. No infrastructure control is claimed
verified. These limitations remain visible under QA-001/QA-006 rather than being
presented as full production security clearance.

## Webhook authentication and privacy

HMAC-SHA256 covers configured integration, decimal timestamp, delivery ID and
original body. Required headers occur once, IDs are restricted ASCII, signature
format is exact lowercase sha256=hex, comparisons use compare_digest. Both past
and future skew are bounded. Missing configuration fails closed 503. Payloads and
nested feedback reject extra authority fields. Header checks precede body reads;
full authentication precedes JSON validation and duplicate lookup. No API key is
required for this separately signed endpoint.

Atomic integration+delivery reservations use SHA256 of exact body bytes without
timestamp; fresh signed retries deduplicate. Conflicting bytes 409, identical 200,
new admitted 202. Invalid signatures never bypass checks for known deliveries.
TTL covers twice the clock-skew tolerance; active records never evict. Restart
loses deduplication, so this is not exactly-once or durable replay protection.

Local provider configuration is checked before 202, without a network probe.
Actual provider errors become FAILED with a fixed code; shared model saturation
can also fail an admitted event. Workers clear raw data, discard results and
expire metadata; status is authenticated/admin only and no-store. SecretStr,
fixed errors/request IDs, provider log suppression and disabled tracing remain.
No credential/authorization header/raw provider diagnostic was recorded. T06 did
not read/print real .env values or install a webhook secret. No additional live
Groq request was made; the prior one-case T01 result remains narrowly VERIFIED.

## Other retained controls and limitations

Existing archive/formula/CSV validation, batch cleanup/evidence reconciliation,
question-only action selection, allowlisted graph capabilities, narrow MCP tools
and protocol-safe diagnostics continue to pass. They do not establish semantic
prompt-injection immunity or live classification accuracy. No permanent customer
feedback storage was introduced. Client copies/host instrumentation are outside
server cleanup; dropping references is not cryptographic memory erasure.

No new dependency was added. uv pip check verifies compatibility, not CVE absence.
Coverage/static/advisory scanning and host penetration testing remain unperformed.
Git/deployment are blocked/unverified (QA-006), Gmail scope unresolved (QA-007).
Overall release decision remains NOT READY.
