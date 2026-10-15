# Gmail import response validation and diagnostics fix

5 November 2026. **Focused fix implemented; 194 relevant tests passed, zero failures,
errors or skips (16.067 seconds JUnit).** All150 previous relevant cases retained,
plus44 new provider-response regressions. Verification uses mocked Google/Groq;
no live Gmail import, token exchange or sentiment inference was performed.

## What the supplied failure establishes

The original job reports GMAIL_RESPONSE_INVALID with selected_messages=0 and no
processed rows. In GmailService._run, selected_messages is assigned only after
_select returns. The exact call chain before that point is:

1. `_access(connection)`: use the existing token or serialize an expired-token refresh.
2. `users.labels.list`: GET `/gmail/v1/users/me/labels`, fields `labels(id,name)`;
   validate and resolve the exact configured feedback label.
3. `_access(connection)` again, then `users.messages.list`: GET
   `/gmail/v1/users/me/messages`, with that label ID, configured newer_than filter,
   includeSpamTrash=false and bounded maxResults/pages. Validate rows/IDs/page tokens.

A failure on any listing page can leave selected_messages=0 because selection has
not committed its returned ID list to the job yet. Profile lookup occurs during
OAuth, not import selection. Message fetch, MIME extraction and sentiment inference
happen after selected_messages is assigned; they do not explain this zero-selected
failure. The route returns a snapshot; GmailStore counts existing result rows and
is not the origin of this response-validation error.

**The original live provider response/operation trace is unavailable. The status
alone does not prove which of these calls failed.** The report does not assume
that the actual mailbox exceeds1,000 labels, that its configured label is missing,
or that reauthorization fixes the reported response error. No live-job root cause
is claimed beyond the code paths proven above. New safe diagnostics identify the
exact operation/stage on the next controlled retest.

## Confirmed application defects and corrections

### Valid label response rejected

`GoogleGmail.label` required a list of at most1,000 labels. The
[Google label resource contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels)
supports10,000 per mailbox. A realistic1,001-row partial response containing the
configured customer-feedback label reproduced FAILED/GMAIL_RESPONSE_INVALID before
message selection. This was a code-bound defect, not a missing-label configuration
error in that fixture.

The bound is now10,000 while the existing256 KiB actual response cap remains.
No broader mailbox query or additional permission is introduced; labels.list
already returns all label metadata. Rows/IDs are validated before use. Missing or
empty label arrays become GMAIL_SELECTION_INVALID, never an unfiltered fallback.
Malformed/null arrays/rows/IDs and excessive count/bytes still fail closed.

### HTTP failures misclassified as successful-response schema errors

The shared adapter parsed JSON before interpreting HTTP error status. A non-JSON
HTTP503 from labels.list reproduced GMAIL_RESPONSE_INVALID immediately instead of
the correct provider-error classification and bounded retry. Non-JSON error bodies
are now handled according to status; HTTP200 still requires a bounded JSON object
with no error envelope. Invalid success JSON remains GMAIL_RESPONSE_INVALID.

Known401/invalid_grant/insufficient-scope responses still require reconnect. Rate
limits retain GMAIL_RATE_LIMITED and bounded retries. Server failures retain
GMAIL_PROVIDER_ERROR and bounded retries. A disabled Gmail API or Workspace policy
403 is distinguished from demonstrated invalid OAuth credentials rather than
forcing an unrelated reconnect. Unknown403 failures remain provider errors;
access still fails closed, with no analysis or broadened scope. See the
[official Gmail error guide](https://developers.google.com/workspace/gmail/api/guides/handle-errors).
Authorization-code exchange remains non-retried; refresh scope/type/expiry checks,
fixed Google hosts, redirects disabled, timeouts and concurrency limits remain.

## Safe diagnostics

The adapter logs only internal allowlisted operation/stage names, HTTP status and
a fixed ErrorCode. There are no provider bodies/errors/messages, label names/IDs,
message/page identifiers, mailbox addresses, access/refresh tokens, client secrets,
headers, codes or authorization URLs in these diagnostics. For example:

```text
gmail_provider_rejected operation=labels.list stage=label_list status=200 code=GMAIL_RESPONSE_INVALID
```

This is an illustrative safe line, not captured live traffic. Supported operations
include oauth.exchange, oauth.refresh, profile.get, labels.list, messages.list and
messages.get. Stages distinguish byte cap, JSON/shape, token fields, label selection/
metadata, message listing/ID and page-token validation. Refresh validation errors
invalidate that connection exactly as before. A missing label keeps a valid
connection but fails the job with GMAIL_SELECTION_INVALID. Empty filtered messages
complete with zero results. Original results/API schemas remain unchanged.

## Files changed

- [app/integrations/google_gmail.py](../../app/integrations/google_gmail.py): label
  validation/count, status-aware provider error handling and safe diagnostics.
- [app/services/gmail_service.py](../../app/services/gmail_service.py): safe operation/
  stage diagnostics at listing and message-identity validation boundaries.
- [tests/integration/test_gmail_provider_responses.py](../../tests/integration/test_gmail_provider_responses.py):44 new cases.
- [docs/GMAIL_INTEGRATION.md](../GMAIL_INTEGRATION.md): exact trace, error/configuration
  distinctions, privacy and Postman retest procedure.
- This report. Generated JUnit/summary evidence is private ignored local QA output.

Inspected but unchanged: Gmail routes, MIME implementation, GmailStore, configuration,
OAuth state/PKCE/scope validation, tenant registry, public schemas and exception codes.
No dependency, database/migration, private .env, Git mount or frontend change.

## Actual test results

Two initial reproductions failed on the old implementation: valid1,001-label import
failed; non-JSON HTTP503 returned the wrong error code. After the fix:

- New focused provider-response suite:44 passed in3.27 seconds.
- All relevant Gmail OAuth/security, existing imports, provider responses, lifecycle,
  MIME and API-contract tests:194 passed in16.07 console seconds (16.067 JUnit),
  zero failures/errors/skips. Existing150 cases and their assertions retained.
- Cases cover complete mocked OAuth/import/results; exact captured analysis;
  fixed label/date filter; omitted/empty message responses; missing/malformed/oversized
  labels; invalid IDs and pages;401/scope/403 configuration/rate/server errors;
  refresh validation; retry bounds; safe diagnostics; broad-label rejection;
  cross-tenant ownership and existing callback issuer/replay protections.
- Python compile checks passed. Ruff/mypy are unavailable and were not installed/run.
  This is the relevant suite, not a new execution of the whole project/PostgreSQL suite.

After README's project-local environment exports, the executed command was:

```bash
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q \
  tests/security/test_gmail_oauth.py \
  tests/integration/test_gmail_import.py \
  tests/integration/test_gmail_provider_responses.py \
  tests/unit/test_gmail_lifecycle.py \
  tests/unit/test_gmail_mime.py \
  tests/integration/test_api_contracts.py \
  --junitxml=.local/qa/gmail-import-response-fix.xml
```

Evidence: [.local JUnit](../../.local/qa/gmail-import-response-fix.xml),
[machine summary](../../.local/qa/gmail-import-response-summary.json).
No test required live credentials, a real mailbox or paid inference.

## Exact live retest and configuration checks

[Full Postman procedure](../GMAIL_INTEGRATION.md#import-response-diagnostics-and-retesting-5-november-2026).
Restart one API process with the working server's same private settings and README
uv exports:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

A restart loses the process-local Gmail connection, so begin a fresh authenticated
connect/Google callback flow. GET /api/v1/integrations/gmail/status should return
CONNECTED for that same owner. In that mailbox, verify the exact configured label
(default customer-feedback), then label one recent synthetic plain-text email with
no attachments, within GMAIL_SEARCH_DAYS (default7) and outside SPAM/TRASH.
POST /api/v1/integrations/gmail/import with the owning X-API-Key and
`{"max_messages":1}`. Save the new job_id. Poll its status about every2 seconds,
then GET /imports/{job_id}/results. A supported selected email should produce one
SUCCESS row with its message reference and original schema-validated sentiment
analysis/evidence. Results retrieval does not invoke the model again.

If the configured label is absent/mismatched, create/apply the exact label in Gmail
or deliberately correct GMAIL_FEEDBACK_LABEL; no mailbox-wide fallback. If the
new diagnostic shows provider403 rather than insufficient scope, check the Gmail
API in the Cloud project owning the OAuth client and Workspace policy. Do not
assume repeated authorization will repair an API configuration error. If response
validation still fails, the new safe operation/stage/status/code line is the
necessary missing evidence for the actual live incident; never publish private
response bodies or credentials. Real Gmail/Groq acceptance remains unverified here.
