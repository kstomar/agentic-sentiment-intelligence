# API contracts — T08

[OpenAPI](../../openapi.json) has19 paths/operations: all12 pre-T08 operations compare
exactly equal, plus seven Gmail operations. Every existing component schema is
unchanged except21 additive Gmail ErrorCode values. No old body/parameter/security/
success response object changed. [Exact comparison](../../t08-compatibility.json) lists
paths/codes and confirms hash-identical T01 classifier/prompt/schema, graph, MCP
and dependency files. [T07 snapshot](../pre-t08/API_CONTRACT_REPORT.md).

## Additive Gmail API

All paths below share /api/v1/integrations/gmail:

| Method/path | Authority | Response |
| --- | --- | --- |
| POST /connect | X-API-Key + gmail:connect | 200 GmailConnect authorization URL + expiry |
| GET /oauth/callback | GmailOAuthState single-use state, no API key | 200 GmailOAuthComplete status CONNECTED |
| GET /status | X-API-Key + gmail:read | 200 GmailConnectionStatus, owner mailbox only |
| DELETE /disconnect | X-API-Key + gmail:connect | 200 GmailDisconnected |
| POST /import | X-API-Key + gmail:import | 202 GmailAccepted |
| GET /imports/{job_id} | X-API-Key + gmail:read + owner | 200 GmailJobStatus |
| GET /imports/{job_id}/results | X-API-Key + gmail:read + owner | 200 GmailResults |

Import accepts only a strict integer max_messages1–100, constrained additionally
by configured maximum (default20). `{}` uses the configured default; no caller query,
mailbox or tenant selection. Job paths require32 lowercase hex; malformed422,
foreign/unknown/expired well-formed IDs404 GMAIL_JOB_NOT_FOUND. Results are bounded
and typed, with mutually consistent SUCCESS/FAILED/SKIPPED/DUPLICATE and analysis/
error fields. Analysis is the existing SentimentResponse; Gmail remains integration
metadata, source=email is existing allowed input. No OAuth token or raw body field.

Callback accepts state plus exactly one code/error, rejects duplicates/unknown
query arguments and ignores documented Google descriptive fields. State captures
verified initiating identity, expires/consumes once and never accepts a query tenant.
No API key header is needed for Google's redirect. Authorization URL contains
state/challenge/client ID but no secret/verifier; treat as sensitive metadata.
Callback security appears as APIKeyQuery GmailOAuthState in OpenAPI to describe
state authority; it is not a reusable API credential.

Gmail permissions append gmail:connect, gmail:import, gmail:read. Explicit existing
permission arrays keep their scope; omitted arrays now default to all ten normal
permissions. Production/legacy policy, identity proofs and owned batch/event
checks are unchanged. Disabled/incomplete/unsafe Gmail configuration yields503
GMAIL_NOT_CONFIGURED without making Gmail credentials mandatory for startup.
All Gmail errors use existing ErrorResponse and sanitized fixed codes/messages.
Scope failure400, OAuth exchange/provider shape errors502, missing/reconnect or
mailbox conflict409, capacity/rate429, deadline504. Full mapping is in the guide.

## Existing behavior and transport policy

T01–T07 route operations, supported sources, batch omission/valid source behavior
and original QA-005 blank/whitespace422 remain unchanged. HMAC verifies original
bytes; webhook16KiB, multipart2MiB and approved global4MiB JSON413 behavior remain.
Global/tenant controls apply to Gmail; the unauthenticated callback uses global
admission and an8KiB query cap, then state authority. No unknown input defines quotas.

Private responses additionally send Referrer-Policy:no-referrer, and application
Uvicorn access logging is suppressed to avoid OAuth query diagnostics. These are
intentional privacy transport changes outside the old OpenAPI operation objects.
No MCP tool/schema/transport was added or changed; exactly two launcher-authorized
stateless tools remain. No new graph, classifier or dependency.

**571/571 pass, all447 baseline plus124 new cases, 0 failed/skipped/errors.**
[JUnit](../../t08-full.xml), [execution](../../TEST_EXECUTION_REPORT.md),
[tenant policy](../../../TENANT_ISOLATION.md), [Gmail guide](../../../GMAIL_INTEGRATION.md).
Live Google and restricted-scope approval remain NOT VERIFIED. T09 not started.
