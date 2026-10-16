> Historical milestone report. The current 6 November 2026 academic submission assessment and executed evidence are in [FINAL_SUBMISSION_AUDIT.md](FINAL_SUBMISSION_AUDIT.md). Original decisions/counts below are preserved; academic submission and production release are different assessments.

> Current update — 4 November 2026: Persistent direct/webhook original feedback, actual analysis and idempotency now use PostgreSQL. All604 previous cases plus34 new pass (638 total). One result endpoint is additive; no new dependency or provider call.
> [Feature report and evidence](FEEDBACK_PERSISTENCE_REPORT.md). The prior T09 report below is retained as milestone history.

# Project audit — T09

3 November 2026. **T09 PostgreSQL batch persistence is implemented and verified
locally; production release remains NOT READY.** This report updates the latest
milestone, preserving the [full pre-T09 audit](history/pre-t09/PROJECT_AUDIT_REPORT.md).
Original reviewer wording is unavailable: reviewer-compliance assessment remains
PROVISIONAL; deployment/frontend are not inferred mandatory reviewer deliverables.

T01–T08 remain implemented in their documented scopes. T09 replaces the production
in-memory batch registry with PostgreSQL-only SQLAlchemy2/psycopg3 repositories,
Alembic revisions, tenant SQL filtering and restart recovery. All five batch routes
retain their public API; completed reports/downloads persist by default. No SQLite,
new agent, graph, queue framework, frontend or other integration was implemented.

604 tests pass (571 previous + 33 PostgreSQL), with no failed/skipped/errors.
The 33 execute against an isolated real PostgreSQL 12.22 server, not SQLite;
inference/Google are mocked. Entire OpenAPI is identical, all 19 paths. Existing
MCP in-process/stdio, graph/chat, Gmail, webhook, tenant and report regressions pass.
Dependencies are locked and all 80 installed packages compatible. Coverage/static/
advisory tooling and broader live acceptance remain unverified.

[Implementation report and modified files](T09_IMPLEMENTATION_REPORT.md),
[test report](TEST_EXECUTION_REPORT.md), [security](SECURITY_REVIEW.md),
[contracts](API_CONTRACT_REPORT.md), [known issues](KNOWN_ISSUES.md),
[readiness](RELEASE_READINESS_REPORT.md). Machine evidence: [summary](t09-summary.json),
[source inventory](source_inventory.json), [manifest](t09-manifest.json),
[PostgreSQL schema](t09-postgres-verification.json), [compatibility](t09-compatibility.json).

The test server is end-of-life; supported-server retesting is required before
production. One coordinator, at-least-once inference and durable sensitive derived
data are intentional limits. App restart persistence is proven; whole-environment
retention is unverified. The real .env and Git mount were not modified. Historical
submission archives were not rebuilt and do not contain T09. No new live request
or deployment occurred. Stop after T09; another milestone is not started.
