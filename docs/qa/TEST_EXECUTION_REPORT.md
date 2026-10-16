> Historical milestone report. The current 6 November 2026 academic submission assessment and executed evidence are in [FINAL_SUBMISSION_AUDIT.md](FINAL_SUBMISSION_AUDIT.md). Original decisions/counts below are preserved; academic submission and production release are different assessments.

> Current update — 4 November 2026: Final full suite:638 passed,0 failed/skipped/errors,45.675 seconds JUnit. All604 prior case IDs retained plus34 new (33 real PostgreSQL,one configuration). Official MCP/graph/chat/Gmail/batch regressions pass. Ruff/mypy/coverage unavailable and unrun.
> [Feature report and evidence](FEEDBACK_PERSISTENCE_REPORT.md). The prior T09 report below is retained as milestone history.

# Test execution — T09

3 November 2026. **604 collected/passed; 0 failed/skipped/errors; 28.462 seconds.**
All 571 previous case IDs retained plus 33 real PostgreSQL integration cases.
33 test modules: integration 184, security 261, unit 156, performance 3.

Executed with project-local uv/Python 3.12 and the dedicated PostgreSQL *_test URL:

```bash
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q --junitxml=docs/qa/t09-full.xml
```

See [database setup/test isolation](../POSTGRESQL_BATCH_STORAGE.md),
[JUnit](t09-full.xml), [actual console output](t09-pytest-output.txt),
[case-ID and exact OpenAPI comparison](t09-compatibility.json),
[versions](t09-summary.json) and [full T09 evidence](T09_IMPLEMENTATION_REPORT.md).

New cases use real PostgreSQL 12.22, SQLAlchemy/psycopg and Alembic, one random
schema per case in a separate test database. They verify CSV/XLSX restart equality,
40/100 interruption, claims/fencing/lease expiry, SQL ownership, pagination, partial
failures, commits/rollback/recovery, permissions, quotas and retention. PostgreSQL
cases executed: 33, skipped: 0. Providers are mocked; no actual inference performed.
Existing unit tests explicitly inject their historical ephemeral adapter and do
not establish PostgreSQL behavior. No original assertion was deleted or weakened.

A separate [two-interpreter restart check](t09-process-restart.json) also passed:
four synthetic rows created in process one, identical owned resources downloaded
in process two, zero retrieval inference and foreign-tenant 404. This additional
manual automation does not change the 604-case pytest count.

All earlier sentiment/schema/provider-adapter, graph/chat, parser/report, ingress,
webhook, tenant and Gmail mock checks pass. Official MCP 2.3.0 in-process and
subprocess stdio checks pass. Entire OpenAPI is unchanged across all 19 paths.
Locked offline sync: 84 resolved; uv pip check: all 80 installed compatible.
[Output](t09-dependency-checks.txt). These are compatibility checks, not vulnerability scans.

The three existing synthetic performance tests ran as part of the suite;
[benchmark_results.json](benchmark_results.json) contains the latest fixture metrics.
No PostgreSQL load/production performance claim is made. Coverage, Ruff, mypy and
advisory tooling were not run. Only end-of-life PostgreSQL 12.22 was available;
a supported release needs its own acceptance run before production.

[Preserved T08 execution history](history/pre-t09/TEST_EXECUTION_REPORT.md),
[original QA-005 remediation](QA005_REMEDIATION_REPORT.md). Archived benchmark and
source/OpenAPI snapshots remain under history/pre-t09.
