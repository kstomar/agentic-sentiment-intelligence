# Security review — T08

2 November 2026. **QA-001 RESOLVED for business API/service/store ownership.**
No demonstrated CRITICAL finding and no remaining open HIGH security finding in
the original scoped pair. This is not a full penetration/host/CVE certification.
[T06 review](../pre-t07/SECURITY_REVIEW.md) and original findings are retained.

## QA-001 root cause and affected surface

Previously one shared key authenticated only possession, with no distinct
principal/owner. Batch lookup used job ID alone; event status selected the one
configured integration. Field hints/opaque IDs were never ownership controls.
Affected protected endpoints: POST sentiment/analyze, agent/investigate, chat,
batch/upload, ingest/feedback; GET batch/jobs/{job_id} and /report, /results,
/download; GET ingest/events/{delivery_id}; signed POST webhooks/feedback also
needed integration-to-business binding. All paths use /api/v1 prefixes.

Primary changed files: core/tenant_auth.py, config.py, security.py,
ingress_limits.py, processing_limits.py, webhook_security.py, exceptions.py;
main.py; all six REST adapters; services/batch_service.py,
investigation_service.py, webhook_service.py; storage/job_store.py, event_store.py.
No sentiment prompt/schema or Groq implementation was rewritten.

## Implemented security boundary

A bounded private registry authenticates API credentials into immutable Principal
objects. IDs, credential hashes, owner mappings and permissions are server-owned.
Constant-time fixed-size credential matching scans the complete bounded registry;
HMAC compare_digest remains. Configuration rejects malformed/ambiguous entries,
duplicate key/integration IDs, API/HMAC secret reuse, unknown owners, oversized
arrays and invalid headroom. SecretStr values protect ordinary and structured
Pydantic error inputs; parser diagnostics are fixed and credential-free.

REST authenticates/authorizes before body parsing. Ten normal permissions are now
explicit (seven T07, three Gmail); empty scopes403, invalid authority401. Request fields and model outputs
cannot issue principals or elevate policy. Services/stores validate proofs/claims,
not bare tenant strings. Batch jobs get verified owners at creation; all public
read paths authorize before exposing object/results. Maps are filtered/read-only;
global cleanup is private. Foreign/missing/expired resources use the same 404.
An occupied caller-owned store cannot be rebound to an authority that fails to
validate its existing owners. Direct Python calls without credential-derived
principal/context fail, including inspection helpers.

Signed integration secrets map to configured owners; the body cannot override
that mapping. Worker admission rechecks original signed bytes and verified context.
Tenant+delivery identifies status storage; integration+digest additionally controls
idempotency. Different tenants reuse IDs safely; another integration of the same
tenant cannot claim a retained ID, even identical content (409). Authentication
always precedes duplicate lookup. Atomic reservation, TTL/replay checks, bounded
retention, temporary raw data and cancellation-safe cleanup remain.

Legacy APP_API_KEY/single webhook own only reserved development. Business registry
mode needs explicit nonproduction opt-in; production always disables both legacy
paths. Legacy cannot read another owner. Multiple keys for a tenant share ownership
and quota; configuration removal revokes keys after restart. No superuser or
public credential-management API exists. The shared legacy key still does not
separate individual users; that is outside the business-level policy.

## Quotas and remaining operational boundary

T06 global actual-byte/intake/rate/deadline/model limits remain. Business mode
adds verified per-owner request/rate, whole-investigation, model, batch active/
retained and webhook pending/worker/retained budgets. Effective caps leave global
headroom; batch active caps also leave another owner's batch model permit. Fixed
workers scan past saturated owners instead of blocking every worker on one owner.
Counters use verified tenant, not key ID/body metadata, and are bounded by registry
or removed on release. Rate expiry is lazy; store retention expiry frees quotas.
Cancelled parser threads retain reservations until actual completion and erasure.

Before full HMAC, webhook bytes use global limits only; unverified header identity
is never charged as a tenant. These controls do not guarantee internet transport
fairness or host-wide DoS protection. Independent ASGI/MCP processes have separate
counters. Per-business app limits differ from shared provider-imposed quotas.
TLS/proxy/header/connection/process/memory policy and deployment capacity remain
unverified under QA-006. No distributed authorization/rate limiter exists.

## Verification and finding status

**571 collected; 571 passed; 0 failed, 0 skipped, 0 errors; 18.286 seconds (console18.28s), exit0.**
All447 T07 cases plus124 new Gmail cases pass. Tests use distinct fabricated
credentials and actual HTTP/service/store boundaries, verifying owner success,
foreign identical404, all batch reads/downloads, event isolation, signed ownership,
collision/duplicate concurrency, forged principals/contexts, rotation/revocation,
legacy containment, every permission boundary and resource release/headroom.
[JUnit evidence](../../t08-full.xml), [execution report](../../TEST_EXECUTION_REPORT.md),
[tenant design](../../../TENANT_ISOLATION.md). QA-001 is therefore RESOLVED within this
scope; it is not merely deferred/documented. QA-003 remains resolved for the
single-instance resource scope, now extended with business accounting.

Stateless local MCP remains trusted-launcher only, with two tools and no owned
lookup, tenant arguments or registry disclosure. No remote MCP identity, user
login, database row isolation or persistent feedback storage was introduced.
T08 Gmail extends the owner boundary described below.
All Python application/configuration code is trusted; this is not an in-process
adversarial-code sandbox. Summaries/evidence remain sensitive and model quality
is not established by ownership tests. Cleanup releases references, not secure
memory erasure; downloaded client copies are outside server retention.

No additional live provider call occurred. Prior single-live-T01 strict smoke
remains VERIFIED only for that sample. Git/deployment handoff, wider live/model
acceptance, live Google/approval and optional static/coverage/advisory assurance remain.
All 73 installed packages pass compatibility, which is not CVE clearance. Overall
release remains NOT READY. T08 is implemented with mocks; T09 was not started.


## T08 OAuth, mailbox and data boundaries

Affected new endpoints: POST /api/v1/integrations/gmail/connect and /import,
GET /status, /oauth/callback, /imports/{job_id}, /imports/{job_id}/results,
DELETE /disconnect (all under that same Gmail prefix). Six use registry API
credentials with gmail:connect/import/read; the browser callback validates
single-use expiring state instead. Service methods revalidate proof/permission,
store.job checks owner, and workers explicitly bind verified principal context.
Foreign and unknown jobs return indistinguishable404; status has no owner selector.

Primary added files: api/v1/gmail.py, schemas/gmail.py, integrations/google_gmail.py,
integrations/gmail_mime.py, services/gmail_service.py, storage/gmail_store.py.
Modified composition/config/auth/transport files: main.py, core/config.py,
core/tenant_auth.py, core/exceptions.py, core/ingress_limits.py. Existing T01 strict
service/prompt/schema, graph and MCP implementations remain hash-identical.

State uses32 random bytes, PKCE verifier64, S256; only a state digest/verifier and
verified principal are retained. Atomically consume before exchange; state replay,
expiry, query owner/redirect overrides and duplicate callback parameters reject.
Exactly readonly scope, fixed registered callback and fixed Google hosts prevent
caller-directed authorization/fetches. Callback scope claims are ignored. HTTPS
outside explicit localhost development; tokens commit only after authenticated
getProfile verifies mailbox ownership. Cross-owner conflicts409 without details.
Late callbacks cannot reconnect after owner disconnect or shutdown.

Token storage is private bounded RAM, SecretStr/repr-safe, never API/model input,
with single-flight refresh, expiry/revocation/scope failure handling and8-hour hard
connection TTL. Expired token references clear while mailbox ownership tombstones
remain until authorized disconnect/reconnect. No plaintext token files/database.
State caps64/one owner, connections33, imports2/one owner including pending,
retained jobs20/five owner, dedup400/100 owner, deadline120s, HTTP4/10s/one retry
and256KiB actual response cap. No authorization-code exchange retry. Existing
T06/T07 global/per-owner controls and headroom remain. Active reservations never
evict, and task count is bounded by admission before creation.

MIME metadata preflight excludes body.data and skips an entire attachment-bearing
message before body retrieval. External bodies/nontext leaves never get decoded;
no attachment API/renderer/URL/image fetch. Text decoding has strict sizes/charset/
structure bounds, no silent truncation. Only selected body text goes to existing
Groq classification, source=email. Untrusted instructions cannot choose tools or
identity. Subject/sender/time are transient, discarded and omitted from inference.
T01 exact evidence validation remains; schema-invalid/ungrounded results fail.

Dedup uses tenant+verified mailbox+message ID with atomic reservations, no thread
conflation and bounded TTL. Failed/skipped attempts remain deduplicated untilTTL;
duplicates return no cached analysis. Disconnect invalidates flows, cancels owner
jobs, clears tokens/results/dedup and releases mailbox claim; no cross-owner effect.
Provider operations already sent cannot be undone and Google grant is not revoked.
Shutdown cancels jobs/callbacks and clears all. Memory-reference cleanup is not
cryptographic erasure. Summaries/evidence may still contain private email text;
clients' copies are outside retention. No raw body/header archive is retained.

Privacy headers add no-referrer to existing no-store/nosniff private responses.
Uvicorn access logs are suppressed to avoid code/state queries; application/provider
logs do not emit OAuth metadata. Production proxy/access/trace policies must be
configured independently and are not verified by local log-capture tests.

## Remaining security/acceptance limits

QA-007 missing code is locally resolved; **Google live/Cloud/approval acceptance
remains OPEN**, not implied by passing mocks. OAuth web-client PKCE acceptance,
real consent/redirect, refresh/revocation and real Gmail partial fields are not
verified with Google. gmail.readonly is restricted; review Google verification/
assessment requirements and authorize transfer of selected feedback to Groq.
No claim of user-data policy compliance, production Google approval or live Gmail.

All connections/jobs/mailbox claims/dedup disappear on restart. No distributed
ownership, persistent encrypted credentials, mailbox transfer workflow or user
login exists. Production persistence/lifecycle design needs separate authorization.
TLS/proxy/transport/host capacity, Git/deployment and broader provider acceptance
remain QA-006/QA-004 gates. Optional scanners/coverage remain QA-009. No newly
demonstrated HIGH/CRITICAL issue is asserted, and no comprehensive security clearance.
See [Gmail guide](../../../GMAIL_INTEGRATION.md), [tests](../../TEST_EXECUTION_REPORT.md),
[T07 review history](../pre-t08/SECURITY_REVIEW.md).
