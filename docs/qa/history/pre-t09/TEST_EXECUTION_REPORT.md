# Test execution — T08

2 November 2026, Asia/Calcutta. **571 collected; 571 passed; 0 failed, 0 skipped,
0 errors; 18.286 seconds JUnit (console18.28s); exit0.**

| Area | Collected | Passed | Failed | Skipped |
| --- | --- | --- | --- | --- |
| Integration | 151 | 151 | 0 | 0 |
| Security | 261 | 261 | 0 | 0 |
| Unit | 156 | 156 | 0 | 0 |
| Existing local mock benchmarks | 3 | 3 | 0 | 0 |
| Total | 571 | 571 | 0 | 0 |

A JUnit case-ID comparison retains all447 T07 cases and adds124; none removed or
skipped. Before new tests, the447 baseline also passed against the new production
implementation. The only existing test-file change extends test_api_contracts.py
for seven authorized routes and the callback state security scheme; existing
operation checks remain. conftest and earlier regressions are unchanged.

| New module | Cases | Scope |
| --- | --- | --- |
| tests/security/test_gmail_oauth.py | 47 | Auth/permissions, state/PKCE, scopes, redirect, callback parameters, verified mailbox, token privacy and bounded HTTP |
| tests/integration/test_gmail_import.py | 35 | Selection, parsing, statuses/counts, dedup, foreign access, failures/evidence and provider contracts |
| tests/unit/test_gmail_mime.py | 31 | Plaintext/HTML, MIME, Unicode/charsets, body/header limits, attachment skipping and malformed data |
| tests/unit/test_gmail_lifecycle.py | 11 | Fair bounded admission, shared model limits, refresh single-flight, cancellation/disconnect/shutdown/expiry |

All tests use fabricated credentials, HTTPX MockTransport and mocked inference.
Autouse fixtures clear configured credentials and block sockets/DNS and real HTTP
transports. Existing MCP subprocesses use isolated mocked harnesses. No live
Google OAuth/Gmail, external webhook or additional Groq call occurred. In-process
and official subprocess stdio MCP, all graph paths, chat, CSV/XLSX/reporting,
HMAC/idempotency and owner/resource regressions pass. Existing bounded mock
benchmarks regenerate [their measurements](../../benchmark_results.json); these are
not live Google/Groq performance tests.

## Commands and artifacts

After README's project-local uv/Python/cache/.venv exports:

```bash
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' GOOGLE_OAUTH_CLIENT_ID='' GOOGLE_OAUTH_CLIENT_SECRET='' uv run --locked --offline pytest -q --junitxml=docs/qa/t08-full.xml
uv sync --locked --offline
uv pip check
uv run --locked --offline python --version
uv --version
```

The ASGI/thread/subprocess tests ran outside the restricted execution sandbox with
authorized offline execution; network-blocking fixtures remained active.
[JUnit](../../t08-full.xml), [console](../../t08-pytest-output.txt),
[dependency checks](../../t08-dependency-checks.txt), [summary](../../t08-summary.json),
[OpenAPI/source/dependency comparison](../../t08-compatibility.json).

Locked sync resolves77; all73 installed packages compatible. Python3.12.16,
uv0.13.6, MCP2.3.0. No package/dependency file changed. Coverage, Ruff, mypy and
advisory scanners remain uninstalled/unrun. No coverage or vulnerability clearance
claim. [T07 history](../pre-t08/TEST_EXECUTION_REPORT.md),
[original audit](../original-audit/TEST_EXECUTION_REPORT.md) and unchanged
[QA-005 remediation](../../QA005_REMEDIATION_REPORT.md) retain historical evidence.
