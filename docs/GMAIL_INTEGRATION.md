# Gmail feedback integration — T08

T08 introduced the API-only, explicitly triggered Gmail import over T01. Later
fixes preserve Google callback issuer checks and strict provider response handling.
The 6 November 2026 incremental extension now stores processed-message identity/retry
metadata in PostgreSQL. The latest user-reported live acceptance includes successful
OAuth, incoming-email imports with real Groq analysis, incremental and partial
selection, failed-message retries, and six previously processed messages recognized
after an application restart. A subsequent job completed with one successful message
and no job-level error. The audit did not replay these private mailbox operations.
Automated verification uses real isolated PostgreSQL and mocked Google/Groq. No
Google policy/production approval or live sanitizer-specific verification is inferred.

[Incremental selection, retry and exact Postman guide](GMAIL_INCREMENTAL_IMPORTS.md)
contains the current persistence/default/scan policy and required migration.

For per-message INVALID_MODEL_RESPONSE, see the shared T01
[safe diagnostic categories and live retest steps](qa/SENTIMENT_MODEL_DIAGNOSTICS.md).
These distinguish SDK, parser, schema and exact-evidence failures without logging
email/model content. The later [bounded evidence recovery](qa/EVIDENCE_GROUNDING_RECOVERY.md)
adds one correction generation only for an otherwise valid nonexact-evidence result.
It shares the original deadline/permit and spends no additional Gmail logical attempt.
If the corrected response still fails ONLY exact grounding, the later
[deterministic sanitizer](qa/EVIDENCE_SANITIZATION_REPORT.md) keeps exact phrases,
drops nonexact ones and revalidates the whole response without another Groq call.
Empty evidence is allowed but supplies no retained model quotation or independent
substantiation of the classification/summary. It is still a successful Gmail
processing outcome and remains durably deduplicated; it is not automatically
retried for more evidence. Other provider/schema errors retain their classifications.

## Architecture and authority

`api/v1/gmail.py` validates HTTP contracts and authenticates through the existing
registry. `services/gmail_service.py` coordinates OAuth, connection ownership,
bounded jobs and shared `IngestionService` → `SentimentService.analyze` calls.
`integrations/google_gmail.py` handles fixed Google endpoints; `gmail_mime.py`
extracts bounded text. `storage/gmail_store.py` holds temporary private objects.
The incremental extension adds only a message-metadata repository on the existing
PostgreSQL engine. No new classifier, prompt, graph, provider or queue framework.

All service/store reads revalidate verified Principal authority. Gmail connections
are keyed by authenticated tenant, jobs capture that principal and workers bind
it explicitly. Rotation keys for one business share ownership and quotas.
Mailbox identity comes only from authenticated
[getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile),
normalized case-insensitively. One connection per tenant and one owner per mailbox
are allowed in this process; conflict returns a fixed409 without disclosing the
other owner. No tenant/mailbox claim supplied in requests grants authority.
Expired connections keep a bounded mailbox-ownership tombstone until the owner
explicitly disconnects or reconnects to the same verified address. Restart clears
these reservations; they are not durable ownership records.

## Google Cloud setup — not performed in this milestone

1. In the intended Google Cloud project, enable the Gmail API.
2. Configure the OAuth consent screen, application identity, support/privacy
   information and intended audience. In testing, configure authorized test users
   where applicable. Authorize only designated feedback mailbox owners.
3. Create a server-side Web application OAuth client and register the exact callback
   `https://your-api.example/api/v1/integrations/gmail/oauth/callback`.
4. Privately supply GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and that
   GOOGLE_OAUTH_REDIRECT_URI. Set GMAIL_OAUTH_ENABLED=true only after configuration.
   Public [.env.example](../.env.example) intentionally contains empty credentials.
5. Use a server-configured feedback label, default customer-feedback, on explicitly
   selected messages. T08 will check that the label exists, without creating it.

See Google's [web-server OAuth flow](https://developers.google.com/identity/protocols/oauth2/web-server)
and [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).
Only `https://www.googleapis.com/auth/gmail.readonly` is requested and accepted;
any missing, additional or changed scope fails closed. Read-only still permits
access to private messages: selection policy narrows application behavior, not
Google's grant. No passwords, IMAP, service accounts or domain-wide delegation.

HTTPS is required except for explicit GMAIL_ALLOW_LOCALHOST_HTTP=true on localhost,
127.0.0.1 or ::1 outside production. No userinfo, query, fragment or alternate
callback path is accepted. Disabled, incomplete or unsafe Gmail configuration
returns503 GMAIL_NOT_CONFIGURED; T01–T07 and health still start and work.

`gmail.readonly` is a restricted scope. Public production use may require Google's
OAuth verification and a security assessment, subject to applicable exceptions.
Local mocks do not establish consent-screen setup, registered redirect/client
acceptance or approval. Review [restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
and authorize selected email-text processing by Groq before any live use. This
implementation does not certify compliance with Google's user-data policies.

## API contracts

All routes below start with `/api/v1/integrations/gmail`. Except the callback,
authenticate using X-API-Key and a registry principal with the listed permission.
Credentials without an explicit permission list default to all ten normal
permissions; existing explicit lists must deliberately add Gmail permissions.

| Method/path | Permission | Success response |
| --- | --- | --- |
| POST /connect | gmail:connect | 200 authorization_url, expires_in_seconds |
| GET /oauth/callback | Single-use state, no API key | 200 status CONNECTED |
| GET /status | gmail:read | 200 connected, mailbox, scope, connection_status |
| DELETE /disconnect | gmail:connect | 200 status DISCONNECTED |
| POST /import | gmail:import | 202 job_id, status PENDING, fixed message |
| GET /imports/{job_id} | gmail:read | 200 state and deterministic progress counts/error_code |
| GET /imports/{job_id}/results | gmail:read | 200 job_id, status, bounded results |

POST /import accepts only `{"max_messages": 10}` or `{}`. Explicit max_messages
must be a strict integer1–100 and no greater than the configured server maximum.
Omission uses GMAIL_MAX_MESSAGES_PER_IMPORT (20 by default). Extra fields, queries,
tenant selectors and mailbox claims cannot broaden selection. Job IDs are32
lowercase hexadecimal characters; malformed IDs422, foreign/unknown/expired valid
IDs404 GMAIL_JOB_NOT_FOUND. GET /status always selects the caller's connection;
there is no mailbox/tenant lookup argument. It reports local verified identity and
credential usability, not a live provider health check. It can report CONNECTED
when expired access can still be refreshed. No token/credential detail is returned.

## OAuth flow, state and refresh

The authenticated connect request generates32 random state bytes and64 PKCE
verifier bytes (URL-safe encoded). Only the state's digest and a private SecretStr
verifier are retained with the verified owner. State expires after600 seconds,
can be consumed once, and is atomically consumed before provider awaits. There
is one flow per tenant, including callbacks in flight, with a64-flow global cap.

The authorization URL uses accounts.google.com/o/oauth2/v2/auth, response_type=code,
offline access, prompt=consent, include_granted_scopes=false and an S256 challenge.
State and challenge are sensitive connection metadata; do not log the returned
URL. The callback requires state and exactly one of code/error. Duplicate/unknown
parameters, including tenant/redirect overrides, reject. Known Google descriptive
fields are ignored; callback scope is never trusted as the grant. Google's
`state`, `code`, `iss`, `scope` callback combination is supported. When `iss` is
present, its decoded value must exactly equal `https://accounts.google.com`;
other issuers, URL variants and duplicate parameters fail with422 before any
token exchange. Issuer omission remains supported for existing callbacks.
The expected issuer matches [Google's published metadata](https://accounts.google.com/.well-known/openid-configuration);
exact comparison follows [RFC9207 issuer validation](https://www.rfc-editor.org/rfc/rfc9207.html#section-2.4).
Callback `scope` is descriptive only: the token response must independently pass
the existing exact `gmail.readonly` scope check. Callback query bytes are capped
at8 KiB before parsing. Denial consumes valid state safely.
After restarting the API to load a callback fix, start a fresh `/connect` flow;
previous process-local state cannot be reused after restart.

Code exchange POSTs only to oauth2.googleapis.com/token using the original verifier,
private confidential-client fields and fixed redirect. There is no code-exchange
retry after an ambiguous response. Granted scope, Bearer token type and bounded
expiry/token shapes are validated before authenticated profile lookup. Only after
verified mailbox ownership checks are tokens committed. Failure, late disconnect,
cancellation and shutdown clear temporary verifier/token references.

PKCE S256 construction and verifier matching are tested locally. See Google's
[PKCE description](https://developers.google.com/identity/protocols/oauth2/native-app)
for the S256 algorithm; acceptance with the deployed registered web client remains
a live verification gate. No fallback to unprotected OAuth is implemented.

Tokens stay in bounded server memory only. Per-connection locks serialize refresh.
If Google omits a new refresh token on refresh, preserve the existing one; a fresh
connection without a refresh token works until its access expires, then requires
reconnection. Invalid/revoked credentials, unsafe scope changes and invalid refresh
responses clear the connection's tokens. Expiry uses monotonic deadlines; connections
have an additional 8-hour hard TTL, even if refreshing would otherwise work. State,
connections, jobs and results do not survive process restart. PostgreSQL message
identity/retry metadata does survive, as described in the incremental section.

## Selection and Gmail access

The configured GMAIL_FEEDBACK_LABEL must match one existing label returned by
[labels.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels/list).
Broad system labels INBOX/SENT/DRAFT and SPAM/TRASH are rejected. Listing uses its
verified label ID, `newer_than:7d -in:sent` by default and includeSpamTrash=false.
GMAIL_SEARCH_DAYS is server configured1–30; callers cannot submit a query or URL.
The filter expresses the business's selection policy: it is not proof that every
selected email is customer feedback. Label unrelated messages appropriately;
T08 has no additional semantic email-selection model or autonomous tools.

[messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
pagination is bounded to five pages by default (configurable up to10) and an
absolute NEW-message maximum20 by default (hard100). Each metadata page requests
the server's configured message cap, independent of a smaller per-request new
count. Already successful or unavailable IDs are filtered before counting selected
claims. Repeated IDs do not consume capacity. Malformed/repeated/oversized page
tokens still fail. scan_limit_reached distinguishes stopping at the page budget
from scan_exhausted. See [the current counter definitions](GMAIL_INCREMENTAL_IMPORTS.md).

Before reserving new work, one owner/mailbox-scoped SQL lookup filters durable
successes from each page. Remaining candidates are checked with messages.get
`format=minimal&fields=id,labelIds` until enough eligible IDs are found. A candidate
carrying SENT is excluded before it consumes a new-message slot or tracking row;
the scan continues through the page and later pages within existing bounds. This
label-only request contains no headers, payload or body. Archived incoming feedback
remains eligible: INBOX is not required and From/mailbox address comparisons are
not used. Busy/cooldown states are still atomically rechecked when claiming.

Fewer available IDs are normal: requesting three with only two new incoming
messages processes two and completes if both succeed; a genuinely exhausted search
with no new IDs completes with zero selected/processed/model calls. A page limit
sets scan_limit_reached rather than scan_exhausted. See the
[eligibility report and exact Postman plan](qa/GMAIL_ELIGIBILITY_REPORT.md).

[messages.get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)
then uses format=full with explicit nested partial-response fields. First fetch MIME
metadata **without body.data**. If it contains any attachment, external body or
nontext leaf, **skip the entire message** with a controlled skip code (GMAIL_ATTACHMENTS_SKIPPED or GMAIL_MESSAGE_INVALID) before a
body-data request. This deliberately conservative policy means feedback in an
email that also contains an attachment is unsupported in T08. No attachments.get
call or attachment decoding exists. Only a clean preflight leads to the second
request for inline text data. See [partial responses](https://developers.google.com/workspace/gmail/api/guides/performance).
Both MIME preflight and final extraction reject SENT/SPAM/TRASH and require the
configured feedback label. This also blocks inference if labels change after the
selection-time check. Such a late change keeps the existing GMAIL_SELECTION_INVALID
skip outcome for the already-selected record; selection is not reopened after a race.
Model validation failures from eligible incoming mail remain FAILED with their
original error code, including INVALID_MODEL_RESPONSE.

## MIME and text extraction

Parsing is iterative/bounded to depth4,64 MIME parts,100 headers and8,192 characters
per header. Decode strict Base64url; declared and actual decoded byte sizes must
match. Supported character sets are UTF-8, ASCII, Latin-1 and Windows-1252.
Prefer nonempty plain text; use HTML-only/empty-plaintext alternatives as a fallback.
Multipart alternatives produce one feedback record, not two. Invalid structures,
missing content, malformed encoding and empty content are controlled skips.

HTML becomes inert plain text with Python's HTMLParser. Script/style/head/template/
noscript/SVG/math contents are excluded. No browser, URL fetch, image load or script
execution exists. Enforce16 KiB selected decoded body plus normalized UTF-8 text
and the existing5,000-character T01 cap. Oversized text is rejected, never silently
truncated. Subject, sender and timestamp are parsed transiently with bounds, then
discarded; headers are not included in model input or retained API results.

## Processing, quotas and deduplication

At most two imports globally and one per tenant may be pending/running by default;
admission reserves capacity before202. Each admitted job has one asyncio worker,
processes messages sequentially and shares the existing global/per-tenant model
budget with REST/graph/chat/batch/webhook callers. Pending scheduler state counts
against the same capacity; there is no additional unbounded queue. Effective
per-tenant active/retained/dedup caps leave global headroom. No active reservation
is evicted to admit new work.

Jobs move PENDING → RUNNING → COMPLETED/PARTIAL_SUCCESS/FAILED, with a120-second
overall deadline. Admission checks local OAuth/Groq configuration and capacity;
it does not probe Google or promise inference success. Malformed/large/attachment
messages are SKIPPED. Controlled per-message errors can continue; fatal credential,
provider/rate/deadline/configuration failures stop further work. Already selected
but unattempted remaining IDs become FAILED with the job's safe code, preserving
count reconciliation without extra provider calls. Counts are outcomes, not a
claim of attempted HTTP/model operations. Empty and duplicate-only imports complete.

Results include integration=gmail, message_id, optional thread_id, status, existing
validated SentimentResponse for SUCCESS, or a fixed error_code for failure/skip.
Selected count equals processed terminal outcomes; success+failed+skipped+duplicate
counts reconcile. No mailbox archive, raw-body field, subject or sender is returned.

Deduplication keys are tenant + SHA256(verified normalized mailbox) + individual
message ID, never thread ID. Short PostgreSQL transactions reserve eligible IDs
at selection time; rows carry fenced tokens and bounded leases. Processing begins
with a committed attempt counter, then all network/model work runs outside DB
transactions. Only a validated analysis followed by a successful registry commit
marks SUCCEEDED. That metadata does not expire on result TTL/disconnect/restart.
Failures remain eligible after60 seconds by default, with at most three logical
attempts across jobs/restarts. Unstarted cancelled reservations spend no attempt.
Expired crash claims recover under the same policy; active local jobs cannot be
stolen. There is no automatic retry scheduler or exactly-once external-call claim.

Global10,000 / tenant1,000 metadata rows are the new defaults. Full history is
preserved and capacity_limit_reached is observable rather than evicting success
records. Bodies, OAuth tokens and analysis are not in this ledger. Detailed
schema, retry/lease, counters and limits: [incremental imports](GMAIL_INCREMENTAL_IMPORTS.md).

Default retained jobs:20 global/five per tenant; terminal job/results TTL:1,800s.
Google HTTP logical operations: four concurrent,10-second total deadline including
backoff, one retry for transient responses/transport errors (zero code-exchange
retries),256 KiB actual response cap, no redirects or environment proxy inheritance.
Provider-level rate limits can still reject. See [Google error guidance](https://developers.google.com/workspace/gmail/api/guides/handle-errors).
All T06/T07 authenticated ingress, request/rate/deadline/model controls remain.
A cleanup task expires only local memory; it never polls Gmail.

## Disconnect, shutdown and privacy

DELETE /disconnect invalidates pending/in-flight owner OAuth flows, removes and
clears owner tokens, cancels/awaits owner jobs and then removes owner results.
Durable success/retry metadata remains; claims are released without erasing history. New work rejects during disconnect; a late callback cannot restore
a removed connection. Other tenants are unaffected. Local disconnect does not
revoke the Google grant. No provider revocation call is implemented or performed.
Cancellation cannot undo provider requests already issued. Shutdown cancels all
workers/callbacks and clears private stores; cleanup releases references rather
than securely overwriting immutable Python memory.

Selected **body text is sent to the configured Groq provider** using the unchanged
T01 native strict structured-output/Pydantic/evidence pipeline, supported source
email and server-side business_type=general by default. Gmail is integration
metadata only. Credentials, subject/sender and OAuth metadata never enter inference.
Email instructions remain untrusted classification data, not tool or policy authority.

No original body field is retained after processing, but derived summaries and
exact evidence are sensitive and may quote all of a very short email. Treat
results as private customer data; TTL does not delete copies already downloaded.
API responses use no-store/nosniff/no-referrer; application access/provider logs
are suppressed to avoid OAuth query/token leaks. Deployment proxies must independently
avoid query and authorization-header logging; production logging is unverified.

## Errors and operational limits

| Condition | HTTP / safe code |
| --- | --- |
| Missing/invalid REST key | 401 AUTHENTICATION_FAILED |
| Missing permission | 403 AUTHORIZATION_FAILED |
| Disabled/missing OAuth setup | 503 GMAIL_NOT_CONFIGURED |
| Invalid/expired/reused state | 400 GMAIL_INVALID_STATE |
| OAuth denial | 400 GMAIL_OAUTH_DENIED |
| Bad scope/provider shape | 400 GMAIL_SCOPE_INVALID / 502 GMAIL_RESPONSE_INVALID |
| Existing usable connection / conflicting mailbox | 409 GMAIL_ALREADY_CONNECTED / GMAIL_MAILBOX_CONFLICT |
| Missing connection / reconnect needed | 409 GMAIL_NOT_CONNECTED / GMAIL_RECONNECT_REQUIRED |
| Foreign/unknown/expired job | 404 GMAIL_JOB_NOT_FOUND |
| Import/OAuth/HTTP capacity or Google rate limit | 429 GMAIL_CAPACITY_EXCEEDED / GMAIL_RATE_LIMITED |
| Google timeout / provider error | 504 GMAIL_TIMEOUT / 502 GMAIL_PROVIDER_ERROR |

All errors retain the existing ErrorResponse/X-Request-ID shape; raw provider
responses and diagnostic strings are never returned. Oversized JSON still413 above
4 MiB actual bytes; webhook16 KiB and multipart2 MiB remain separate. Per-message
error codes appear in successful job-read responses, not as per-row HTTP requests.

Single-process only: run one ASGI worker. Reload/restart/config rotation loses
connections, mailbox reservations, jobs and results. Successful-message tracking
and retry budgets survive in PostgreSQL; unfinished claims wait for lease recovery.
No persistent OAuth storage, distributed authorization/synchronization or permanent raw-email
storage exists. Production needs encrypted credential storage with appropriate
access/lifecycle management, an approved persistence/recovery policy, provider
acceptance and Google authorization review. Git/deployment remain unverified.

## Local verification

After README's project-local uv/Python/cache exports, use the network-blocked,
fabricated-credential fixtures. Do not set real keys in test command arguments:

```bash
uv sync --locked --offline
uv pip check
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' GOOGLE_OAUTH_CLIENT_ID='' GOOGLE_OAUTH_CLIENT_SECRET='' uv run --locked --offline pytest -q
```

The full suite passed571/571 (447 retained baseline +124 new cases). In-process
and official subprocess stdio MCP, LangGraph, batch reports, HMAC, quotas and
previous API regressions pass. See [execution evidence](qa/TEST_EXECUTION_REPORT.md),
[implementation report](qa/T08_IMPLEMENTATION_REPORT.md),
[API compatibility](qa/t08-compatibility.json) and [release gates](qa/RELEASE_READINESS_REPORT.md).
No Cloud configuration, real OAuth redirect/code exchange, live Gmail message,
restricted-scope approval or additional inference has been verified. Live checks
require separate authorization. T08 is complete locally; release remains NOT READY.

## Import response diagnostics and retesting (5 November 2026)

A job with selected_messages=0 and GMAIL_RESPONSE_INVALID failed before `_select`
returned. It does not establish which Google call failed: `_select` first obtains
an access token (refreshing when needed), then calls users.labels.list and
users.messages.list. selected_messages is assigned only after the whole selection
succeeds, including all bounded pages. users.getProfile is called during OAuth,
not on every import; messages.get, MIME parsing and sentiment analysis run after
selection. The old status alone cannot identify the original live provider response.

Two response-handling defects were reproduced and corrected:

- Label lookup rejected any response with more than1,000 labels. Google's
  [label resource contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels)
  supports10,000. Validation now permits up to that count **within the unchanged
  256 KiB response-byte cap**. It still resolves only the exact configured label;
  the date filter, message/page caps, SPAM/TRASH exclusion and readonly scope remain.
- Error-body JSON parsing could mask HTTP401/429/5xx as GMAIL_RESPONSE_INVALID.
  Non-JSON HTTP errors now retain their authentication/rate/provider classification
  and bounded retries. Known insufficient-scope403 responses still require
  reconnection. Disabled-API, policy and unknown403 failures are provider errors,
  without falsely clearing a valid token. An HTTP200 malformed/oversized JSON or
  invalid success schema still fails closed. No response bodies are logged.

Missing/empty label arrays mean no configured label was found and produce
GMAIL_SELECTION_INVALID. Malformed label arrays/rows/IDs remain GMAIL_RESPONSE_INVALID.
An existing label with no matching recent messages completes with zero results;
Google may omit messages entirely in that empty response. There is never a fallback
to an unfiltered inbox or another label. Labels are not created by this app.

Sanitized warning lines now identify the operation and validation stage:

```text
gmail_provider_rejected operation=labels.list stage=label_list status=200 code=GMAIL_RESPONSE_INVALID
```

These examples describe possible failures, not captured private-provider traffic.
Only fixed internal operation/stage labels, HTTP status and ErrorCode are emitted.
No tokens, client secrets, authorization URLs/headers, mailbox addresses, label
names/IDs, page tokens, message IDs or email contents appear in these diagnostics.

| Operation / stage | Meaning and next step |
| --- | --- |
| labels.list / label_selection | Check the exact case-sensitive GMAIL_FEEDBACK_LABEL in the connected mailbox; default customer-feedback. Create/apply it in Gmail manually or deliberately correct server configuration. Do not broaden to INBOX. |
| labels.list / label_list, label_row, label_id | Invalid label response or count bound. Check this safe diagnostic; do not publish the private response. |
| any operation / response_bytes | Response exceeds the existing byte cap; it is not an empty-mailbox error. |
| any operation / json, response_shape | HTTP200 success body is not the required JSON object/schema. |
| messages.list / message_list, message_row, message_id, page_token | Invalid listing/count/ID or invalid/repeated pagination token before selection completes. |
| oauth.refresh / tokens | Refresh returned a token response that failed existing expiry/type/readonly-scope validation; connection is invalidated safely. |
| http_status with401, invalid_grant, insufficient scope | Reauthorize using a fresh state flow; token/grant access is no longer usable. |
| http_status with403 and GMAIL_PROVIDER_ERROR | Check that Gmail API is enabled in the OAuth client's Cloud project and Workspace policies permit access; repeated consent alone may not fix this. |
| http_status with429 or server5xx | Existing bounded retry applies; rate/transient provider failure does not itself prove revoked credentials. |

To retest with Postman:

1. Restart one API process with the same private settings as the working OAuth
   server, using README's local uv exports:

   ```bash
   uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
   ```

   No migration or dependency change is required. Restart clears Gmail's in-memory
   connection/state/jobs; request a fresh connection instead of reusing old state.
2. POST `/api/v1/integrations/gmail/connect` with the owning business X-API-Key and
   open its authorization URL privately. Complete the Google callback, then GET
   `/api/v1/integrations/gmail/status`; expect CONNECTED for that same owner.
3. In that connected mailbox, create/verify the exact customer-feedback label
   (or the deliberately configured GMAIL_FEEDBACK_LABEL). Apply it to one recent
   synthetic, plain-text feedback email with no attachments. It must be within
   GMAIL_SEARCH_DAYS (default7) and outside SPAM/TRASH.
4. POST `/api/v1/integrations/gmail/import`, same X-API-Key, JSON
   `{"max_messages":1}`. Save the newly returned job_id.
5. Poll GET `/api/v1/integrations/gmail/imports/{job_id}` about every2 seconds.
   For a supported single message, expect COMPLETED and selected/processed/successful
   counts1. Empty selection is valid COMPLETED/zero; it does not prove a labelled
   message matched the configured date window. Failed imports expose a safe code.
6. GET `/api/v1/integrations/gmail/imports/{job_id}/results` with that same owner.
   Expect a SUCCESS row with its message reference and actual SentimentResponse,
   including grounded evidence. Retrieval makes no extra Groq call. Gmail's existing
   result schema does not add a full-body field or permanent email storage.
7. If failure persists, use only the new sanitized operation/stage/status/code
   warning to identify the next diagnostic step. Avoid enabling HTTP debug/access
   query logging or sharing tokens/private provider bodies.

[Implementation report and exact test evidence](qa/GMAIL_IMPORT_RESPONSE_FIX.md).
The implementation task used mocked Google/Groq providers only; the original live
job's exact response remains unverified, and no live Gmail import is claimed.

## Investigating an HTTP 204 from messages.list

The live diagnostic `operation=messages.list stage=http_status status=204` confirms
that the application received204 for the listing call. It does not identify whether
the response originated from Gmail, a custom transport/runtime, or an intermediary.
The method, body and query built by this repository match the
[official messages.list contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list):

| Component | Application request |
| --- | --- |
| Method | GET, empty request body |
| URL | https://gmail.googleapis.com/gmail/v1/users/me/messages |
| labelIds | Exact ID resolved from the configured feedback label |
| q | Server-configured newer_than:Nd -in:sent filter, default 7 days |
| includeSpamTrash | false |
| maxResults | Server-configured metadata page size, default20; independent of a smaller requested NEW count |
| pageToken | Only on subsequent bounded pages |
| fields | messages(id,threadId),nextPageToken |
| Accept / Accept-Encoding | application/json / identity |

Google's [partial-response guidance](https://developers.google.com/workspace/gmail/api/guides/performance#partial-response)
documents HTTP200 for valid fields requests and400 for invalid field selections.
Excluding resultSizeEstimate from a valid projection does not establish that204
means zero matching messages. The app continues to accept only200 with valid JSON:
200 `{}` or `{"messages":[]}` can represent an empty selection;204 and200 with no
JSON body cannot prove it. No status/response normalization, synthetic completed
job, broader query, extra retry, host substitution or model call is introduced.

The production Google client uses the normal HTTPX AsyncHTTPTransport unless the
trusted Python launcher explicitly passes gmail_transport to create_app. It has
trust_env=False, no explicit proxy/mounts, redirects disabled, certificate/hostname
verification enabled, HTTP/1.1 enabled/HTTP2 disabled, and configured timeouts plus
the existing logical-operation deadline. Proxy environment variables alone do not
route this client through a proxy. See [HTTPX environment controls](https://www.python-httpx.org/environment_variables/).
This does not prove the origin of a live response or exclude transparent egress,
a patched runtime/transport or unexpected upstream behavior. No live TLS/egress
trace was collected. Environment flags in a separate terminal are not proof of
the running Uvicorn process's configuration.

HTTP rejection logs now append safe metadata to the existing diagnostic:

```text
gmail_provider_rejected operation=messages.list stage=http_status status=204 code=GMAIL_PROVIDER_ERROR method=GET host=gmail.googleapis.com response_bytes=0 transport=default
```

This is an illustrative line. Request method/host are taken from HTTPX's actual
request after hooks when a response is available. Methods and hosts are allowlisted;
unexpected values become OTHER. response_bytes counts bytes yielded by HTTPX's
bounded decoded response stream; it does not trust Content-Length and is not a
packet capture. transport=default describes this app's normal-client configuration;
injected means the launcher supplied a transport (as test fixtures do), and
unspecified means an independently constructed adapter supplied no mode. It is
configuration metadata, not cryptographic proof of which server replied. Other
validation-stage warnings may lack HTTP request metadata because validation occurs
after the transport method returns. No URLs/query strings, headers, tokens, label/
message/page IDs, mailbox data, provider messages or email content are logged.

Retest using the same owning business and private settings as the working OAuth
server. From the project root and README's local uv environment:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

After restart, reconnect using POST `/api/v1/integrations/gmail/connect` and the
fresh Google authorization URL/callback; process-local OAuth connections do not
survive restart. Confirm GET `/api/v1/integrations/gmail/status` is CONNECTED.
Apply the exact customer-feedback label to a recent plain-text synthetic email
without attachments, inside the configured date window and outside SPAM/TRASH.
Then, in Postman with the owning X-API-Key:

1. POST `/api/v1/integrations/gmail/import` with `{"max_messages":1}`; save the new job_id.
2. Poll GET `/api/v1/integrations/gmail/imports/{job_id}` about every2 seconds.
3. GET `/api/v1/integrations/gmail/imports/{job_id}/results`. A successful selected
   message has SUCCESS plus its original validated analysis. An unexplained204
   remains FAILED/GMAIL_PROVIDER_ERROR with zero rows and no Groq call.
4. If204 persists, retain only the safe diagnostic above. Check that method=GET,
   host=gmail.googleapis.com and transport=default. If injected, inspect the trusted
   launcher for an explicit custom/mock transport; do not expose its credentials.
   With the expected metadata, the remaining investigation belongs to provider/
   egress provenance: ask the responsible operator to check that method/host/status
   path on the running server without capturing authorization headers or email data.
   The application log alone cannot distinguish a legitimate origin bug from an
   intermediary-generated response. Do not bypass TLS/proxy/security controls or
   treat the anomaly as proof of an empty mailbox.

[HTTP204 investigation and regression evidence](qa/GMAIL_MESSAGES_204_INVESTIGATION.md).
No real Google API/token exchange or Groq inference was performed by this investigation.


## Current incremental-import acceptance

The persistent selection-time ledger supersedes historical T08 TTL-based message
dedup behavior. It does not alter the strict HTTP204 handling or OAuth/client
security documented above. [Implementation evidence](qa/GMAIL_INCREMENTAL_IMPORT_REPORT.md)
and [Postman/bulk configuration](GMAIL_INCREMENTAL_IMPORTS.md). Job outcomes still
reflect only admitted rows; selection-time exclusions use separate additive counters.
