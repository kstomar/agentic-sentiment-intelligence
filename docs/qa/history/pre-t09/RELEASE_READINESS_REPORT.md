# Release readiness — T08

2 November 2026. **Release decision: NOT READY. T08 locally complete with mocks.**
T09 may begin only when separately authorized; it was not started. Passing the
implementation suite does not verify Google Cloud setup, live OAuth/Gmail,
restricted-scope approval or deployment. [Prior decision](../pre-t08/RELEASE_READINESS_REPORT.md).

| Area | Evidence |
| --- | --- |
| T00 | Python3.12.16/uv0.13.6, locked offline sync and compatibility pass |
| T01 | Strict classifier unchanged; prior single synthetic live smoke verified; no new live call |
| T02/T03 | Existing graph/chat and principal/model/graph quotas pass |
| T04 | All owner-scoped batch reads/reports/downloads and original QA-005 regression pass |
| T05 | Official MCP2.3.0 in-process/stdio pass; two local stateless tools |
| T06/T07 | HMAC, global ingress, verified registry/owners/permissions and quotas retained |
| T08 | OAuth/state/PKCE, mailbox identity, readonly filtered imports, MIME, owner results, refresh/dedup/cleanup verified with mocks |
| Gmail live/Google approval | NOT VERIFIED; Cloud setup and separate live authorization required |
| Git/deployment | Blocked/unverified; mount untouched and no Git/deployment action |

**571 collected/passed; 0 failed/skipped/errors; 18.286 seconds JUnit**. All447
baseline case IDs retained plus124 new Gmail cases. No assertion weakened or skipped.
[Tests](../../TEST_EXECUTION_REPORT.md), [JUnit](../../t08-full.xml),
[compatibility](../../t08-compatibility.json), [security review](../../SECURITY_REVIEW.md).
77 packages resolve offline, all73 installed compatible; dependency files unchanged.
All12 previous OpenAPI operations identical; seven new Gmail operations,21 error
codes and three permissions are additive. Private responses/logging gain documented
privacy protections.

## Remaining gates

- **QA-007 external Gmail acceptance:** missing implementation is resolved locally.
  Google Cloud API/consent/test-user/client/registered redirect setup, real web-client
  state/PKCE/code exchange, actual profile/message fields, refresh/revocation and
  restricted-scope verification/security assessment are NOT VERIFIED. Authorize
  appropriate testing separately; no real Google request was permitted in T08.
  Business approval of selected email-text transfer to Groq and Google user-data
  policy review are required; no compliance/production approval claim.
- **QA-006 operational handoff:** supported Git/provenance/release handoff, deployment,
  TLS/proxy/header/query logging/connection/process/resource controls, monitoring
  and recovery remain unverified. Production needs an approved encrypted OAuth
  credential storage and lifecycle/persistence design; T08 intentionally uses RAM.
- **QA-004 wider live acceptance:** only the earlier direct T01 smoke is verified,
  HTTP200 native strict/Pydantic/evidence,1.4903s/1,371tokens. Broader HTTP/graph/chat/
  batch/webhook/MCP/Gmail model-quality/end-to-end acceptance is unverified. No
  additional inference performed; paid checks require separate authorization.
- **QA-009 optional assurance:** coverage/Ruff/mypy/advisory scans remain unrun.
  Compatibility is not vulnerability clearance or exhaustive security certification.

QA-001/002/003/005 remain resolved in their stated scopes and extend to mocked
Gmail ownership/admission. No demonstrated open HIGH security issue from the
original scoped pair; external approval/deployment are still blocking gates.

Known intentional limits: attachment-bearing messages skipped before body data;
one process/one ASGI worker; memory-only tokens, jobs, results, ownership and dedup;
restart loses everything, no exactly-once/distributed history. Disconnect clears
local state but does not revoke Google's grant or undo already issued operations.
No scheduler, sending/deleting/label mutation, frontend, database, new graph or T09.
Files are available now; cross-session/container retention remains unverified.
[Known issues](../../KNOWN_ISSUES.md) retain all unresolved findings/history.
