# Release readiness — T07

2 November 2026. Decision: **NOT READY** for full release.
**T07 complete in its documented single-process business API scope. T08 may begin
as separately authorized work; it has not been started.**

| Area | Current evidence |
| --- | --- |
| T00 | Python 3.12.16/uv 0.13.6; locked offline sync and compatibility pass |
| T01 | Existing strict classifier; prior one synthetic live smoke verified; no new live request |
| T02/T03 | Existing graph/chat pass, with verified API policy and owner model/graph quotas |
| T04 | Owner-scoped jobs/status/report/results/download and expiry pass; QA-005 still resolved |
| T05 | Official MCP 2.3.0 in-process/stdio pass; trusted launcher, stateless only |
| T06 | HMAC/raw bytes/time, worker lifecycle/global ingress and idempotency retained |
| T07 | Bounded registry, verified principals/permissions, owner stores, tenant-bound integrations and quotas verified |
| QA-001 | RESOLVED for business API/service/store scope with distinct credential tests |
| Gmail | NOT_IMPLEMENTED; delivery inclusion/deferral unresolved |
| Git/deployment | Blocked/unverified; mount untouched, no Git command or deployment |

## Verification gate

**447 collected; 447 passed; 0 failed, 0 skipped, 0 errors; 11.461 seconds (console 11.46 s), exit 0.**
All 330 baseline cases and 117 new security cases pass. No assertion weakened,
removed or skipped. Existing direct-service fixtures now authenticate explicitly.
[JUnit](../../t07-full.xml), [console](../../t07-pytest-output.txt),
[execution report](../../TEST_EXECUTION_REPORT.md), [security scope](../../SECURITY_REVIEW.md).
Locked offline sync77resolved; all 73 installed packages compatible. Dependency
files and existing request/success contracts unchanged; new 403/tenant quota/
collision policy and configuration restrictions are documented.

QA-001 and the earlier QA-002/QA-003/QA-005 findings are resolved in their stated
scopes. This does not establish exhaustive application/infrastructure security,
user-level login, database isolation, or distributed authorization. Production
rejects legacy fallback; a deployment still must provision real private registry
credentials and verify supported operation. No real tenant keys were created here.

## Remaining release gates

- QA-006: supported Git/provenance/release handoff and production deployment,
  TLS/proxy/header/connection/process/resource limits, monitoring and recovery.
- QA-004: wider live/interface/model-quality acceptance remains unverified. Prior
  one direct T01 request passed HTTP 200/native strict/Pydantic/evidence,1.4903s,
  1,371 tokens. T07 made zero additional calls; further paid checks need separate
  authorization. No external webhook or production authentication deployment tested.
- QA-007: explicitly include/defer Gmail. No Gmail adapter, login, tokens or messages
  were implemented. Frontend is outside the API-only scope.
- QA-009: optional coverage/static/advisory assurance remains unperformed; dependency
  compatibility is not CVE clearance. Decide/authorize desired additional tools.

All jobs/events/quotas are single-process, nondurable and independent across
processes. Restart/reload/config rotation loses queued work/results/deduplication;
no exactly-once guarantee. Use one ASGI worker. Existing files are present now;
managed-session/container restart persistence remains unverified. Local MCP has
no remote tenant authorization or owned lookup. No database, distributed identity,
user login, frontend, Gmail, deployment or T08 feature was added.

Passing these mocks resolves the demonstrated ownership issue, not the remaining
operational/acceptance gates. [Known issues](../../KNOWN_ISSUES.md) retain those blockers;
[T06 decision](../pre-t07/RELEASE_READINESS_REPORT.md) remains preserved.
