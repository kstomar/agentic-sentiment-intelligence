# Project audit report

## Executive summary

**Release decision: NOT READY** for the complete requested 6 November 2026 scope.
T01–T05 work in the executed offline/mock scenarios, but required T06 ingestion
and signed webhooks are absent, multi-business ownership is absent, live Groq
verification is blocked, public REST resource controls are incomplete, and one
batch validation contract test fails. No production code was fixed in this audit.

The audit inspected **45 application modules / 3021 source lines**, all existing
project documentation, pyproject.toml, uv.lock, authentication, configuration,
logging, storage, and actual installed SDK interfaces. The generated source
inventory lists each file, definitions, line numbers, and SHA-256 digest. Existing
feature claims were checked against actual files rather than prior completion
reports. Before this task, there were no permanent automated tests.

## Implementation status

Implementation columns use IMPLEMENTED, PARTIALLY_IMPLEMENTED, NOT_IMPLEMENTED,
BLOCKED, or NOT_APPLICABLE. Verified=IMPLEMENTED means executed local verification
supports the stated scope; it is not a live provider/security certification.

| Feature | Expected | Implemented | Verified | Missing/issues |
| --- | --- | --- | --- | --- |
| T00 Python/uv/local environment | Yes | IMPLEMENTED | IMPLEMENTED | Locked environment reproduced; Git separately blocked |
| T01 sentiment API | Yes | IMPLEMENTED | PARTIALLY_IMPLEMENTED | Local service/adapter/API verified; live model/account/accuracy blocked |
| T02 LangGraph investigation | Yes | IMPLEMENTED | PARTIALLY_IMPLEMENTED | All four routes and evidence gates verified with mocks; live selector unverified |
| T03 conversational API | Yes | IMPLEMENTED | IMPLEMENTED | Two modes, service reuse, stateless behavior verified locally |
| T04 CSV/XLSX bulk/reporting | Yes | IMPLEMENTED | PARTIALLY_IMPLEMENTED | Jobs/reporting/limits/TTL verified; blank-source contract defect remains |
| T05 local stdio MCP | Yes | IMPLEMENTED | IMPLEMENTED | Official client discovery/invocation, schema/error/cancellation/stdio verified with mocks |
| T06 external REST ingestion | Yes | NOT_IMPLEMENTED | NOT_APPLICABLE | Endpoint and ingestion service absent |
| T06 signed webhooks | Yes | NOT_IMPLEMENTED | NOT_APPLICABLE | Signing/replay/worker/status components and documentation absent |
| Multi-business isolation | Planned | NOT_IMPLEMENTED | NOT_APPLICABLE | Shared development key, no authenticated principal/owned jobs |
| Gmail | Planned | NOT_IMPLEMENTED | NOT_APPLICABLE | Package stub only; delivery-scope decision required |
| Frontend | Optional | NOT_IMPLEMENTED | NOT_APPLICABLE | API-only project; no frontend needed for current core scope |

`LIVE_GROQ_VERIFICATION = BLOCKED` and
`MULTI_TENANT_ISOLATION = NOT_IMPLEMENTED` are explicit audit conclusions.

## Technology stack

Python 3.12.16, uv 0.13.6, FastAPI 0.162.0,
Pydantic 2.14.2, Groq 0.37.1,
langchain-groq 1.1.3, LangGraph 1.2.18,
Pandas 3.1.0, openpyxl 3.1.5,
HTTPX 0.28.1, python-multipart 0.0.32,
and official MCP SDK 2.3.0. pytest/pytest-asyncio were added only after explicit
user approval. No system software, standalone FastMCP, queue framework, or new
production dependency was introduced. SQLite is a reserved metadata setting,
not a currently used store.

## Architecture and reusable services

Thin FastAPI adapters call `SentimentService.analyze`,
`InvestigationService.investigate`, `ConversationService.respond`, and the batch
service. The REST lifespan owns shared HTTP clients and passes the same T01
instance into investigations and batch workers. MCP has a separate stdio process
lifespan using those same constructors and service implementations. MCP does not
call our REST endpoints or mount a network listener.

T01's ChatGroq adapter requests strict json_schema output for the two explicitly
supported GPT-OSS model IDs. Pydantic revalidates output and checks every quoted
phrase against original text. Async wall-clock deadlines include retry/backoff;
permanent credentials/configuration failures do not retry.

T02 compiles one acyclic StateGraph: select a validated question-only action,
analyze supplied records via T01, conditionally aggregate/retrieve evidence,
verify, then generate deterministic insights and validate/reverify the response.
There is no checkpoint/cache, tool-feedback-to-selector edge, or arbitrary tool
execution. All four conditional paths were tested. T03 delegates by explicit
mode with current payload and adds neither graph nor formatter model call.

T04 independently maps each valid CSV/XLSX row through T01, then reduces in
Python/Pandas. The parser validates mappings/IDs/dates and bounds input/archive
resources. Jobs have one sequential worker each, shared batch permits, bounded
active/retained capacity, whole-job deadlines, partial failure reporting, fatal
configuration/auth latch, and terminal TTL. Source/issue/aspect/evidence metrics
are deterministic and reconciled. Job IDs are opaque, not authorization tokens.

T05 registers only analyze_feedback and investigate_feedback. Full request models
validate raw arguments before SDK parsing; typed Pydantic results become SDK
structured content. The call boundary preserves safe application error codes
through SDK wrappers, and per-instance admission rejects excess active calls.

## API and schemas

Nine HTTP operations exist: public `/health`; authenticated sentiment,
investigation, chat; and five batch upload/status/report/results/download routes.
See [API contract report](API_CONTRACT_REPORT.md) for full inventory, request and
response models, errors, and the reproduced inconsistency. Existing OpenAPI was
compared exactly with the pre-audit snapshot and did not change.

## Authentication, data, and logging

REST uses constant-time comparison against one development X-API-Key. There is
no principal identity or tenant ownership. MCP trusts the launching local process
and deliberately excludes batch lookup. These choices support a local development
workflow but not multi-business isolation.

Batch inputs/results live in process memory. Raw mapped text is cleared as rows
settle and removed at terminal completion; derived reports/results expire after
configured TTL. Idle expiry, lazy lookup expiry, parse cancellation, worker
shutdown, and spooled-upload closure were tested. Original uploads/exports are
not permanently copied; framework spooling may briefly use temporary disk.
Reload/restart loses jobs, and multi-worker consistency is not implemented.

Known codes/request IDs are logged without feedback/provider bodies; provider
logging/tracing is restricted. Mock sentinels did not leak through tested HTTP,
MCP, or captured logging paths. Derived quotes and summaries remain sensitive,
and clients may retain copies outside server retention.

## Documentation, tests, and missing components

Reviewed README, AGENTS, architecture, agentic patterns, MCP instructions, and
.env.example. No webhook document exists. Zero broken local Markdown targets were
found. Historical scope language and mixed planned/implemented responsibility
entries need clarification; production documentation was not silently rewritten.

Created 19 automated test modules plus fixtures/helpers/subprocess bootstrap and
pytest.ini, covering unit, REST integration, security characterization, MCP
protocol, and bounded performance checks. Final execution: **210 collected,
209 passed, 1 failed, 0 skipped/errors**, 17.732 seconds.
Coverage is not measured. Missing T06/Gmail/tenant features are explicitly listed,
not represented by fake passing tests. [Known issues](KNOWN_ISSUES.md) records nine
findings/gaps with severities and recommended fixes.

All 45 original application files are byte-identical to the pre-audit snapshot.
Only preexisting pyproject.toml/uv.lock changed, for the approved dev dependencies.
New files are test and QA artifacts. `.git` is empty/read-only and no Git command
was run. Files can be reopened within this environment; host/session-restart
persistence is not established.
