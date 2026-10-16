# Runtime architecture and data responsibilities

Current architecture, 6 November 2026. The [root README](../README.md) is the primary
setup/API/demo guide; [final audit](qa/FINAL_SUBMISSION_AUDIT.md) records actual
verification, limitations and submission status. Historical milestone reports are
not current architecture specifications.

## Shared services and interfaces

FastAPI composition in app/main.py creates one TenantRegistry, shared model
admission, SentimentService, InvestigationService, batch/ingestion/webhook services
and optional Gmail integration. Async HTTP clients live for the application
lifespan. SQL and file parsing run off the event loop. Routes validate transport
contracts and permissions, then delegate reusable logic.

SentimentService performs native strict Groq classification and final Pydantic
validation against original feedback. One grounding-specific correction can be
followed by deterministic exact-phrase filtering and full revalidation. Empty
model evidence provides no retained quotation or independent semantic support.
No additional model call is used for that sanitization.

InvestigationService invokes one compiled StateGraph. The question-only selector
chooses four validated actions, producing three distinct paths after per-record
analysis: overview → verification; evidence search → retrieval → verification;
issue/general summary → aggregation → retrieval → verification. Final answers,
counts and recommendations are deterministic Python. State is request-local;
no checkpoint, persistent memory, observation-driven replanning or graph cycle.

Chat explicitly delegates ANALYZE_TEXT or INVESTIGATE_FEEDBACK. No chat history
or automatic intent routing exists. Batch processing is separate from this graph:
one task per admitted job, independent row classification, deterministic reports.

Local MCP is a separate stdio process using the same factories, with exactly
analyze_feedback and investigate_feedback. Its authority is the trusted launcher,
not a REST API key or caller-supplied tenant. It exposes no owned-resource lookup.
Separate processes do not share budgets or memory. External-host testing is pending.

## Data and restart boundaries

| Subsystem | Durable state | Temporary state / restart |
| --- | --- | --- |
| Batches | PostgreSQL jobs, row outcomes, report inputs; raw pending text until outcome commit | Active tasks/permits; restart recovers authorized unfinished rows after leases |
| Direct/webhook ingestion | PostgreSQL original feedback, validated analysis, errors, exact-byte digest and tenant/delivery identity | Fixed worker queue; unfinished startup events become FAILED/INGESTION_INTERRUPTED without replay |
| Gmail | PostgreSQL tenant/mailbox-hash/message identity, bounded attempts, retry/error/timestamps, fenced claims | OAuth state, tokens, mailbox ownership reservations, jobs/results; reconnect after restart |
| Chat/investigation | None | Request state only |
| Local MCP | None | Lifespan services; client host can separately retain inputs/results |

PostgreSQL models share one Base and migrations. Head is gmail_incremental_v1,
after feedback_results_v1 and the two T09 batch revisions. No SQLite fallback.
Ephemeral stores are explicitly injected historical test adapters, never automatic
production fallback. Default terminal batch/ingestion retention is indefinite,
with finite quotas and explicitly configurable expiry. Gmail success identities
do not expire with job TTL; history is not silently evicted.

## Security and lifecycle

REST derives immutable principals from a private bounded credential registry;
services/stores revalidate sensitive authority. SQL predicates scope owned resources
to verified tenant IDs. Legacy keys are development-only; production disables them.
HMAC authenticates exact webhook bytes plus integration/timestamp/delivery headers
on every retry. Durable reservation precedes acknowledgment/inference. Direct POST
has a new server ID per call; only signed delivery identities provide idempotency.

Gmail uses fixed Google endpoints, exact gmail.readonly, S256 PKCE, single-use
state, issuer validation, token-response scope checks and authenticated mailbox
identity. Query and metadata checks exclude SENT without excluding archived
incoming mail. MIME preflight rejects attachment-bearing messages before body
fetch; text extraction is bounded and inert. OAuth data never enters inference.

Actual-byte/body deadlines, active/rate/tenant/model quotas, bounded queues and
fixed workers prevent unbounded admitted work. They do not replace transport-level
protection. One database advisory-locked application coordinator is supported;
no distributed or exactly-once execution guarantee. Transactions close before
provider awaits; claims use leases and fencing. Cancellation waits for commits.

## Current operating guides

- [Patterns and exact catalogue mappings](AGENTIC_PATTERNS.md)
- [Business credentials/permissions](TENANT_ISOLATION.md)
- [PostgreSQL lifecycle/setup](POSTGRESQL_BATCH_STORAGE.md)
- [Batch recovery](BATCH_PERSISTENCE.md)
- [Persistent direct/webhook contracts](WEBHOOK_INTEGRATION.md)
- [Gmail OAuth/MIME/security](GMAIL_INTEGRATION.md)
- [Incremental Gmail profile and counter meanings](GMAIL_INCREMENTAL_IMPORTS.md)
- [MCP setup and pending external-host acceptance](MCP_INTEGRATION.md)
- [Evidence sanitization and reduced-evidence trade-off](qa/EVIDENCE_SANITIZATION_REPORT.md)
