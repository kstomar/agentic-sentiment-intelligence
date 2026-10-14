> Current head —6 November2026: gmail_incremental_v1 adds the Gmail identity/retry
> ledger after feedback_results_v1. Run the same upgrade-head command. Existing
> batch/feedback data remain. See [incremental Gmail](GMAIL_INCREMENTAL_IMPORTS.md).
> Older revision references below describe the previous milestones.

> Previous ingestion milestone — 4 November 2026: that milestone added
> feedback_results_v1 (after t09_batch_v2), adding feedback_events without changing
> the batch tables. The same upgrade-head command applies both. See the
> [persistent ingestion contract](WEBHOOK_INTEGRATION.md) and
> [verification report](qa/FEEDBACK_PERSISTENCE_REPORT.md). T09-specific revision
> references below are retained as the original batch implementation history.

# PostgreSQL batch storage — T09

T09 replaces production batch memory storage with PostgreSQL/SQLAlchemy 2,
Alembic and psycopg3. PostgreSQL is the only supported application database;
there is no SQLite prototype/fallback. Existing API requests/results/download JSON
remain unchanged. Later revisions persist direct/webhook feedback/results and Gmail message metadata;
OAuth credentials and historical Gmail jobs/results remain process-local.

## Existing environment and isolated local server

The environment had PostgreSQL 12.22 binaries and a stopped system cluster.
That system cluster was left untouched. T09 created a separate cluster under
`.local/postgres-t09`, private socket `.local/postgres-t09-socket`, local role
sentiment_app and separate agentic_sentiment_dev / agentic_sentiment_test databases.
The role is not a PostgreSQL superuser and cannot create databases/roles. Directories
are 0700; TCP is disabled. Local trust authentication is restricted by that private
Unix-socket directory and is intended only for this single-user development setup.
No real password, API key, customer feedback or private .env was created/changed.

The actually tested server is 12.22, which is **end-of-life**. Use a supported release
and reverify before production. See [PostgreSQL version policy](https://www.postgresql.org/support/versioning/).
No modern-server/production verification or system-server upgrade is claimed.

### Start the prepared local server

From this project's directory, using its existing installation:

```bash
export PG_BIN="$(pg_config --bindir)"
"$PG_BIN/pg_ctl" -D "$PWD/.local/postgres-t09" status
```

If it is stopped:

```bash
"$PG_BIN/pg_ctl" -D "$PWD/.local/postgres-t09" \
  -l "$PWD/.local/postgres-t09/server.log" \
  -o "-k $PWD/.local/postgres-t09-socket -c listen_addresses=''" -w start
```

These are database setup commands, not a deployment stack or system-service change.
Never initialize over existing data. The source/tests do not start/alter a server.

### First-time cluster and database creation elsewhere

Install a supported PostgreSQL server with your environment administrator, then
set PG_BIN to that installation. If making an equivalent private local cluster,
run this only when its PG_VERSION does not already exist:

```bash
mkdir -p .local/postgres-t09 .local/postgres-t09-socket
chmod 700 .local/postgres-t09 .local/postgres-t09-socket
"$PG_BIN/initdb" -D "$PWD/.local/postgres-t09" --auth-local=trust \
  --auth-host=reject --username=t09_owner --no-locale --encoding=UTF8
```

Start as above, then create the role/databases once (already done in this workspace):

```bash
psql -h "$PWD/.local/postgres-t09-socket" -U t09_owner -d postgres \
  -v ON_ERROR_STOP=1 \
  -c 'CREATE ROLE sentiment_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
createdb -h "$PWD/.local/postgres-t09-socket" -U t09_owner \
  -O sentiment_app agentic_sentiment_dev
createdb -h "$PWD/.local/postgres-t09-socket" -U t09_owner \
  -O sentiment_app agentic_sentiment_test
```

For an administrator-managed passworded server instead, create a dedicated role
and database in an administrator psql session. Set the password interactively;
do not paste it into source, shell command arguments or shared transcripts:

```sql
CREATE ROLE agentic_app LOGIN;
\password agentic_app
CREATE DATABASE agentic_sentiment OWNER agentic_app;
```

Configure an appropriate authenticated/encrypted connection and access/logging policy
for that server. Public examples contain placeholders only. No Docker is needed
for the existing environment, and none is introduced.

## Configure the application and run migrations

Use README's local Python/uv/cache exports and the isolated .venv. For the prepared
private-socket development database:

```bash
export DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_dev?host=$PWD/.local/postgres-t09-socket"
export BATCH_JOB_TTL_SECONDS=0
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

For a passworded server, set DATABASE_URL privately in the supported form:
`postgresql+psycopg://app_user:<URL_ENCODED_PRIVATE_PASSWORD>@localhost:5432/agentic_sentiment`.
Never display the actual URL. DATABASE_URL is SecretStr configuration and SQLAlchemy
parameters/driver diagnostics are not exposed to clients. The committed INI has no
URL/credential. Replace any old sqlite:/// URL; it is no longer a supported backend.
Do not copy the .env.example placeholder password as a usable credential.

**Existing private .env overrides still apply.** If an earlier .env contains
BATCH_JOB_TTL_SECONDS=1800, it still explicitly enables30-minute expiry. Set it to 0
or use the export above for indefinite retention. The task did not rewrite .env.
API/business/Groq credentials remain the existing private settings; new live inference
was not part of T09. Missing DATABASE_URL leaves stateless features available but
batch work fails closed503. A configured unavailable/unmigrated/occupied database
fails application startup with a fixed safe error; check configuration, migration
and the single-worker guard privately.

Alembic revisions:

- t09_batch_v1 creates jobs/records, JSONB, indexes and initial constraints.
- t09_batch_v2 normalizes explicit business_type/source fields from job options and
  strengthens claim/terminal invariants without discarding job data.

Current startup verifies revision gmail_incremental_v1; it never implicitly creates tables.
The chain continues through feedback_results_v1 (feedback_events) and
gmail_incremental_v1 (gmail_message_tracking). Older T09 revision names above are history.
`uv run --locked alembic current` inspects the revision using private configuration.
Downgrades refuse destructive operations; restore into a separate database or use
a separately reviewed migration rather than dropping customer tables.

## Sessions, concurrency and recovery

The sync psycopg engine has a bounded4-connection pool, no overflow,5-second pool/
connect/statement limits,3-second lock timeout and pre-ping. Production async routes,
creation, worker transactions and maintenance offload blocking database work. Each
ORM Session/transaction closes before inference; only a separate idle coordination
connection holds a session advisory lock, without an open transaction or row lock.

One Uvicorn application worker per database is supported. A second coordinator
fails closed on the PostgreSQL advisory lock. Do not use --workers 2, multiple app
replicas or overlapping reload/failover as a distributed design. Other existing
Gmail/webhook/rate state is still process-local. The guard detects lock-connection
replacement/loss and stops admitting work; restart the application to reacquire safely.

Validated jobs/records commit before202/scheduling. A bounded task per job claims
one record atomically with row locking/SKIP LOCKED and a random fencing token.
A claim lease lasts GROQ_TIMEOUT_SECONDS+15 seconds; the actual model operation also
has a deadline. Committed SUCCESS/FAILED rows are skipped, not replayed. Every
settled outcome and corresponding job counters commit together. No database
transaction is held while waiting for Groq.

Graceful shutdown awaits outstanding commits, cancels model work and returns owned
unfinished claims to PENDING; it clears RAM copies, not PostgreSQL. A crash can
leave PROCESSING rows: recovery waits for their leases to expire rather than
immediately stealing active work. Tokens prevent a stale writer overwriting a
new result. A lost response before commit can require another external call;
**at-least-once recovery, never exactly-once Groq execution**. Extreme pauses/failures
around lease boundaries are another reason not to claim distributed execution guarantees.

Recovery uses current verified tenant CREATE authority from the server registry.
Removed/read-only owners stay paused without an unauthorized model call; restoring
an eligible credential allows recovery. Tenant ownership is stored separately from
key IDs, so credential rotation preserves access. Paused jobs still consume quota;
restore authority or perform an explicit authorized administrative cleanup if needed.
No original lost in-memory job can be reconstructed or fabricated after the fact.

## Retention, data privacy and capacity

Default BATCH_JOB_TTL_SECONDS=0 retains terminal reports/results indefinitely.
A positive value explicitly enables deletion after completed_at+seconds, including
existing terminal jobs; a periodic/lazy maintenance step deletes expired parent
jobs and cascades records. Setting back to 0 removes outstanding expiry timestamps
for retained jobs; already-deleted jobs cannot be recovered without a backup.
Pending/running jobs are not TTL-evicted. There is no new public delete endpoint.

Existing quotas remain: default3 active jobs globally,20 retained globally and5
retained per business, with existing owner/model headroom. Indefinite retention
can fill those quotas and cause429; history is not silently evicted. Choose explicit
retention/capacity settings for the organization's needs. Limits remain configurable
within existing bounds. No user can change another owner's quota or identity via data.

Pending raw text is stored because retry/recovery needs it, then cleared from the
row when its final outcome commits. Invalid records store metadata/errors, not
invented analysis. Derived summaries, aspects and exact evidence can contain private
feedback and are retained until the explicit policy deletes them. PostgreSQL access,
backups, replicas and operator copies need their own secure retention policy; reference
cleanup is not cryptographic erasure. Original filenames are deliberately not retained
or used as filesystem paths. No credentials or principal proofs are persisted.

Application SQL/provider logs are suppressed or parameter-hidden. Configure database
server logs separately to avoid statement/parameter/DETAIL payload disclosure
(for example log_statement=none, log_error_verbosity=terse and restricted error-statement
logging appropriate to your server). Do not enable SQL echo or publish database logs.

## Backup and restore

Use a private ignored path and matching PostgreSQL client tools. For the prepared
local database, a consistent custom-format backup can be made with:

```bash
mkdir -p .local/backups
chmod 700 .local/backups
pg_dump -h "$PWD/.local/postgres-t09-socket" -U sentiment_app \
  -d agentic_sentiment_dev -Fc -f .local/backups/agentic_sentiment.dump
```

A database backup contains customer-derived data and possibly pending raw input;
protect/encrypt it appropriately and define backup expiry separately. Keep .env and
API/OAuth credentials separate from source/database backups. .local/, data/, pgdata/
and *.dump are ignored. The .git mount remains untouched.

Restore only into a separately prepared empty database, not over live work:

```bash
pg_restore -h "$PWD/.local/postgres-t09-socket" -U sentiment_app \
  -d <NEW_EMPTY_DATABASE_OWNED_BY_SENTIMENT_APP> --no-owner .local/backups/agentic_sentiment.dump
```

Provide the restored database URL privately, apply migrations and start one app
worker with the intended tenant registry. Recovery still observes claim leases.
No production backup/restore, host/container recovery or modern PostgreSQL deployment
has been claimed by these local tests. Workspace-file retention across managed
environment/container replacement remains unverified; application-process restart
persistence has actual test evidence.

## Run real PostgreSQL tests

Use the dedicated test database, never developer/customer data:

```bash
export T09_TEST_DATABASE_URL="postgresql+psycopg://sentiment_app@/agentic_sentiment_test?host=$PWD/.local/postgres-t09-socket"
GROQ_API_KEY='' APP_API_KEY='' uv run --locked --offline pytest -q
uv pip check
```

The fixture requires a *_test database, creates a random schema for each PostgreSQL
case, runs real migrations and drops only that schema afterwards. Providers are
mocked/network blocked. If the test URL is missing those tests skip explicitly;
the T09 evidence run supplies the real URL and has no skips. Historical unit tests
use an explicit ephemeral adapter for unit-only lifecycle behavior; they are not
represented as PostgreSQL verification. No SQLite testing is used.

[Batch architecture](BATCH_PERSISTENCE.md), [Postman restart exercise](POSTMAN_BATCH_PERSISTENCE.md),
[T09 executed evidence](qa/T09_IMPLEMENTATION_REPORT.md).
