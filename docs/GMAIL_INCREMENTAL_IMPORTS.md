# Persistent incremental Gmail imports

6 November 2026. This extends the working explicitly triggered Gmail integration.
It uses the existing PostgreSQL/SQLAlchemy/Alembic infrastructure and shared T01
classifier. No scheduler, persistent Gmail page cursor, new graph/provider/client,
queue framework or OAuth-token storage is introduced.

## Selection and max_messages

POST `/api/v1/integrations/gmail/import` accepts the same request:

```json
{"max_messages":100}
```

The server must be configured to permit 100; the normal default cap remains 20 and
the absolute cap remains 100. max_messages now bounds eligible NEW work selected
for this job, including an eligible failed-message retry. Successful persisted
identities and unavailable attempts do not consume that capacity.

Each import starts listing from page=None using the exact configured label,
newer_than date filter, -in:sent and includeSpamTrash=false. Each metadata page requests the
server's configured GMAIL_MAX_MESSAGES_PER_IMPORT, independently of a smaller
request's NEW count. A 100-cap server can scan 100 IDs to find one new message for a
max_messages=1 request. Returned IDs/page tokens remain strictly validated; repeated
IDs across pages are counted once for eligibility. HTTP 204 remains a provider
failure, never a fabricated empty mailbox.

For each page, a batch SQL lookup scopes IDs to authenticated tenant + verified
mailbox hash and filters durable successes before network metadata checks. A minimal
id/labelIds request excludes SENT from remaining candidates before counting or
reserving them; no outgoing body is fetched for those exclusions. A short transaction
then atomically rechecks states and reserves eligible IDs. No INBOX requirement or
sender-address inference is introduced; archived incoming mail remains eligible.
The worker continues until its new-message count is met, listing ends, the configured
page budget is consumed, or tracking capacity is reached. No stable Gmail ordering
or reusable cross-job page token is assumed. Restarting scans plus durable IDs
avoids relying on stale cursors, but a finite scan budget can repeatedly encounter
an already-completed prefix. The new flags make that limitation explicit.

max_messages is a maximum, not a required batch size. Fewer eligible new messages
process normally and a genuinely exhausted empty import completes successfully.
Page/capacity limits remain observable and are not proof of an empty mailbox.
See [eligibility rules, regression results and Postman steps](qa/GMAIL_ELIGIBILITY_REPORT.md).
The minimal metadata calls add bounded Google API work for non-successful candidate
IDs; the existing job/HTTP deadlines, retries, page and concurrency limits still apply.
The normal processing path then performs the same MIME preflight and text fetch,
rechecking SENT before inference. A label added after selection can still produce
an existing selection-invalid skip for that admitted record, with no Groq call.

## PostgreSQL registry

Migration **gmail_incremental_v1**, descending from feedback_results_v1, creates
`gmail_message_tracking`. Previous batch/feedback migrations and rows are preserved.

| Stored metadata | Purpose |
| --- | --- |
| tenant_id + mailbox_key + message_id, unique | Isolation and durable message identity |
| mailbox_key | SHA256 of normalized getProfile-verified mailbox; no plaintext address |
| status | PENDING, RESERVED, PROCESSING, SUCCEEDED or FAILED |
| attempts, last_error, retry_at | Bounded logical attempt policy and safe audit metadata |
| claim_token, claim_expires_at | Fenced short-lived work ownership |
| job_id | Last claiming/successful job reference; not a durable job/result foreign key |
| created/updated/last_attempt/completed timestamps | UTC lifecycle metadata; completed_at records success |

There are no access/refresh tokens, OAuth secrets/proofs, subjects, senders, raw
email bodies or analysis values in this table. Hashing an address is pseudonymization,
not anonymization; metadata/backups still require private handling.

Indexes support the unique owner/mailbox/message key, claim expiry and retry lookup.
Constraints enforce valid states, nonnegative attempts, claim shape and successful
completion. The registry uses the existing bounded engine/coordinator, with blocking
SQL off the event loop. No database transaction stays open during Gmail/Groq calls.
Default application composition always chooses PostgreSQL; the MemoryGmailMessageStore
is an explicit isolated-test adapter, never a database failure fallback.

## Success, failure and retry policy

- **SUCCEEDED:** written only after T01 returns a validated analysis and the metadata
  commit succeeds. It is skipped during every later selection, even after job TTL,
  disconnect, credential rotation or process restart. A GET never adds inference.
- **RESERVED:** selected work with a random fencing token and lease, but no attempt
  spent yet. The worker atomically begins PROCESSING before fetching the message.
- **PROCESSING:** attempt counter commits before network/model work. Other jobs
  skip it and keep looking for additional IDs. Current local active jobs cannot
  have their reservations stolen even if a clock/lease appears expired.
- **FAILED:** not successful and not permanently treated as a duplicate. By default
  another import can retry after 60 seconds, up to three logical processing attempts
  across jobs/restarts. MIME skips also follow this bounded policy. Exhausted budgets
  remain parked and count as deferred; they do not loop forever or become successes.
- **Unstarted/cancelled work:** released without spending an attempt. Started work
  is failed with a safe code and cooldown. Successful metadata is never erased.

Retries require another explicit import API request; there is no automatic retry
scheduler. Existing T01/provider retries remain separately bounded inside each
logical attempt. Configuration controls are GMAIL_MESSAGE_MAX_ATTEMPTS (default 3,
range 1–10) and GMAIL_MESSAGE_RETRY_DELAY_SECONDS (default 60, positive, at most 86400).

A crash leaves claims until their lease expires. The computed lease is job deadline
+ Groq deadline + twice Google HTTP deadline + 30 seconds (default 200 seconds).
An expired PROCESSING claim also observes its retry cooldown/attempt budget;
RESERVED work that never began does not spend an attempt. Fencing prevents an old
writer from overwriting a new claim/result. Normal overlapping imports cannot
classify the same identity concurrently. A lost provider response or failed success
commit can require repeating uncommitted work: no exactly-once external-call claim.

## Status counters and limits

All existing endpoints and outcome fields remain. New status fields are additive.

| Field | Meaning |
| --- | --- |
| selected_messages | Eligible IDs atomically admitted to this job, at most max_messages |
| processed_messages | Terminal per-message outcome rows produced by this job |
| successful/failed/skipped/duplicate_messages | Existing outcome categories; sum to processed_messages |
| duplicate_messages | Processing-stage claim no longer usable; normally 0 because selection filters earlier |
| scanned_messages | Provider ID rows returned across pages, including repeated IDs and unselected page tail |
| previously_processed_messages | Distinct already-SUCCEEDED IDs filtered before selection |
| deferred_messages | Distinct in-progress, cooldown-blocked or attempt-exhausted IDs filtered before selection |
| scan_exhausted | Provider ended before the requested new count was reached; not proof all returned IDs succeeded |
| scan_limit_reached | More listing pages exist but the page budget stopped scanning |
| capacity_limit_reached | Persistent tracking quota prevented admitting an unseen identity |

When the requested count is reached, scan_exhausted remains conservatively false.
Scanned metadata rows need not equal selected + filtered counts: repeated IDs and
eligible unselected page tails are included in scanning. The old outcome-counter
reconciliation for selected terminal rows still holds. A page-limited job may be
COMPLETED for its admitted rows while scan_limit_reached=true; it must not be
presented as the entire mailbox being exhausted. All-busy/retry-blocked imports
can complete with zero selected plus deferred_messages>0.

Tracking quotas now default to 10,000 global / 1,000 per tenant, leaving global
headroom. They include successes, failures and pending metadata and do not evict
history. Positive old private overrides (for example 400/100) still apply. A full
registry stops selection with capacity_limit_reached and GMAIL_CAPACITY_EXCEEDED;
already admitted rows can finish, yielding PARTIAL_SUCCESS, or FAILED when none
were admitted. Retained-job quotas are separate and still reject excessive jobs 429.

The default five-page scan and 20 metadata IDs/page can scan at most 100 rows/job.
The maximum permitted profile is 10 pages and 100 IDs/page (1,000 rows/job). At the
head of a larger already-processed prefix, those limits can prevent reaching new
mail. Increasing a limit must be deliberate and stay within configured bounds;
no hidden unbounded scan or cursor escape is added.

## Restart and concurrency limits

Only successful/attempt/claim metadata is durable. OAuth connections, refresh tokens,
mailbox ownership reservations and job status/results remain in bounded private
memory. Reauthorize after restart using the same tenant/mailbox; the ledger then
skips successes without needing old jobs or credentials. Historical job IDs can
return 404 after restart/TTL even though duplicate protection remains. Disconnect
clears tokens/results and releases claims, not the successful-message registry.

Pre-upgrade in-memory history cannot be reconstructed automatically. Protection
begins with identities committed by this version; do not fabricate success flags
for unknown old attempts. Metadata is retained indefinitely within quotas; a future
administrative reset/retention policy would affect reprocessing and is outside this
feature. Whole-container/file retention and production backup restore remain
unverified; application/store recreation was tested against actual PostgreSQL.

The existing database-wide advisory lock still requires **one Uvicorn worker**.
Database uniqueness and fenced claims coordinate overlapping jobs, not a newly
supported distributed application deployment. Global and tenant model/HTTP/job
limits remain; an import still processes its selected messages sequentially.

## Migration and normal startup

Use README's local uv/Python/cache exports and the existing private DATABASE_URL:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

No new dependency or private .env edit is required. New retry defaults are optional
server configuration. Old explicit metadata-cap settings remain in force; change
them deliberately if they constrain the intended workload. PostgreSQL must be
running; [existing setup and backups](POSTGRESQL_BATCH_STORAGE.md). Missing database
availability fails import admission 503 rather than using memory.

## Exact 1,000-email / 100-message profile

With the same existing private OAuth/API/Groq/database configuration, explicitly
set this bounded workload profile before startup:

```bash
export GMAIL_MAX_MESSAGES_PER_IMPORT=100
export GMAIL_MAX_LIST_PAGES=10
export GMAIL_TENANT_MAX_RETAINED_IMPORTS=12
export GMAIL_IMPORT_TIMEOUT_SECONDS=600
export GMAIL_MAX_DEDUP_RECORDS=10000
export GMAIL_TENANT_MAX_DEDUP_RECORDS=1000
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Global retained jobs default 20 is sufficient for the 11-job demo; the old per-tenant
five-job default would otherwise reject the sixth job before its 30-minute TTL.
The 600-second job deadline is bounded headroom for 100 messages, not a live latency
or throughput guarantee. Requests still respect provider quotas/model timeouts.
Existing positive retry overrides remain explicit; normal defaults are 3/60 seconds.

In Postman, use the same owning X-API-Key for every protected operation:

1. After restart, POST `/api/v1/integrations/gmail/connect`, open its private URL and
   complete the fresh Google callback. GET `/api/v1/integrations/gmail/status` must
   show CONNECTED for the intended mailbox.
2. In that mailbox, identify recent synthetic plain-text feedback emails with the
   exact customer-feedback label (or configured label), within GMAIL_SEARCH_DAYS,
   outside SPAM/TRASH and with no attachments. The app never creates/modifies labels.
3. POST `/api/v1/integrations/gmail/import` with `{"max_messages":100}`. Save job_id;
   poll `/api/v1/integrations/gmail/imports/{job_id}` about every 2 seconds. Retrieve
   `/imports/{job_id}/results` under the same Gmail prefix for actual analyses.
4. Repeat the same POST after each job settles. Each new job excludes persisted
   successes before its 100 selection slots. For 1,000 supported eligible emails,
   ten jobs can process 100 each; inspect failures/deferred/limit flags rather than
   assuming every selected email passed MIME/model checks.
5. Submit an eleventh job: with no new eligible mail and no deferred failures,
   expect selected_messages=0, previously_processed_messages=1000, scan_exhausted=true, no new analysis.
   If scan_limit_reached=true, the mailbox is not established exhausted.
6. Restart FastAPI, reauthorize the same tenant/mailbox, and submit again. Prior
   successes remain skipped. Add a fresh labelled synthetic email and it can be
   selected if tracking/scanning capacity permits; a full 1,000-identity tenant quota
   must first be deliberately raised within supported bounds. Old results remain
   available only while their original process/TTL survives.

Failed-job IDs/history are not a durable archive. A safe retry requires a new import
request after cooldown; it does not require resubmitting text to sentiment/analyze.
Do not run this against real providers as a benchmark: manual imports consume the
configured provider quota. This implementation used real PostgreSQL with mocked
Gmail/Groq, not live credentials.

[Implementation and actual test evidence](qa/GMAIL_INCREMENTAL_IMPORT_REPORT.md).
