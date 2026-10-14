# Postman: verify PostgreSQL persistence across a FastAPI restart

This is a manual acceptance procedure, not a claim that Postman or live Groq was
executed during T09. The automated equivalent uses real PostgreSQL and mocked
inference. Manually analyzing through your configured Groq account consumes its
quota; no new live provider request was made by this implementation task.

## 1. Configure database and start the existing API

Use [PostgreSQL setup](POSTGRESQL_BATCH_STORAGE.md). The prepared local cluster
and developer database are separate from the stopped system cluster. Start that
server only if it is stopped, then use README's project-local Python/uv exports.
From the project root:

```bash
export DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_dev?host=$PWD/.local/postgres-t09-socket"
export BATCH_JOB_TTL_SECONDS=0
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The two exports override any old sqlite:/// or 1800-second values in a private .env.
Use your existing private API/Groq/tenant registry configuration; do not print it.
For a different PostgreSQL server, privately configure the correct psycopg3 URL.
Do not use --workers 2. Keep the same database and tenant identity across restart.

## 2. Prepare a private/local Postman environment

| Variable | Value |
| --- | --- |
| base_url | http://127.0.0.1:8000 |
| api_key | Your existing owning business credential, entered privately |
| batch_job_id | Set from the upload response |
| batch_report_before | Saved synthetic report JSON for comparison |
| batch_download_before | Saved synthetic download JSON for comparison |

Do not put credentials or actual customer feedback in a shared demonstration.
Use the provided synthetic [t09_reviews.csv](examples/t09_reviews.csv) file.
Health: GET `{{base_url}}/health` returns 200 `{"status":"ok"}`; liveness is not
provider readiness. X-API-Key authenticates batch operations, not a body tenant field.

## 3. Upload the four synthetic reviews

Method: **POST** `{{base_url}}/api/v1/batch/upload`.
Header: **X-API-Key** `{{api_key}}`.
Body: **form-data**. Let Postman generate multipart Content-Type/boundary.

| Key | Type | Value |
| --- | --- | --- |
| file | File | Select docs/examples/t09_reviews.csv |
| text_column | Text | review |
| id_column | Text | id |
| date_column | Text | date |
| business_type | Text | general |
| source | Text | customer_review |

Expected: HTTP 202 with a generated 32-character lowercase hex job_id, status PENDING,
total_records 4 and the existing acceptance message. The transaction has already
committed jobs/records before this response. Save that original ID. Optional
Postman post-response script:

```javascript
pm.test("Accepted", () => pm.response.to.have.status(202));
pm.environment.set("batch_job_id", pm.response.json().job_id);
```

## 4. Poll status and retrieve the completed report

**GET** `{{base_url}}/api/v1/batch/jobs/{{batch_job_id}}`, same X-API-Key header.
Poll until COMPLETED, PARTIAL_SUCCESS or FAILED. For four successful records,
processed_records and successful_records are 4, failed_records 0, progress_percentage 100.
Provider errors can produce controlled partial/failed outcomes; they are not
invented success. A retained job remains visible even when individual records fail.

**GET** `{{base_url}}/api/v1/batch/jobs/{{batch_job_id}}/report`.
Before terminal state: 202 JobStatus. On a valid terminal report: 200 BatchReport.
Check total 4, counter reconciliation, percentages totaling 100 over successful rows,
source-linked issues/aspects/evidence and the same public job ID. Model classifications
may vary in a live manual run; do not assume a particular 25% distribution or accuracy.
Save the actual synthetic response for equality after restart:

```javascript
pm.test("Report returned", () => pm.response.to.have.status(200));
pm.environment.set("batch_report_before", JSON.stringify(pm.response.json()));
```

## 5. Retrieve results, pagination and download before restart

All requests use the same owning API key:

- **GET** `{{base_url}}/api/v1/batch/jobs/{{batch_job_id}}/results`
- **GET** `{{base_url}}/api/v1/batch/jobs/{{batch_job_id}}/results?page=2&page_size=2`
- **GET** `{{base_url}}/api/v1/batch/jobs/{{batch_job_id}}/download`

Results should contain the settled records in original input order. With four
settled records, page 2/page_size 2 contains C, D. Download remains 200 JSON with report
and results, Content-Disposition filename `batch-<job_id>.json`; no new export format.
Postman's Save response can save that JSON. Capture the synthetic download:

```javascript
pm.test("Download returned", () => pm.response.to.have.status(200));
pm.environment.set("batch_download_before", JSON.stringify(pm.response.json()));
```

## 6. Restart FastAPI without changing database or tenant

Stop only the Uvicorn process with Ctrl-C and start it again with the same
DATABASE_URL/BATCH_JOB_TTL_SECONDS and tenant configuration:

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

If using a new terminal, repeat the local uv exports and the two database/retention
exports from step1. Do not remove the PostgreSQL data directory, change database
URL, run destructive migrations or change the owner's tenant ID. A new key for the
same configured tenant may access the same history; a different tenant may not.

## 7. Retrieve the same ID after restart

Repeat status/report/results/pagination/download with the **original** batch_job_id.
Do not upload another file to obtain a replacement ID. Each completed resource
should return200 and the same report/results. Retrieval does not call Groq.
Compare the report post-response:

```javascript
pm.test("Report survived FastAPI restart", () => {
  pm.response.to.have.status(200);
  pm.expect(pm.response.json()).to.deep.equal(
    JSON.parse(pm.environment.get("batch_report_before"))
  );
});
```

For download, compare against batch_download_before in the same way. The automated
T09 tests assert exact before/after status/report/results/download equality for CSV
and XLSX, including pagination and zero retrieval model calls.

## 8. Tenant-denial check

Repeat report/results/download with a separate valid business credential belonging
to another tenant. Expected: 404 BATCH_JOB_NOT_FOUND, same shape as an unknown ID.
An absent/invalid key gives 401; a key without batch:read gives 403. Supplying a tenant
string in query/header/CSV does not transfer ownership. Never reveal another key in
a recording; fixture-based tenant demos use fabricated credentials.

## 9. Interrupted-job recovery

Use the automated 100-record recovery test for a repeatable no-cost demonstration:

```bash
export T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket"
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q \
  tests/integration/test_postgres_batches.py::test_postgres_100_record_interruption_keeps_40_commits_and_recovers_60 \
  tests/integration/test_postgres_batches.py::test_postgres_stale_crash_claim_is_recovered_without_repeating_committed_rows
```

A manual live job can also be stopped while running and restarted, but is not
necessary for the automated acceptance. Graceful shutdown releases owned pending
claims; a hard crash can require waiting for GROQ_TIMEOUT_SECONDS+15 seconds before
a PROCESSING claim is eligible. Committed outcomes are skipped. A provider response
lost before its commit may be called again; no exactly-once claim.

## If 404 still occurs

Confirm the same persisted database/schema and original ID, valid ownership, migration
head and retention0. An old 1800 override still opts into deletion. Already-expired,
previously lost in-memory jobs cannot be recovered by creating a new schema, and
T09 does not fabricate historical records. A quota 429 preserves existing history;
it does not evict jobs. [Architecture and limits](BATCH_PERSISTENCE.md),
[T09 actual test results](qa/T09_IMPLEMENTATION_REPORT.md).
