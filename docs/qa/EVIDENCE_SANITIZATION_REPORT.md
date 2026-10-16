# Strict evidence sanitization after bounded correction

6 November 2026. Implemented on the 832-test baseline. The user reports that live
Groq correction sometimes succeeds and sometimes still fails exact grounding.
This task used mocked Google/Groq only; **live sanitization is not yet verified**.
Neither complete AI reliability nor recovery from every invalid response is claimed.

## Investigation and decision

The shared T01 service already validates complete structured output with the
original feedback context, logs the fixed exact-grounding category, and allows
one correction generation through the same strict ChatGroq adapter. Corrected
output was then rejected even when the only remaining defect was a nonexact quote.
The trusted root-level evidence_not_grounded validation type distinguishes that
case from missing fields, malformed aspects, invalid enums/summary and parser/SDK
errors. The original exact-substring validator and strict adapter remain unchanged.

The existing SentimentResponse explicitly permits empty evidence. Batch reporting
already omits evidence excerpts for records with no evidence phrases; aggregation
still counts their validated classifications. Other shared consumers revalidate
against original input. The chosen policy therefore accepts a fully revalidated
empty list after sanitization, consistent with that existing response contract.

**Reduced-evidence trade-off:** removing quotes reduces supporting material. An
empty list means no model quotation survived. It does not independently substantiate
the sentiment, category, urgency, summary, aspects or recommendation. Even an exact
quote does not independently prove the interpretation is correct. The sanitizer
does not repair hallucinated summaries or verify business facts. Callers must read
the actual evidence list and must not present zero quotes as verified support.
No artificial quotation, confidence score or successful-evidence claim is added.

## Exact processing order and safety boundary

1. Generate with the existing provider-native strict JSON schema and validate all
   fields against the original feedback, with no change to first-generation behavior.
2. On an exclusively exact-grounding failure, keep its warning and make the existing
   single correction call with fixed verbatim-quotation guidance. Other failures
   follow their original rejection/provider classifications.
3. Validate the complete corrected result with the original feedback again. If it
   is valid, return it normally and log the existing recovered event.
4. If and only if the corrected result fails exclusively with the trusted root-level
   evidence_not_grounded error, retain phrases for which `phrase in original_text`
   is true. This is case-sensitive contiguous matching of the original Unicode
   string. Keep order and duplicates. No trim, Unicode normalization, fuzzy match,
   punctuation replacement, paraphrase or new quote is used.
5. Copy the corrected mapping with only evidence_phrases replaced, then run the
   complete SentimentResponse.model_validate with original feedback context again.
   Schema/field restrictions remain intact. The sanitizer changes no other field;
   the schema's existing normal validation behavior remains in force.
6. Return success only after that validation and original deadline checks pass.
   A final validation error still becomes INVALID_MODEL_RESPONSE. A deadline expiry
   remains UPSTREAM_TIMEOUT. No sanitization-success log precedes validation.

A first-generation mismatch never bypasses the correction call. Adapter-raised or
parser-wrapped validation exceptions do not qualify for sanitization. Evidence
blank/length/count/type errors, missing/extra fields, invalid enum/aspect/summary
or any other schema defect remain errors, including when nonexact evidence is also
present. SDK, parsing, output-type, authentication, rate and provider errors are not
converted to successful analyses.

The corrected response supplies all non-evidence fields. The service never falls
back to the first response's classification, reconstructs missing fields or mutates
the original result mapping. The unchanged original Pydantic evidence validator
continues to reject ungrounded output when called directly.

## Budgets and diagnostics

Sanitization is bounded local work over the existing maximum of 20 phrases, each
already subject to the existing field bounds. It adds no network or inference call.
The original request snapshot, one overall timeout and one global/tenant admission
permit cover initial generation, correction and sanitization. Deadline checks run
before and after the final sanitization validation. No permit is reacquired or
released early; cancellation and timeout cleanup remain unchanged.

The prior call bound remains GROQ_MAX_RETRIES + 2, default four invocations per
logical analysis. Initially valid output still uses one call; a grounding-only
initial/correction pair uses two in the absence of provider retries. The correction
has no separate provider retry budget. Gmail lifetime attempts/cooldowns are not
reset. Sanitization itself adds no Groq usage beyond the previously authorized
correction mechanism.

Two rejection warnings remain visible if both generations fail grounding. A
successfully revalidated sanitized result adds exactly this fixed INFO diagnostic
with bounded numeric counts:

```text
sentiment_output_sanitized category=exact_evidence_grounding retained=0 discarded=1
```

Counts reveal no quote content. This event is distinct from the existing
sentiment_output_recovered event for a model correction that validates directly.
No feedback, model content, phrase values, email identifiers, credential, provider
message, error string or traceback is included in these diagnostics. Tracing and
provider logging restrictions remain unchanged.

## API, Gmail and persistence implications

OpenAPI fields/endpoints and SentimentResponse schema remain identical. There is
an intentional authorized behavior change: a previously terminal *second,
otherwise-valid grounding-only* response can now return success with partial or
empty evidence. Other INVALID_MODEL_RESPONSE pathways remain failures.

All shared T01 consumers receive this policy: sentiment REST, ingestion, batch,
chat/graph, Gmail and the two local MCP tools. No new tool/client/graph is introduced.
Gmail commits a sanitized valid result as one SUCCESS and one SUCCEEDED metadata
identity with one logical attempt, including with empty evidence. Subsequent
imports skip it after job expiry or process restart; more evidence is not an
automatic reason to repeat classification. OAuth/jobs/results remain RAM-only.
Unrelated validation failures still commit FAILED and retain cooldown/retry rules.
No OAuth, selection/SENT rules, deduplication, tenant or PostgreSQL code changed.

## Files

Production modified:

- app/services/sentiment_service.py — only the targeted post-correction filter,
  full revalidation, deadline checks and fixed safe success event.

Added:

- tests/unit/test_evidence_sanitization.py — 57 deterministic cases.
- tests/integration/test_gmail_evidence_sanitization.py — 5 real PostgreSQL cases.
- docs/qa/EVIDENCE_SANITIZATION_REPORT.md — this report.

Existing tests updated to the authorized grounding-only behavior:

- tests/unit/test_sentiment_service.py — unrelated malformed outputs still reject;
  grounding-only repeated output returns validated empty evidence.
- tests/unit/test_evidence_recovery.py — still two calls maximum; only exclusive
  grounding can sanitize, other invalid correction outputs remain failures.
- tests/unit/test_sentiment_diagnostics.py — original warnings and privacy assertions
  retained while allowing the new sanitized result/event.
- tests/integration/test_sentiment_api.py — malformed input still rejects; repeated
  grounding-only model output now returns 200 with empty evidence and two calls.
- tests/integration/test_gmail_import.py — grounding-only success with zero quotes;
  the renamed test no longer falsely describes that outcome as a failed message.
- tests/integration/test_gmail_evidence_recovery.py — the negative retry/cooldown
  case now includes an unrelated correction schema defect, preserving its genuine
  failure assertions; dedicated new cases cover sanitized success/deduplication.

Docs modified: README.md, docs/GMAIL_INTEGRATION.md, and a historical banner on
EVIDENCE_GROUNDING_RECOVERY.md. No schema, prompt, settings, dependency, migration,
Gmail implementation, tenant registry, private .env or Git changes. No new config
is required. Restart FastAPI to load this service-code change.

## Actual verification

- Focused sentiment/recovery/Gmail suite: **268 passed in 56.64 seconds**.
- Full regression suite: **894 passed in 134.12 seconds; zero failures/errors/skips**.
- 832 baseline cases plus 62 new cases: 57 unit/adapter/budget cases and 5 real
  PostgreSQL Gmail cases. Grounding-only assertions intentionally reflect the
  requested success behavior; unrelated strict rejection tests remain intact.
- All 20 OpenAPI paths and schemas are identical to the pre-change snapshot.
- Source comparison confirms only sentiment_service.py changed in production;
  schema, prompt, Gmail/tenant/settings code, dependencies and migrations unchanged.
- All 80 installed packages pass compatibility checks. Documentation links and
  credential-pattern checks passed. No new live Google/Groq call was performed.

Evidence artifacts are `.local/qa/evidence-sanitization-focused.xml`,
`.local/qa/evidence-sanitization-full.xml`, `.local/qa/evidence-sanitization-summary.json`,
and the source/OpenAPI/compatibility snapshots under that prefix. These are temporary
local QA artifacts; no cross-environment retention claim is made.

Tests cover valid first output, valid correction, partial/empty sanitization,
verbatim/ordered duplicate retention, nonmutation of other fields, complete
revalidation with original context, final-validation rejection, all unrelated
schema/field/parser/provider errors, no third call, unchanged provider call bound,
deadline expiry before/after validation, admission/cancellation and content-safe
INFO/WARNING logs. The actual ChatGroq adapter is exercised with mocked HTTP and
strict wire schema checks. Real PostgreSQL verifies sanitized Gmail success,
restart deduplication, one-attempt accounting and genuine failed-schema cooldown.

Test providers are mocked and outbound access blocked. PostgreSQL tests use the
existing isolated *_test database and per-test random schemas. The local test
server is PostgreSQL 12.22; the existing supported-server acceptance limitation,
single application coordinator and environment-retention limits remain unchanged.
No live Google/Groq request, new dependency, deployment, Ruff/mypy or coverage claim.
The user's previously successful live model correction is not a live test of this
new deterministic sanitization step.

After README's project-local uv/Python/cache exports, full reproduction is:

```bash
T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket" \
  GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
```

For the new cases only, use that same environment with
`pytest -q tests/unit/test_evidence_sanitization.py tests/integration/test_gmail_evidence_sanitization.py`.
A missing test DB URL skips PostgreSQL cases and does not establish equivalent
verification. Never substitute a development/customer database for this test DB.

## Safe live verification

Restart using existing private configuration:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In Postman, use the owning X-API-Key and either POST /api/v1/sentiment/analyze with
fresh synthetic feedback or reconnect Gmail after restart and submit
POST /api/v1/integrations/gmail/import with {"max_messages":1}. Poll the job and
read its /results. Existing date/label/SENT/dedup/attempt rules still determine
eligibility; do not clear history or raise exhausted retry budgets to hide failures.

Check every returned evidence phrase against original submitted text. An empty
list is an explicit lack of retained model quotation, not verified support. A
fixed sanitized INFO event identifies this path and its retained/discarded counts;
a normal 200/COMPLETED alone does not prove sanitization ran. Other schema errors
should still report their original failure codes. Do not enable raw provider/OAuth
logging or share private feedback, outputs, secrets or authorization URLs.

Only a new real Groq result taking the sanitization path would establish live
sanitization acceptance. This implementation is verified locally with mocks; it
does not guarantee semantic accuracy or make every invalid model output recoverable.
