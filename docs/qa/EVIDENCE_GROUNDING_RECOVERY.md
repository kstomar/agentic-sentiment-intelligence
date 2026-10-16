# Safe, bounded exact-evidence recovery

Historical correction-only implementation report. The later
[strict evidence sanitization extension](EVIDENCE_SANITIZATION_REPORT.md) supersedes
the rule that a second grounding-only failure must remain terminal: it can now
discard nonexact phrases and fully revalidate the result without a third model call.
Other failures still reject. Original test evidence and decisions below are retained.

6 November 2026. Implemented on top of the 787-test Gmail eligibility baseline.
This report supersedes the no-invalid-output-retry policy from the earlier
[diagnostics-only report](SENTIMENT_MODEL_DIAGNOSTICS.md). Its historical results
remain intact. No new live Google or Groq call was made for this feature.

## Root-cause findings and uncertainty

The user supplied a live warning with category=exact_evidence_grounding,
stage=service and fields=evidence_phrases. This confirms that at least one returned
phrase did not occur exactly in the feedback used for final service validation.
It does not identify the phrase or prove paraphrasing, punctuation, whitespace,
Unicode composition, escaping or an extraction defect as the specific cause.
No private model response/email was collected to speculate beyond that evidence.

Inspection traced one input through prompt serialization and validation:

- SentimentRequest preserves original feedback; it rejects blank/oversized input.
- build_messages serializes the same text using JSON with Unicode preserved.
- The strict ChatGroq parser validates response fields without feedback context.
- T01 then validates the complete response with that original feedback context.
- Gmail extraction occurs before T01; IngestionService constructs its sentiment
  request from that extracted text and revalidates the result against the same text.

No demonstrated mismatch between text sent by the application and text validated
was found. Mocked tests preserve CRLF, tabs, quotes, backslashes, Unicode composition
and emoji through the actual adapter's request serialization. The service also now
snapshots its input model before awaits so a direct Python caller retaining the
mutable request cannot change the feedback between attempts/validation.

Strict JSON schema cannot establish that quotations occur in a particular input.
The existing exact-substring validator remains necessary and is unchanged.

## Exact behavior

1. Keep the original strict adapter, model allowlist, schema, validator and admission.
2. Make the original generation, with its existing provider-error retry policy.
3. If final service-context Pydantic validation fails, retain its existing safe
   warning. Recovery qualifies only if every error is the fixed root-level
   evidence_not_grounded type. Other field/parser/SDK/type errors do not qualify.
4. Permit one additional generation using the same original feedback and complete
   schema. Append only a fixed system instruction requiring contiguous verbatim
   quotations with original punctuation, whitespace, casing and Unicode. Do not
   replay the failed response, exception text, evidence or an assistant history.
5. Validate the entire correction with the same SentimentResponse and original text.
   Accept only a fully valid result. No quotation repair, truncation, normalization,
   phrase deletion, enum substitution or automatic empty-list fallback is performed.
   The existing schema still permits a model-generated empty evidence list.
6. If correction output is invalid, log its fixed diagnostic and return the existing
   INVALID_MODEL_RESPONSE. There is no third generation. Provider failures/timeouts
   retain their existing sanitized codes; they are not fabricated invalid results.

Only final service validation can initiate correction. An adapter-raised or
parser-wrapped ValidationError is not enough, even if it has a similar custom type.
The complete schema must have passed far enough to reach the trusted after-validator.

## Budgets, provider errors and cost

Both generations remain inside the same asyncio.timeout and ModelAdmission claim.
No permit is released/reacquired for correction, and no timeout is reset. A deadline
check prevents starting another invocation after the original budget expires.
Timeout still yields UPSTREAM_TIMEOUT. Cancellation/timeout release permits and
leave existing worker/claim cleanup in control.

The correction is **one invocation with no separate provider-retry loop**. An
initial authentication failure remains immediate; initial transient connection,
timeout/408/409/429/5xx errors retain their existing bounded retries/backoff and
Retry-After behavior. If the one correction invocation encounters a provider error,
it returns that same classified code without starting another retry budget.
SDK retries remain disabled; strict json_schema, model, max_tokens, temperature,
tracing and client configuration are unchanged.

For provider retry setting R, calls per logical analysis are bounded by R+2:
at most R+1 initial invocations plus one correction. With the default R=2 this
is at most four invocations; an initially valid result needs one. Targeted recovery
also applies with R=0, because that setting controls provider retries. It adds at
most one billable generation per eligible logical analysis; actual token/currency
usage was not measured with a live provider.

Gmail's separate logical attempt counter is unchanged. An initial generation plus
correction still commits one processing attempt, one terminal outcome and one
successful identity. Two invalid generations produce one FAILED attempt; cooldown
and the configured lifetime attempt budget remain. A new import does not reset
that budget. For Gmail attempt budget M, a conservative upper bound on sentiment
invocations is M*(R+2), not a nested reset of provider retries per correction.
The usual M=3/R=2 bound is twelve, all subject to the existing per-job deadlines.
Metadata/MIME failures can stop work before any model invocation.

All shared T01 consumers receive this narrowly scoped behavior: REST, Gmail,
batches, graph/chat and local MCP. Their logical quotas and own overall deadlines
remain in force. No Gmail eligibility, PostgreSQL, OAuth, tenant or endpoint rewrite.

## Privacy-safe diagnostics

The original rejection warning remains, including on eventual recovery success:

```text
sentiment_output_rejected category=exact_evidence_grounding stage=service fields=evidence_phrases
```

A fully validated recovery adds a fixed INFO event:

```text
sentiment_output_recovered category=exact_evidence_grounding
```

Repeated invalid grounding produces two rejection warnings and no success event.
No feedback, evidence, raw model output, prompt payload, exception string, provider
message, token, API key, mailbox or message ID is logged by these diagnostics.
Existing safe allowlisted field-path handling remains. Tracing stays disabled.
The INFO success event is visible with normal INFO logging; no debug mode is needed.

## Files changed

Production:

- app/services/sentiment_service.py — original-input snapshot, narrowly qualified
  correction, shared deadline/permit, hard call bound and fixed success diagnostic.
- app/prompts/sentiment.py — optional fixed correction instruction; original prompt
  and original human payload preserved for the first generation.

Tests:

- tests/unit/test_evidence_recovery.py — new deterministic recovery/budget/privacy tests.
- tests/integration/test_gmail_evidence_recovery.py — real PostgreSQL logical-attempt,
  cooldown and durable success tests over mocked Google/Groq.
- tests/unit/test_sentiment_diagnostics.py — deliberate expectations for two rejected
  service-grounding generations; all other single-failure expectations preserved.

Docs: README.md, docs/GMAIL_INTEGRATION.md, docs/qa/SENTIMENT_MODEL_DIAGNOSTICS.md
(historical banner) and this report. No schema, config/env, dependency, migration,
Gmail implementation, tenant authorization or Git change. No private .env edit.
No deployment or unrelated milestone started.

## Verification

- Focused recovery/sentiment/schema/API/Gmail suite: **132 passed in 3.13 seconds**.
- Complete regression suite: **832 passed in 131.44 seconds; zero failures/errors/skips**.
- All 787 previous test identities remain, plus 45 new recovery cases (43 unit,
  including adapter/tenant REST checks, and 2 real-PostgreSQL Gmail cases).
- OpenAPI is identical, including all 20 paths and schemas. Sentiment schema,
  Gmail/tenant/SQL implementations, configuration, migrations and dependency files
  are unchanged. All 80 installed packages passed compatibility checks.
- Documentation links and public credential-pattern checks passed. No new live
  Google/Groq call was performed; strict provider behavior was verified with mocks.

Evidence artifacts: `.local/qa/evidence-recovery-focused.xml`,
`.local/qa/evidence-recovery-full.xml`, `.local/qa/evidence-recovery-summary.json`,
and the compatibility, documentation and source/API snapshots under the same prefix.

The first focused run caught two new test fixtures using a mailbox body different
from their expected corrected quote. The fixtures were aligned to the intended
synthetic message; no validator was relaxed to make them pass.

Tests cover valid-first-call; mismatch then success; two mismatches; unrelated
schema/parser/type failures; original provider authentication/rate/server behavior;
no correction transport-retry multiplication; actual native strict adapter wire
format; exact original input across serialization; rejection logging/privacy;
single timeout; deadline exhaustion before correction; admission/tenant headroom;
cancellation; caller mutation; and Gmail logical attempts/restart dedup/cooldown.
Original Gmail incremental/eligibility/SQL/OAuth and all earlier regressions run in
the complete suite. Real isolated PostgreSQL is used; Gmail/Groq are mocked and
outbound network access is blocked. No live credentials are needed.

After README's local uv/Python/cache exports, reproduce the full suite against the
prepared isolated PostgreSQL *_test database:

```bash
T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket" \
  GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
```

For focused recovery tests use the same environment and select
`tests/unit/test_evidence_recovery.py tests/integration/test_gmail_evidence_recovery.py`.
Focused diagnostic coverage also includes the original sentiment service, schemas,
REST API and diagnostics modules. Missing test DB configuration skips PostgreSQL
cases and does not establish the reported database evidence. The test server is
PostgreSQL 12.22; its existing end-of-life/supported-server acceptance limitation
and single-coordinator restriction remain. Ruff/mypy/coverage are not newly claimed.

## Restart and safe live Postman verification

No configuration or migration change is required. **Restart FastAPI to load code**:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Use existing private settings. Do not enable provider debug or OAuth access logs.
A direct synthetic verification avoids depending on mailbox selection:

1. In Postman set base_url=http://127.0.0.1:8000 and the owning X-API-Key header.
2. POST {{base_url}}/api/v1/sentiment/analyze with JSON:
   {"text":"The product is excellent, but delivery was very late.","source":"manual","business_type":"general"}.
3. A 200 response must satisfy the existing schema and contain only exact evidence
   substrings. A valid first generation will have no recovery diagnostic. A fixed
   rejection followed by the recovered INFO event identifies a successful correction.
   An ordinary 200 alone does not prove the correction path ran.
4. For Gmail, reconnect the same tenant/mailbox after restart (OAuth/results remain
   RAM-only). Verify GET /api/v1/integrations/gmail/status shows CONNECTED.
5. After the existing cooldown, submit POST /api/v1/integrations/gmail/import with
   {"max_messages":1}; poll /imports/{job_id} and retrieve /imports/{job_id}/results
   under the same Gmail prefix. Selection still follows label/date/SENT/dedup/page
   rules; do not force an arbitrary message ID or reset durable attempts.
6. If eligible failed messages still have retry attempts, they can be retried. If
   the budget is exhausted, they remain deferred; use fresh synthetic feedback for
   acceptance rather than silently deleting history or increasing retry counts.
7. Record only status/error, counts and fixed diagnostic categories. Keep private
   feedback, responses, authorization URLs and credentials out of shared logs/reports.

A successful live response establishes that invocation passed strict validation.
Only a live rejection followed by recovery success verifies the correction path
with real Groq. Production recovery is **not yet verified** by these mocked tests.
The specific paraphrase/whitespace/punctuation origin of the original mismatch
remains unknown; no customer text was exposed to make that determination.
