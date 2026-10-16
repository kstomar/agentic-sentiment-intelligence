> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# End-to-end verification — local/mocked

The fresh full suite passed **571/571 in18.834 seconds JUnit (18.83s console)**,
with0 failures/skips/collection or execution errors and0 pytest warnings reported.
All571 T08 baseline case IDs are retained, including all124 Gmail cases.
[JUnit](pytest.xml), [console](pytest-output.txt), [case ledger](test-results.json).

In addition, [verify_workflows.py](verify_workflows.py) executed the following nine
workflows through FastAPI ASGI, the actual ChatGroq adapter/strict schemas, official
MCP client and HTTPX MockTransport. Socket/DNS and real HTTP transports are blocked;
Google and Groq credentials/outputs are fabricated. No production code/configuration
or existing tests were modified. These are nine additional scenario checks, not
nine extra collected pytest cases. [Actual results](workflow-results.json),
[console](workflow-output.txt). Expected owner-denial log warnings contain only safe
codes/request IDs; they are not pytest warnings or new security findings.

## Observed workflows A–I

| Workflow | Executed input/scenario | Actual observed result | Dependencies / scope | Executable evidence and final status |
| --- | --- | --- | --- | --- |
| A — Sentiment | Four synthetic texts: excellent quality, late delivery, neutral package arrival, mixed quality/delivery | All200; POSITIVE/NEGATIVE/NEUTRAL/MIXED; native strict wire format and Pydantic/exact-evidence checks passed | Actual ChatGroq adapter; HTTP response fixture supplies labels | verify_workflows.py; test_sentiment_classifications; test_actual_chatgroq_adapter_strict_schema_with_mock_http — PASSED locally |
| B — LangGraph | Four records, one of each sentiment; each of four action-selection outputs | Four real conditional routes;1/1/1/1 sentiment counts; DELIVERY complaint count2 with IDs2,4; branch-specific tools_used | Real compiled StateGraph/selector adapter; controlled action/classifier outputs | workflow-results.json/B; test_all_four_conditional_routes — PASSED locally |
| C — Chat | ANALYZE_TEXT and INVESTIGATE_FEEDBACK using current synthetic text/records | Both200 with the correct exclusive sentiment/investigation response; deterministic investigation findings | Existing T01/T02 instances; no formatter model; mocked providers | workflow-results.json/C; both chat workflow tests and stateless validation tests — PASSED locally |
| D — CSV/Excel | Same four records uploaded as CSV and XLSX with ID/text mappings | Both202 → COMPLETED;4 successes; each sentiment25%; DELIVERY complaints2; delivery/product_quality aspects each2 and package_arrival1; status/results/report/download work | Actual parser/background jobs/Python-Pandas reducer; mocked independent T01 extraction | workflow-results.json/D; test_upload_report_download_workflows_e_f[csv/xlsx]; percentage/evidence tests — PASSED locally |
| E — MCP | Official Client discovers and invokes both tools with synthetic data | Exactly two tools; structured POSITIVE analysis and issue count2; controlled schemas/results | Real official in-process protocol/SDK; mocked Groq. Full suite also executes actual subprocess stdio | workflow-results.json/E; test_real_inprocess_protocol_workflows_g_h; test_stdio_official_client_protocol_only_stdout_and_clean_shutdown — PASSED locally |
| F — External REST | Authenticated external_api feedback with late delivery text |200, normalized ANALYZED response with NEGATIVE result through T01 | Actual tenant auth/IngestionService/T01; mocked HTTP provider | workflow-results.json/F; test_direct_reuses_t01_and_normalizes_metadata — PASSED locally |
| G — Webhook | Signed original JSON, followed by identical authenticated retry | First202; background status COMPLETED; retry200 DUPLICATE without another classification | Actual HMAC/timestamp/digest/store/worker; fabricated signing secret and mocked model | workflow-results.json/G; raw signature/parallel duplicate/timestamp/tamper tests — PASSED locally |
| H — Multi-business | Alpha creates batch data; Beta requests Alpha report; Alpha requests it | Foreign404; owner200. Full suite covers all four batch reads plus event/Gmail stores and forged authority | Real bounded registry, immutable principal, service/store ownership; fabricated keys | workflow-results.json/H; batch/webhook/Gmail tenant-isolation modules — PASSED locally |
| I — Gmail | Mock state/PKCE OAuth → verified mock profile → existing label/date selection → text import → owned results → disconnect | Connect/callback/status200; import202 → COMPLETED with one success; Beta results404; local disconnect/status cleared | Actual OAuth/Gmail/MIME/service/store/T01 code; Google and Groq HTTP mocked | workflow-results.json/I;124 Gmail cases reviewed and passed — PASSED with mocks; LIVE NOT VERIFIED |

## What the results establish

The provider response fixtures define labels, categories, aspects, summaries and
recommendations in advance. The application still makes real adapter calls,
validates structured outputs and evidence, runs actual conditional graph nodes,
and computes deterministic counts/percentages. These are integration and arithmetic
checks, not classification accuracy measurements. Two delivery-related records
really reduce to count2, and four single-class records reduce to25% each. Existing
tests also verify largest-remainder rounding, partial/invalid rows and forged IDs/
quotes/count rejection. Useful structured feedback intelligence is demonstrable
when classifications are valid; general model quality remains separately unmeasured.

No live Groq or Google request occurred in this audit. Prior live T01 evidence:
[original sanitized record](../qa/live-groq-result.json),
[historical report](../qa/LIVE_GROQ_VERIFICATION_REPORT.md),
[current schema/evidence revalidation](historical-live-evidence.json). That prior
one sample used openai/gpt-oss-20b, HTTP200/native strict/Pydantic/exact evidence,
1.4903 seconds and1,371 tokens. Its service-level success does not establish live
HTTP/graph/chat/batch/MCP/webhook/Gmail behavior or statistical accuracy.

## Reproduction and execution boundaries

After README's project-local uv/Python/cache exports:

```bash
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' GOOGLE_OAUTH_CLIENT_ID='' GOOGLE_OAUTH_CLIENT_SECRET='' uv run --locked --offline pytest -q --junitxml=docs/reviewer/pytest.xml
.venv/bin/python docs/reviewer/verify_workflows.py
uv sync --locked --offline
uv pip check
```

The fresh suite and completed scenario verification ran with authorized execution
outside the restrictive sandbox for thread/subprocess compatibility; network
blocking remained active. A stalled sandbox copy of the scenario script was stopped
without changing application files. The completed run is the source of workflow-results.
The script disables .env loading in its own process and clears inherited Settings
variables before importing application composition. Never pass real credentials
in test command arguments. The full suite's fixture regenerates a mock benchmark
artifact; its fresh copy is [retained here](mock-benchmarks.json), and the existing
QA artifact was restored byte-for-byte to preserve earlier reports.

No new dependency: locked offline sync77resolved/73checked, all installed compatible,
Python3.12.16/uv0.13.6/MCP2.3.0. [Dependency output](dependency-checks.txt).
No coverage/Ruff/mypy/advisory tool was installed/run. Production/API/test and
existing QA hashes are checked in [preservation evidence](preservation.json).
