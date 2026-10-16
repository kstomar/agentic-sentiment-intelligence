# Test execution report — QA-005 follow-up

## Current result

30 October 2026, Asia/Kolkata. **220 collected, 220 passed, 0 failed, 0 skipped,
0 collection/execution errors**, **9.390 seconds**, exit status 0. Start:
`2026-10-30T18:55:06.139304+05:30`. No pytest warning summary was emitted.

The focused original test ran first after the fix, before new tests were added:
**1 passed**, console 0.09 seconds / JUnit 0.098 seconds. Its exact function text
matches the pre-fix snapshot. All **210 original cases** remain in the full run
and pass; ten legitimate source-validation cases explain the increase to 220.

| Area | Collected | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- |
| integration | 92 | 92 | 0 | 0 | 0 |
| performance | 3 | 3 | 0 | 0 | 0 |
| security | 25 | 25 | 0 | 0 | 0 |
| unit | 100 | 100 | 0 | 0 | 0 |

## Root cause, production change, and regression cases

FastAPI optional Form extraction maps an explicit empty string to Undefined and
substitutes the default before the route calls Pydantic. The only production
change is `app/api/v1/batch.py`: include source in its existing raw blank-field
guard for ID/date mappings. Empty or whitespace-only supplied source parts now
use the existing 422 path before file analysis/job creation. Omitted defaults,
normalization, bounds, schema/error envelopes, and source contracts are unchanged.

New tests cover omission, documented default, existing source labels, custom
metadata labels, trimming, the 64-character boundary, two whitespace forms,
65-character rejection, and non-text source parts. Invalid inputs create no job
or provider call; accepted inputs preserve report metadata and T01 manual-source
delegation. The original failing assertion is unchanged and remains a regression.

Batch source is not an allowlist: existing rules allow any nonblank 1–64 character
metadata label. T01 and MCP retain their separate shared source enumeration.
No arbitrary label was newly made unsupported.

## Executed commands and compatibility

Use README's documented project-local uv exports first, including local Python,
cache, bin, and .venv paths. Commands executed in order:

```bash
uv run --locked --offline pytest -q tests/integration/test_batch_api.py::test_explicit_blank_source_is_rejected --junitxml=docs/qa/qa005-focused.xml
uv run pytest -q --junitxml=docs/qa/qa005-full.xml
uv sync --locked --offline
uv pip check
uv run --locked --offline python --version
```

Both pytest commands exited 0. Compatibility checks also passed: Python 3.12.16,
uv 0.13.6, 77 locked packages and 73 installed packages checked compatible.
No dependency was added or changed in this remediation; pyproject.toml and uv.lock
hashes match their pre-fix snapshots. Existing offline network guards remain in
place. Tests used the execution mode required by sandbox thread/subprocess limits.
No live provider request was made.

The suite verifies FastAPI imports/startup, all existing REST APIs, Pydantic
response/evidence validation, all four LangGraph paths, batch CSV/XLSX/report and
lifecycle behavior, and official MCP in-process/stdio discovery, invocation,
errors, cancellation, and clean protocol output/shutdown. The complete generated
OpenAPI document matches the pre-fix snapshot exactly. No new regression was found.

The tenant-access and oversized-JSON characterization tests still pass by
reproducing unresolved security gaps; their pass is not a security-compliance claim.
Coverage remains unmeasured; Ruff, mypy, and coverage tooling were not installed.

## Audit history and evidence

- Original audit unit subset: 90 passed in 0.44 seconds.
- First full audit: 208 passed / 2 failed in 18.05 seconds (one test-harness route
  traversal assumption corrected for FastAPI 0.162, one true source defect).
- Final pre-remediation audit: 209 passed / 1 failed, 17.732 seconds. The real
  source assertion was retained unchanged, not skipped or weakened.
- Remediation: focused 1 passed; all original 210 cases plus ten new cases pass.

Original [test report](../original-audit/TEST_EXECUTION_REPORT.md),
[original full XML](../../test-results-final.xml), and original console output remain.
Current [focused XML](../../qa005-focused.xml), [focused console](../../qa005-focused.txt),
[full XML](../../qa005-full.xml), [full console](../../qa005-full.txt),
[dependency checks](../../qa005-dependency-checks.txt), and [integrity summary](../../qa005-summary.json)
record this correction. No failing assertion was removed or changed.

## Bounded mock measurements automatically rerun by the suite

The existing performance checks reran as part of the requested full suite. All
measurements below use mocks and concurrency 1, not live Groq. Samples are 20–30
per case, with nearest-rank p95 and no explicit warm-up exclusion; they are local
indicative overhead, not a production SLO or evidence of a speedup. Expected
validation rejections are not unexpected errors. Original audit measurements
remain [archived](../original-audit/benchmark_results.json).

| Operation | Samples | Median ms | p95 ms | Max ms | Unexpected errors |
| --- | --- | --- | --- | --- | --- |
| health | 30 | 0.3026 | 0.7887 | 2.0545 | 0 |
| validation | 30 | 0.8556 | 1.1601 | 2.7682 | 0 |
| mock_sentiment | 30 | 0.7744 | 0.9658 | 1.0091 | 0 |
| mock_investigation | 20 | 3.2369 | 3.6849 | 5.0171 | 0 |
| csv_100 | 20 | 0.3864 | 0.5123 | 0.5459 | 0 |
| xlsx_100 | 20 | 3.2134 | 4.0563 | 4.2465 | 0 |
| aggregation_100 | 20 | 0.6297 | 0.7788 | 1.2386 | 0 |
| mcp_inprocess_mock_sentiment | 30 | 0.4930 | 0.6431 | 3.5279 | 0 |

Webhook verification/benchmark remains NOT_APPLICABLE because T06 is absent.
Live Groq/account/accuracy, tenant isolation, deployment/proxy controls,
external desktop MCP hosts, Gmail, coverage, and advisory scanning remain
unverified or unimplemented as documented. **Release remains NOT READY.**
