> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Final project summary

## 1. Project title

**Agentic AI Sentiment Analysis & Customer Feedback Intelligence API**.
Prepared2 November2026 (Asia/Calcutta); communicated deadline6 November2026.
Submission scope is API-only and provisional: the original reviewer assignment
remains unavailable. Deployment and frontend are excluded from the communicated
reviewer scope. No claim of definitive original-reviewer compliance is made.

## 2. Problem statement

Customer feedback arrives as individual reviews, uploaded files and external
messages. Unstructured text makes it difficult to compare sentiment, identify
recurring complaints and trace an insight to the feedback supporting it. This
backend turns selected feedback into typed analysis and deterministic reports
while restricting access and temporary retention by business.

## 3. Objectives

Provide reusable APIs, meaningful bounded agentic investigation, structured
sentiment/aspect/issue extraction and useful aggregate insights. Apply relevant
patterns from the mandatory catalogue in actual code. Demonstrate functionality
with synthetic, reproducible API/protocol checks and distinguish model-generated
classifications from verified calculations and provider acceptance evidence.

The latest audit found six supplied provisional core items implemented and locally
verified, with no demonstrated missing core feature. These are the user's planning
requirements, not independently recovered reviewer wording. See
[traceability](REQUIREMENTS_TRACEABILITY_MATRIX.md) and
[source provenance](REQUIREMENTS_SOURCE_RECORD.md).

## 4. Technologies

Python3.12.16 and uv0.13.6; FastAPI/Uvicorn; Pydantic v2/pydantic-settings;
Groq through langchain-groq with openai/gpt-oss-20b; LangGraph; official MCP SDK2.3.0;
HTTPX; Pandas, Python CSV and openpyxl; pytest/pytest-asyncio for offline verification.
pyproject.toml and uv.lock define the reproducible environment. SQLite is only a
reserved configuration/architecture option: no database persistence is implemented.
No new package was added for submission preparation.

## 5. System architecture

Thin versioned REST routes feed shared transport-independent services. Verified
principals and global/owner limits protect work before body intake and sensitive
store operations. The same T01 sentiment implementation supports direct REST,
LangGraph, chat, file jobs, generic ingestion and Gmail. Local stdio MCP uses the
same service implementations in its own process/lifespan, not cross-process object
sharing. Stores and counters are bounded process-local memory.
[Architecture walkthrough](ARCHITECTURE_WALKTHROUGH.md).

## 6. Agentic AI workflow

A model interprets the current question into one allowlisted action with validated
arguments. A compiled StateGraph runs independent feedback analysis, deterministic
counts, branch-specific issue/evidence tools, validation and final prose. It selects
and executes meaningful operations conditionally; it is not just a sentiment
endpoint renamed an agent. No unbounded autonomous loop, checkpoint or memory.

## 7. Groq sentiment analysis

T01 accepts nonblank feedback up to5,000 characters, supported source and business
hints, and requests provider-native strict JSON-schema output. Pydantic revalidates
sentiment, aspects, primary issue, urgency, summary, suggested next step and exact
source evidence. No successful unvalidated/free-form fallback exists. Provider
errors, timeout/retry policy and safe diagnostics are centralized.

One historical synthetic T01 service request passed live: MIXED/product praise and
late delivery, HTTP200/native strict/Pydantic/exact evidence,1.4903s/1,371tokens.
[Recorded live evidence](../qa/LIVE_GROQ_VERIFICATION_REPORT.md). This package made
zero new live Groq requests. That one sample is not measured classification accuracy,
triage calibration or live verification of every interface.

## 8. LangGraph

One acyclic request-scoped StateGraph supports SENTIMENT_OVERVIEW, ISSUE_FREQUENCY,
EVIDENCE_SEARCH and GENERAL_FEEDBACK_SUMMARY. The selector receives only question
and business hint, not reviews/tool outputs. Up to ten records are analyzed
sequentially, with fail-fast behavior, bounded invocation/deadline and no persistent
state. Source IDs, quotations, filters, counts and final findings are rechecked.

## 9. MCP

Official SDK2.3.0 exposes only analyze_feedback and investigate_feedback over local
stdio. Official in-process and subprocess clients verify discovery, schemas,
invocation, structured results/errors and protocol-only stdout. Business logic is
shared with REST/T02; no second classifier or graph. Trusted-launcher authority
is distinct from REST business credentials. No remote transport or owned-resource
lookup is exposed; additional MCP reporting tools are not a confirmed reviewer mandate.

## 10. CSV/Excel processing

CSV/XLSX uploads validate mappings, IDs, formats, sizes, rows and text before bounded
background jobs. Each valid record uses T01 independently. Python/Pandas calculate
sentiment counts/percentages, issues, unique-record aspects and evidence references.
Status, partial failures, results, JSON reports and downloads remain visible. Raw
mapped text is cleared as processing finishes; terminal data expires after30minutes.
No PDF or Excel report export is claimed; XLSX input and JSON output are supported.

## 11. External REST and signed webhooks

Authenticated direct ingestion normalizes external metadata into T01. Generic
webhooks authenticate HMAC-SHA256 over exact original bytes plus integration,
timestamp and delivery headers before parsing. Time-window checks and atomic
owner/integration/digest reservations protect retries/conflicts; fixed bounded
workers expose temporary lifecycle status. No named commercial-platform connector,
durable queue or exactly-once delivery guarantee is implied.

## 12. Tenant isolation

A bounded private server registry issues immutable verified Principals with explicit
permissions. Caller/body business labels cannot select authority. Jobs, reports,
downloads, signed integrations/events and Gmail connections/results are owner-scoped
at routes and sensitive service/store boundaries. Foreign and unknown owned IDs
return the same404. Rotation keys share owner quotas; production rejects legacy
development credentials. There is no SaaS user-login/account-management interface.

## 13. Gmail

Optional readonly authorization-code OAuth uses S256 PKCE, single-use expiring
owner-bound state, fixed callback/Google hosts, exact scope and authenticated
getProfile identity before mailbox binding. Explicit imports select a configured
feedback label/date window with bounded pages/messages. Metadata preflight skips
whole attachment-bearing messages before body retrieval. Bounded plain text/inert
HTML feeds existing T01 with source=email; Gmail stays integration metadata.

Temporary owner results, deduplication, serialized refresh, disconnect and cleanup
are implemented.124 Gmail cases pass with mocked Google/inference. No live Google
account connection, Cloud setup or public restricted-scope approval was verified.
Selected email text would go to Groq in authorized live use; business authorization
and applicable Google data-use review are separate requirements.

## 14. API inventory

Nineteen application operations, all registered and locally verified:

| Surface | Operations |
| --- | --- |
| Health | GET /health |
| Sentiment | POST /api/v1/sentiment/analyze |
| Investigation | POST /api/v1/agent/investigate |
| Conversation | POST /api/v1/chat |
| Batch | POST /api/v1/batch/upload; GET /api/v1/batch/jobs/{job_id} and /report, /results, /download |
| Generic ingestion | POST /api/v1/ingest/feedback; GET /api/v1/ingest/events/{delivery_id} |
| Webhook | POST /api/v1/webhooks/feedback |
| Gmail | POST /api/v1/integrations/gmail/connect and /import; GET /oauth/callback, /status, /imports/{job_id}, /imports/{job_id}/results; DELETE /disconnect, all under the same Gmail prefix |

[Complete method/auth/schema/service/test inventory](API_FUNCTIONAL_COVERAGE.md)
and [fresh OpenAPI](submission-openapi.json). Framework documentation routes are
additional optional development endpoints, not extra business capabilities.

## 15. Automated testing and demonstration evidence

Fresh submission run: **571 collected/passed,0 failed/skipped/errors, 17.848s
JUnit (17.85s console)**. All571 prior case IDs retained; all124 Gmail cases included.
Nine independent offline workflows reran successfully using actual app/ChatGroq/
LangGraph/MCP code and mocked HTTP provider responses. CSV/XLSX results reconcile
to25% per sentiment, two delivery complaints and verified aspect/source counts.
Real loopback Uvicorn health, Swagger and19-path OpenAPI startup checks also pass.

[JUnit](submission-pytest.xml), [console](submission-pytest-output.txt),
[workflow evidence](submission-workflows.json), [startup](submission-startup.json),
[dependency checks](submission-dependencies.txt). Offline locked sync77resolved;
73 installed packages compatible. Model accuracy is unmeasured. Existing QA/test
history and production/dependency files are preserved; source packaging is separate.

## 16. Mandatory agentic patterns

The mandatory [awesome-agentic-patterns catalogue](https://github.com/nibzard/awesome-agentic-patterns)
is mapped to actual code/tests. Five core applications are verified: Structured
Output Specification, Action-Selector, shared dual-use stateless services,
independent LLM map/Python reduce and LLM-friendly API design. Three adaptations
are narrower: output grounding, generic authenticated webhook triggers and narrow
MCP capability exposure. Hybrid LLM/code coordination is a principle only, not a
switchable coordinator implementation. No whole-catalogue claim.
[Detailed independent mapping](AGENTIC_AI_VERIFICATION.md).

## 17. Known limitations

Original reviewer specification/rubric unavailable; this submission is provisional.
Gmail is mock verified, not live verified or publicly Google approved. One historical
live Groq sample does not establish broad model/selector accuracy or arbitrary
summary truthfulness. Urgency and recommendations are tentative model suggestions.

State/tokens/ownership/jobs/results/dedup live in one process; restart loses them.
No distributed/exactly-once or durable encrypted OAuth storage. Local disconnect
does not revoke Google's grant. Attachment-bearing emails are skipped. Chat is
stateless; MCP has only two local processors. Production hardening/deployment and
frontend are outside the communicated review scope. Files exist now; cross-session/
container persistence is unverified. [Gap register](REQUIREMENT_GAPS.md).

## 18. Conclusion

The existing API-only implementation is ready for a **provisional local reviewer
demonstration**, supported by reproducible tests and explicitly mocked integrations.
Definitive reviewer acceptance requires the original assignment and agreement on
its demo/quality standard. No new feature, production-code change, deployment,
frontend, live provider request or Git action was performed for this package.
[Demo script](FINAL_DEMO_SCRIPT.md), [technical Q&A](TECHNICAL_QA.md),
[submission checklist](FINAL_SUBMISSION_CHECKLIST.md).
