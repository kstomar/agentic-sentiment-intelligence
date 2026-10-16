> Historical milestone report. The current 6 November 2026 academic submission assessment and executed evidence are in [FINAL_SUBMISSION_AUDIT.md](FINAL_SUBMISSION_AUDIT.md). Original decisions/counts below are preserved; academic submission and production release are different assessments.

> Current update — 4 November 2026: events:read now authorizes the sensitive stored original feedback and analysis through the new result route. Both reads filter tenant+delivery in SQL; HMAC/time/idempotency and quotas remain. Raw inputs/results persist indefinitely by default under explicit retention. No original scoped high finding is reopened by the executed evidence; this is not a security certification.
> [Feature report and evidence](FEEDBACK_PERSISTENCE_REPORT.md). The prior T09 report below is retained as milestone history.

# Security review — T09 PostgreSQL persistence

3 November 2026. No newly demonstrated critical or open high finding from the
original scoped pair. This is local code/test evidence, not production security
certification or a vulnerability scan. [Prior full review/history](history/pre-t09/SECURITY_REVIEW.md).

## Ownership (QA-001)

Original missing tenant ownership is resolved in the established T07 scope and
extended to PostgreSQL. Affected endpoints: POST /api/v1/batch/upload and all four
GET /api/v1/batch/jobs/{job_id}[ /report, /results, /download ]; webhook event status
and Gmail owner resources retain their existing T07/T08 authorization.
Relevant files: app/core/tenant_auth.py, app/api/v1/batch.py,
app/services/batch_service.py, app/storage/postgres_job_store.py,
app/storage/batch_models.py; existing event/Gmail route/service/store files are
unchanged (their exact endpoint/file maps remain in the linked prior review).

A forged or client-selected tenant cannot authorize a query. Verified batch:read
permission precedes SQL lookup by tenant+public ID, then child reads. Foreign and
unknown IDs share 404; valid create-only credentials cannot read status/report/
results/download or public store projection. Recovery obtains a current verified
batch:create principal from the configured registry; removed/read-only owners are
paused and still counted. Rotation credentials share tenant ownership/quotas.
No credential, proof, registry or caller-selected identity is persisted in tables.
Real PostgreSQL tests assert owner filtering in SQL before child rows and exercise
two separate tenants, unknown IDs, permission denial, rotation and recovery.

## Ingress/resource controls (QA-003)

Existing actual-byte 4 MiB JSON cap, 16 KiB webhook cap, 2 MiB multipart file cap,
authentication before protected intake, rate/deadline/admission limits, model permits,
webhook workers and per-owner quotas remain unchanged. They apply across sentiment,
agent, chat, direct ingestion, webhook and batch intake. Source: app/core/ingress_limits.py,
app/core/processing_limits.py, app/core/tenant_auth.py, app/services/batch_service.py
and the existing ingestion/webhook services. See the prior exact endpoint map.

T09 adds bounded connection pooling/timeouts, short off-loop transactions, a single
coordinator advisory lock, fenced bounded row claims, no transaction during model
awaits, and preserved active/retained quotas. Job-history saturation returns 429;
no eviction of active/history data to make room. Database errors roll back and
return fixed codes without SQL/URL/parameter disclosure. Worker shutdown waits for
commits, preserves durable outcomes and safely releases pending claims. No separate
unbounded worker/queue/model client was introduced.

## New storage risk and minimal operational design

Necessary pending raw text is durable until row outcome commit; derived summaries,
evidence and dates remain sensitive even after raw_text clears. Default indefinite
retention is an intentional T09 requirement and requires an explicit organizational
retention policy. Use least-privilege DB access, private backups with appropriate
encryption/expiry, protected storage/network, and policy review before customer use.
An explicit positive TTL enables cascading terminal deletion; it is not silent
short-lived expiry. Database server/proxy statement/error logging must independently
avoid capturing input parameters. SQLAlchemy echo is disabled, hide_parameters is
true and application SQL/provider diagnostics are suppressed/sanitized. Database
URLs use SecretStr; public examples use placeholders or the local private socket.

The development instance is isolated, Unix-socket-only, directory 0700, local trust
for this single-user environment, and a non-superuser app role. It is PostgreSQL
12.22, end-of-life; retest on a supported release before production. The separate
system cluster was untouched. Durable storage does not persist OAuth tokens or
webhook dedup state. No exactly-once/distributed guarantee, user-login system,
production network hardening, backup-restore acceptance or compliance approval.

## Verification and remaining gates

604 tests pass; 33 new real PostgreSQL cases, all 571 earlier cases retained.
[Schema evidence](t09-postgres-verification.json), [compatibility](t09-compatibility.json),
[T09 report](T09_IMPLEMENTATION_REPORT.md). All inference and Google calls mocked.
Only the historical one-call strict T01 live smoke is established; no new live call.
Live Google/Cloud/restricted-scope acceptance, supported-server verification,
operational handoff and optional static/coverage/advisory checks remain outstanding.
Production release remains NOT READY; these are not inferred original reviewer requirements.
