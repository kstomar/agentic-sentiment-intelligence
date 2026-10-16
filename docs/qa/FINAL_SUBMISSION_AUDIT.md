# Final pre-submission audit

6 November 2026 · Agentic AI Sentiment Analysis & Customer Feedback Intelligence API

## A. Executive Verdict

**READY WITH DOCUMENTED LIMITATIONS — academic/API-only submission; provisional reviewer compliance.**

The implemented application is functional under the tested conditions. The current
suite passed **901 tests, 0 failures, 0 errors and 0 skips** in 131.766 seconds.
This includes actual isolated PostgreSQL, real compiled LangGraph and official MCP
protocol execution with mocked model/Google services. A fresh source-copy environment
installed from the locked cache, migrated and started successfully. No production
application, schema, migration or dependency file was changed during this audit.

The title is defensible when explained as a **bounded, tool-using agentic workflow**,
not a fully autonomous agent. Documentation now makes that distinction explicit.
No demonstrated P0 application defect remains. Important outstanding acceptance and
credential-hygiene actions are listed in K; they must remain visible to the evaluator.

The independently verified original reviewer assignment is unavailable. This is an
assessment against established project scope, source and tests, not a definitive
rubric score. Frontend, deployment, Docker, cloud hosting and CI/CD are not invented
submission requirements. This verdict does **not** approve production release.

Evidence is deliberately separated:

| Evidence class | What can be concluded |
| --- | --- |
| Executed in this audit | Full/focused automated tests; local SDK stdio protocol; real isolated PostgreSQL; migrations; locked install; startup/HTTP; source and public-file checks. Google/Groq mocked or explicitly unconfigured. |
| Historical artifact | [Single live T01 Groq smoke](LIVE_GROQ_VERIFICATION_REPORT.md): records HTTP 200, strict/schema/grounding success, 1.4903 s and 1,371 tokens on 2 November. Not repeated or an accuracy benchmark. |
| User-reported manual live evidence | OAuth; real incoming-email/Groq imports; incremental and partial selection; successful failed-message retries; restart deduplication. Latest account describes COMPLETED, one success and six prior successes recognized after restart. Private mailbox operations were not replayed or independently captured here. |
| Still unverified | **Real external MCP host acceptance**; sanitizer-specific live exercise; equivalent live sent-message/1,000-message scenarios; supported-version PostgreSQL acceptance, online fresh-clone install, production operations and original rubric. |

Executed artifacts are in [final-submission/](final-submission/). Raw private email,
tokens, credentials and model output are excluded.

## B. Is It Truly Agentic AI?

**YES, with the precise classification “bounded, tool-using agentic workflow.”**
Ordinary sentiment classification is conventional LLM inference. Investigation
adds actual intent-dependent control flow, typed shared tools, intermediate state,
deterministic reductions and verified source retrieval. MCP exposes those functions;
it does not independently establish agency.

Source: [build_feedback_graph](../../app/agents/feedback_graph.py#L34),
[ActionSelector](../../app/agents/action_selector.py#L25),
[InvestigationState](../../app/agents/state.py),
[InvestigationService](../../app/services/investigation_service.py#L20),
[aggregation](../../app/tools/aggregation.py), [evidence verification](../../app/tools/evidence.py#L41).

| Agentic property / expected behavior | Actual source evidence | Status | Limitation |
| --- | --- | --- | --- |
| 1. Runtime LangGraph use | InvestigationService invokes its compiled StateGraph with ainvoke | Implemented | Not an unused import. |
| 2. Meaningful graph/state | Six nodes; request, selection, analyses, counts, issues, evidence, response state | Implemented | Request-scoped state only. |
| 3. Decision-driven execution | Conditional edges after analysis use selected action | Implemented | Reviewed finite topology. |
| 4. Intent-based tool selection | ActionSelector receives question and business hint only | Implemented | Does not select from feedback or tool observations. |
| 5. LLM and policy roles | Strict LLM action/arguments; deterministic dispatch/allowlist | Implemented | No arbitrary tool discovery/execution. |
| 6. Observation-driven replanning | Counts/filtering/source results inform final findings | Partial | No second selector or new plan based on observations. |
| 7. Multiple paths | Overview; evidence; issue/general aggregation | Implemented | Four actions, three topologies. |
| 8. Bounded multi-step investigation | Select → per-record classification → optional grouping/retrieval → verify → answer | Implemented | Maximum ten submitted records; unrecovered record failure aborts. |
| 9. Conditional/iterative execution | Conditional edges and selected filters | Partial | Acyclic; no iterative graph planning or reflection. |
| 10. Tool observations used | Deterministic answer/recommendations use actual counts/issues/evidence | Implemented | No final LLM prose call. |
| 11. Grounded verification | IDs, exact source excerpts, membership, category filters and counts checked before/after construction | Implemented | Does not prove model interpretations true. |
| 12. Classification vs investigation | Separate REST/service/schema contracts | Implemented | Chat explicitly chooses one mode. |
| 13. Bounded work | Deadline, recursion limit 12, ≤10 sequential analyses, shared admission and retries | Implemented | Each analysis can use bounded additional provider invocations. |
| 14. Injection safeguards | Selector has no corpus access; isolated data prompts; strict schemas/allowlisted tools; no shell/browser execution | Implemented | Model semantic errors remain possible; not an OS sandbox. |
| 15. Beyond a single model call | Actual graph plus deterministic tools and source checks | Implemented | Statistical/evidence workflow, not external research. |
| 16. Autonomy, memory, self-directed planning | No checkpoint/store/cache, durable conversation or goal loop | Missing by design | Not a general-purpose autonomous agent. |

The mandatory [awesome-agentic-patterns reference](https://github.com/nibzard/awesome-agentic-patterns)
was inspected directly, including eight relevant pattern files. [Pattern mapping](../AGENTIC_PATTERNS.md)
distinguishes implemented mechanisms from adaptations, particularly partial output
verification, hybrid coordination and generic webhook triggers. [Reference blob hashes](final-submission/pattern-references.json)
record the fetched files. There is no requirement to implement the entire catalogue.
No artificial loop or extra agent is needed to justify the qualified title.

### Three executed graph examples

The new regression uses an actual compiled graph and actual strict ChatGroq adapters
over HTTP MockTransport. The selector's response is controlled, so this proves
dispatch, schemas and findings, **not live natural-language intent accuracy**.
Inputs in all three cases are two synthetic records: positive product feedback and
negative late-delivery feedback. The latter contains a hostile run_shell instruction.
The selector receives neither record nor its ID. Initial state contains the request,
no selection/response, empty analysis/issues/evidence/tools and no sentiment summary.

| Request question | Validated selector decision | Executed tools / observation | Later decision and final result |
| --- | --- | --- | --- |
| “Show the overall sentiment distribution.” | SENTIMENT_OVERVIEW | analyze_feedback_items, aggregate_sentiment; POSITIVE 1, NEGATIVE 1 | Edge skips issue/retrieval tools; verifies counts then generate_insights. Empty issues/evidence, total 2. |
| “Which complaints are most frequent?” | ISSUE_FREQUENCY | Same analysis/count tools, aggregate_issues, retrieve_evidence; DELIVERY count 1 under the negative record ID | Edge requires grouping then source retrieval; verifies membership/count/excerpt and generates findings. One delivery complaint and its original record. |
| “Which negative feedback mentions delivery?” | EVIDENCE_SEARCH, category DELIVERY, sentiment NEGATIVE, limit 3 | Analysis/counts then retrieve_evidence; only the matching negative source record | Edge skips issue grouping; verifies retrieved source and returns one excerpt. Not unrestricted semantic search. |

Each result has explicit limitations. Tools_used lists domain tools, not every
control/verification node. Later observations influence findings, not a new selector
decision. In these adversarial-evidence cases both classifier generations have
nonexact quotations; sanitization leaves empty model evidence while graph retrieval
still returns verified original request excerpts. Those excerpts do not independently
validate the sentiment. Each example uses five mocked provider invocations: one
selector and two per record. See [the executed regression](../../tests/integration/test_final_submission_regressions.py#L21).

## C. Architecture Assessment

FastAPI composes reusable services at application lifespan. Thin /api/v1 routes
declare permissions; ingress authenticates before bounded body intake. Registry-issued
immutable principals bind tenant identity at service/store boundaries. SQL lookups
include ownership, and foreign/unknown owned resources return the same 404.

REST sentiment calls shared T01; graph, explicit-mode stateless chat, CSV/XLSX rows,
direct ingestion, signed webhook workers and Gmail imports delegate to that instance.
Selector/classifier operations share REST global/tenant admission. Sync file parsing
and PostgreSQL operations run off the event loop. Fixed workers, immediate capacity
rejection, cancellation cleanup and deadlines prevent unbounded work queues.

The separate MCP stdio process builds the **same implementation**, not REST's live
service objects or shared memory/budget. Trusted local launcher authority is distinct
from business authentication; there are exactly two tools and no owned-resource lookup,
tenant_id authority argument, remote MCP HTTP or generic filesystem/database/shell tool.

| State | Actual storage and lifecycle |
| --- | --- |
| Batch jobs, row outcomes and recoverable pending rows | PostgreSQL; raw pending row text is cleared after settlement; bounded retry/leases and restart recovery. Terminal TTL default 0 means indefinite retention within quotas. |
| Direct/webhook original feedback, validated analysis, status and authenticated delivery identity | PostgreSQL feedback_events; owner result read requires events:read. Default TTL 0; optional expiry. Unfinished events become FAILED/INGESTION_INTERRUPTED on startup without automatic replay. |
| Gmail processed identity/attempts/cooldown/claims | PostgreSQL gmail_message_tracking, keyed by tenant + verified mailbox hash + message ID. Successful metadata survives job TTL, disconnect and restart within quotas. Not historical analysis storage. |
| Gmail tokens, state/PKCE, connection/mailbox reservations, jobs/results | Bounded private process memory. Reauthorize after restart; old Gmail job/result IDs can return 404. No plaintext token file. |
| Investigation/chat state, REST counters/worker queues; MCP state | Process/request-local. No conversation memory, checkpoint or shared distributed limiter. |

Alembic chain: t09_batch_v1 → t09_batch_v2 → feedback_results_v1 →
**gmail_incremental_v1**. SQL constraints/indexes and repository ownership enforce
application consistency; this is not PostgreSQL RLS. A session advisory lock permits
one application coordinator per database. Leases/tokens fence stale commits; model
calls do not hold database transactions. Lost uncommitted external responses can
cause at-least-once work; no distributed/exactly-once claim is justified.

Actual components/flows are diagrammed in [README](../../README.md#architecture).
There is no Redis, Celery, scheduler, sending/replying Gmail service or frontend.

## D. Feature Verification Matrix

“Automated” below means executed in this audit. Unless noted, external services are
mocked. “User live” is the user's manual account, not an independently replayed result.

| Planned/documented feature | Implemented / source | Automated tested | Live tested | Remaining gap |
| --- | --- | --- | --- | --- |
| Sentiment REST | sentiment_service, sentiment router | Schema/adapter/API/provider failures | Historical T01 artifact; user Gmail/Groq | No accuracy/calibration benchmark. |
| Aspect extraction | Aspect schema, strict T01 | Malformed/valid aspect regressions | Within reported analyses, not independently scored | Interpretation quality. |
| Category/urgency/summary/next step | Closed enums/required schema | Enum, lengths, required/extra fields | Smoke/manual, not field accuracy study | Urgency remains tentative triage. |
| Exact evidence grounding | SentimentResponse contextual validator | Exact substring, malicious and mixed errors | Historical smoke/user grounded results | Exact quote does not prove interpretation. |
| Evidence correction | One fixed correction for grounding-only failure | Retries, errors, deadlines, permit retention | User reports at least one recovery | Does not recover every invalid output. |
| Evidence sanitization | Filter only corrected grounding-only phrases, full revalidation | 57 unit cases plus Gmail and new cross-interface tests | **Not specifically verified live** | Empty evidence reduces support. |
| Agentic investigation | Compiled graph/shared tools | Runtime routing, invalid state/evidence, timeout | No independent live graph replay | Natural-language action accuracy not measured. |
| LangGraph orchestration | Six real nodes/typed state | Compiled execution, conditional tools | No new live provider run | No autonomous planning loop. |
| Conditional tool selection | ActionSelection strict allowlist | All actions and three path topologies | No independent live selector acceptance | One-shot intent mapping. |
| Chat | Explicit ANALYZE_TEXT / INVESTIGATE_FEEDBACK | Shared service routing, validation/errors | No independent live chat replay | Stateless; no auto intent/history. |
| CSV/XLSX batches | Bounded parsers, workers, reports | Real formats, partial rows, quotas, PG/restarts | No audit live inference | Temporary raw pending rows; quotas/retention. |
| PostgreSQL/Alembic | Four revisions/four application tables | 113 real-PG cases; isolated migration/schema comparison | User restart-dedup account | Tested PG 12 EOL; backup/restore not accepted. |
| Tenant authentication/ownership | tenant_auth and owner-scoped stores | Forged principals, foreign reads, rotation, permissions/quotas | No live penetration test | Application isolation, not DB RLS. |
| Direct ingestion/result retrieval | Shared T01 + feedback_events | Durable success/failure, restart, foreign 404 | Not independently live verified | Each POST creates a new delivery. |
| HMAC webhook | Exact-byte signature/reservation/workers | Tamper/skew/replay/duplicates/conflicts/cancel/restart | No external sender test in audit | No unfinished-event replay; finite reservations. |
| Gmail OAuth | PKCE, state, exact Google issuer, token scopes/profile | 71 security cases plus lifecycle/provider tests | **User live** | Google policy approval not inferred. |
| Gmail incremental import | Selection + persistent ledger | Real PG, mocked Gmail/Groq | **User live** incremental/partial/retry | Bounded prefix scans, no permanent cursor. |
| Durable Gmail duplicate prevention | Tenant/mailbox/message identity | Restart/disconnect/rotation/leases | **User live** six prior successes after restart | Old RAM-only successes not backfilled. |
| Sent-message exclusion | Query -in:sent, minimal labels, MIME rechecks | Five incoming/one sent; archived/pagination/capacity | Equivalent live edge scenario unverified | Late label races can become selected SKIPPED. |
| Failed-email retry | Default three logical attempts, 60 s cooldown | Cross-job/restart budget, stale fencing, timeout | **User live** successful retries | Permanent failures still consume bounded attempts. |
| Partial/empty/large Gmail workloads | Maximum is upper bound; flags | 250 → 100/100/50/0; configured 1,000; exhausted zero | **User live** partial; bulk simulated | 1,000 not live-tested. |
| MCP tools | Official SDK 2.3.0 MCPServer, stdio | 21 protocol-marked cases, including subprocess | **External real host pending** | SDK clients are not external-host acceptance. |
| Frontend/deployment/CI | Not implemented | Not claimed | Not claimed | Optional unless original rubric says otherwise. |

### Evidence recovery correctness

[SentimentService._analyze](../../app/services/sentiment_service.py#L138) retains
native strict json_schema output and the original validator. Only root-level
evidence_not_grounded failures qualify. A corrected response with any other schema,
enum, aspect, missing/extra-field or parser error still fails. Sanitization clones
only evidence_phrases, retains case-sensitive contiguous substrings, never fuzzy
matches/normalizes/invents text, and completely revalidates against original input.
Timeout is checked before/after filtering; the original model permit/deadline remains.
No added generation follows the correction, and correction has no transport retry loop.
SDK retries are disabled; service provider retries default 2, hard maximum 3.
Worst-case invocations per logical analysis are R+2 (default 4); valid first output
uses one. A ten-record graph has ≤11 logical operations, ≤41 default invocations
(≤51 at R=3), further constrained by its wall-clock deadline.

Empty evidence is already a valid contract. Batch reports omit absent quotes;
ingestion/Gmail store validated empty evidence as successful, so durable Gmail
deduplication prevents automatic evidence-refill retries. Graph source evidence
comes from verified original records, not invented model quotations. An empty list
is **not independently evidence-substantiated**. Fixed diagnostic categories and
numeric sanitation counts provide internal observability without new response fields.
There are no confidence scores or complete semantic-reliability guarantees.

### Gmail selection and six status fields

[GmailService._select](../../app/services/gmail_service.py#L310) resolves only the
configured customer-feedback label and server newer_than date window. Gmail query
excludes SENT and Spam/Trash; no INBOX or sender-equality requirement excludes
archived incoming mail. SQL successes are excluded before new-message capacity.
Minimal label checks exclude SENT before claiming; metadata/full MIME checks again
reject SENT/SPAM/TRASH/missing custom label. Attachment/external/nontext content is
skipped; selected text is bounded to 16 KiB/5,000 characters. HTTP 204 remains an
unexpected provider error, not fabricated empty success.

| Additive status field | Verified meaning |
| --- | --- |
| scanned_messages | Distinct provider IDs examined under this bounded listing, including IDs later excluded; not selected/processed count. |
| previously_processed_messages | Successful ledger identities excluded during selection; not old duplicate result rows. |
| deferred_messages | Identities unavailable because of active claims, cooldown or exhausted retry policy. |
| scan_exhausted | Listing genuinely exhausted after seeking available capacity; reaching requested max need not assert exhaustion even on a final page. |
| scan_limit_reached | Page bound reached before listing exhaustion and before satisfying selection. Not an empty mailbox. |
| capacity_limit_reached | Durable tracking capacity blocked further new reservations. Never silently evicts success history. |

Selected/processed/success/failure/skipped/duplicate outcome counters still describe
admitted messages and reconcile separately. Empty genuinely exhausted imports complete
with zero selections/model calls. Pages continue past successes/ineligible candidates.
Default max is 20 new messages (hard 100), five pages (hard 10), 120 seconds (hard
600); ledger defaults 10,000 global/1,000 tenant. Failed analysis default cooldown
60 s and three attempts across jobs/restarts; unstarted claims do not spend attempts.
Default computed lease is 200 s; fences protect stale updates. Tests cover overlapping
claims without a transaction held during inference.

[Real-PG large-workload tests](../../tests/integration/test_postgres_gmail_incremental.py#L66)
process 250 simulated messages in 100/100/50/0, then reconnect/restart and process
only one new message. The 1,000-message test sets max 100, ten pages, tenant retained
jobs 12 and deadline 600; ten imports process 100 each, then zero, exactly 1,000
mocked analyses. This profile is explicit configuration, not a new default or live
Google performance result. Prefix scans have no durable cursor; large processed
prefixes can repeatedly reach the scan limit.

## E. Test Results

Full executed command, after the README project-local uv exports:

```bash
T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-demo-socket" \
  GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q \
  --junitxml=docs/qa/final-submission/full.xml
```

| Execution | Result |
| --- | --- |
| Full suite | **901 passed**, 0 failed/errors/skipped; 131.766 s JUnit, pytest rounds to 131.77 s. |
| Focused new regressions + existing MCP module | **25 passed**, 6.29 s; [focused.xml](final-submission/focused.xml). |
| Test categories, disjoint | Unit 286; integration 327; security 285; local synthetic benchmark 3. |
| Real PostgreSQL fixture cases, overlapping categories | **113 passed**, no DB skips; dedicated *_test DB, random schema per case, cleanup of that schema only. |
| MCP protocol-marked cases, overlapping categories | **21 passed**: existing MCP module 18; two new reduced-evidence cases; one tenant-boundary case. Includes real official SDK legacy/auto and subprocess stdio. |
| Baseline preservation | All 894 pre-audit test cases retained; seven new cases; existing test files unchanged. |
| Python checks | 125 Python files compile; 69 application modules import. |
| OpenAPI | 3.1.0; 20 paths/20 operations; 316 local refs resolve; unique operation IDs; all paths represented in README. Existing contract regressions pass. |
| Alembic / ORM | One head gmail_incremental_v1; all four revisions apply to isolated schema; zero ORM schema differences; inspected uniqueness/checks/indexes. |
| Environment/lock | Python 3.12.16; uv 0.13.6; uv sync --locked --offline, uv lock --check --offline and uv pip check pass; 80 installed compatible packages/84 lock entries. |
| Fresh source-copy startup | New cached .venv; no private .env/.git copied; migration; real Uvicorn /health, /docs, /redoc, /openapi.json all 200; no-provider authenticated analysis 503 GROQ_NOT_CONFIGURED. Graceful SIGTERM shutdown verified. |

Focused command used the same isolated database and blank credential overrides:

```bash
uv run --locked --offline pytest -q \
  tests/integration/test_final_submission_regressions.py \
  tests/integration/test_mcp_server.py \
  --junitxml=.local/qa/final-submission/focused.xml
```

[Full XML](final-submission/full.xml), [module/count summary](final-submission/test-summary.json),
[OpenAPI/import/lock checks](final-submission/verification.json),
[migration checks](final-submission/migrations.json), [bootstrap](final-submission/database-bootstrap.json),
[fresh setup](final-submission/clean-setup.json), [versions](final-submission/environment.json).

The installed official MCP SDK remains pinned to 2.3.0. Groq 0.37.1,
langchain-groq 1.1.3, LangGraph 1.2.18, Pydantic 2.14.2, FastAPI 0.162.0,
Starlette 1.10.0, HTTPX 0.28.1, SQLAlchemy 2.0.55, Alembic 1.20.1 and psycopg
3.3.7 are recorded. Dependencies and lockfile were not modified.

Tests exercise strict real adapters through mocked HTTP rather than only bypassing
Pydantic with service stubs. Security tests cover foreign resources, forged principal,
tenant saturation/headroom, original-byte HMAC, chunked/misleading-length ingress,
OAuth refresh/state replay, MIME exclusions, response caps, retry/cancel/expiry,
fencing and restart. Fault injection and multi-tenant cases are meaningful evidence.
They do not establish production capacity or real-world model accuracy.

Coverage, ruff, mypy and pip-audit were unavailable and were not installed or claimed.
No coverage percentage, complete advisory scan or live benchmark is reported.
No CI configuration exists. High-value remaining verification is external MCP host
acceptance, a supported PostgreSQL version, a curated semantic-quality corpus and
sanitizer-specific owner-authorized live observation. Current fixed-category logs
are sufficient for bounded recovery diagnosis; no raw-response logging is justified.

## F. Security Findings

No demonstrated P0 exploit or new P1 application-code defect was found within this
source/test review. This is not a penetration-test or production security certification.

| Boundary | Implemented evidence | Residual responsibility |
| --- | --- | --- |
| Authentication/tenants | Private SecretStr registries reject ambiguous IDs/secrets; immutable registry proofs, permission checks, timing-safe key comparison; ownership at routes/services/SQL; no production legacy fallback | Keep registry secrets private; no database RLS or cross-process identity service. |
| Ingress/resources | Actual-byte 4 MiB JSON cap, 16 KiB webhook cap, 2 MiB multipart file cap; chunk/deadline/concurrency/rate/tenant controls; shared logical model admission | One-process limits; configure reverse-proxy TLS/body/logging separately. |
| Signed events | HMAC-SHA256 covers integration.timestamp.delivery.raw bytes, compare_digest, skew check, per-retry auth, atomic durable reservation/conflict detection | Sender must use exact bytes and fresh timestamp. No exactly-once external effects. |
| OAuth | Single-use expiring tenant state, S256 PKCE, fixed callback/hosts, exact optional Google issuer, duplicate/unknown parameter rejection; callback scope not trusted; token scopes/profile establish grant/identity | OAuth tokens/ownership remain RAM; reconnect after restart; Google policy approval outstanding. |
| Gmail HTTP/MIME | TLS defaults verified, direct client trust_env=False, redirects disabled; fixed URLs, caps/timeouts, safe operation/method/host/status/length diagnostics; no attachment endpoint | HTTP204 errors remain errors; Google/proxy environmental behavior cannot be certified by mocks. |
| LLM safety | Native strict output; full contextual validation; allowlisted action isolation; bounded correction/filtering; suppressed tracing/provider/SDK logs | Schemas/quotes do not eliminate semantic hallucination; no independent business-fact verification. |
| SQL/storage | Parameterized ORM queries, tenant predicates, explicit transactions, constraints/leases/fences, offloaded blocking work, hidden SQL parameters | Durable original direct/webhook feedback needs owner retention/access/backup policy. No audit of an external DB deployment. |
| MCP | Stdio only, exactly two schema-limited tools, trusted launcher, protocol stdout/fixed stderr, no remote database/tenant tool | Real host acceptance pending; installing/trusting a host is an owner action. |

**Credential hygiene — P1 external action:** a Groq credential was supplied in an
earlier conversation. Its current validity/revocation is unknown; do not repeat it.
Owner should verify revocation or rotate it if still active before further use or
sharing. No automatic rotation, live validity test or copying into reports occurred.
This is prior disclosure in conversation, not evidence of a tracked repository secret.

The public candidate scan checks known token/private-key shapes and exact matches
against selected private configuration secrets **in memory only**. It does not emit
secret values and is not a universal secret detector. See [scan result](final-submission/secret-scan.json).
Private .env, token/runtime folders, databases/logs and Postman private exports must
remain excluded. .gitignore covers .env (keeps blank .env.example), .tools, .cache,
.venv, .local, database files/dumps, credentials/key/token patterns and temporary
feedback. Ignoring does not untrack a previously tracked file.

The empty, read-only .git mount was inspected without Git commands and left intact.
**Tracked/untracked status, commits and Git-history secret exposure cannot be verified.**
Do not claim a clean Git repository. Before any later publication, inspect tracking
and history in an authorized normal checkout. No push/upload/public release occurred.

Targeted primary advisory checks, **not an exhaustive dependency scan**:

- [langchain-core deserialization advisory](https://github.com/langchain-ai/langchain/security/advisories/GHSA-c67j-w6g6-q2cm): installed core 1.7.3 is beyond the listed 1.2.5 fix; dangerous deserialization APIs are not used in this application.
- [Starlette multipart advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq): installed 1.10.0 is beyond listed 1.3.1 fix; application intake is bounded too.
- [MCP HTTP DNS rebinding advisory](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-9h52-p55h-vw2f): this application exposes stdio only, which the advisory identifies as unaffected. This does not certify all SDK risks.
- Actual PostgreSQL **12.22 is end-of-life**; [official support policy](https://www.postgresql.org/support/versioning/) records version 12 support ending 21 November 2024. Retest on a supported release before production use; no server upgrade was performed.

## G. README and Documentation Audit

README was reviewed against actual routes/services/tests and rewritten as one
coherent entry point. It now covers all 37 requested topics: purpose; bounded agency;
Groq/LangGraph/MCP roles; two architecture diagrams; modular layout/stack; local uv/
Python installation; private config; isolated PostgreSQL/roles/test database; migrations;
one-worker startup; docs; all 20 routes/permissions; analysis/investigation/chat/batch/
HMAC/Gmail/MCP examples; tests; safe errors; limits; persistence; privacy; limitations;
future work and demo/submission guidance. No predetermined model response is promised.

Corrected discrepancies include memory-only versus durable batches/events/Gmail
ledger, stale migration head, discarded versus retained ingestion feedback, sent
filtering, max-new selection/pagination, retry policy, RAM OAuth/historical results,
strict correction/sanitization/empty evidence, graph invocation bounds and qualification
of agency/live acceptance. Commands use project-local exports and portable placeholders.

Architecture, pattern mapping, MCP, PostgreSQL, webhook, tenant and Gmail guides
were aligned. Earlier QA/reviewer packages carry explicit historical banners and
links here rather than silently replacing old failures/counts. The exact old README
is retained in [history/pre-final-submission/](history/pre-final-submission/README.md)
with a notice that its relative links were originally rooted at the project directory.
Historical original bodies and original test XML remain preserved.

README shell/Python/JSON examples and active relative links are checked separately
in [documentation-checks.json](final-submission/documentation-checks.json). Mermaid
source syntax/flow was reviewed, with lexical declaration/edge checks. **No Mermaid
renderer was available**, so rendered layout is not claimed. A fresh online clone
and real desktop MCP GUI were not exercised. CLI setup/startup is independently
verified as a fresh source-copy/cached install, not merely copied from the README.

## H. Code Quality Assessment

The project is modular: route adapters, strict schemas, business services, graph/
prompts/tools, fixed provider integration and separate repositories/migrations.
Shared T01 behavior avoids per-interface classifiers/prompts. Python performs
aggregation; cancellation, contexts, HTTP clients, SQL sessions and worker shutdown
have explicit lifecycles. Model/provider errors map to fixed safe codes rather than
raw exception messages. Provider tracing is disabled. No debug print of customer
data, arbitrary execution tool, hardcoded production secret or unsupported dependency
substitution was identified in application source.

Maintainability is good for the scope, with areas for improvement. Some SQL stores
use dense one-line/semicolon statements and private store coupling; future changes
need careful transaction/authority review. A legacy UploadSizeLimitMiddleware is
not mounted by current composition (IngressLimitMiddleware replaces it) but retains
isolated tests. A generic string-too-long error message always says 5,000 even for
shorter schema-specific fields: validation bounds remain correct, messaging is
imprecise. Avoid contract-changing refactors merely for style during submission.

Declared constraints are broad but reproducibility comes from uv.lock plus required
uv version; locked/offline checks passed. LangSmith is used for tracing_context(False),
not a telemetry feature, so removing it blindly is unjustified. Optional frameworks,
Redis/Celery/full LangChain are absent. No lint/type/coverage result is invented.

## I. Known Limitations

- **Real external MCP client integration remains pending.** Official SDK protocol tests are separate evidence.
- Gmail OAuth/state/tokens/connections, mailbox reservations and historical jobs/results are process-local. Durable processed metadata is not historical analysis storage. Reconnect after restart.
- One application coordinator/ASGI worker; no distributed authorization/queue/rate limiter or exactly-once inference.
- Gmail explicitly imports bounded, labelled incoming mail. No polling, sending, attachments, mailbox-wide configurable query or permanent page cursor. Prefix/page/capacity exhaustion can leave available mail unselected.
- Model/provider failures can remain unrecoverable. Single primary categories and urgency/summary/aspect quality are interpretations, not measured truth.
- Empty evidence success is contract-valid but has no retained quotation or independent support; it can still count/deduplicate successfully. No automatic evidence-refill retry.
- Default durable terminal retention is indefinite within finite quotas; no public administrative purge/history expansion endpoint. Owners must plan retention/access/backups before operational use.
- Direct ingestion POST is not caller-idempotent; signed webhook delivery identity is idempotent under retained authenticated bytes. Unfinished event processing is marked interrupted, not replayed.
- Local PostgreSQL 12 is unsupported; no supported-version, restore drill, independent penetration test or comprehensive advisory scan was completed.
- Offline cached source-copy setup passed; online clean-machine download/clone, Git handoff/history and cross-session/environment filesystem retention remain unverified.
- Frontend, deployment and CI are absent and outside the established required scope; original reviewer rubric still unavailable.

## J. Issues Fixed

| Finding | Severity | Correction / files | Verification |
| --- | --- | --- | --- |
| Stale README obscured current persistence, agentic scope and acceptance evidence | P1 documentation | Rewrote README.md; preserved exact original in docs/qa/history/pre-final-submission/README.md and added NOTICE.md | Source/path/schema/example checks; actual fresh setup; historical hash comparison. |
| Important reduced-evidence integration gaps | P1 verification gap | Added tests/integration/test_final_submission_regressions.py only: three real graph/strict adapter paths, two official MCP modes, PG batch/report and PG direct/restart/foreign lookup | Seven new cases pass; full 894-case baseline retained plus seven = 901. No production fix needed. |
| Active guides contradicted current persistence/retry/acceptance and pattern scope | P2 documentation | docs/README.md, AGENTIC_PATTERNS.md, MCP_INTEGRATION.md, POSTGRESQL_BATCH_STORAGE.md, WEBHOOK_INTEGRATION.md, TENANT_ISOLATION.md, GMAIL_INTEGRATION.md | Actual source and test comparisons; active-link/example checks. |
| Old audit/reviewer decisions could be mistaken for current status | P2 documentation | Current pointers prepended to seven core docs/qa reports and all docs/reviewer/*.md; bodies retained verbatim | Preservation check against pre-audit hashes. |
| Missing final reproducible audit bundle | P2 evidence | This report and sanitized docs/qa/final-submission/* artifacts; test fixture refreshes docs/qa/benchmark_results.json | Executed XML/checks/inventory/scan. Benchmark artifact is synthetic local timing, not model performance. |

No production .py, schema, migration, pyproject.toml, uv.lock, .env, Git mount or
existing test file was changed. No new dependency, OAuth permission, endpoint or
response contract was introduced. No private data was deleted or credential rotated.
File-level changed/new/deleted inventories are in [preservation.json](final-submission/preservation.json).

## K. Unresolved Issues

Line references identify the affected boundary, not evidence of a defect on every line.

| ID / severity | File and line / boundary | Problem and impact | Recommended action / verification |
| --- | --- | --- | --- |
| U1 — P1 external hygiene | Earlier conversation; secret-setting boundary app/core/config.py:38 | Previously pasted Groq key may still be active; revocation unknown | Owner privately verify revocation/rotate if active. Do not echo/copy it. No live credential check or rotation performed. |
| U2 — P1 integration acceptance | app/mcp_server/server.py:125; docs/MCP_INTEGRATION.md:300 | Real external MCP host acceptance remains pending; SDK success does not prove host behavior | Follow documented owner-controlled host setup/discovery and both actual tool calls; retain sanitized result. Explicitly disclose pending status at submission. |
| U3 — P1 conditional handoff | .git read-only empty mount; README.md:110 | Cannot verify tracked/untracked files, commit history or supply verified Git handoff | In a later authorized normal checkout, review tracking/history before publication. If evaluator requires Git delivery, complete that check before declaring delivery complete. No mount bypass. |
| U4 — P2 academic / important production prerequisite | docs/qa/final-submission/migrations.json; README.md:105 | Tested PostgreSQL 12.22 is EOL; fixes/support unavailable | Retest locked app/migrations/113 DB cases on a supported release before production. Do not claim that verification here. |
| U5 — P2 grounding/quality | app/services/sentiment_service.py:197; app/schemas/sentiment.py:76 | Empty evidence and wrong interpretations may be valid schema output | Preserve explicit trade-off; evaluate synthetic semantic corpus and aggregate safe recovery counts later. Live sanitizer exercise requires owner authorization. |
| U6 — P2 retention/capacity | app/core/config.py:56; app/core/config.py:64; app/core/config.py:89 | Finite quotas plus indefinite history can eventually block new admissions; durable original event text needs policy | Choose documented TTL/metadata retention and trusted maintenance procedure; no destructive cleanup or new admin API during audit. |
| U7 — P2 scan/lifecycle | app/services/gmail_service.py:310; app/storage/gmail_store.py | Bounded prefix scans; OAuth/jobs/results RAM; ownership registry resets on restart | Explain flags/reconnect/results limits; do not treat page limit as empty. Durable token/cursor design would require a separate scoped change. |
| U8 — P2 diagnostics/maintenance | app/main.py:261; app/core/upload_limits.py:12; app/storage/postgres_job_store.py:81 | Generic 5,000-char message for shorter fields; unused legacy middleware; dense repository code | Later field-aware safe messages and limited cleanup/refactor with contract/security tests. Existing validation remains correct. |
| U9 — P2 verification | tests/conftest.py:37; docs/qa/final-submission/environment.json | No coverage/lint/static typing/full advisory/production load/restore results | Add appropriate tooling only as a separate approved effort; do not infer absence of risks from 901 tests. |
| U10 — P2 compliance evidence | docs/reviewer/REQUIREMENTS_SOURCE_RECORD.md | Original assignment absent; final rubric acceptance cannot be definitive | Obtain original wording if possible; keep provisional qualifier. Do not invent frontend/deployment/MCP-reporting requirements. |
| U11 — P3 optional | README.md:523 | No frontend, scheduler, remote MCP or general autonomous planning | Consider only if subsequently required; unnecessary for current qualified workflow claim. |

These do not justify manufacturing autonomy, weakening strict schemas or silently
expanding persistence/OAuth scope. No live sanitizer-specific failure is claimed fixed
by mocked tests, and prior INVALID_MODEL_RESPONSE errors are not conclusively attributed
to sent mail.

## L. Submission Instructions

Use a new source copy with app/, tests/, migrations/, docs/, README.md, AGENTS.md,
pyproject.toml, uv.lock, .python-version, .env.example, .gitignore, alembic.ini and
pytest.ini. The following local path/config forms were exercised; prerequisites
are already installed project-local uv/Python and PostgreSQL binaries. New online
installer download is documented in README but was not repeated here.

```bash
export PATH="$PWD/.tools/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
export UV_PYTHON_BIN_DIR="$PWD/.tools/bin"
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_CACHE_DIR="$PWD/.cache/uv-python"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
uv sync --locked --offline
uv lock --check --offline
uv pip check --python .venv/bin/python
```

Remove --offline on another machine only after installing the pinned interpreter
and allowing ordinary package downloads; no online clone/install claim is made.
On a fresh copy, create private .env from .env.example as described in README;
never overwrite an existing .env. Put inference/business/Google secrets there or in
private environment variables, not in shared commands/reports. A fake/blank key
supports offline checks only, not live inference. Google settings remain optional.

For a **new isolated demo directory only**, these exact bootstrap operations passed.
Do not rerun initdb/CREATE ROLE/createdb against existing data. Local trust is restricted
to a 0700 Unix socket with TCP disabled and is not production authentication.

```bash
export PG_BIN="$(pg_config --bindir)"
mkdir -p .local/postgres-demo .local/postgres-demo-socket
chmod 700 .local/postgres-demo .local/postgres-demo-socket
"$PG_BIN/initdb" -D "$PWD/.local/postgres-demo" --auth-local=trust \
  --auth-host=reject --username=sentiment_owner --no-locale --encoding=UTF8
"$PG_BIN/pg_ctl" -D "$PWD/.local/postgres-demo" \
  -l "$PWD/.local/postgres-demo/server.log" \
  -o "-k $PWD/.local/postgres-demo-socket -c listen_addresses=''" -w start
"$PG_BIN/psql" -h "$PWD/.local/postgres-demo-socket" -U sentiment_owner -d postgres \
  -v ON_ERROR_STOP=1 -c 'CREATE ROLE sentiment_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
"$PG_BIN/createdb" -h "$PWD/.local/postgres-demo-socket" -U sentiment_owner \
  -O sentiment_app agentic_sentiment_dev
"$PG_BIN/createdb" -h "$PWD/.local/postgres-demo-socket" -U sentiment_owner \
  -O sentiment_app agentic_sentiment_test
export DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_dev?host=$PWD/.local/postgres-demo-socket"
uv run --locked --offline alembic upgrade head
uv run --locked --offline uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000/docs, /redoc and /openapi.json. All served 200 in the
fresh setup probe. /health is liveness, not provider/database readiness. The audit
created only this new demo cluster; previous/system clusters and development data
were untouched. The demo cluster remains available locally; .local is private and
excluded from submission. Reuse it on later runs instead of initializing again.

In another shell with the same uv exports and a running dedicated test database:

```bash
export T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-demo-socket"
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q -m protocol
GROQ_API_KEY='' APP_API_KEY='' .venv/bin/python -B -m app.mcp_server.server
```

The last command is a stdio server, not an HTTP listener; launch it through a client
rather than treating an idle terminal as failure. Official subprocess tests verify
this entry point with empty provider key, controlled configuration errors, clean
shutdown and protocol-only stdout. The protocol-only test subset is also included
in the full run. [External-host instructions and configuration](../MCP_INTEGRATION.md#real-external-client-acceptance-still-pending)
use absolute interpreter/PYTHONPATH placeholders to avoid host working-directory
assumptions. Discover exactly analyze_feedback/investigate_feedback. With a blank key,
expect GROQ_NOT_CONFIGURED on inference. **Actual external-host steps are documentation-
checked instructions, not an executed or claimed acceptance result.** The owner must
separately authorize/configure private live credentials and inspect both actual
structured tool responses before recording successful real-host integration.

Private inference/demo API commands are in README and the Gmail guide. Their request
schemas/signing are checked using synthetic values, and corresponding mocked APIs
pass; no fresh paid request or real mailbox operation was made during this audit.

## M. Academic Demonstration Guide

1. **Problem:** businesses receive fragmented reviews/emails; this backend classifies feedback and computes verifiable counts to support tentative triage. It does not manage incidents or act on customers.
2. **Architecture:** show README diagrams and C's durable/RAM table. Explain REST authentication, provider/schema boundaries and one coordinator.
3. **Sentiment:** use Swagger with an owner key and synthetic product-quality/late-delivery text only when live inference is intentionally authorized. Explain strict output, category/urgency/aspects and exact evidence. Do not promise a predetermined classification.
4. **Investigation:** submit two synthetic records and the three questions in B. Show selected_action, tools_used, counts and source IDs. For deterministic demonstration without live model uncertainty, run the new graph regression and describe its controlled selector.
5. **Conditional execution:** point to build_feedback_graph edges; contrast overview's skipped retrieval with evidence-only retrieval and issue grouping. Both issue/general actions share topology. No observation-driven replanning claim.
6. **Batch:** upload docs/examples/t09_reviews.csv with text_column=review/id_column=id. Poll job, read report/results/download; show per-row status and Python totals. XLSX path is automated too.
7. **Persistence:** retain job ID, restart the one application process and retrieve the same result. Explain precommit at-least-once risk, row-text cleanup and default indefinite terminal retention.
8. **Webhook:** use README's synthetic exact-byte HMAC sender with privately configured integration values. Show 202 admission, owner result, authenticated duplicate 200 and changed-byte conflict; do not display signature secrets.
9. **Gmail:** explain prior user-reported manual acceptance. If owner intentionally demonstrates live, connect/authorize readonly, confirm CONNECTED, label synthetic incoming mail customer-feedback, import with max_messages as upper bound, poll status/results. Repeat to show durable previous-success counts. After restart reconnect; old jobs may be 404. Do not claim this audit replayed live or that zero evidence proves the model interpretation.
10. **MCP:** show two tool schemas and automated official-client stdio evidence. State explicitly that **real external-client acceptance is pending**; use the separate owner-controlled guide later.

Three likely evaluator questions:

**Q: Why is this agentic rather than just sentiment classification?**
Classification alone is not. Investigation uses one strict LLM intent decision to
choose a bounded LangGraph path, invokes shared analysis plus deterministic tools,
tracks observations, retrieves original source records and verifies results. The
qualified term is bounded tool-using agentic workflow.

**Q: Does it plan, reflect and remember conversations autonomously?**
No. Four allowlisted actions map to three acyclic paths. Selection happens once;
intermediate evidence informs final findings, not a new plan. Chat requires explicit
mode/current data. No checkpoint, persistent conversation or autonomous action exists.

**Q: How do you prevent hallucinated evidence and what does empty evidence mean?**
Strict native/Pydantic schemas and contextual exact-substring validation reject
fabricated quotations. Grounding-only failures get one bounded correction; only
otherwise-valid corrected output can have nonexact phrases dropped and fully
revalidated. Empty is contract-valid but supplies no retained quote or independent
support. Counts/IDs/excerpts are checked; model interpretations can still be wrong.

## N. Final Submission Checklist

- [x] Actual source/architecture/routes/schema/provider/storage/security review completed.
- [x] 901 tests pass; seven justified regressions added; no weakened/deleted/skipped baseline tests.
- [x] Real isolated PostgreSQL, complete migrations/ORM comparison and restart tests pass.
- [x] Locked dependency compatibility, imports, compilation, OpenAPI and fresh cached source-copy startup pass.
- [x] README and active guides updated; historical README/report bodies preserved.
- [x] Public candidate files reviewed/scanned without exposing credentials; no production application/API/dependency changes.
- [x] Local stdio official SDK/protocol checks pass; no new live Google/Groq calls.
- [ ] Owner verify prior disclosed key's revocation or rotate if still active.
- [ ] **Real external MCP host integration remains pending**; disclose until completed.
- [ ] Definitive original reviewer-rubric compliance remains provisional.
- [ ] Git tracking/history and actual handoff cannot be verified in this mount; check a normal authorized checkout if Git delivery/publication is required.
- [ ] Live sanitizer-specific acceptance, supported PostgreSQL/production security/backup/operational checks remain outside demonstrated evidence.

Recommended submission **include**: app/, tests/, migrations/, current docs/ and
sanitized audit evidence, README.md, AGENTS.md, pyproject.toml, uv.lock,
.python-version, .env.example, .gitignore, alembic.ini and pytest.ini. Historical
reports are included as labelled history, not current success claims.

**Exclude**: .env/.env.*, except blank .env.example; .git runtime mount; .tools/,
.cache/, .venv/, .local/, caches/__pycache__; OAuth tokens/codes/URLs; registry secrets;
private Postman environments, logs, customer emails/uploads, sockets, database
clusters/dumps, key files and machine-managed .agents/.codex/.aws. Review a file
allowlist; do not zip the entire workspace. Existing historical artifacts may contain
machine-specific development paths, not portable required inputs. Current setup uses
relative paths or explicit replaceable placeholders.

No push, upload, publication, email, credential rotation, private data deletion,
new repository initialization or Git mount workaround occurred. Scratch environments
and the audit-created local DB live only under ignored .local. Files remain available
in this environment; cross-session/environment retention is not established. SQL
restart tests establish application restart persistence, not host-volume durability.

## O. Final Verdict

**READY WITH DOCUMENTED LIMITATIONS for the provisional academic/API-only submission.**
The existing backend demonstrates a real bounded agentic investigation, shared strict
sentiment pipeline, persistent feedback/batches, secure tenant-aware ingestion and
incremental Gmail processing under the verified conditions. The 901-test run and
fresh cached setup provide substantial reproducible evidence, not production or
semantic-accuracy certification. Disclose pending external MCP-host acceptance,
address the previously disclosed credential privately, and verify the submission
file allowlist/Git handoff in an appropriate checkout before sharing. Do not describe
this project as a fully autonomous general-purpose agent or a production-ready service.
