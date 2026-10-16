# Security review — T07

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

REST authenticates/authorizes before body parsing. Seven normal permissions are
explicit; empty scopes403, invalid authority401. Request fields and model outputs
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

**447 collected; 447 passed; 0 failed, 0 skipped, 0 errors; 11.461 seconds (console 11.46 s), exit 0.**
All 330 baseline cases plus 117T07 cases pass. Tests use distinct fabricated
credentials and actual HTTP/service/store boundaries, verifying owner success,
foreign identical404, all batch reads/downloads, event isolation, signed ownership,
collision/duplicate concurrency, forged principals/contexts, rotation/revocation,
legacy containment, every permission boundary and resource release/headroom.
[Junit evidence](../../t07-full.xml), [execution report](../../TEST_EXECUTION_REPORT.md),
[tenant design](../../../TENANT_ISOLATION.md). QA-001 is therefore RESOLVED within this
scope; it is not merely deferred/documented. QA-003 remains resolved for the
single-instance resource scope, now extended with business accounting.

Stateless local MCP remains trusted-launcher only, with two tools and no owned
lookup, tenant arguments or registry disclosure. No remote MCP identity, user
login, database row isolation, Gmail or persistent feedback storage was introduced.
All Python application/configuration code is trusted; this is not an in-process
adversarial-code sandbox. Summaries/evidence remain sensitive and model quality
is not established by ownership tests. Cleanup releases references, not secure
memory erasure; downloaded client copies are outside server retention.

No additional live provider call occurred. Prior single-live-T01 strict smoke
remains VERIFIED only for that sample. Git/deployment handoff, wider live/model
acceptance, Gmail scope and optional static/coverage/advisory assurance remain.
All 73 installed packages pass compatibility, which is not CVE clearance. Overall
release remains NOT READY. T08 was not started.
