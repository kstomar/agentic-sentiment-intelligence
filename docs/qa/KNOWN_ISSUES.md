> Historical milestone report. The current 6 November 2026 academic submission assessment and executed evidence are in [FINAL_SUBMISSION_AUDIT.md](FINAL_SUBMISSION_AUDIT.md). Original decisions/counts below are preserved; academic submission and production release are different assessments.

> Current update — 4 November 2026: Missing ingestion-result capability is resolved for newly admitted direct/webhook feedback. Old discarded events cannot be backfilled. Interrupted work becomes FAILED/INGESTION_INTERRUPTED on restart; result-write failure requires restart and cannot fabricate analysis. Existing unresolved live/operational/version/static-assurance issues remain.
> [Feature report and evidence](FEEDBACK_PERSISTENCE_REPORT.md). The prior T09 report below is retained as milestone history.

# Known issues — T09

3 November 2026. Original issue history is retained in the
[pre-T09 snapshot](history/pre-t09/KNOWN_ISSUES.md), including links to original
210/209/1 audit, QA-005 remediation and later milestone snapshots. Current states:

| Issue | Current evidence/status |
| --- | --- |
| QA-001 Missing tenant ownership | RESOLVED in scoped T07 implementation; T09 SQL tenant+job filters, permissions and current-authority recovery verified against real PostgreSQL |
| QA-002 External ingestion/webhooks absent | RESOLVED in T06; current direct/HMAC/status regressions pass; event persistence remains intentionally outside T09 |
| QA-003 Incomplete ingress/resource controls | RESOLVED within single-instance T06/T07 scope; T09 preserves limits/quotas and adds bounded DB operations/claims |
| QA-004 Wider live acceptance | OPEN; prior single strict T01 synthetic smoke verified; no broader paid/live acceptance or new call in T09 |
| QA-005 Explicit blank source accepted | RESOLVED; original unchanged regression passes; full suite now 604 passing; omission/default and nonblank behavior preserved |
| QA-006 Operational/Git handoff | OPEN; Git mount untouched; deployment/proxy/TLS/logging/backups/release provenance unverified. Batch app-restart loss is now resolved; other integrations remain process-local |
| QA-007 Gmail external acceptance | Local T08 implementation mock-verified; real Google/Cloud/restricted-scope acceptance outstanding; not automatically an original-reviewer blocker |
| QA-008 Documentation | Updated for T09; historical reviewer source archive remains pre-T09 and is explicitly labeled; original reviewer assignment unavailable |
| QA-009 Optional assurance | Coverage/Ruff/mypy/advisory scans unrun; not installed during T09 |

## T09 limitations and follow-up

- Only PostgreSQL 12.22 was available/tested; it is end-of-life. Reverify a supported
  server before production. No modern-server compatibility claim is made.
- One application coordinator is enforced with a PostgreSQL advisory lock. No
  multiple Uvicorn workers/distributed queue or exactly-once external inference.
  A crash before result commit may repeat that uncommitted call after lease expiry.
- Pending raw inputs and retained derived quotes/summaries are sensitive. Default
  terminal TTL 0 is indefinite; explicit positive retention opts into deletion.
  Existing private .env TTL=1800 still deletes; override deliberately, not silently.
- Retained quotas remain finite; history saturation rejects new uploads with 429
  rather than deleting prior jobs. Removed/read-only owners' unfinished work pauses
  and remains counted until appropriate authority/retention is restored.
- Already lost/expired in-memory job IDs cannot be reconstructed. Use new uploads
  after PostgreSQL migration and retain the same database/tenant across restarts.
- Other Gmail/webhook/OAuth state remains nondurable. Workspace/DB files are
  available now; managed-container replacement retention and backup restore are unverified.

[Implementation and exact correction](T09_IMPLEMENTATION_REPORT.md),
[Postman restart procedure](../POSTMAN_BATCH_PERSISTENCE.md),
[updated release assessment](RELEASE_READINESS_REPORT.md).
