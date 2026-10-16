# API contracts — T07

[Current OpenAPI](../../openapi.json) retains exactly12application paths/operations:
public health, ten API-key protected operations and one separately signed webhook.
No new endpoint, request-body tenant field, query selector, response tenant field
or MCP capability was added. [Comparison evidence](../../t07-compatibility.json).

All existing request bodies/parameters, success models/defaults, auth scheme names,
prior declared responses and analysis enums remain equal to the T06 snapshot.
Changes: three additive ErrorCode values (AUTHORIZATION_FAILED,
TENANT_CAPACITY_EXCEEDED, WEBHOOK_DELIVERY_COLLISION),403 declarations on ten REST operations, updated
DevelopmentAPIKey description and owner-scoped event-status summary. The actual
ErrorCode additions are listed precisely in compatibility evidence; error/status
codes below define the policy. APP_AUTH_NOT_CONFIGURED now says configure server
credentials generally, rather than incorrectly recommending APP_API_KEY in production.

## Authentication and owned responses

X-API-Key is now verified against private tenant registry rows. Existing development
APP_API_KEY still works in documented compatibility mode, owning only development.
Business registry mode requires explicit true for legacy nonproduction access;
production always ignores legacy API and single-webhook configuration. Bad registry
configuration aborts startup with safe errors; no fallback occurs. Required headers
and HMAC canonical bytes are unchanged. Registry data is not exposed by OpenAPI.

| Condition | HTTP/code |
| --- | --- |
| Missing/invalid API key | 401 AUTHENTICATION_FAILED |
| Missing configured API authentication | 503 APP_AUTH_NOT_CONFIGURED |
| Authenticated but permission missing | 403 AUTHORIZATION_FAILED |
| Foreign/unknown/expired batch | 404 BATCH_JOB_NOT_FOUND |
| Foreign/unknown/expired event | 404 WEBHOOK_EVENT_NOT_FOUND |
| Per-business quota | 429 TENANT_CAPACITY_EXCEEDED |
| Same tenant/delivery, different integration | 409 WEBHOOK_DELIVERY_COLLISION |
| Same integration/delivery, changed raw bytes | Existing409 WEBHOOK_DELIVERY_CONFLICT |
| Identical authenticated retry | Existing200 DUPLICATE, no new analysis |
| New admitted signed event | Existing202 ACCEPTED, not provider success |

Batch status/report/results/download shapes and pagination remain. Every read
checks verified owner before data return, including direct service/store use.
Event lookup route remains delivery-only; trusted tenant scoping disambiguates
cross-business reuse. IDs must be unique across integrations of one tenant during
retention, so a second integration409 rather than overwriting or claiming a record.

Global4 MiB JSON 413 policy, webhook 16 KiB, multipart2 MiB+64 KiB, existing provider errors,
read deadlines and global429 remain. New owner quotas are configurable and may
return 429 under pressure while preserving headroom. Tenant is not a model input.
Legacy-only development retains previous T06 capacities. No foreign existence is
revealed through errors. ErrorResponse/request IDs/no-store/privacy remain.

## Python and configuration compatibility

Owned Python calls now require a verified Principal argument or authenticated
principal_context; omitting both fails401. Webhook accept requires verified typed
signed context, not an arbitrary integration string. Store maintenance is private;
public inspection requires permission and is owner-filtered. Existing test fixtures
supply authenticated authority and keep behavioral assertions. Stateless AI service
inputs/results remain unchanged. No dependency/MCP source/transport change occurred.

Registry/configuration schemas, generation, rotation, legacy mode and effective
quotas are documented in [TENANT_ISOLATION.md](../../../TENANT_ISOLATION.md).
Configuration restart loses all in-memory state; no durable rotation claim exists.

**447 collected; 447 passed; 0 failed, 0 skipped, 0 errors; 11.461 seconds (console 11.46 s), exit 0.**
Existing REST/graph/batch/MCP and 330 baseline cases pass with 117 new cases.
QA-005's original blank-source regression and source behavior remain unchanged.
[T06 contract history](../pre-t07/API_CONTRACT_REPORT.md) and original audit
are retained. [Full report](../../T07_IMPLEMENTATION_REPORT.md).
