# Persistent external feedback ingestion

Updated 4 November 2026. Direct and signed-webhook ingestion share the existing
IngestionService/T01 classifier. PostgreSQL now retains validated original feedback,
the actual structured analysis and tenant-scoped idempotency. There is no additional
model, graph or retrieval inference. Use one application coordinator, enforced by
the existing database advisory lock; no distributed or exactly-once claim.

## Configure and migrate

Use README's project-local uv/Python exports, private PostgreSQL DATABASE_URL and
existing API/integration registries. Apply the additive revision before starting:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The ingestion revision feedback_results_v1 follows t09_batch_v2 and creates feedback_events;
current head gmail_incremental_v1 additionally creates the Gmail tracking ledger;
existing batch migrations/tables/data remain. [PostgreSQL setup](POSTGRESQL_BATCH_STORAGE.md).
No SQLite fallback. Missing DB configuration makes ingestion unavailable; missing
migration/unreachable configured DB fails startup safely. No private .env edit is
performed automatically. Live provider credentials must remain private.

## Direct ingestion

POST /api/v1/ingest/feedback requires X-API-Key and feedback:ingest:

```json
{"feedback_id":"WEB-1001","text":"The delivery was late.","channel":"website","source":"customer_review","business_type":"ecommerce"}
```

The existing HTTP200 body remains feedback_id, channel, status ANALYZED and the
unchanged SentimentResponse in analysis. The endpoint is still synchronous and
uses one existing classifier operation. Optional feedback_id is trimmed/nonblank,
maximum100 characters; text remains exact, nonblank, maximum5,000 characters.
channel: website/mobile_app/support_platform/external_api. source defaults
customer_review and permits customer_review/support_ticket/email/social_media/manual;
business_type defaults general and permits ecommerce/restaurant/software/banking/general.
Extra fields, including tenant claims, fail validation as before.

After durable admission, responses add X-Feedback-Delivery-Id (server-generated)
and a relative Location: /api/v1/ingest/events/{delivery_id}/result. Save these headers;
they also accompany controlled provider errors after reservation. Failures before
reservation have no event ID. The original error body/status is unchanged. Repeated
GETs use the persisted outcome. Repeating direct POST creates a new event and
new inference; it has no caller-idempotency contract. Gmail's internal use of the
shared IngestionService does not persist emails in this table.

## Signed trigger

POST /api/v1/webhooks/feedback uses HMAC-SHA256, without X-API-Key. Configure private
WEBHOOK_INTEGRATIONS_JSON entries with integration_id, tenant_id and shared_secret;
the owner must exist in the server registry. Production ignores the legacy shared
key/single-integration fallback. [Business configuration](TENANT_ISOLATION.md).

| Required header (exactly once) | Contract |
| --- | --- |
| X-Feedback-Integration-Id | Configured ASCII identifier |
| X-Feedback-Delivery-Id | Caller-created ASCII identifier; unique within its authenticated tenant |
| X-Feedback-Timestamp | Canonical positive decimal Unix seconds, max12 digits |
| X-Feedback-Signature | sha256= followed by64 lowercase hex digits |

Identifiers match [A-Za-z0-9][A-Za-z0-9_-]{0,99}. Past/future skew is at most
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS (default300 seconds). HMAC is computed over:

```python
canonical = f"{integration_id}.{timestamp}.{delivery_id}.".encode("utf-8") + raw_body
signature = "sha256=" + hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
```

Sign the exact bytes sent. HMAC/time/integration checks run on every attempt,
including duplicates, before JSON parsing/reservation. Body bytes are never
reserialized for signature/digest comparison. Service submission also verifies
that the normalized stored request matches the signed payload.

```json
{"event_type":"customer.feedback.created","feedback":{"id":"WEBHOOK-TEST-001","text":"My order was delivered five days late, and customer support has not responded to my complaint."},"source":"customer_review","business_type":"ecommerce"}
```

Only customer.feedback.created is allowed. Existing schemas enforce ID/text/source/
business rules; normalization sets channel external_api. Payload/model fields never
authorize tenant access or tool execution.

## Acknowledgment, durable idempotency and concurrency

- New valid event:202 with unchanged delivery_id, status ACCEPTED and message
  "Feedback event accepted for analysis." The input/identity transaction commits
  before queueing/acknowledgment.202 is not proof of successful classification.
- Same tenant+delivery+integration+exact raw bytes:200 DUPLICATE, message unchanged,
  no queueing/classifier call. Fresh valid timestamp/signature is required.
- Same delivery/integration with changed bytes, even whitespace:409
  WEBHOOK_DELIVERY_CONFLICT. A different integration within the same tenant gets409
  WEBHOOK_DELIVERY_COLLISION. Neither overwrites the existing event.
- Another tenant can independently use the same delivery ID. Invalid HMAC401 always
  precedes duplicate handling. Registry identity, never request JSON, owns the row.

A timestamp-independent SHA-256 digest preserves the original exact-byte identity.
Unique tenant+delivery plus a short transaction advisory lock make lookup, quotas
and insertion atomic, including concurrent new-key races. No signature/header,
API key, secret, principal proof or access token is stored. Deduplication survives
process restart for as long as the event is retained, including failed events.
A failed/interrupted retained delivery cannot be restarted by resubmitting it;
any intentional new attempt needs a new delivery ID and incurs a new provider call.

## Status and original-result retrieval

Both GETs require an owning business X-API-Key with events:read. HMAC credentials
are not business-read credentials. Missing/invalid key401, missing permission403,
foreign/unknown/explicitly expired delivery404 WEBHOOK_EVENT_NOT_FOUND. Tenant and
delivery predicates run in SQL, before data is returned. Legacy development keys
own only development, not business records.

GET /api/v1/ingest/events/{delivery_id} remains HTTP200 EventStatus with exactly
its prior body: delivery_id, status and safe error_code. It never returns feedback
or analysis and never invokes Groq.

GET /api/v1/ingest/events/{delivery_id}/result:

| State | HTTP and body |
| --- | --- |
| ACCEPTED / PROCESSING |202 EventStatus only; no fabricated/null success result |
| COMPLETED |200 EventResult with original normalized feedback and actual saved SentimentResponse |
| FAILED |200 EventResult with saved feedback, analysis null and safe error_code |

EventResult fields: delivery_id, status, integration_id (null for direct), event_type
(null for direct), feedback (existing IngestionRequest with feedback_id/text/source/
business_type/channel), analysis, error_code, created_at/updated_at/completed_at.
Timestamps are timezone-aware ISO8601. Original feedback text is preserved exactly;
existing feedback-ID normalization/defaults apply. SentimentResponse fields remain
sentiment, issue_category, urgency, aspects, summary, suggested_next_step and
evidence_phrases. Stored outcomes are revalidated against saved text; invalid stored
analysis fails closed503 rather than reclassifying or returning fabricated output.
All private responses retain no-store, no-cache, nosniff and no-referrer headers.
No credential, tenant registry, internal write token or raw exception is returned.

## Lifecycle and explicit restart policy

Two fixed workers, the existing bounded queue and shared global/tenant model limits
remain. PROCESSING commits before inference; its transaction closes before the model
await. The actual validated result commits before COMPLETED. No combined prompt or
second classification is introduced. Direct requests similarly reserve before
classification and commit before returning their successful body.

Completed/failed feedback and results survive application-process restart. Startup
under the exclusive coordinator marks all unfinished ACCEPTED/PROCESSING records
FAILED with INGESTION_INTERRUPTED, analysis null, completion timestamp and the
original input preserved. There is **no automatic inference replay**, even if a
provider response was received but not committed. Graceful shutdown marks queued/
active work FAILED/WEBHOOK_UNAVAILABLE. Cancellation shields terminal writes from
ASGI/AnyIO cancellation. A result-commit failure never claims completion; new
ingestion admission fails closed until restart, which reconciles unfinished rows.
No exactly-once guarantee: a caller choosing a new delivery ID creates new work.

INGESTION_RESULT_TTL_SECONDS defaults0, retaining terminal input/results/digests
indefinitely. Positive seconds explicitly enable terminal cascading expiry/deletion
and must cover at least twice timestamp skew. Active rows never expire/evict.
WEBHOOK_EVENT_TTL_SECONDS retains its historical memory-adapter/minimum-replay
configuration; it does not impose a hidden30-minute expiry on PostgreSQL results.
Global WEBHOOK_MAX_RETAINED_EVENTS and TENANT_MAX_RETAINED_EVENTS include direct
and webhook rows (defaults100 globally/20 per tenant). Full history rejects new work
with429, preserves history and still admits authenticated duplicates. Configure an
intentional retention/capacity policy rather than deleting customer data silently.

Original text, summaries and exact evidence are sensitive durable data. Protect
DB access/storage, configure server/proxy statement logging privately and apply
appropriate backup access/encryption/expiry policies. No plaintext token file is
created; Gmail/OAuth remains process-local. Application restart persistence is
verified; whole-environment replacement/backup-restore durability is not. The local
available PostgreSQL12.22 is end-of-life; supported-server verification remains a
production gate. Pre-update lost in-memory events cannot be backfilled.

## Preserved resource controls and errors

JSON cap4 MiB actual bytes, webhook cap16 KiB, multipart file cap2 MiB remain distinct.
The T06 approved413 compatibility policy is unchanged. Global defaults16 protected
requests,120 admissions/minute,15-second intake deadline and four logical REST model
operations remain; webhook defaults20 pending, two workers,60-second processing
deadline. Per-owner quotas/headroom remain. Upload/report/MCP/Gmail behavior is
unchanged. No distributed/transport-wide DoS guarantee is made.

Existing ErrorResponse contains fixed safe code/message and request_id. Authentication
401; schema422; body413/408; conflict409; quota429; unavailable503; unknown404.
Provider errors keep existing direct status codes; background failures are visible
through FAILED status/result. A default database failure is WEBHOOK_UNAVAILABLE,
never SQL/parameters/URL/credentials. INGESTION_INTERRUPTED is a new stored terminal
error, not a new success field or inference fallback.

## Postman and verification

Import the [shareable collection](postman/feedback-results.postman_collection.json)
and [blank-secret environment](postman/feedback-results.postman_environment.json).
[Exact walkthrough](POSTMAN_FEEDBACK_RESULTS.md) uses Web Crypto HMAC, stores the
original delivery/body, retrieves the original result, tests duplicates/conflicts/
security and compares the same ID after a manual restart. No npm signing dependency.
The runner's bounded status polling is not a benchmark or batch-inference tool.
[Tutorial and actual evidence](qa/FEEDBACK_PERSISTENCE_REPORT.md) distinguish real
PostgreSQL/mocked-provider verification from live/Postman acceptance, which was not
performed by this implementation task.

## Working standard-library sender

Set the same placeholders privately in the receiving app and sender before use.
This sample makes a real request only when you explicitly run it. T06 verification
did not run this against Groq or any external host.

```python
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

integration_id = "YOUR_INTEGRATION_ID"
secret = "REPLACE_WITH_YOUR_PRIVATE_HIGH_ENTROPY_SHARED_SECRET"
delivery_id = uuid.uuid4().hex  # retain this ID and exact body for retries
timestamp = str(int(time.time()))
raw_body = json.dumps({
    "event_type": "customer.feedback.created",
    "feedback": {"id": "SYNTHETIC-1", "text": "Delivery was late."},
    "source": "customer_review", "business_type": "general",
}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
canonical = f"{integration_id}.{timestamp}.{delivery_id}.".encode("utf-8") + raw_body
signature = "sha256=" + hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/webhooks/feedback",
    data=raw_body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Feedback-Integration-Id": integration_id,
        "X-Feedback-Delivery-Id": delivery_id,
        "X-Feedback-Timestamp": timestamp,
        "X-Feedback-Signature": signature,
    },
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        print(response.status, json.loads(response.read()))
except urllib.error.HTTPError as error:
    print("Request rejected:", error.code)  # never print signed headers or secrets
```

Use HTTPS at a verified deployment boundary. The loopback URL above is for local
development only. The app must also have working Groq configuration; receipt is
rejected before acknowledgment when local T01 configuration is unavailable.

