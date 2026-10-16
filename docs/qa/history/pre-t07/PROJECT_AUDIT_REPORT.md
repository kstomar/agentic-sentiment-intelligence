# Project audit — T06 follow-up

Date: 2 November 2026, Asia/Kolkata. **T06 IMPLEMENTED; release NOT READY.**
This report supersedes current-state claims in the [pre-T06 assessment](../pre-t06/PROJECT_AUDIT_REPORT.md).
The [original audit](../original-audit/PROJECT_AUDIT_REPORT.md), QA-005
remediation and earlier single-live-Groq evidence remain retained.

## Implemented scope

T00–T05 remain implemented. T06 adds authenticated POST /api/v1/ingest/feedback,
HMAC-signed POST /api/v1/webhooks/feedback, and authenticated development/admin
GET /api/v1/ingest/events/{delivery_id}. Thin REST adapters delegate to a
transport-independent IngestionService and the same application-owned T01
SentimentService. There is no new classifier, prompt, graph, MCP server/tool,
provider integration, database, queue dependency or frontend.

Webhook admission authenticates original bytes, validates typed payloads, checks
local provider readiness, atomically reserves integration+delivery and queues
bounded work before 202. Two fixed workers, 20 pending slots, 100 retained
reservations, 60-second event deadlines, terminal 1,800-second TTL and cleanup
bound execution. Exact-body SHA256 excludes timestamps for retries. Identical
authenticated duplicates return 200; conflicts return 409. Status exposes no
feedback/results. Raw requests are dropped on termination and shutdown.

The ASGI guard authenticates REST before intake, checks actual bytes/chunks,
preserves HMAC bytes and FastAPI validation, and enforces bounded concurrency,
rolling rate and read deadlines. One shared four-operation model budget covers
REST classifier and selector calls, including graph/chat/batch/webhook consumers.
Existing batch two-permit/three-job bounds and separate MCP two-call bounds remain.

## Evidence

**330 collected; 330 passed; zero failures, skips or errors; 8.894 seconds**.
All 220 baseline cases remain and 110 meaningful T06 cases were added. The two
existing route inventory checks now include the three authorized endpoints and
separate HMAC security scheme. No baseline assertion was skipped or weakened.
FastAPI startup/imports, Pydantic evidence validation, all four LangGraph paths,
CSV/XLSX/report lifecycles and official MCP in-process/stdio checks pass.

Python 3.12.16, uv 0.13.6, official MCP 2.3.0. Locked offline sync resolves 77
packages; all 73 installed packages pass uv pip check. pyproject.toml and uv.lock
are unchanged. [JUnit](../../t06-full.xml), [OpenAPI](../../openapi.json),
[compatibility evidence](../../t06-compatibility.json), [test report](../../TEST_EXECUTION_REPORT.md).

## Security and compatibility

QA-002 external ingestion gap and QA-003 demonstrated ingress/resource defects
are resolved for the documented single-instance scope. QA-005 remains resolved.
QA-001 missing tenant ownership remains HIGH and belongs to T07. One development
API key is not principal/tenant authentication; one configured HMAC integration
is not a multi-business account system. Per-business quotas and deployment-level
resource/auth/TLS policy remain outstanding.

Existing request/success schemas, defaults and allowlists are unchanged. Three
routes, additive ErrorCode values, HMAC security and documented error responses
were added. The user approved the intentional compatibility change: JSON above
4,194,304 actual bytes now returns 413. Existing 2 MiB compatibility and Unicode
within cap pass. Webhook 16 KiB and multipart 2 MiB file limits remain distinct.
New global overload 429/read-timeout 408 policy is documented.

The previous single live T01 request was VERIFIED (HTTP 200, strict output,
validated evidence, 1.4903 s, 1,371 tokens); T06 made zero live requests. Broader
live interfaces/model quality are not verified. No external webhook was sent.

## Remaining delivery limitations

T07 tenant ownership/accounting, Gmail scope/implementation, production deployment,
TLS/proxy/header/connection limits, operational acceptance and Git release handoff
remain unresolved. No Git command or mount modification occurred. File presence
is confirmed now; retention across managed-session/container restart is unverified.
Events/jobs are single-process, temporary and nondurable; no distributed or
exactly-once promise exists. Coverage, Ruff, mypy and advisory scanning were not
run or installed. See [known issues](../../KNOWN_ISSUES.md) and
[release decision](../../RELEASE_READINESS_REPORT.md). T07 may begin only as separately
authorized work; it was not started.
