# API contract verification

The generated [OpenAPI snapshot](openapi.json) contains exactly **nine HTTP
operations**. `test_api_contracts.py` checks schemas, security definitions,
response declarations, all module imports, and effective route traversal in
FastAPI 0.162.0, including deferred included routers. The complete generated
OpenAPI document is identical to the pre-audit snapshot.

## Endpoint inventory

| Method | Path | Request | Success response | Authentication |
| --- | --- | --- | --- | --- |
| GET | `/health` | None | 200 `HealthResponse` | Public |
| POST | `/api/v1/sentiment/analyze` | `SentimentRequest` JSON | 200 `SentimentResponse` | DevelopmentAPIKey |
| POST | `/api/v1/agent/investigate` | `InvestigationRequest` JSON | 200 `InvestigationResponse` | DevelopmentAPIKey |
| POST | `/api/v1/chat` | `ChatRequest` JSON | 200 `ChatResponse` | DevelopmentAPIKey |
| POST | `/api/v1/batch/upload` | Multipart file/mappings/business/source | 202 `JobAccepted` | DevelopmentAPIKey |
| GET | `/api/v1/batch/jobs/{job_id}` | Validated path ID | 200 `JobStatus` | DevelopmentAPIKey |
| GET | `/api/v1/batch/jobs/{job_id}/report` | Validated path ID | 200 `BatchReport`, or 202 `JobStatus` while active | DevelopmentAPIKey |
| GET | `/api/v1/batch/jobs/{job_id}/results` | ID, page, page_size | 200 `ResultsPage` | DevelopmentAPIKey |
| GET | `/api/v1/batch/jobs/{job_id}/download` | Validated path ID | 200 `BatchDownload` JSON attachment, or 202 `JobStatus` | DevelopmentAPIKey |

No external-ingestion, webhook, debug, arbitrary execution, or remote MCP route
exists. Framework documentation routes are separate from these application
operations and are configurable by environment.

## Schemas and constraints

- `SentimentRequest`: required strict nonblank text, maximum 5000 characters;
  existing source/business allowlists; unknown fields forbidden.
- `SentimentResponse`: sentiment/category/urgency enums, bounded aspects and
  text, exact source evidence. Invented evidence produces a controlled failure.
- `InvestigationRequest`: nonblank question <=500, 1–10 records with unique
  nonblank string IDs <=100 and text <=5000, existing business allowlist.
- `InvestigationResponse`: selected action, deterministic answer, reconciled
  totals, primary issue groups, verified source evidence, tools, limitations,
  tentative recommendations. Four actions have tested conditional tool paths.
- `ChatRequest`: explicit mode/message and compatible current feedback payload.
  `ChatResponse` contains exactly one result and preserves verified findings.
- Multipart upload requires file and text_column. Optional id/date mappings must
  be distinct existing headers. Batch job IDs are 32 lowercase hex characters;
  page is 1–1,000,000, page_size is 1–100. Failed row results contain controlled
  codes without successful classification data; successful rows reuse T01 fields.
- Reports use successful records as the sentiment percentage denominator,
  deterministic two-decimal largest-remainder rounding, primary issue groups,
  unique record/aspect counts, supporting IDs, and verified excerpts. No success
  yields all-zero percentages.

Runtime validators additionally enforce nonblank and cross-field/uniqueness
rules; not all such semantics are fully expressible by JSON Schema keywords.

## Status codes and error contracts

Protected operations document `DevelopmentAPIKey` (`X-API-Key`) and response
schemas. Tests confirm 401 for absent/incorrect credentials; 503 for absent
server auth/provider configuration; 422 for invalid JSON/schema/mappings/IDs;
413 for oversized upload bodies/files; 415 for unsupported file type/MIME;
429 for exhausted batch capacity or provider rate limits; 404 for unknown jobs;
502 for invalid/upstream/authentication responses; 504 for provider deadlines;
and sanitized 500 for unexpected failures. Not every static error-map branch has
an independent HTTP test; lower-level worker/graph failures are additionally tested.

All HTTP errors use `ErrorResponse` with fixed code/message and request ID.
Validation details omit rejected values. The request ID matches the response
header. Batch responses include no-store/nosniff; downloads have generated safe
filenames. Active report/download requests return 202, not fabricated final data.

## Observed inconsistency

**QA-005:** README and `UploadOptions` require a nonblank supplied source label,
but an explicit empty multipart `source` is accepted as 202. The retained test
`test_explicit_blank_source_is_rejected` expects 422 and fails. Likely Form default
substitution occurs before the model validator sees the empty value. No assertion
or production contract was weakened to hide this mismatch.

## MCP contracts

MCP is a separate local stdio interface, not an HTTP endpoint. Official protocol
clients discover exactly `analyze_feedback` and `investigate_feedback` with typed
arguments and output schemas equal to the existing Pydantic result schemas.
Structured success uses `structuredContent`; tool failure uses `isError=true`,
safe error text, and no successful analysis payload. Context/services/keys are
not tool inputs. No batch lookup capability is exposed. Local process authority
differs from REST key authentication; neither provides tenant isolation.

## Documentation review

Reviewed README, AGENTS, architecture, patterns, MCP integration, and environment
examples. No webhook integration document exists. Local Markdown target checking
found zero broken links; external links were not exhaustively checked. MCP launch
instructions and absolute executable/cwd configuration were exercised through
the official SDK. README examples were compared structurally to tested request/
response models rather than sending credentialed curl examples externally.

Historical no-tests/no-MCP statements need temporal labels and the new QA commands
should be linked (QA-008). Deployment/security gaps are documented rather than
silently changed. No API contract or application source file changed in this audit.
