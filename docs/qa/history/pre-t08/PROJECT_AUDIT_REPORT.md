# Project audit — T07

2 November 2026, Asia/Calcutta. **T07 IMPLEMENTED; release NOT READY.**
The [T06 assessment](../pre-t07/PROJECT_AUDIT_REPORT.md) and original audit findings
remain archived. This report describes the current business API boundary.

T00–T06 remain implemented. T07 adds a bounded environment-configured credential
and integration registry, immutable verified Principal, seven explicit permissions,
owner-scoped batch/event storage and per-business request/processing/retention
quotas. It introduces no public endpoint, user login, database, frontend, Gmail,
provider client, prompt, graph, remote MCP or new dependency.

API credentials map to server-owned businesses. A request field, business_type,
CSV value, review ID, model output or arbitrary header never selects authority.
Every protected REST operation authenticates and authorizes before work. Batch
creation and all four read paths enforce ownership in services/stores; direct
Python calls also need a verified principal or authenticated context. Inspection
maps are owner-filtered; global maintenance is private. Foreign and unknown IDs
have the same 404 response. Signed integrations bind to configured tenants;
status keys tenant+delivery, while idempotency also checks integration/digest.
Same-tenant cross-integration delivery collisions409; separate tenants may reuse IDs.

Legacy APP_API_KEY/single webhook belong only to development. Production always
disables them. With a business registry, nonproduction compatibility requires
explicit opt-in. Registry validation rejects ambiguity, duplicate secrets/IDs,
unknown integration owners and unsafe capacity configurations. Secrets stay masked
even in structured Pydantic error diagnostics. Configuration rotation preserves
owner semantics but requires restart, losing all temporary state.

## Verification

**447 collected; 447 passed; 0 failed, 0 skipped, 0 errors; 11.461 seconds (console 11.46 s), exit 0.**
All 330T06 baseline cases remain and 117 new T07 cases pass. Tests demonstrate
cross-business HTTP/service/store denials, valid owner access, rotation/revocation,
permissions, legacy containment, HMAC owner mapping, collision/idempotency isolation,
model/graph/batch/webhook/rate quotas and cancellation/deadline/expiry release.
Existing FastAPI imports/startup, strict adapter/Pydantic/evidence checks, all four
LangGraph paths, CSV/XLSX/reports and official MCP in-process/stdio checks pass.

Python 3.12.16 / uv 0.13.6 / official MCP 2.3.0. Locked offline sync resolves77 packages;
all 73 installed packages pass compatibility. pyproject.toml/uv.lock are unchanged.
Existing12paths, request parameters/bodies, success schemas and previous responses
are preserved. New403 declarations, three additive error codes, security-description
and status-summary updates reflect the new policy. No tenant field was added to
AI inputs/results. [JUnit](../../t07-full.xml), [compatibility](../../t07-compatibility.json),
[complete report](../../T07_IMPLEMENTATION_REPORT.md).

## Findings and readiness

QA-001 is RESOLVED for the documented business API/service/store scope, with real
cross-credential tests. QA-002/QA-003/QA-005 remain resolved in their documented
scopes. No demonstrated HIGH security finding remains open from that audited set;
this is not exhaustive security certification. QA-004's broader live acceptance,
QA-006 Git/deployment handoff, QA-007 Gmail scope and QA-009 optional assurance
remain open. Prior single-live-T01 verification remains narrowly VERIFIED; this
task made zero additional live requests.

In-memory state/counters are single-process, not durable/distributed. No user-level
or database isolation is claimed. MCP remains stateless trusted-launcher analysis,
without owned lookup/tenant arguments/remote authorization. Files are available
now; cross-managed-session/container persistence is unverified. Git mount untouched,
no Git commands/deployment performed. T08 may begin as separately authorized work;
it was not started. [Release decision](../../RELEASE_READINESS_REPORT.md).
