# Test execution — T07

Date: 2 November 2026, Asia/Calcutta.

**447 collected; 447 passed; 0 failed, 0 skipped, 0 errors; 11.461 seconds (console 11.46 s), exit 0.**

| Area | Collected | Passed | Failed | Skipped |
| --- | --- | --- | --- | --- |
| Integration | 116 | 116 | 0 | 0 |
| Security | 214 | 214 | 0 | 0 |
| Unit | 114 | 114 | 0 | 0 |
| Existing local mock benchmarks | 3 | 3 | 0 | 0 |
| Total | 447 | 447 | 0 | 0 |

All 330 baseline case IDs remain. 117 new cases cover the T07 security policy in
five modules plus a fabricated-credential helper. Existing assertions were not
weakened or skipped. Baseline setup adaptations: autouse verified development
context for direct service/store calls; signed synthetic delivery fixtures and
new status method signatures; frozen wall time for the original 5 ms-skew sweeper
test while monotonic TTL continues. Production has no default principal; new
negative tests explicitly clear context and reject unauthenticated calls.

## New evidence

- Registry/API authentication: Alpha/Beta identity, missing/invalid keys, frozen
  principals, forged/unrelated-registry claims, malformed/oversized JSON and
  duplicate properties/IDs/secrets, owner mappings, bounds, permissions on every
  protected operation, safe ordinary/structured/JSON error diagnostics.
- Compatibility: existing dev key, explicit registry+legacy development owner,
  production legacy rejection even when flag true, overlap keys sharing owner/
  quota and revoked key rejection. No caller identity field changes authority.
- Batch: all four HTTP read variants deny foreign owners with the same 404 as
  missing resources; service/store read paths reject foreign/missing authority;
  owners read/download; concurrent owners, rotation, CSV/header/query spoofing,
  expiry erasure and protection against rebinding an occupied store's authority.
- Webhook: tenant-bound HMAC, changed integration identity rejection, signed body
  tenant claims rejected, same-ID cross-tenant independence, same-tenant cross-
  integration409, retry/conflict/auth checks, concurrent atomic duplicates,
  service-boundary signed-context forgery rejection, status/store isolation/expiry.
- Quotas: one owner's saturation leaves another capacity; global model/HTTP/queue
  caps still enforce; whole-investigation cap includes chat; batch parsing keeps
  reservations after cancellation; worker scheduling skips saturated tenants;
  pending/retained/rate bounds and expiry; body/provider deadlines and cancellation
  release counters; invalid keys cannot reserve tenant/model/work capacity.
- Existing T01–T06 and official MCP protocol/stdio regressions pass. New MCP check
  proves registry secrets are not discovered, tenant_id arguments reject and
  launcher-authorized stateless analysis remains usable.

## Executed commands

After README's local uv/Python/cache/.venv exports:

```bash
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' WEBHOOK_SHARED_SECRET='' WEBHOOK_INTEGRATION_ID='' uv run --locked --offline pytest -q --junitxml=docs/qa/t07-full.xml
uv sync --locked --offline
uv pip check
uv run --locked --offline python --version
uv --version
```

Full pytest exit 0. Network-blocking fixtures and mocked inference were active;
all credentials are fabricated. Existing ASGI/thread/subprocess checks ran outside
the restricted sandbox with authorization. No real Groq or external webhook
request occurred. The three existing bounded mock benchmarks regenerated their
artifact; they are not a live performance/load test.

[JUnit](../../t07-full.xml), [actual console](../../t07-pytest-output.txt),
[dependency checks](../../t07-dependency-checks.txt), [summary](../../t07-summary.json).
Locked offline sync77resolved/73 installed checked compatible; dependency files
unchanged. Python 3.12.16/uv 0.13.6/MCP 2.3.0. Coverage/Ruff/mypy/advisory scanners
were neither added nor run. [T06 history](../pre-t07/TEST_EXECUTION_REPORT.md),
[original audit](../original-audit/TEST_EXECUTION_REPORT.md),
[QA-005 focused evidence](../../QA005_REMEDIATION_REPORT.md) remain retained.
