# Gmail incoming eligibility and partial-batch verification

6 November 2026. This focused extension excludes sent messages without replacing
Gmail OAuth, PostgreSQL tracking or shared sentiment validation. The sent message's
relationship to the two earlier INVALID_MODEL_RESPONSE failures remains unknown.
No live Gmail or Groq call was performed for this change.

## Root cause and selection rules

The prior query required the configured feedback label and recent date window but
had no outgoing-mail exclusion. MIME preflight rejected SPAM/TRASH but not SENT.
A custom label can coexist with SENT, so a labelled outgoing message could reach
sentiment analysis. Sender address is not a reliable substitute for Gmail labels.
This eligibility gap is confirmed in code; it does not establish the cause of the
historical model-validation errors.

Current rules:

1. Resolve the exact configured custom feedback label through the authenticated
   mailbox. Existing rejection of broad system-label configuration remains.
2. GET users/me/messages with labelIds set to that ID, q=`newer_than:Nd -in:sent`,
   includeSpamTrash=false and existing bounded maxResults/pageToken/fields. N is
   the existing server-side GMAIL_SEARCH_DAYS. No caller-selected query is accepted.
3. Validate IDs/page tokens as before. Batch-filter successful tracked identities
   in owner/mailbox-scoped SQL, so they incur neither label/body fetches nor inference.
4. For remaining candidates, GET users/me/messages/{id} with format=minimal and
   fields=id,labelIds. Validate identity and label-list shape. Exclude SENT before
   creating a claim, spending an attempt, counting selected_messages or fetching a
   body. Continue through the same page and then subsequent pages until enough
   eligible claims are selected, listing ends, or an existing safety limit is reached.
5. Claims still atomically recheck success, busy, retry and quota state after label
   checking. The new success-only lookup is an optimization, never ownership authority.
6. After selection, retain existing full-format MIME preflight without body data,
   then bounded inline text extraction. Both require the feedback label and reject
   SENT/SPAM/TRASH before inference. There is no INBOX requirement or sender-address
   comparison. Archived incoming feedback remains eligible.

The Gmail API documents q search filtering, including in:sent, and message-level
label filters in its [search guide](https://developers.google.com/workspace/gmail/api/guides/filtering).
The minus operator excludes matching search criteria per
[Google's search syntax](https://support.google.com/mail/answer/7190?hl=en).
[Minimal format](https://developers.google.com/workspace/gmail/api/reference/rest/v1/Format)
returns identity/labels without email headers, body or payload. Gmail's
[system-label documentation](https://developers.google.com/workspace/gmail/api/guides/labels)
identifies SENT independently of mailbox sender comparisons.

The extra label-only requests are bounded by the existing distinct-ID/page cap,
job deadline and shared Google operation/concurrency/retry/response-byte limits.
Only enough candidate metadata is fetched to fill remaining selection slots;
concurrent claim losses allow scanning the remaining page tail. Already successful
IDs need one batch SQL lookup per page, not per-ID queries. No transaction is open
during Google or Groq network calls.

A label may change after selection. If SENT appears in MIME preflight or the final
text response, the already-admitted record keeps the existing SKIPPED /
GMAIL_SELECTION_INVALID outcome; it never reaches Groq. Selection is not reopened
for that race. This is distinct from a SENT label observed before selection, which
consumes no selection slot and creates no message-tracking record.

## Partial/empty batches and failures

No minimum selected count is required. With max_messages=3 and only two new eligible
incoming messages, the job selects/processes two and is COMPLETED if both succeed.
With no new eligible IDs and genuinely exhausted listing, it completes with zero
selected, zero processed, zero model calls and scan_exhausted=true.

If a next page remains but the configured page budget ends, scan_limit_reached=true
and scan_exhausted=false, even if the job has zero selected. Capacity/error flags
retain their existing meanings. Reaching the requested count stops scanning without
claiming full exhaustion. No resultSizeEstimate or fabricated ID fills a batch.

Selected and outcome counters retain their API shapes. scanned_messages can include
query-leaked SENT IDs caught by metadata; those IDs do not appear in outcome counters
or previously_processed_messages. No new status field is needed: scanning already
includes repeated IDs and unselected page tails. Query-excluded IDs never enter the
application's scan count.

Eligible incoming model failures remain FAILED with analysis=null and their existing
error_code, including INVALID_MODEL_RESPONSE. The safe sentiment diagnostics and
strict structured output/evidence rules are untouched. Such failures retain their
durable attempts/cooldown; nothing is silently reclassified as outgoing mail.
Historical successful outgoing identities are not deleted or reprocessed by this
change. There is no automatic metadata reset or retry-budget increase.

## Files changed

Production:

- app/integrations/google_gmail.py — fixed -in:sent query and minimal validated label fetch.
- app/integrations/gmail_mime.py — SENT defense in the existing shared label check.
- app/services/gmail_service.py — preselection success/label filtering and bounded refill.
- app/storage/gmail_message_store.py — scoped batch success lookup interface/test adapter.
- app/storage/postgres_gmail_message_store.py — single scoped success-ID SQL lookup.

Tests:

- tests/integration/test_gmail_eligibility.py — new real-PostgreSQL acceptance/security cases.
- tests/t08_helpers.py — realistic optional sent-query filtering and minimal-format projection.
- tests/integration/test_gmail_import.py — updated query contract and extra label-only request.
- tests/integration/test_gmail_messages_transport.py — updated strict wire query expectation.
- tests/integration/test_gmail_provider_responses.py — updated query expectation.

Docs: README.md, docs/GMAIL_INTEGRATION.md, docs/GMAIL_INCREMENTAL_IMPORTS.md and this report.
No configuration, dependency, migration, OAuth scope, permission, schema, claim/lease,
retry or model/prompt change. Alembic head remains gmail_incremental_v1. Existing
GMAIL_MAX_MESSAGES_PER_IMPORT must allow the requested maximum (normal default 20
already allows 3 or 5); existing bulk profiles and scan limits remain applicable.
No private .env edit, Git operation or new provider diagnostic data was introduced.

## Automated verification

- Focused Gmail/OAuth/provider/MIME/PostgreSQL suite: **243 passed in 63.63 seconds**.
- Complete suite: **787 passed in 132.66 seconds; zero failures/errors/skips**.
- All 769 existing test identities retained, plus 18 new real-PostgreSQL cases.
- OpenAPI identical to the pre-change snapshot, including all 20 paths and schemas.
- All 80 installed packages compatible; dependency files and migrations unchanged.
- The first focused run found one new test counted the existing cleanup SELECT
  along with its batched success lookup. The test was corrected to distinguish the
  queries; production behavior needed no further change, and the rerun above passed.

Execution artifacts are `.local/qa/gmail-eligibility-focused.xml`,
`.local/qa/gmail-eligibility-full.xml`, `.local/qa/gmail-eligibility-summary.json`
and the source/API snapshots there. These are temporary local QA artifacts.

Tests use real isolated PostgreSQL with random schemas, mocked Gmail and mocked
Groq; network access is blocked by the fixture. Cases include query exclusion and
a deliberately query-leaking provider, five incoming plus one SENT, partial two,
empty incoming mail, archived/mailbox-sender headers, 2/2/1/0 plus application
recreation, page-budget vs exhaustion, invalid incoming model output, late SENT
races, invalid minimal metadata/HTTP 204, and batched owner/mailbox SQL filtering.
Existing OAuth, provider, Gmail limits, PostgreSQL retry/claim/tenant and earlier
API/MCP/graph regressions are retained.

After README's project-local Python/uv/cache exports, full reproduction on the
prepared isolated test server is:

```bash
T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket" \
  GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
```

For the focused new acceptance cases, use the same environment and add
`tests/integration/test_gmail_eligibility.py` to pytest. Full tests require the
isolated *_test database; without it, PostgreSQL cases skip. No live credentials
are needed. PostgreSQL 12.22 test-server/support limitations and the application's
single-coordinator requirement remain unchanged. Environment/backup retention is
not newly established by this task.

## Exact live Postman plan

1. Restart the application to load the changes using its existing private config:
   `uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log`.
   No migration/env update is needed for this feature. Connections/results remain
   RAM-only, so reconnect the same tenant/mailbox after restart.
2. Set Postman base_url to http://127.0.0.1:8000 and use the owning X-API-Key for
   protected requests. POST {{base_url}}/api/v1/integrations/gmail/connect with no
   body; open its private authorization_url and complete Google OAuth. GET
   {{base_url}}/api/v1/integrations/gmail/status should show CONNECTED. Do not export
   credentials, authorization URLs or OAuth query parameters.
3. In Gmail prepare five NEW synthetic incoming plain-text messages with the exact
   configured customer-feedback label, within the configured date window and not
   in Spam/Trash. Archive one. Also label one sent message. Existing successful
   IDs will deliberately not be reanalyzed, so use new IDs for a five-result check.
4. POST {{base_url}}/api/v1/integrations/gmail/import with Content-Type:application/json
   and body {"max_messages":5}. Save job_id. Poll
   {{base_url}}/api/v1/integrations/gmail/imports/{{job_id}} about every two seconds.
   Retrieve the same URL plus /results. If all five pass MIME/model validation,
   expect selected=processed=successful=5 and COMPLETED; no outgoing message result.
   The archived incoming message remains eligible. Genuine model errors stay visible.
5. Repeat with {"max_messages":3}. With no new eligible mail, expect selected=0,
   processed=0, COMPLETED and scan_exhausted=true, subject to retry/deferred states
   and scan/capacity limits. A true scan limit is not proof of an empty mailbox.
6. Add only two NEW eligible incoming messages. Submit {"max_messages":3}; if both
   succeed, expect selected=processed=successful=2, COMPLETED, scan_exhausted=true.
7. For a separate incremental check, add five more NEW eligible incoming messages
   and submit {"max_messages":2} four times after each prior job settles. With no
   other new/failing eligible mail and sufficient scan capacity, expect 2/2/1/0.
   Existing four earlier successes remain excluded; do not clear the durable table.

This plan is provided for manual live verification. These automated results alone
do not prove that the earlier live INVALID_MODEL_RESPONSE failures are fixed or
were caused by the outgoing message.
