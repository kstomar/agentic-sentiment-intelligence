> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Final reviewer demo script

This is a **local, explicitly mocked demonstration** of the agreed API-only scope.
Original reviewer assignment unavailable; definitive compliance remains provisional.
The only real external-provider result shown is the previously recorded single
Groq service smoke. Do not make a new Groq or Google request for this presentation.

## Preparation and one-command replay

Use README's project-local Python/uv/cache exports; from the project root:

```bash
uv sync --locked --offline
uv pip check
.venv/bin/python docs/reviewer/verify_workflows.py
```

The existing verifier clears Settings environment variables, disables .env loading
in its process, fabricates credentials, blocks sockets/DNS/real HTTP transports and
supplies Groq/Google responses through MockTransport. It executes actual FastAPI
ASGI routes, ChatGroq strict schemas, LangGraph and official MCP. Its printed result
is “Reviewer workflows A–I:9 passed”; sensitive requests/headers are not printed.
It writes synthetic outcome/OpenAPI artifacts under docs/reviewer. Preserve historical
artifacts before a repeat if necessary; this preparation saved its rerun separately
as [submission-workflows.json](submission-workflows.json).

Fresh suite:571 passed,0 failed/skipped/errors,17.848s JUnit (17.85s console).
[Current evidence](submission-pytest.xml), [startup](submission-startup.json).
No real provider credential is required for the fixtures below. In pytest, the
autouse offline fixture clears configured fields and blocks real network transport.

The HTTP blocks below are the requests made by the local fixtures/replay, not
standalone live curl commands against a privately configured stock server. Header
values and state/code/job placeholders are filled by fixtures and must not be shown
as real credentials. JSON response examples are labeled subsets or controlled
fixture outputs; they are not newly generated live model responses.

The submission's presentation letters differ from the older audit workflow letters:
A is health; B–F map to audit workflows A–E; G/H/I map to audit G/H/I. Direct external
REST is additionally exercised by audit workflow F in the same replay.

## Demonstration A — Health and API inventory

**Purpose:** show executable application startup and public liveness.
**Configuration:** local Python/uv; no provider credentials. The test creates an
isolated app with explicit settings. A separate real Uvicorn loopback probe already
verified health, Swagger,19 OpenAPI paths and completed lifespan shutdown.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/security/test_authentication.py::test_health_public_and_missing_application_configuration tests/integration/test_api_contracts.py
```

**Request/expected response:**

```http
GET /health
```

```json
{"status":"ok"}
```

**What to say/prove:** “The app starts, all19 business operations register, and
health is public. OpenAPI schemas and route/service tests are available.” Inspect
[submission-openapi.json](submission-openapi.json) or Swagger in a separately
configured local test instance. Health is liveness, not provider readiness.
**Provider status:** no inference request; FULLY LOCAL. **Limit:** this is not
hosting/deployment acceptance. Stock README Uvicorn startup can load private .env;
use only health/docs there, and use the offline fixtures for analysis demonstrations.

## Demonstration B — Structured Groq sentiment analysis

**Purpose:** show schema-constrained sentiment, aspects, issue category, urgency,
summary, suggested next step and exact evidence through actual T01/adapter code.
**Configuration:** verifier/test fixtures provide fabricated key and MockTransport;
no real Groq credential or new external request.

**Exact commands:**

```bash
uv run --locked --offline pytest -q tests/unit/test_sentiment_service.py::test_actual_chatgroq_adapter_strict_schema_with_mock_http tests/integration/test_sentiment_api.py::test_sentiment_classifications
.venv/bin/python docs/reviewer/verify_workflows.py
```

**Unified replay request and controlled mock response:**

```http
POST /api/v1/sentiment/analyze
Content-Type: application/json
X-API-Key: <fabricated fixture credential supplied internally>

{"text":"Excellent quality but late delivery."}
```

```json
{
  "sentiment":"MIXED",
  "issue_category":"DELIVERY",
  "urgency":"LOW",
  "aspects":[
    {"name":"product_quality","sentiment":"POSITIVE"},
    {"name":"delivery","sentiment":"NEGATIVE"}
  ],
  "summary":"Customer praised quality and complained about delivery.",
  "suggested_next_step":"Review delivery feedback while preserving product quality.",
  "evidence_phrases":["Excellent quality but late delivery."]
}
```

**What to say/prove:** actual ChatGroq HTTP payload has json_schema/strict=true,
Pydantic validates it, and the quotation occurs exactly in the input. All four
sentiment classes have response-path tests. Display the prior
[live Groq report](../qa/LIVE_GROQ_VERIFICATION_REPORT.md) separately: one historical
real sample, HTTP200,1.4903s/1,371tokens, native strict/Pydantic/evidence passed.
**Provider status:** new demonstrations MOCKED; that prior evidence PREVIOUSLY LIVE
VERIFIED at service level. **Limits:** fixture labels do not measure model accuracy,
and the historical sample does not establish live HTTP or arbitrary-summary truth.

## Demonstration C — Agentic LangGraph orchestration

**Purpose:** show validated model-selected actions and meaningful conditional tools.
**Configuration:** actual compiled graph/T01, controlled strict selector/classifier
outputs. No live question interpretation is requested.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/unit/test_langgraph_workflow.py::test_all_four_conditional_routes tests/integration/test_investigation_api.py::test_investigation_rest_workflow_b
```

**Unified replay request for one branch:**

```http
POST /api/v1/agent/investigate
Content-Type: application/json
X-API-Key: <fabricated fixture credential supplied internally>

{
  "question":"ISSUE_FREQUENCY",
  "feedback":[
    {"id":"1","text":"Excellent product quality."},
    {"id":"2","text":"Delivery was very late."},
    {"id":"3","text":"The package arrived today."},
    {"id":"4","text":"Excellent quality but late delivery."}
  ]
}
```

The replay deliberately uses action-name questions to force each controlled
selector branch; these are valid question strings, not client commands granting
new tool authority. In normal use, a natural-language question is interpreted by
the configured selector, whose intent quality remains a separate model concern.

**Expected observed subset:** four sentiment counts1/1/1/1; DELIVERY issue count2
with feedback IDs2,4. tools_used includes analyze_feedback_items, aggregate_sentiment,
aggregate_issues, retrieve_evidence and generate_insights. Overview omits issue/
evidence tools; evidence-search runs retrieval without issue aggregation. Run all
four parametric cases and show [branch traces](submission-workflows.json).
**What it proves:** conditional selection/execution, shared analysis and grounded
counts. **Provider status:** MOCKED model outputs; REAL LangGraph. **Limits:** max
10records, request scoped, no checkpoint or autonomous replanning; no claim of live
selector accuracy. This is agentic orchestration rather than a renamed LLM wrapper.

## Demonstration D — Conversational API

**Purpose:** demonstrate both explicit stateless modes over the same services.
**Configuration:** existing mocked API fixtures; current feedback required.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/integration/test_chat_api.py
```

**Requests:** POST /api/v1/chat with the fixture API-key header and JSON:

```json
{"mode":"ANALYZE_TEXT","message":"Analyze this feedback","feedback_text":"Excellent product quality."}
```

```json
{"mode":"INVESTIGATE_FEEDBACK","message":"Which issues recur?","feedback":[{"id":"A","text":"Delivery was very late."}]}
```

**Expected response:** HTTP200; exactly the corresponding sentiment_analysis or
investigation branch is nonnull. Answers are composed deterministically from the
validated results; investigation findings are preserved. Missing current feedback
or history fields reject422 in tests. **What it proves:** proper service reuse and
mode-specific validation without another formatting model or graph. **Provider
status:** MOCKED. **Limits:** no memory or automatic intent detection is claimed.

## Demonstration E — CSV/Excel and reports

**Purpose:** upload, process and reduce multiple synthetic reviews into insights.
**Configuration:** existing multipart/parser/background fixtures and mocked T01.

**Exact commands:**

```bash
uv run --locked --offline pytest -q tests/integration/test_batch_api.py::test_upload_report_download_workflows_e_f tests/unit/test_reporting.py
.venv/bin/python docs/reviewer/verify_workflows.py
```

The unified replay creates CSV bytes and XLSX in memory from this safe dataset:

```csv
id,review
1,Excellent product quality.
2,Delivery was very late.
3,The package arrived today.
4,Excellent quality but late delivery.
```

**Requests:** POST /api/v1/batch/upload with multipart file=reviewer.csv or reviewer.xlsx,
text_column=review, id_column=id and the fixture key. Then GET
/api/v1/batch/jobs/{job_id}, /report, /results and /download using the returned ID.
The script generates/uploads the actual CSV/XLSX, fills IDs and awaits bounded jobs.

**Expected unified replay result:**202 PENDING → COMPLETED,4 successful records,
25% per sentiment, two delivery complaints, delivery/product_quality aspect counts2
each, package_arrival1, verified evidence and JSON download. The focused upload
regression additionally demonstrates PARTIAL_SUCCESS for one valid and one invalid
row. **What it proves:** independent record extraction plus deterministic map-reduce,
validations/progress, useful aggregates and downloadable JSON. **Provider status:**
MOCKED inference; REAL CSV/XLSX parsing and calculations. **Limits:**2MiB/100records,
30-minute terminal retention, no PDF/Excel output or durable queue.

## Demonstration F — Official MCP protocol

**Purpose:** demonstrate real discovery/invocation and shared typed services.
**Configuration:** official SDK2.3.0 and existing mock-service/stdio fixtures.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/integration/test_mcp_server.py::test_real_inprocess_protocol_workflows_g_h tests/integration/test_mcp_server.py::test_stdio_official_client_protocol_only_stdout_and_clean_shutdown
```

The tests use official Client.list_tools() then Client.call_tool(), including a
real subprocess stdio transport. Example tool arguments:

```json
{"text":"Excellent product quality."}
```

```json
{"question":"Which issues recur?","feedback":[{"id":"A","text":"Delivery was very late."}]}
```

**Expected result:** discovery contains exactly analyze_feedback and investigate_feedback;
structured result schemas match REST/T02. Valid mocked calls succeed; the separately
unconfigured real server returns controlled GROQ_NOT_CONFIGURED. Stdout validates as
MCP protocol only and shutdown is clean. **What it proves:** actual protocol support,
service reuse and safe errors. **Provider status:** MOCKED inference, REAL local
MCP. **Limits:** launcher-authorized stateless processors, no remote/owned reporting
lookup. Do not start a privately configured production MCP tool call for this demo.

## Demonstration G — Signed webhook

**Purpose:** authenticate original bytes, process feedback and deduplicate retries.
**Configuration:** fabricated registry integration secret held only inside fixture;
mocked inference, real HMAC/background workers.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/security/test_webhook_security.py::test_valid_raw_signature_no_rest_key_status_and_duplicate tests/security/test_webhook_security.py::test_body_tampering_and_duplicate_authentication_cannot_be_bypassed
```

**Payload/request:** POST /api/v1/webhooks/feedback with JSON bytes containing
customer.feedback.created and feedback{id,text}. X-Feedback-Integration-Id,
X-Feedback-Timestamp, X-Feedback-Delivery-Id and X-Feedback-Signature are signed
fixture headers; no REST key is required on this endpoint. The existing helper uses:

```python
canonical = f"{integration}.{timestamp}.{delivery}.".encode() + raw_body
signature = "sha256=" + hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
```

This is the exact algorithm; fixture code supplies the fabricated secret. Never
print it or reserialize the signed bytes. GET /api/v1/ingest/events/{delivery_id}
uses the owning tenant's API credential.

**Expected observed responses:**202 ACCEPTED, terminal200 with status COMPLETED,
then identical authenticated retry200 DUPLICATE and no second classification.
Tampered bytes/signatures reject401; valid changed-content conflicts409 are covered
elsewhere in the suite. **What it proves:** HMAC/replay/idempotency and actual worker
initiation. **Provider status:** MOCKED inference. **Limits:** generic signed adapter,
no named vendor delivery, nondurable single-process reservations.

## Demonstration H — Tenant isolation

**Purpose:** prove ownership beyond a guessed job ID or business-type hint.
**Configuration:** two fabricated registry businesses; real Principal/service/store
policy, mocked analysis.

**Exact command:**

```bash
uv run --locked --offline pytest -q tests/security/test_batch_tenant_isolation.py::test_owner_can_read_but_foreign_and_missing_are_identical_404 tests/security/test_batch_tenant_isolation.py::test_service_and_store_enforce_ownership_without_http
```

**Requests:** Alpha uploads data and receives a job ID. Beta GETs
/api/v1/batch/jobs/{job_id}/report with Beta's fixture credential; Alpha repeats with
Alpha's. Tests also exercise status/results/download and direct service/store paths.

**Expected observation:** Beta404, Alpha200; foreign and unknown IDs have the same
error shape. **What it proves:** trusted registry ownership and permission checks,
not opaque IDs/body tenant claims. **Provider status:** MOCKED inference; LOCAL auth.
**Limits:** business-level API credentials and process-local ownership, not SaaS
user login or durable cross-worker isolation.

## Demonstration I — Gmail, explicitly mocked

**Purpose:** demonstrate readonly OAuth and selected email-to-T01 processing without
connecting a real account. **Configuration:** existing FakeGoogle, fabricated
client credentials/tokens, controlled classifier responses; fixed mock callback,
readonly scope and two tenant fixtures. Do not display authorization URL/state/code
or token values in the presentation.

**Exact commands:**

```bash
uv run --locked --offline pytest -q tests/security/test_gmail_oauth.py tests/integration/test_gmail_import.py tests/unit/test_gmail_mime.py tests/unit/test_gmail_lifecycle.py
.venv/bin/python docs/reviewer/verify_workflows.py
```

**Fixture requests:** POST /api/v1/integrations/gmail/connect; GET /oauth/callback
with fixture-held one-use state/code; GET /status; POST /import with
`{"max_messages":1}`; GET /imports/{job_id} and /imports/{job_id}/results; finally
DELETE /disconnect and GET /status. All suffixes share the Gmail prefix. Callback
uses state authority, all other operations use the correct tenant API permission.

**Expected observation:** connect/callback/status200; import202 → COMPLETED with
one successful NEGATIVE analysis; Beta results404; disconnect/status show cleared
connection. No response contains OAuth tokens.124 Gmail cases cover state/PKCE,
profile ownership, refresh/revocation/scope handling, MIME, selection, capacities,
deduplication and shutdown. **What it proves:** actual OAuth/Gmail/service/store
plumbing with mocked provider contracts. **Provider status:** GOOGLE AND GROQ MOCKED.
**Limits:** no live Google connection/public approval, no polling or attachments;
whole attachment-bearing messages skip before body fetch. RAM-only state; disconnect
does not revoke Google's grant. Selected text would go to Groq in authorized live use.

## Additional direct ingestion and final narration

The unified replay also POSTs /api/v1/ingest/feedback with external_api channel,
expecting200 ANALYZED through T01. To show it independently:

```bash
uv run --locked --offline pytest -q tests/integration/test_ingestion_api.py
```

Close by showing [fresh results](submission-workflows.json),
[architecture](ARCHITECTURE_WALKTHROUGH.md), [technical Q&A](TECHNICAL_QA.md) and
[checklist](FINAL_SUBMISSION_CHECKLIST.md). Say: “The documented API-only scope is
ready for a provisional local demonstration. Original rubric unavailable; Gmail is
mock verified, one prior T01 request is live recorded, and accuracy/deployment are
not claimed.” No deployment/frontend or live acceptance is automatically required
by the communicated reviewer scope, and no later milestone is started.
