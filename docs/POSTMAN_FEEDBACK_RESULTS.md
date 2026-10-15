# Postman: submit feedback and retrieve the original stored analysis

This is a manual acceptance walkthrough. The implementation task tested real
PostgreSQL with mocked inference, not the Postman desktop app or a live Groq account.
A new valid webhook invokes the configured classifier; status/result GETs and
identical authenticated retries do not. The optional direct POST is a second,
separately triggered analysis. Use synthetic feedback for demonstrations.

## 1. Run the database migration and API

From the project root, use README's local uv/Python exports and privately configure
the existing PostgreSQL DATABASE_URL, business API key/permissions, integration
registry and Groq key. The integration and reading API key must belong to the same
business. No secrets belong in this guide or shared exports.

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Head is feedback_results_v1. Use one application worker. To use the prepared local
cluster, see [PostgreSQL setup](POSTGRESQL_BATCH_STORAGE.md). Explicitly configuring
an older SQLite URL is unsupported. INGESTION_RESULT_TTL_SECONDS=0 retains terminal
feedback/results/digests indefinitely. Existing
WEBHOOK_EVENT_TTL_SECONDS=1800 does not delete PostgreSQL results after 30 minutes.

## 2. Import the collection and blank environment

Import both files using Postman's Import action:

- [feedback-results.postman_collection.json](postman/feedback-results.postman_collection.json)
- [feedback-results.postman_environment.json](postman/feedback-results.postman_environment.json)

Select the imported environment. Populate private local values:

| Variable | Required value |
| --- | --- |
| base_url | API URL; default http://127.0.0.1:8000 |
| integration_id | Configured webhook integration owned by the business |
| signing_secret | Its private HMAC shared secret |
| api_key | Business API key with events:read; feedback:ingest additionally needed for the optional direct demo |
| other_tenant_api_key | Optional valid key belonging to a different business, with events:read |
| review_text | Synthetic review; supplied default is the late-delivery/support example |
| verify_restart | Keep false until the actual manual restart; set true to send request10 |
| run_direct_demo | Default false; set true only to run requests11–12 and one additional analysis |

Keep credentials local/secret and blank in any exported environment. Saved review,
response and original-body variables also contain data; do not share populated
customer payloads. The sample files contain no API keys, signing secrets or passwords.

The pre-request script uses crypto.subtle HMAC with TextEncoder and SHA-256. It
signs integration.timestamp.delivery.exact_body, then sends those exact UTF-8 bytes.
It uses no npm/crypto-js dependency. A new delivery ID is generated only in request01.
Duplicates/conflicts reuse the original ID and receive a fresh timestamp/signature.
Literal review text containing Postman variable expressions is rejected by the
signer so interpolation cannot change bytes after signing. No script logs secrets.

## 3. Send request01: valid signed feedback

Open **01 Valid signed webhook: accept new event**, then Send:

```http
POST {{base_url}}/api/v1/webhooks/feedback
```

The script fills the four signed headers and this body from the environment:

```json
{"event_type":"customer.feedback.created","feedback":{"id":"WEBHOOK-TEST-001","text":"My order was delivered five days late, and customer support has not responded to my complaint."},"source":"customer_review","business_type":"ecommerce"}
```

Expected HTTP202, status ACCEPTED and the existing acceptance message. Both script
and response save event_delivery_id; event_original_body retains the exact bytes.
Do not send request01 again to retrieve the result: it creates another delivery.

## 4. Send request02: processing status

```http
GET {{base_url}}/api/v1/ingest/events/{{event_delivery_id}}
X-API-Key: {{api_key}}
```

Expected HTTP200 and the existing EventStatus body. Wait until COMPLETED before
the success demonstration. FAILED is a real safe outcome; inspect error_code and
request03, not a reason to submit the same review through sentiment/analyze.

When running the collection, the script polls at one-second intervals, at most
40 times, then stops. setNextRequest affects a Collection Runner run; individual
Send does not automatically repeat. Resend request02 manually if using Send.
See [official Postman workflow documentation](https://learning.postman.com/docs/tests-and-scripts/running-collections/building-workflows/).
This is bounded status polling, not repeated inference or performance testing.

## 5. Send request03: retrieve the actual stored analysis

```http
GET {{base_url}}/api/v1/ingest/events/{{event_delivery_id}}/result
X-API-Key: {{api_key}}
```

Expected HTTP200 after terminal completion. For a successful event, verify:

- status COMPLETED, the same delivery_id and feedback.feedback_id WEBHOOK-TEST-001.
- feedback.text exactly equals the submitted review; channel external_api and the
  validated source/business_type are retained.
- analysis contains the actual saved SentimentResponse: sentiment, issue_category,
  urgency, aspects, summary, suggested_next_step and evidence_phrases.
- Exact evidence phrases occur in the original feedback. No invented issues/values
  or extra response-formatting call is required.
- created_at, updated_at and completed_at are timezone-aware ISO8601 timestamps.

The script saves the whole response in event_result_before_restart. Send request03
again as often as needed: reads do not invoke Groq. While pending, the result route
returns202 EventStatus. Failed events return200 with original feedback, analysis
null and a safe error_code. Unknown/foreign records return404 without leaking data.

## 6. Send requests04–09: idempotency and security

| Request | Expected |
| --- | --- |
|04 Identical correctly signed delivery |200 DUPLICATE; no second classification |
|05 Invalid HMAC for that same delivery |401 WEBHOOK_AUTHENTICATION_FAILED |
|06 Same ID, modified body, valid new signature |409 WEBHOOK_DELIVERY_CONFLICT; original remains unchanged |
|07 Result with no key |401 |
|08 Result with deliberately invalid key |401 |
|09 Result with another tenant's valid key |404 |

Request09 is explicitly skipped when other_tenant_api_key is blank; a skipped case
is not evidence of isolation. Fill it to demonstrate the actual404. Postman supports
skipRequest in pre-request scripts; see [official execution reference](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-execution).
Missing events:read gives403 even when a credential authenticates successfully.
To see same-owner/different-integration collision, retry with the original delivery
and another correctly configured integration for that same owner:409
WEBHOOK_DELIVERY_COLLISION. A different owner's integration can independently use
the same delivery ID and cannot claim the first owner's resource.

## 7. Restart FastAPI and send request10 only

Stop Uvicorn with Ctrl-C. Keep PostgreSQL, DATABASE_URL, retained data, tenant identity
and Postman environment unchanged. Start the app again:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Set verify_restart=true. Send **10 MANUAL after FastAPI restart: same result**
using the original ID. It asserts exact JSON equality with event_result_before_restart.
Do not run request01 again or overwrite the saved snapshot. Resend request04 if
needed to prove duplicate detection also survived restart; it still returns200.
The collection cannot restart your server itself. Running request10 without an
actual restart only checks equality, not restart acceptance.

Unfinished events found at exclusive startup become FAILED/INGESTION_INTERRUPTED,
analysis null; their original input remains available. They are not automatically
reanalyzed. Gracefully cancelled work uses FAILED/WEBHOOK_UNAVAILABLE. A retained
failed delivery still deduplicates. Any deliberate new processing attempt requires
a new delivery ID and a new provider invocation.

## 8. Optional synchronous direct-ingestion demonstration

Set run_direct_demo=true and run request11. This performs one new analysis through
POST /api/v1/ingest/feedback, preserving the existing synchronous response body.
It saves X-Feedback-Delivery-Id as direct_delivery_id. The response also provides a
relative Location URL; controlled provider errors after admission keep those headers.

Send request12 to retrieve the same stored direct analysis by its server-generated
ID. Its analysis must equal the original synchronous response. Do not repeat
request11 merely to retrieve the result: direct POST has no idempotency key.

## Troubleshooting and actual verification limits

- 503: check migrated PostgreSQL/one coordinator, provider configuration and safe
  server error codes. A result-write failure stops new ingestion until restart;
  no completed result is fabricated.
- 404: check exact original ID, same DB/tenant and explicit retention. Old events
  processed before this feature were discarded in RAM and cannot be reconstructed.
- 429: global/owner ingress, model or retained-event quotas remain bounded; history
  is preserved. Configure explicit retention/capacity deliberately.
- 401: verify server integration identity, private secret, clock and signed exact
  bytes. A valid API key cannot replace HMAC for the webhook.

[Full contract](WEBHOOK_INTEGRATION.md), [implementation/test evidence](qa/FEEDBACK_PERSISTENCE_REPORT.md),
[Postman script checks](qa/feedback-persistence/postman-verification.json).
The signer was executed with Node Web Crypto and independently checked; the desktop
Postman/real-Groq workflow was not run by the implementation task. All persisted
integration tests use synthetic feedback, real isolated PostgreSQL and mocked inference.
