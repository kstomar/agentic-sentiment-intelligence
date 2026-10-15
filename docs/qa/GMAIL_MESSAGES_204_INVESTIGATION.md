# Gmail messages.list HTTP204 investigation

5 November 2026. **206 relevant tests passed; zero failures/errors/skips.**
The immediate job-failure cause is confirmed: the application received HTTP204
for messages.list and rejected it as GMAIL_PROVIDER_ERROR before selection returned.
**Why the live request received204 remains unknown.** No live Gmail, OAuth token
exchange, packet/TLS trace or Groq call was performed in this investigation.

## Request and contract findings

GoogleGmail.list_page calls _request with GET and the fixed canonical URL
https://gmail.googleapis.com/gmail/v1/users/me/messages. It sends an empty body,
Accept application/json, Accept-Encoding identity and the existing bearer credential.
Only the existing private header carries the token; it is never logged.

The actual request built by the installed HTTPX client was inspected with a
MockTransport, including first/subsequent pages. It contains:

- labelIds: exact label ID previously resolved from the configured feedback label.
- q: server-configured newer_than:Nd (default7 days), never a caller-selected query.
- includeSpamTrash=false; maxResults=remaining bounded job selection capacity.
- fields=messages(id,threadId),nextPageToken.
- pageToken only when continuing a bounded page sequence.

No Origin, method override or conditional-cache headers are added by the adapter.
The wire-request tests use synthetic label/page/token values. None is logged.
The source request matches the
[official Gmail list contract](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).
Google's [partial-response documentation](https://developers.google.com/workspace/gmail/api/guides/performance#partial-response)
describes200 with requested data for valid fields selection and400 for invalid
fields. No documented204 empty-mailbox convention was established for this call.
The missing resultSizeEstimate projection is valid; it is not proof that204 means
zero matches. HTTP200 with valid empty JSON can complete empty;204 or200 without
JSON cannot establish that result. A JSON-looking body attached to204 is not
accepted either. An arbitrary2xx code is not the resource's success contract.

## HTTP transport and intermediary findings

Production lifespan creates a dedicated HTTPX AsyncClient with gmail_transport=None
unless a trusted launcher explicitly injects a transport. Settings include
trust_env=False, follow_redirects=False and the existing configured timeout.
Installed HTTPX0.28.1 creates its normal AsyncHTTPTransport/connection pool with
certificate and hostname verification enabled, HTTP/1.1 enabled and HTTP2 disabled.
No explicit proxy, mounts, response cache or request mutation hook is configured
for the Google client. The existing outer deadline/retry/concurrency controls remain.

A regression sets all common proxy environment variables to a synthetic proxy and
starts the actual app composition without a Gmail transport override. It verifies
the native transport, empty proxy mounts, TLS verification, HTTP flags and timeouts
without issuing any network request. Environment variables alone do not select a
proxy for this client; see [HTTPX's documented controls](https://www.python-httpx.org/environment_variables/).
The tool shell's proxy-variable names were also checked for presence only (all
absent); values were not read into reports. This is not evidence of the separate
running Uvicorn process's environment or actual live egress path.

These findings do not authenticate the origin of the live204. Transparent egress,
a patched runtime, custom/injected transport, a different running checkout, or
unexpected upstream behavior require runtime/operator evidence to distinguish.
No one of these possibilities is presented as the proven root cause. HTTPS/TLS
remains enforced; no security-bypass probe, alternate host, wider query or speculative
protocol/cache/header change was introduced. Reauthorization is not a demonstrated
remedy for a non-authentication204 response.

## Response handling and diagnostic correction

The current status handler is correct to fail closed for this undocumented204.
It raises GMAIL_PROVIDER_ERROR, leaves selected/processed counts zero, creates no
successful result and invokes no classifier. No automatic204 retry, JSON synthesis,
empty-success mapping, token invalidation or query/host fallback was added.

The identified diagnostic gap was missing actual method/host/length/transport
metadata. A regression verified that the old code already rejected204 correctly
but failed its new safe-metadata assertion. The focused production change now:

- Appends actual HTTPX request method/host after hooks when a response is available.
  Before a response, only the configured method/host are known.
- Emits an observed decoded-stream response_bytes count, independent of untrusted
  Content-Length. It is not a wire capture or proof that an intermediary sent no
  extra bytes; HTTPX has already applied protocol/decoding behavior.
- Reports default/injected/unspecified transport configuration. default means this
  app selected its normal client; it does not prove the origin of the reply.
- Whitelists method/host/transport values and numeric byte counts before logging.
  Unexpected custom-client values are masked, not echoed.

Illustrative next-run warning:

```text
gmail_provider_rejected operation=messages.list stage=http_status status=204 code=GMAIL_PROVIDER_ERROR method=GET host=gmail.googleapis.com response_bytes=0 transport=default
```

No URL/query string, header, token, OAuth code/secret, provider body/message, label/
page/message ID, mailbox address or email body appears. Earlier post-response
validation warnings can retain the shorter form when request metadata is no longer
available. All public API/error/result schemas and scope/tenant rules are unchanged.

## Files changed

- [app/integrations/google_gmail.py](../../app/integrations/google_gmail.py): safe
  metadata, actual request/byte observation and transport-mode annotation only.
- [app/main.py](../../app/main.py): identify normal versus explicitly injected
  Google-client transport; existing transport/proxy/TLS settings unchanged.
- [tests/integration/test_gmail_messages_transport.py](../../tests/integration/test_gmail_messages_transport.py):12 new cases.
- [docs/GMAIL_INTEGRATION.md](../GMAIL_INTEGRATION.md): request/transport findings,
  limits of evidence and exact Postman retest procedure.
- This report. Generated evidence is private ignored .local/qa output.

Source SHA checks confirm GmailService selection/filtering, callback route,
configuration, Gmail schemas/store and dependency files are unchanged in this task.
No migration, private .env edit, credential extraction, dependency install, Git
command/mount change, frontend or deployment was performed.

## Executed tests

- Focused12 new cases:12 passed in0.54 seconds.
- Relevant complete Gmail OAuth/import/provider-response/transport/lifecycle/MIME
  and API-contract suite:206 passed in20.45 console seconds (20.455 JUnit),
  zero failed/errors/skipped. All194 preceding relevant case IDs retained.
- New cases verify the actual GET method, URL/host/body/query, fixed selection,
  first/subsequent pages,204 empty/body-bearing failure, other unexpected2xx,
  invalid200 empty body, no inference/results/extra attempt, safe observed lengths,
  private-header/body omission, actual post-hook method observation, proxy-env
  isolation, TLS/timeouts and custom-metadata redaction.
- Existing cases preserve valid200 empty responses, positive imported analysis,
  OAuth issuer/state/readonly-token checks, refresh lifecycle, tenant isolation,
  MIME/attachment safety, provider error categories and public API contracts.
- Python compile checks passed. Ruff/mypy unavailable and not installed/run.
  The whole-project/PostgreSQL suite was not rerun for this diagnostic-only change.

After README's project-local uv/Python/cache exports, executed:

```bash
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q \
  tests/security/test_gmail_oauth.py \
  tests/integration/test_gmail_import.py \
  tests/integration/test_gmail_provider_responses.py \
  tests/integration/test_gmail_messages_transport.py \
  tests/unit/test_gmail_lifecycle.py \
  tests/unit/test_gmail_mime.py \
  tests/integration/test_api_contracts.py \
  --junitxml=.local/qa/gmail-204-regressions.xml
```

[JUnit](../../.local/qa/gmail-204-regressions.xml),
[sanitized summary](../../.local/qa/gmail-204-summary.json),
[source hash baseline](../../.local/qa/gmail-204-source-before.json).
All providers are mocked or never called; test fixtures block outbound network.

## Exact Postman retest and remaining blocker

Use the working server's private configuration and README's local uv exports.
Restart from the intended project directory:

```bash
cd /home/rails/agentic-sentiment-intelligence
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

1. With the owning business X-API-Key, POST
   `/api/v1/integrations/gmail/connect`; use the fresh authorization URL/callback.
   GET `/api/v1/integrations/gmail/status` must show CONNECTED. Old process-local
   connection/state/job IDs cannot be reused after restart.
2. In the connected mailbox, apply the exact customer-feedback label (or deliberate
   server-configured label) to a recent synthetic plain-text email, no attachments,
   within the configured date window and outside SPAM/TRASH.
3. POST `/api/v1/integrations/gmail/import`, same owning X-API-Key, JSON
   `{"max_messages":1}`. Save the new job_id; poll
   `/api/v1/integrations/gmail/imports/{job_id}` about every2 seconds.
4. GET `/api/v1/integrations/gmail/imports/{job_id}/results`. A genuine successful
   selection has a SUCCESS row and its actual saved analysis; an unresolved204
   remains FAILED/GMAIL_PROVIDER_ERROR with no rows or additional inference.
5. If204 recurs, retain only the new safe diagnostic. GET/gmail.googleapis.com/
   default is the expected metadata. An injected mode warrants inspecting the
   trusted process launcher; an unexpected method/host warrants checking runtime
   customization. With expected metadata, operator/provider egress/origin evidence
   remains necessary to determine who produced204. Do not capture/share bearer
   headers, OAuth tokens, private response bodies or email contents, and do not
   disable TLS or relax response/selection checks to force success.

**Real Gmail import remains unverified; the remaining live204 origin is an external
acceptance/investigation blocker, not a proven application request defect.** This
change supplies the missing safe evidence and locks the correct failure behavior.
