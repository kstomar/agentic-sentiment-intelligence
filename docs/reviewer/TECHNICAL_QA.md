> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Reviewer technical questions and answers

Answers describe this implementation and its verification limits. Original-reviewer
compliance remains provisional; no live provider request is part of this package.

### 1. What is agentic AI in this project?

A model interprets a feedback-investigation question into a validated action, and a
bounded workflow conditionally executes analysis, issue aggregation and evidence
tools. It returns grounded structured findings. This is controlled orchestration,
not unrestricted autonomous planning, persistent memory or a collection of agents.

### 2. Why use LangGraph?

The application needs explicit typed state, conditional routes and predictable
termination for four investigation actions. One compiled acyclic StateGraph makes
those transitions visible and testable. Direct sentiment, batch and Gmail do not
need separate graphs and reuse T01 instead.

### 3. What makes the workflow agentic?

Action selection depends on a model interpretation of the question, followed by
schema validation and branch-specific tool execution. Overview, issue-frequency,
evidence-search and general-summary branches call different operations. All four
execute in tests; live arbitrary-question selection quality is not measured.

### 4. Which agentic patterns are implemented?

Five core applications are verified: strict structured output, Action-Selector,
shared dual-use stateless services, independent LLM map/Python reduce and
LLM-friendly APIs. Output grounding, generic webhook triggers and narrow MCP
capability exposure are three scoped adaptations. Hybrid LLM/code coordination is
a principle only. We do not claim the entire catalogue or all mechanisms of each
adaptation. [Detailed mapping](AGENTIC_AI_VERIFICATION.md).

### 5. Why is the required patterns repository relevant?

The communicated project requirement names awesome-agentic-patterns as a mandatory
design reference. It provides concrete mechanisms for validated actions, constrained
outputs and deterministic reduction. The mapping links each selected pattern to
actual functions and executed tests; merely citing the repository would not prove use.

### 6. How does the action selector work?

ActionSelector receives only the current question and allowed business-type hint,
then requests native strict ActionSelection output. The four actions and bounded
filters are validated again in the graph. Feedback and tool outputs never return
to the selector, reducing control-flow injection exposure. The selector uses one
attempt; it cannot request arbitrary tools, URLs, shell execution or identity changes.

### 7. Why use deterministic aggregation?

Counts, denominators, percentages, ordering, category filters and unique-record
aspect frequencies must reconcile exactly. Python/Pandas compute them from validated
record results; no report-formatting/arithmetic model call is added. Correct math
does not imply correct input classifications, so both scopes are reported separately.

### 8. How does MCP differ from REST here?

REST exposes HTTP operations with API-key/HMAC/OAuth-state authority and OpenAPI.
MCP exposes discoverable typed tools through the official local stdio protocol.
Both use shared T01/T02 implementations; transport, error envelopes and authority
boundaries differ. Local MCP is trusted-launcher analysis, not a remote business login.

### 9. How does the MCP server reuse services?

analyze_feedback calls SentimentService.analyze; investigate_feedback calls the
existing InvestigationService. The separate MCP process creates its own service
instances/HTTP clients and admission budget, using the same implementation and
schemas as REST. It does not proxy REST or build another classifier/graph.

### 10. How does the system prevent fabricated evidence?

T01 validates every evidence phrase as an exact substring of submitted text.
Investigation verification checks source IDs, quotations, filters, category membership
and recomputed counts before/after response construction. Reports reconcile source
metadata and excerpts. Invalid results fail; these checks do not semantically prove
every generated summary or recommendation true.

### 11. How does CSV/Excel processing work?

Bounded off-loop parsing validates CSV/XLSX, column mappings, IDs and row/text sizes.
A temporary owner-bound job independently calls T01 for valid records, continues
controlled row failures and stops further calls on fatal provider configuration/auth
errors. Python/Pandas aggregate validated outcomes into JSON reports/results/downloads.
Raw text clears as rows finish; terminal data expires after30minutes by default.

### 12. How are provider errors handled?

T01 classifies Groq exception types/statuses into fixed safe codes, with at most two
configured transient retries after the first attempt and a default30-second total
deadline including backoff. SDK retries are disabled to avoid stacked retries.
Invalid output has no successful free-form fallback. The selector is one-shot;
Google has its own bounded HTTP retry/deadline policy and no code-exchange retry.
Diagnostics never return raw provider error strings or credentials.

### 13. How is webhook authentication implemented?

HMAC-SHA256 covers integration.timestamp.delivery plus the original body bytes,
using a privately configured integration secret and constant-time comparison.
Signed headers/timestamps and actual-byte limits are checked before parsing.
Atomic tenant+delivery reservation also verifies integration/body digest; identical
authenticated retries return200 DUPLICATE, changed content/collisions409. Authentication
still applies to retries, and retention covers the replay acceptance window.

### 14. How is tenant isolation enforced?

The server registry maps credentials/integrations to immutable verified Principals.
Routes check permissions, sensitive services/stores revalidate proof/owner and
workers bind verified context. Batch reports/results/downloads, event status and
Gmail jobs/connections are owner-scoped; foreign and unknown IDs both404. Request
business_type/tenant fields do not create authority. Rotation keys share tenant
ownership and quotas; production disables legacy development credentials.

### 15. How does Gmail OAuth work?

An authenticated business starts a one-use expiring state/S256 PKCE flow with fixed
redirect and Google hosts. Callback uses saved state authority without X-API-Key,
exchanges the code using the verifier, validates exact readonly scope/Bearer/expiry,
and obtains authenticated getProfile mailbox identity before committing ownership.
Tokens stay in bounded RAM, refresh is serialized and disconnect/expiry/shutdown
clear state. All Google interactions have been mocked; live acceptance is unverified.

### 16. Why does Gmail request read-only permission?

Selected feedback analysis needs message reading, not sending, deleting, replying
or label mutation. The application narrows behavior further to an existing configured
feedback label/date window and bounded messages. Readonly still grants access to
private mail and is a restricted Google scope; it does not automatically establish
user-data policy approval. Whole attachment-bearing messages are skipped before
body-data retrieval, and no attachment API is called.

### 17. Which integrations have been tested live?

Only one previously authorized synthetic direct T01 Groq service request is recorded
as live verified: openai/gpt-oss-20b, HTTP200/native strict/Pydantic/evidence,
1.4903seconds/1,371tokens. Other interfaces have local/mocked provider verification.
MCP uses real local protocol clients, and startup has real loopback HTTP checks.
Gmail OAuth/messages, commercial webhook delivery and deployment have not been
live verified. No new external provider calls occurred for this submission.

### 18. What are the current limitations?

The original reviewer assignment is unavailable. Gmail is mock-only and public
Google approval is unverified. Model/selector accuracy and arbitrary-summary truth
are unmeasured. State/ownership/tokens/jobs/dedup are one-process RAM and disappear
on restart; there is no durable/distributed/exactly-once guarantee. Chat is stateless,
MCP has two local tools, attachment-bearing messages skip, and disconnect does not
revoke Google's grant. Production encrypted OAuth storage/deployment are future scope.

### 19. How could the system scale later?

A separately authorized design would need durable encrypted credential/metadata
storage, distributed ownership/idempotency, shared global/per-tenant admission and
a bounded recoverable job mechanism. Current multiple ASGI workers would have
independent state and cannot supply those guarantees. Measure workload first and
choose the smallest justified infrastructure; none is added or required for this
local reviewer demonstration.

### 20. How would sentiment accuracy be improved?

Agree a representative labeled synthetic/deidentified evaluation dataset and
criteria for sentiment, aspects, category, urgency, selector intent and grounded
summaries. Measure errors by class/domain, then evaluate prompt/schema/model
changes against held-out cases and resource/privacy constraints.571 passing tests
and one live sample are not an accuracy percentage. New paid/live evaluation needs
separate authorization; this package claims integration and calculation correctness.
