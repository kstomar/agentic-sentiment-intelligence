# Known issues — T06 follow-up

Date: 2 November 2026. Current findings below supersede the
[pre-T06 issue states](../pre-t06/KNOWN_ISSUES.md); original reproductions
remain in that snapshot and the [original audit](../original-audit/KNOWN_ISSUES.md).
Resolved findings are retained rather than deleted.

## QA-001 — Missing tenant ownership

**HIGH security; OPEN; T07.** Shared-key holders can access known batch job,
report, results and download IDs without owner checks. Existing characterization
still reproduces this. New event status is also development/admin shared-key
access for the configured integration (metadata only). Business_type is never
identity. One verified HMAC integration does not implement account ownership.
Affected endpoints/files and minimal trusted-context/service/store design are
listed in [SECURITY_REVIEW.md](../../SECURITY_REVIEW.md). T07 must add real principals,
server integration ownership, authorized lookup and per-business quotas with
cross-principal tests. It was not implemented here.

## QA-002 — External ingestion/webhooks absent

**Originally HIGH delivery gap; RESOLVED in T06.** Original inventory had no
routes/verifier/workers/store. Now direct ingestion, generic signed webhook and
protected event status exist with typed contracts, HMAC/time checks, atomic
idempotency, bounded fixed workers and TTL/privacy cleanup. New tests and all
baseline cases pass (330 total). Scope is one generic integration, no vendor
adapter or durable/distributed/exactly-once delivery. No live external webhook
or new provider call was performed. See [integration guide](../../../WEBHOOK_INTEGRATION.md).

## QA-003 — Incomplete ingress/resource controls

**Originally HIGH security; RESOLVED for the documented single-instance scope.**
Original evidence: >2 MiB padded JSON accepted with no whole-body cap, no shared
direct-call admission, multipart read/parse before authentication/job admission.
T06 adds actual-byte caps, early REST auth, pre-parse upload admission, global
concurrency/rate/body deadlines, shared classifier/selector budget and bounded
webhook workers/store. New cap/chunked/misleading-length/Unicode/concurrency/
cancellation tests pass. The user explicitly approved the 4 MiB / 413 compatibility
change; the old >2 MiB test is retained as an accepted within-cap regression.
No active reservation is evicted on storage exhaustion. Full suite: 330 passes.
Per-business quotas/fairness await T07; multi-process coordination and proxy/
header/connection/TLS/memory limits await deployment acceptance (QA-006).
This resolution does not claim host-wide DoS protection or production clearance.

## QA-004 — Live Groq verification incomplete

**Historical HIGH acceptance gap; single-live-T01 prerequisite VERIFIED before
T06; broader acceptance still OPEN.** Exactly one authorized synthetic call on
2 November returned HTTP 200 with configured openai/gpt-oss-20b, native strict
output, Pydantic/exact evidence, 1.4903 s and 1,371 tokens. T06 made zero provider
calls. No live REST/webhook/selector/graph/chat/MCP/batch inference or broad model
accuracy/security claim follows. Wider live checks require separate authorization.
[Unchanged live evidence](../../LIVE_GROQ_VERIFICATION_REPORT.md).

## QA-005 — Explicit blank batch source accepted

**MEDIUM functional; RESOLVED before T06, retained regression.** FastAPI optional
Form extraction maps an empty FormData value to Undefined and applies the default
before Pydantic. The production correction in app/api/v1/batch.py includes source
in the existing raw blank-field guard, returning the established 422 before a job
or inference. Omitted source remains file_upload; nonblank custom labels <=64,
normalization and source rules remain. Empty/whitespace reject; invalid types/
lengths reject. T01's source allowlist remains separate.
Original audit:210 collected / 209 passed / 1 failed. Focused unchanged test:1 passed;
QA-005 full suite: 220 passed. T06 retains all these tests unchanged and all 330 pass.
[Detailed root cause and original evidence](../../QA005_REMEDIATION_REPORT.md).
T06 only adds 408 declaration to this route's router, not another source patch.

## QA-006 — Repository/production operation unverified

**MEDIUM operational; OPEN.** Existing read-only .git mount remains untouched;
no Git commands, alternate repository, repair, deployment or bypass occurred.
No verified production TLS/proxy/header/connection/resource/recovery handoff.
Jobs/events/deduplication are process-local and lost on restart; multiple workers
are unsupported for consistent state. File presence now does not prove managed
session/container persistence. Environment owner must restore supported Git
access; deployment needs an explicit acceptance plan and one-worker policy until
separately designed durability/distribution exists.

## QA-007 — Gmail integration not delivered

**MEDIUM scope-dependent; OPEN.** No Gmail adapter/OAuth/token lifecycle or Gmail
tests/connection were added. Explicitly include or defer this delivery scope.
T06 is a generic webhook, not a claim of Gmail or provider-specific integrations.

## QA-008 — Documentation stale

**Originally LOW; RESOLVED for current T06 scope.** README, AGENTS, architecture,
pattern mapping and all seven QA reports now distinguish implemented T06,
authorized tests, prior one-case live verification, shared-key/T07 limitations and
approved JSON 413 policy. A signing/retention/restart/security guide was created.
Original and pre-T06 findings remain archived; historical T01–T05 scope paragraphs
are identified as history rather than current prohibitions.

## QA-009 — Optional assurance incomplete

**LOW verification limitation; OPEN.** Coverage, Ruff, mypy and vulnerability
advisory scanning were not installed or executed. uv pip check passes 73 installed
packages but is not CVE clearance. No new dependency was introduced. Decide and
authorize desired tools/gates separately; do not infer full test completeness or
static/security correctness from 330 passing tests.

Overall release decision: **NOT READY**. T06 complete; T07 may begin as separately
authorized work. No T07, frontend, Gmail or deployment was started.
