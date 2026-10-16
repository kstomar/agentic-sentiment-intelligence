# API contracts — T06

Generated [OpenAPI](../../openapi.json) contains **12 application operations**.
The nine prior operations remain, with unchanged request models, success response
schemas/defaults and allowlists. Public health is unchanged. REST uses
DevelopmentAPIKey; the new webhook uses FeedbackHMAC separately. Framework docs
routes are outside this count. [Comparison](../../t06-compatibility.json).

| Method | Path | Success | Authentication |
| --- | --- | --- | --- |
| GET | /health | 200 HealthResponse | Public |
| POST | /api/v1/sentiment/analyze | 200 SentimentResponse | X-API-Key |
| POST | /api/v1/agent/investigate | 200 InvestigationResponse | X-API-Key |
| POST | /api/v1/chat | 200 ChatResponse | X-API-Key |
| POST | /api/v1/batch/upload | 202 JobAccepted | X-API-Key |
| GET | /api/v1/batch/jobs/{job_id} | 200 JobStatus | X-API-Key |
| GET | /api/v1/batch/jobs/{job_id}/report | 200 BatchReport or 202 JobStatus | X-API-Key |
| GET | /api/v1/batch/jobs/{job_id}/results | 200 ResultsPage | X-API-Key |
| GET | /api/v1/batch/jobs/{job_id}/download | 200 BatchDownload or 202 JobStatus | X-API-Key |
| POST | /api/v1/ingest/feedback | 200 IngestionResponse | X-API-Key |
| POST | /api/v1/webhooks/feedback | 202 ACCEPTED or 200 DUPLICATE | Four signed HMAC headers; no API key |
| GET | /api/v1/ingest/events/{delivery_id} | 200 EventStatus | X-API-Key, development/admin |

New contracts and executable signing example:
[WEBHOOK_INTEGRATION.md](../../../WEBHOOK_INTEGRATION.md). Direct input uses existing
T01 text/source/business validation, channel enum, optional bounded ID. Webhook
supports only customer.feedback.created and nested bounded id/text. Both forbid
extra fields. Webhook HMAC covers original bytes before parsing; OpenAPI declares
all required signed headers and the payload. Status returns only delivery_id,
state and nullable controlled error_code, never results/raw feedback.

## Intentional compatibility changes

The user explicitly approved configurable **4 MiB / 4,194,304-byte JSON limits**
with HTTP 413 above actual bytes for T01–T03 and direct ingestion. Previously
accepted larger whitespace-heavy JSON now rejects; this is an intentional policy
change, not an unchanged contract claim. Existing 2 MiB padded JSON and Unicode
within the cap remain accepted. Webhook16KiB and multipart 2 MiB file + 64 KiB envelope
remain separate. Chunked/misleading Content-Length requests cannot bypass caps.

Global ingress/model capacity/rate limits add fail-fast429 under pressure and
body-read deadline408. Early REST authentication precedes parsing, so invalid
credentials reject before potentially invalid/oversized bodies. Existing ErrorResponse
and request-ID formats are retained. New ErrorCode enum values are additive;
new 408/413 declarations are additive. The batch router inherits408 declarations
on all its operations, though body reads/deadlines apply only to POST upload.
All prior declared responses and old operation fields remain equal to baseline.

## New statuses/errors

401 invalid REST or HMAC/time/headers; 422 invalid schema/event; 413 excessive
body; 408 read deadline; 409 delivery conflict; 429 global intake/rate/model or
queue/retention exhaustion; 503 missing webhook/local provider configuration or
stopped workers; 404 unknown/expired event; existing direct provider failures
remain controlled. All validation errors omit rejected values. Event/ingestion
responses are no-store/nosniff. Invalid authentication never gains duplicate access.

202 is local acceptance only: fixed workers may later mark FAILED, including on
provider/model capacity errors. No background result lookup exists. Identical
raw bytes with fresh signed timestamp deduplicate; changed serialization conflicts.
Terminal TTL defaults1,800 seconds; restart loses identity reservations. No tenant claim.

## Regression and history

330 tests pass: all existing REST, schema, graph, batch/report and official MCP
protocol paths plus 110 new cases. Only two old inventory expectations changed,
for three authorized endpoints/security. New byte boundaries and Unicode are tested.
Existing MCP analyze_feedback/investigate_feedback discovery, argument/result
schemas and stdio behavior are unchanged; MCP source was not modified.

QA-005 remains RESOLVED: raw FormData blank-source guard enforces existing 422,
omitted source uses file_upload, valid custom nonblank labels <=64 remain valid.
T01/MCP source allowlists are separate and unchanged. Original root cause and
focused evidence: [QA005_REMEDIATION_REPORT.md](../../QA005_REMEDIATION_REPORT.md).
[Pre-T06 contract](../pre-t06/API_CONTRACT_REPORT.md) and
[original contract audit](../original-audit/API_CONTRACT_REPORT.md) preserve
prior nine-route/unchanged-schema findings as history.
