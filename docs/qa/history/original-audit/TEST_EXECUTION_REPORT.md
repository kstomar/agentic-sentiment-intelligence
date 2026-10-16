# Test execution report

## Final executed result

Audit date: 30 October 2026 (Asia/Kolkata). Final run started at
`2026-10-30T17:34:43.157494+05:30`. **210 collected,
209 passed, 1 failed,
0 skipped, 0 collection/execution errors**.
Pytest duration: **17.732 seconds**. Exit status: **1**.
No pytest warning summary was emitted; warnings count reported by this run: 0.
Normal captured application rejection logs are not pytest warnings.

| Area | Collected | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- |
| integration | 82 | 81 | 1 | 0 | 0 |
| performance | 3 | 3 | 0 | 0 | 0 |
| security | 25 | 25 | 0 | 0 | 0 |
| unit | 100 | 100 | 0 | 0 | 0 |

The failing assertion is deliberately retained. A green suite is not claimed.
Missing features are not represented by skipped/fake passing tests.

## Environment and dependency changes

- Python: 3.12.16, interpreter `/home/rails/agentic-sentiment-intelligence/.venv/bin/python`.
- Platform: Linux-5.15.0-139-generic-x86_64-with-glibc2.31; architecture x86_64; 12 logical CPUs
  reported by the host (not a guarantee of assigned CPU quota).
- uv: 0.13.6; official MCP SDK: 2.3.0.
- pytest: 9.2.0; pytest-asyncio: 1.4.1.
- User-approved installation: `uv add --dev 'pytest>=8,<10' 'pytest-asyncio>=1,<2'`.
  This added a dev group and updated uv.lock; five packages were installed:
  pytest, pytest-asyncio, iniconfig 2.3.1, pluggy 1.7.0, Pygments 2.21.0.
  The lock also records platform-conditional dependencies. Runtime dependency
  declarations and application source are unchanged.
- Locked offline synchronization and `uv pip check` passed: 77 lock packages,
  73 installed packages checked and compatible. See [dependency output](dependency-checks.txt).
- Coverage measured: **No**. coverage/pytest-cov, Ruff, and mypy are missing;
  no mypy configuration exists. No unauthorized tooling was installed.

The initial package-download attempt failed because sandbox DNS could not
resolve PyPI. The approved command succeeded outside that network restriction.
Async REST/stdio verification used the execution mode required by the known
sandbox process/thread limitation. This did not authorize live provider calls.

## Reproduction

From `/home/rails/agentic-sentiment-intelligence`:

```bash
export PATH="$PWD/.tools/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
export UV_PYTHON_BIN_DIR="$PWD/.tools/bin"
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_CACHE_DIR="$PWD/.cache/uv-python"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
export PYTHONDONTWRITEBYTECODE=1
uv sync --locked --offline
uv pip check
uv run --locked --offline python --version
uv run --locked --offline pytest -q --junitxml=docs/qa/test-results-final.xml
```

An external shell with normal local thread/subprocess support is required. No
network inference is required. The autouse fixture clears inherited application
settings, disables credentials/tracing, and blocks outbound sockets and real HTTP
transports. HTTPX ASGITransport/MockTransport and mock model interfaces remain
usable. The stdio child bootstrap independently blocks networking, injects mocks,
and executes the production module entry point. The no-key subprocess launches
the actual module with explicitly blank provider credentials.

`pytest.ini` configures asyncio and test discovery. tests/helpers.py provides
fabricated deterministic responses rather than another production classifier.
Re-running the suite updates benchmark JSON; preserve the current evidence if a
new run must be compared. The QA reports describe this recorded run, not future
measurements.

## Test development history

1. Initial completed unit subset: **90 passed in 0.44 s** (`unit-first.xml`).
2. First complete run: **208 passed, 2 failed in 18.05 s** (`test-results.xml`).
   One failure was the real blank-source contract defect; the other was a test
   traversal assumption that every FastAPI route has `.path`.
3. Installed FastAPI 0.162 uses deferred `_IncludedRouter` branches. The test
   harness was corrected to use `fastapi.routing.iter_route_contexts`, retaining
   the same expected effective route set, including hidden routes. This was a
   test compatibility correction, not a production fix or weakened expectation.
4. Final complete run: **209 passed, 1 failed in 17.73 s**. No production assertion
   was changed to conceal the remaining failure.

## Failed test and recommended fix

- **ID:** QA-005, MEDIUM.
- **Test:** `tests/integration/test_batch_api.py::test_explicit_blank_source_is_rejected`.
- **Input:** valid fabricated CSV with text_column=review and explicit empty source.
- **Expected:** HTTP 422 according to README and UploadOptions nonblank constraint.
- **Actual:** HTTP 202. Assertion `202 == 422` fails.
- **Likely cause:** optional Form default substitution precedes model validation;
  the route checks raw blank ID/date mappings but not raw source.
- **Affected files:** app/api/v1/batch.py, app/schemas/batch.py, README upload contract.
- **Recommended fix:** distinguish omitted and supplied-empty source at the raw
  multipart boundary; reject the latter and preserve the omitted default. Review
  blank business_type handling in that authorized change, then rerun regressions.

## Representative end-to-end workflows

| Workflow | Input/components | Actual result | Status | Automated evidence |
| --- | --- | --- | --- | --- |
| A | Text → REST → actual T01 with mock model → schema | Four explicit sentiment fixtures accepted; invented evidence rejected | VERIFIED locally | test_sentiment_api.py; actual ChatGroq MockTransport test |
| B | Records/question → T02 selector → LangGraph → tools/verification | Reconciled counts, source IDs/evidence, and bounded termination | VERIFIED locally | test_investigation_api.py; all four conditional-route tests |
| C | Chat ANALYZE_TEXT → T01 | Exactly one classification, deterministic envelope | VERIFIED locally | test_chat_analysis_workflow_c_reuses_t01_once |
| D | Chat INVESTIGATE_FEEDBACK → T02 | One graph execution, preserved answer/counts/evidence | VERIFIED locally | test_chat_investigation_workflow_d_preserves_findings |
| E | CSV → background job → mapper → report/download | 202, partial row failure, valid report, pagination and attachment | VERIFIED locally | test_upload_report_download_workflows_e_f[csv] |
| F | XLSX → background job → mapper → report | First-sheet input, partial outcome, reconciled JSON | VERIFIED locally | test_upload_report_download_workflows_e_f[xlsx] |
| G | Official MCP client → discovery → analyze_feedback | Structured T01 output in legacy/modern in-process and stdio | VERIFIED locally | test_mcp_server.py |
| H | Official MCP client → investigate_feedback → LangGraph | Structured T02 findings and source evidence | VERIFIED locally | test_mcp_server.py |
| I | Signed webhook → worker → status | Components absent; no invocation/test invented | NOT_APPLICABLE | T06 NOT_IMPLEMENTED, source/OpenAPI inventory |

Additional tests cover provider 401/429/500, network errors, timeouts, bounded
retries, no auth retries, malformed model output, unknown graph actions, exact
quote verification, ID/count tampering, stateless requests, per-job partial/fatal
failures, retention, raw-text clearance, parser cancellation, capacity, shutdown,
and official MCP protocol-only stdout/clean process exit.

Security characterization tests intentionally demonstrate missing tenant
ownership and missing JSON byte limits. Their pass means the observation was
reproduced, not that the security requirement is satisfied.

## Small safe performance measurements

All results are **mocked local application/protocol overhead**, not Groq latency,
throughput, or production SLOs. HTTP uses in-process ASGITransport. MCP latency
uses an initialized in-process legacy protocol connection; subprocess startup is
verified separately and excluded from these latency samples. No destructive
stress or operating-system changes occurred. Fixtures/workbooks are constructed
before timing; no explicit warm-up exclusion is applied. Error count excludes
expected 422 validation rejections. p95 is the nearest-rank sample percentile;
20–30 samples provide only indicative small-sample results.

| Operation | Samples | Median ms | p95 ms | Max ms | Unexpected errors | Concurrency |
| --- | --- | --- | --- | --- | --- | --- |
| health | 30 | 0.6612 | 1.0258 | 1.4305 | 0 | 1 |
| validation | 30 | 2.0621 | 2.5676 | 5.6882 | 0 | 1 |
| mock_sentiment | 30 | 1.7639 | 2.3523 | 3.6436 | 0 | 1 |
| mock_investigation | 20 | 6.4100 | 7.4274 | 10.1995 | 0 | 1 |
| csv_100 | 20 | 0.8252 | 1.0033 | 1.0210 | 0 | 1 |
| xlsx_100 | 20 | 6.7247 | 7.9836 | 8.0499 | 0 | 1 |
| aggregation_100 | 20 | 1.3880 | 1.5367 | 2.1365 | 0 | 1 |
| mcp_inprocess_mock_sentiment | 30 | 1.0835 | 1.3740 | 7.2269 | 0 | 1 |

Total measured operations: 200. Webhook HMAC benchmark:
NOT_APPLICABLE because no verifier exists. [Raw measurements](benchmark_results.json)
are generated by tests/performance/test_local_benchmarks.py.

## Evidence and limits

- Final [JUnit XML](test-results-final.xml), [console output](pytest-output-final.txt),
  [environment](environment.json), [summary](audit_summary.json),
  [source inventory](source_inventory.json), and [OpenAPI](openapi.json).
- No live Groq/account/model-quality, external desktop MCP host, Gmail, webhook,
  production proxy/TLS/deployment, dependency advisory scan, or coverage evidence.
- Crafted archive safety cases are bounded fabricated fixtures, not an exhaustive
  malicious-workbook corpus. No real encrypted vendor workbook was available;
  corruption/unreadable-workbook and archive-safety paths were tested.
- Source/OpenAPI hashes prove application contracts were unchanged, not that all
  possible runtime or host configurations are correct.
