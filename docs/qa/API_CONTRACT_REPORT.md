> Historical milestone report. The current 6 November 2026 academic submission assessment and executed evidence are in [FINAL_SUBMISSION_AUDIT.md](FINAL_SUBMISSION_AUDIT.md). Original decisions/counts below are preserved; academic submission and production release are different assessments.

> Current update — 4 November 2026: 20 paths: existing19 retained plus GET /api/v1/ingest/events/{delivery_id}/result. Existing request/response bodies and status codes remain; direct POST adds delivery-ID/Location headers. ErrorCode adds only INGESTION_INTERRUPTED. See machine comparison.
> [Feature report and evidence](FEEDBACK_PERSISTENCE_REPORT.md). The prior T09 report below is retained as milestone history.

# API contract report — T09

3 November 2026. **Entire OpenAPI document exactly equal to the pre-T09 snapshot**,
including all 19 paths and their operations/schemas. [Machine comparison](t09-compatibility.json).
No changes to request formats, public response JSON, validation, status codes,
pagination or download format. Five durable batch endpoints remain:

- POST /api/v1/batch/upload
- GET /api/v1/batch/jobs/{job_id}
- GET /api/v1/batch/jobs/{job_id}/report
- GET /api/v1/batch/jobs/{job_id}/results
- GET /api/v1/batch/jobs/{job_id}/download

Storage/operational semantics intentionally change: production batches require
PostgreSQL/migration head and commit before 202; terminal retention defaults to
indefinite (TTL 0). Existing positive TTL overrides still opt into deletion.
Database unavailability uses the existing sanitized BATCH_UNAVAILABLE error.
All owned reads filter tenant+public ID in SQL; foreign/unknown IDs remain 404.
Explicit blank source remains 422; omitted source retains its documented default.

CSV/XLSX reports, individual results, pagination and JSON downloads are exactly
equal before/after recreation with the same database/owner. Reads add no model
calls. API authentication, validated principals, HMAC bytes, Gmail and MCP contracts
are unchanged. One enforced coordinator is required; no new remote MCP tools.
604 tests pass, including the retained 571 cases and 33 PostgreSQL cases.

[T09 implementation/evidence](T09_IMPLEMENTATION_REPORT.md),
[Postman steps](../POSTMAN_BATCH_PERSISTENCE.md),
[retained T08 contracts/history](history/pre-t09/API_CONTRACT_REPORT.md).
The approved T06 4 MiB JSON/413 compatibility change remains unchanged; this task
does not introduce another body-limit or validation exception.
