# Release readiness — T06

Date: **2 November 2026**. Decision: **NOT READY** for the full delivery.
**T06 is complete with mocked integration verification. T07 can begin as a
separately authorized milestone; it has not been started.**

| Area | Evidence-based status |
| --- | --- |
| T00 | Python 3.12.16 / uv 0.13.6; reproducible locked offline sync and compatibility pass |
| T01 | Implemented; prior one-case live Groq strict/output/evidence verified; broad quality unverified |
| T02 | Implemented; four bounded graph paths and shared model budget verified with mocks |
| T03 | Implemented; both explicit stateless modes pass |
| T04 | Implemented; CSV/XLSX/jobs/reports/TTL pass; QA-005 remains resolved |
| T05 | Implemented; official SDK 2.3.0 in-process and stdio checks pass; local launcher authority only |
| T06 | Implemented; direct ingestion, HMAC trigger, duplicate/replay, fixed workers/status, ingress/admission verified offline |
| T07 tenant ownership | NOT_IMPLEMENTED; QA-001 HIGH remains open |
| Gmail | NOT_IMPLEMENTED; inclusion/deferral remains a scope decision |
| Frontend/remote MCP | Not implemented, outside this task |
| Git/deployment handoff | Blocked/unverified; mount untouched; no Git commands |

## Functional and security gates

**330 collected; 330 passed; zero failed/skipped/errors; 8.894 seconds.**
All 220 previous cases plus 110 new T06 cases pass. Dependency files unchanged;
77 locked packages resolve offline; 73 installed packages pass compatibility.
See [execution evidence](../../TEST_EXECUTION_REPORT.md) and [JUnit](../../t06-full.xml).

QA-002 required T06 feature gap is resolved. QA-003 demonstrated application
JSON/intake/model/rate controls are resolved for one process. QA-005 remains
resolved. QA-001 ownership remains HIGH. Deployment-level resource/TLS/header/
connection policy, process-level limits and real acceptance are unverified.
Global quotas are not per-business quotas or fair scheduling.

Approved intentional contract change: actual JSON above4,194,304 bytes now413;
old request/success schemas remain unchanged, with three added routes/HMAC/error
codes/declarations. New global 429/read-deadline 408 behavior is documented.
No new dependency, model client, prompt, graph, MCP tool or database was added.

## Live inference and operational limits

LIVE_GROQ_VERIFIED remains scoped to the earlier one synthetic direct T01 service
request: HTTP 200, strict output/Pydantic/evidence pass, 1.4903 s, 1,371 tokens.
No additional provider or external webhook request occurred in T06. Live HTTP,
webhook/graph/chat/MCP/batch inference and broad/adversarial model quality remain
unverified. Further paid acceptance needs separate authorization.

Jobs, webhook queues, reservations and limits are single-process, nondurable and
not distributed. Restart/reload loses work/deduplication; no exactly-once promise.
Run one ASGI worker. File presence is verified now; persistence across managed
session/container restart remains unverified. No Git repair/bypass/deployment was
attempted. Coverage, Ruff, mypy and CVE scanning are unperformed.

## Remaining release gates

1. T07: trusted business/principal identity, integration ownership mapping,
   service/store authorization, cross-business tests, revocation and fair quotas.
2. Resolve supported Git/release provenance and verify intended deployment,
   TLS/proxy/resource policies, startup/shutdown/restart handling and monitoring.
3. Define wider live integration/accuracy acceptance with separate authorization.
   Preserve one-call T01 evidence without claiming it verifies every interface.
4. Explicitly include or defer Gmail and any remaining delivery scope; no Gmail
   support is delivered by T06.
5. Decide optional quality/advisory/coverage gates and authorize tools if desired.

Passing mocks does not clear these gates. The release remains NOT READY.
[Pre-T06 decision](../pre-t06/RELEASE_READINESS_REPORT.md),
[original audit](../original-audit/RELEASE_READINESS_REPORT.md) and
[known issues](../../KNOWN_ISSUES.md) preserve unresolved history. Stop after T06;
this report is not authorization to implement T07 or deploy.
