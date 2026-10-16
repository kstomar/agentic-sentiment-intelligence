# Known issues — T08

2 November 2026. Current states supersede the
[T07 issue snapshot](../pre-t08/KNOWN_ISSUES.md). Original audit, QA-005 and
single-live-T01 records remain retained; resolved issues are not removed.

## QA-001 — Missing tenant ownership

**Originally HIGH security; RESOLVED in scoped T07 business API implementation.**
Root cause: one shared key without principal/owner and ID-only batch/event lookup.
Fix: server-configured bounded API/integration registries, immutable credential-
verified principals, explicit permissions, owner capture at creation and service/
store authorization before all batch/event data access. Legacy credentials own
only development and are always disabled in production. Forged/body-selected
identity cannot authenticate. Direct Python callers need verified authority;
public maps filter owners and global maintenance is private.

Webhook integrations bind to configured owners; tenant+delivery status keys and
integration+digest idempotency isolate reused IDs. Cross-integration same-tenant
collision409, foreign/unknown 404. Owner quotas share across rotation keys, leave
global headroom, and release with cancellation/deadline/expiry. Configuration
errors/diagnostics are sanitized. Affected source paths and exact endpoint map:
[SECURITY_REVIEW.md](../../SECURITY_REVIEW.md).

Evidence: 447 passed, all 330 baseline plus 117 new cases. Distinct Alpha/Beta
credentials exercise every batch read/download and event access through actual
HTTP and direct service/store methods, plus rotation/legacy/permissions/signatures/
collisions/quotas. [JUnit](../../t07-full.xml), [execution](../../TEST_EXECUTION_REPORT.md).
Remaining limits: business-level credentials, trusted Python/config operators,
single process/in-memory state; no user login/database/distributed or remote MCP
identity. This is verified resolution within that scope, not full production
security certification.

## QA-002 — External ingestion/webhooks absent

**Resolved in T06; retained.** Generic direct/HMAC ingestion and status exist.
T07 extends configured integrations/ownership, without vendor-specific adapters,
durable queues or exactly-once delivery. All regressions pass; no live external
webhook or additional Groq request occurred.

## QA-003 — Incomplete ingress/resource controls

**Resolved for single-instance T06 scope; extended in T07.** Actual-byte caps,
early auth, upload admission, global rate/deadline/model limits and bounded webhook
workers/store remain. T07 adds verified per-owner headroom and quotas. The approved
4 MiB JSON 413 policy remains intentional; the old accepted2 MiB case is retained,
not evidence of unlimited bytes. Invalid signatures cannot reserve tenant/model/
queue quota; pre-HMAC intake still needs global caps. No transport-wide DoS or
distributed fairness guarantee. Deployment controls remain under QA-006.

## QA-004 — Live acceptance incomplete

**Earlier HIGH acceptance gap; single T01 prerequisite VERIFIED; broader scope OPEN.**
Prior one synthetic direct service call: openai/gpt-oss-20b, HTTP 200, native strict,
Pydantic/exact evidence pass, 1.4903 s/1,371 tokens. No live T07, HTTP/webhook/selector/
graph/chat/MCP/batch or broad accuracy/security acceptance is claimed. Further
paid checks need authorization. [Prior unchanged report](../../LIVE_GROQ_VERIFICATION_REPORT.md).

## QA-005 — Explicit blank batch source accepted

**Resolved before T06; retained unchanged.** FastAPI optional form extraction
substituted its default before Pydantic. Existing raw-form blank guard rejects
empty/whitespace source 422; omission defaults file_upload and valid nonblank labels
<=64 remain accepted. No T07/T08 source-validation change. Original audit210/209/1,
focused1 passed, remediation220 passed, T06 330 passed; T07 447 passed; current571 all pass.
[Original root cause and fix evidence](../../QA005_REMEDIATION_REPORT.md).

## QA-006 — Repository/production operation unverified

**MEDIUM operational; OPEN.** Git mount unavailable/untouched; no Git command,
repair, bypass, deployment or provenance verification. Production TLS/proxy/
header/connection/process/resource/monitoring/recovery policies remain unverified.
In-memory jobs/events/deduplication lose state on restart, including config rotation;
multiple workers do not coordinate. Files are available now; cross-managed-session/
container retention is unverified. Resolve via supported environment/release work.

## QA-007 — Gmail implementation and external acceptance

**Originally MEDIUM missing scope; implementation RESOLVED locally in T08;
Google live/Cloud/approval acceptance OPEN.** Seven typed endpoints, readonly
state/PKCE OAuth, authenticated mailbox/owner binding, temporary token refresh,
filtered imports, safe MIME, shared T01, owned results, bounds/dedup/cleanup now
exist.124 Gmail cases plus447 retained baseline all pass. Foreign/unknown jobs404,
mailbox conflict409, service/store permission/proof checks and owner quotas pass.
No real Google OAuth/Gmail request or extra Groq request occurred. Cloud enablement,
consent/test users/client/redirect setup, real web-client PKCE/token/profile/message
behavior and restricted-scope verification/security assessment are unverified.
Business authorization of selected-text transfer to Groq and user-data-policy
review are required. Do not treat mocks as production Google approval.

Intentional limits: skip entire attachment-bearing messages before body data;
explicit bounded imports only, no polling. Tokens/claims/jobs/dedup are RAM-only
and disappear on restart. Encrypted production credential storage/lifecycle needs
future authorized design. Local disconnect does not revoke Google's grant.
[Gmail guide](../../../GMAIL_INTEGRATION.md), [T08 report](../../T08_IMPLEMENTATION_REPORT.md).

## QA-008 — Documentation stale

**Resolved for current scope.** README, AGENTS, .env.example, architecture, pattern,
webhook/MCP guides and QA reports now describe verified owner isolation, legacy/
production policy, quotas, rotation/restart limits and service authentication.
TENANT_ISOLATION.md supplies private placeholder setup and verification guidance.
Original and milestone history remain archived.

## QA-009 — Optional assurance incomplete

**LOW verification limitation; OPEN.** Coverage, Ruff, mypy and advisory scans
remain unperformed/uninstalled. uv pip check confirms73 installed packages are
compatible, not vulnerability-free. No unnecessary dependency was added.

**Release NOT READY. T08 locally complete; T09 needs separate authorization and was not started.**


T08 extension: QA-001 verified ownership now covers connection/job/results and
mailbox conflicts, using three new explicit permissions and bound worker principals.
QA-003 covers Gmail state/token/job/HTTP/response/MIME/dedup quotas and deadlines,
preserving global/per-owner model budgets. QA-006 also requires production OAuth
storage/lifecycle and proxy query-log review. QA-008 docs now include Gmail setup,
privacy and external Google gates. No earlier unresolved issue is removed.
[Current571-case evidence](../../t08-full.xml), [security review](../../SECURITY_REVIEW.md).
