# Live Groq integration verification

Date: **2 November 2026**, Asia/Kolkata.
Assessment: **LIVE_GROQ_VERIFIED** for the single authorized T01 smoke request.
Overall application release assessment remains **NOT READY**.

## 1. Environment and configuration

| Item | Verified value |
| --- | --- |
| Python | 3.12.16 |
| Groq Python SDK | 0.37.1 |
| LangChain-Groq | 1.1.3 |
| Configured model | `openai/gpt-oss-20b` |
| uv | 0.13.6 |

Inspected AGENTS.md, settings, T01 implementation, sentiment schemas/prompt,
.env.example, installed adapter code, REST route, investigation path, and MCP
tools. Settings load environment variables and the ignored project-root `.env`.
The credential file has restrictive owner-only permissions. No credential value,
substring, authorization header, or raw provider diagnostic is included here.

## 2. Credential status

**CONFIGURED**

## 3. Current provider documentation

Groq lists `openai/gpt-oss-20b` as supporting chat completions and strict
JSON-schema structured output. It documents Pydantic schema usage, and its Python
SDK documents async inference with AsyncGroq. References checked for this task:
[model documentation](https://console.groq.com/docs/model/openai/gpt-oss-20b),
[structured outputs](https://console.groq.com/docs/structured-outputs), and
[official SDK async usage](https://github.com/groq/groq-python#async-usage).

The existing T01 factory uses ChatGroq, the configured credential/model,
`with_structured_output(SentimentResponse, method="json_schema", strict=True)`,
and an async shared HTTP client. No alternative Groq implementation was created.
The existing schema uses required fields and closed objects; local validators
enforce enums, lengths, aspect names, and exact source quotations.

## 4. Single-request controls

- One invocation of the actual `create_sentiment_service` / `SentimentService.analyze`.
- An in-memory Settings copy sets service retries to zero for this invocation
  only. The factory already sets SDK retries to zero; HTTP transport retries
  were also zero. Production retry behavior and configuration files are unchanged.
- The verification transport checks the outgoing model, `json_schema`,
  `strict=true`, required result fields, and closed root object before allowing
  one POST to Groq's canonical HTTPS chat-completions endpoint.
- A consumed request guard prevents a repeated invocation from silently issuing
  another inference. Redirects and synchronous inference are disabled in this
  verification instance. No preflight model-list or alternate inference occurred.
- Diagnostics/tracing were disabled; only selected numeric token metrics and the
  validated synthetic result were recorded. No request headers or provider bodies
  were logged. Exactly **one** live provider request was made, with no retry.

## 5. Provider connection and validation

| Check | Actual result |
| --- | --- |
| Provider connection | Successful; HTTP **200** |
| Authentication | Configured credentials accepted |
| Model accessibility | Authorized model accessible |
| Native strict structured output | **Strict mode accepted** |
| T01 Pydantic validation | **Passed** |
| Independent revalidation with existing SentimentResponse | **Passed** |
| Exact evidence verification | **Passed** |
| Controlled provider error | None |

The outgoing request was confirmed to use native strict JSON-schema mode. The
HTTP 200 response was parsed through the existing adapter and T01 validation;
it was then revalidated against the unchanged Pydantic model with the original
feedback as evidence context. No free-form fallback or schema modification was used.

## 6. Input and actual validated response

Synthetic input:

```text
The product quality is excellent, but the delivery was extremely late.
```

Context: `business_type=ecommerce`, `source=customer_review`.

Actual result, not a mock or expected-output fixture:

```json
{
  "sentiment": "MIXED",
  "issue_category": "DELIVERY",
  "urgency": "HIGH",
  "aspects": [
    {"name": "product_quality", "sentiment": "POSITIVE"},
    {"name": "delivery", "sentiment": "NEGATIVE"}
  ],
  "summary": "Customer praised product quality but complained about delivery being extremely late.",
  "suggested_next_step": "Investigate delivery delay and confirm if compensation is warranted.",
  "evidence_phrases": [
    "The product quality is excellent",
    "delivery was extremely late"
  ]
}
```

Manual semantic review:

- MIXED captures both the praise and complaint without requiring that output in
  advance. Product quality is positive; delivery is negative, matching the input.
- DELIVERY is consistent with the specific complaint. HIGH is an allowed urgency
  value, but this single example does not calibrate triage severity.
- The summary restates supplied information without inventing dates, causes,
  operational metrics, or actions already performed.
- The proposed next step is conditional investigation/review; it does not claim
  a refund, resolution, or external action occurred.
- Both evidence strings occur exactly in the supplied synthetic text.

## 7. Request metrics

| Metric | Actual value |
| --- | --- |
| Real provider requests | **1** |
| Retries | **0** |
| Wall-clock T01 request duration | **1.4903 seconds** |
| Prompt tokens | **856** |
| Completion tokens | **515** |
| Total tokens | **1,371** |

Token counts come from the provider response's numeric usage fields observed
through the existing client's transport. Latency includes the awaited T01
operation, HTTP connection/inference, parsing, and validation; factory setup is
excluded. This is one sample, not a benchmark or performance guarantee.

## 8. REST, LangGraph, and MCP reuse

`app/api/v1/sentiment.py` resolves the application-owned T01 service and awaits
`analyze` with the existing request/result schemas and API-key dependency.
The production factory in app/main.py is the same factory used for the live
request. REST authentication, request/response validation, sanitization, and
provider-error mappings were exercised only with local mocks in this task.
**The HTTP endpoint itself was not live-tested.** REST also requires its separate
APP_API_KEY configuration for real authenticated HTTP usage.

`InvestigationService` uses the existing graph; its analysis tool delegates each
record to T01. `app/mcp_server/tools.py` delegates analyze_feedback to T01 and
investigate_feedback to T02. Both use the shared implementations/configuration;
neither duplicates the sentiment prompt/classifier. Existing question, record,
graph, provider-timeout/retry, and tool admission limits remain in force.

Mocked regressions verify all four graph actions and official MCP discovery/
invocation in-process and over stdio. **No live LangGraph, selector, MCP, chat,
or batch request was made.** Their live end-to-end/model-quality behavior is
not established merely by this T01 smoke result.

## 9. Regression and dependency verification

Executed `uv run pytest -q` with the existing offline network-blocking fixtures,
explicitly blank provider/application credentials in the test process, and
mocked inference. Result: **220 passed in 9.28 seconds**, zero failures/skips/
errors. All existing API, schema, graph, batch, and MCP protocol checks passed.

`uv sync --locked --offline` and `uv pip check` passed. The lock contains 77
packages, and 73 installed packages were checked compatible. No dependency was
added or changed. Hash comparison confirms **no application source or dependency
file modification** during this task. QA-005 remains resolved.

Evidence: [sanitized live result/metrics](live-groq-result.json),
[regression console](live-groq-regression.txt),
[regression JUnit](live-groq-regression.xml), and
[dependency checks](live-groq-dependencies.txt).
Existing bounded mock performance checks ran as part of the suite; their output
is not additional live inference. The preceding QA-005 measurements are preserved
in qa005-benchmark-results.json.

## 10. Remaining limitations and final assessment

**LIVE_GROQ_VERIFIED** is scoped to one real synthetic sentiment request, using
the configured model, native strict mode, and unchanged service/schema. This
supersedes earlier credential-blocked/live-unverified status for the T01 smoke
check. It does not establish broad sentiment accuracy, adversarial robustness,
quota behavior, uptime, or live operation of every interface/model schema.

Tenant ownership and global ingress/resource findings remain open HIGH issues.
T06 ingestion/signed webhooks and Gmail are not implemented; deployment/repository
handoff and Gmail delivery scope remain unresolved. The full project is still
**NOT READY** for its complete delivery scope. The live T01 prerequisite has now
been demonstrated; T06 still requires separate explicit authorization and its
security/ownership groundwork. No T06 work was started.
