# Sentiment model-response diagnostics

Historical diagnostics-only report. A later user-supplied live diagnostic confirmed
the exact-grounding failure path and authorized one narrowly targeted correction.
The [current evidence-recovery implementation](EVIDENCE_GROUNDING_RECOVERY.md)
supersedes this report's no-retry policy and unknown-category assessment. The
original findings and test evidence below are retained as history.

6 November 2026. Targeted investigation of recurring INVALID_MODEL_RESPONSE during
Gmail imports. **The exact causes of the two reported live failures remain unknown.**
Their existing failed-job entries identify the public error only; they do not retain
model responses or the specific validation path. No email body, provider exception
message, private configuration or live mailbox was inspected for this task.

## Findings

The existing T01 adapter still uses `openai/gpt-oss-20b` by default with
`with_structured_output(SentimentResponse, method="json_schema", strict=True)`.
Unsupported strict models fail closed. SDK retries remain disabled, temperature is
0, max_tokens is 2048, streaming/cache are disabled and tracing is context-disabled.
No prompt, adapter parameters, model, validator restriction or retry count changed.

The installed langchain-groq adapter uses PydanticOutputParser. It validates the
schema without feedback context, and wraps a schema ValidationError in an
OutputParserException with that ValidationError as its direct cause. Invalid JSON
also raises OutputParserException, usually with a JSON parsing cause. Previously
both reached the same broad ValueError handler without a diagnostic distinction.
The service dumps parsed BaseModel results and validates again with the original
feedback context, which performs the exact substring check.

Provider-native JSON schema cannot establish that quotations occur in a particular
input. Local aspect-name, length/count/nonblank restrictions are also implemented
in Python validators rather than JSON-schema pattern/length keywords. A strong
prompt and strict schema therefore do not eliminate every local rejection. These
are possible failure mechanisms, not a conclusion about the reported emails.
No fallback, quotation normalization, truncation, enum coercion or fabricated result
was added. Malformed output remains rejected with the same public error.

## Safe diagnostics

One warning is emitted at the rejection boundary by logger `app.sentiment`:

```text
sentiment_output_rejected category=exact_evidence_grounding stage=service fields=evidence_phrases
```

| Fixed category | Failure path |
| --- | --- |
| groq_sdk_response_validation | Groq APIResponseValidationError: invalid SDK response envelope |
| structured_output_parsing | OutputParserException without a direct Pydantic ValidationError cause |
| unexpected_output_type | Normalized output is neither a dictionary nor a serializable BaseModel result |
| pydantic_schema_validation | Direct or parser-wrapped Pydantic schema/local field restriction failure |
| exact_evidence_grounding | Exact-substring validator rejects evidence with stable internal error type evidence_not_grounded |
| output_processing_error | Other ValueError/TypeError during adapter invocation or normalization; preserves prior controlled mapping |

Stages are fixed `adapter`, `normalization` or `service`. Known field identifiers
come only from complete allowlisted schema paths, including aspects.name and
aspects.sentiment. Unknown/extra field locations collapse to `response`, because
model-generated field names can contain customer data or forged log lines. Error
values, messages, raw exception types, tracebacks, parser llm_output, model output,
quotations, headers, tokens, mailbox addresses and message IDs are never logged by
these diagnostics. Pydantic error inputs/context/URLs are excluded when examining
locations. Valid analyses emit no rejection warning.

The evidence validator uses PydanticCustomError with a fixed type and the same
existing message, rather than a generic ValueError. Its predicate and all schema
restrictions are unchanged; the tag enables reliable classification without
matching exception text. All public responses still use INVALID_MODEL_RESPONSE.
This internal error type is not a new HTTP error code or JSON-schema property.

Groq HTTP status errors retain their existing classifications. For example, a
provider request rejection is UPSTREAM_REQUEST_REJECTED, not necessarily an invalid
parsed model response. Unexpected runtime failures still map to INTERNAL_ERROR.

## Retry assessment

**No invalid-output retry was added.** The two historical failures contain no
category evidence proving transience. Repeating an identical temperature-zero
request may reproduce a deterministic local validation failure and adds model
cost. The change intentionally gathers the missing category evidence first.

The current configured retries still apply only to the existing allowlisted
transport/status failures, within the original one wall-clock budget covering
attempts and backoff. Invalid output stops immediately even when max_retries is
positive; a transport retry followed by invalid output also stops. Therefore this
change introduces no extra inference calls or timeout extension.

If safe live diagnostics later demonstrate transient parse/schema failures, a
separately evaluated one-shot retry could share the existing total deadline and
attempt budget, repeat the same strict request, and revalidate completely. It must
not replay untrusted exception/output text into the prompt or retry indefinitely.
At most one extra billable inference per eligible logical call would be incurred;
Gmail's separate durable logical-attempt budget must also remain bounded.

Existing explicit Gmail failure retry remains available: another import after the
configured cooldown can retry a failed identity while attempts remain. Successful
identities continue to be skipped; no PostgreSQL tracking logic was changed here.

## Implementation and verification

Production files changed:

- app/services/sentiment_service.py — fixed logging categories, safe field extraction,
  explicit parser/schema exception handling; original error/retry behavior retained.
- app/schemas/sentiment.py — stable evidence failure tag, same validation rule.

Added tests/unit/test_sentiment_diagnostics.py: 30 tests, covering all categories,
wrapped and direct validation, nested/unknown field locations, forged sensitive
sentinels, exact evidence failures, successful output, normalization failures,
no automatic invalid-output retry and transport-then-invalid termination. Actual
ChatGroq parsing is exercised through mocked HTTP, including strict wire schema.
Original sentiment tests and assertions remain intact.

Docs changed: README.md, docs/GMAIL_INTEGRATION.md and this report. No dependency,
configuration, migration, Gmail import/store/provider, tenant or prompt changes.
No Git operation or private .env edit was performed. No live Google or Groq call.

- Focused sentiment/schema/API/diagnostic suite: **87 passed in 0.98 seconds**.
- Complete regression suite: **769 passed in 121.21 seconds; 0 failed/errors/skipped**.
- OpenAPI: identical to the pre-change snapshot, including all 20 paths and schemas.
- Source comparison: all previous tests, Gmail/tenant/OAuth/SQL code, migrations,
  prompt and dependency files are unchanged. Locked dependency compatibility passed.

The first sandboxed adapter run stalled; the corrected fixtures and focused run
passed outside the sandbox with outbound access still blocked by the test fixture.
Database regressions use the isolated PostgreSQL test database and temporary schemas.
Artifacts: `.local/qa/sentiment-diagnostics-focused.xml`,
`.local/qa/sentiment-diagnostics-full.xml` and compatibility/source snapshots there.
No coverage, Ruff or mypy result is claimed.

Use README's project-local Python/uv/cache exports, then reproduce:

```bash
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q \
  tests/unit/test_sentiment_diagnostics.py tests/unit/test_sentiment_service.py \
  tests/unit/test_sentiment_schemas.py tests/integration/test_sentiment_api.py

T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket" \
  GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
```

The dedicated test database must be running; do not point the tests at a customer
or development database. Without its URL, PostgreSQL tests skip, which would not
establish the same verification. Existing PostgreSQL 12.22 test-server limitations
and single-coordinator constraints remain unchanged.

## Live retest steps

1. Restart the application to load the new diagnostics using the existing private
   configuration and `uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log`.
2. Gmail connections/results are RAM-only, so reconnect the same tenant/mailbox
   through POST `/api/v1/integrations/gmail/connect` and its Google callback. Verify
   GET `/api/v1/integrations/gmail/status` returns CONNECTED. Do not enable OAuth
   query access logs or provider debug logging.
3. In Postman, use the owning X-API-Key and submit POST
   `/api/v1/integrations/gmail/import` with `{"max_messages":1}` after the configured
   failure cooldown (default 60 seconds), while the durable attempt budget remains.
   Existing scan limits and listing order determine which eligible message is
   selected; this API intentionally does not accept an arbitrary message-ID override.
4. Poll `/api/v1/integrations/gmail/imports/{job_id}` and read its `/results`.
   If invalid output recurs, record only the fixed warning category/stage/field
   identifiers. Do not share bodies, raw output, authorization URLs or secrets.
5. Success on retry proves that attempt succeeded; it does not identify why the
   historical attempts failed. Exhausted failures remain deferred under the existing
   policy; do not delete metadata or raise budgets merely to conceal failures.

There is no claim that the two original live failures are fixed. A new live attempt
that reproduces the error with these diagnostics is needed to identify its path.
