# Academic ZIP handoff

6 November 2026. This submission is a source ZIP, not a Git/GitHub delivery.
No external recipient is contacted by the packaging process.

## Extract and start from your own environment

1. Save agentic-sentiment-intelligence-submission.zip to a writable Linux directory
   owned by your non-root user. Extract to a **new directory**, then enter its single
   agentic-sentiment-intelligence/ top-level folder. Do not extract over an existing
   private .env or database. Python's standard zipfile extractor or unzip can be used.
2. Read [README](../README.md), especially prerequisites, project-local uv 0.13.6/
   Python 3.12.16 installation and shell exports. Dependencies are pinned by uv.lock.
   A fresh machine needs download access; --offline applies only after tools/packages
   are cached. No .tools or .venv from the author's machine is required or included.
3. On this fresh copy, create private .env from .env.example and chmod 600 it. All
   real API/OAuth/HMAC/tenant credentials must be supplied privately by the evaluator.
   Replace the DATABASE_URL placeholder; it is not a working database password.
   The Postman environment is a **blank example**; secret/result/identity fields are
   empty, and its feedback is synthetic. Never share a populated private export.
4. Install PostgreSQL server/client binaries and initialize your own isolated cluster
   using README's bootstrap instructions, or configure your own private database.
   No active author's cluster, socket, database dump or password is in the archive.
   Run the full Alembic chain through gmail_incremental_v1 before database-backed work.
   Use a supported PostgreSQL release; the historical verification used EOL 12.22.
5. Start one FastAPI worker using README's command. Open http://127.0.0.1:8000/docs.
   With no database/provider configured, stateless startup and documentation work;
   inference/database features correctly report unavailable configuration. Copying
   the example database placeholder without replacing it will fail startup safely.
6. Configure a dedicated *_test database for the complete automated suite, with
   T09_TEST_DATABASE_URL set as documented. Tests block live providers and use
   fabricated credentials. Without this database, PostgreSQL tests skip: that is
   not equivalent to the audited complete run of **901 passed, including 113 real
   PostgreSQL and 21 MCP protocol cases**. These are overlapping subsets, not extra
   tests to add to 901.
7. Start local stdio MCP with .venv/bin/python -B -m app.mcp_server.server, from the
   extracted project root after installation. It is not an HTTP listener. Exactly
   analyze_feedback and investigate_feedback are exposed. See [MCP guide](MCP_INTEGRATION.md)
   for official SDK/client instructions, safe no-key discovery and controlled errors.

## Scope and evidence

The project is a bounded, tool-using LangGraph agentic workflow, not a fully
autonomous general-purpose agent. The [final academic audit](qa/FINAL_SUBMISSION_AUDIT.md)
is the detailed source/test/security assessment; historical reports are labelled.
**Real external MCP-client integration remains pending.** Official SDK in-process
and subprocess protocol tests are different evidence. Gmail live acceptance is
user-reported; this packaging task makes no live Google/Groq call. Sanitizer-specific
live exercise remains unverified. OAuth connections/historical Gmail job results
are process-local; only the processed identity ledger is durable. One coordinator,
bounded scans, empty-evidence and semantic-model limitations remain documented.

The archive's SUBMISSION_MANIFEST.json lists payload paths, byte sizes and SHA-256
hashes. It excludes its own hash to avoid self-reference. ZIP CRC and per-file hashes
are verified after extraction. The packager checks explicit candidate paths and
secret patterns/in-memory matches against local private configuration; a clean scan
does not certify absence of all secrets, unknown personal data or vulnerabilities.

Application, tests, migrations and dependency files are copied without modifications.
Current guides, safe synthetic examples and historical machine-readable evidence
are included. Obsolete console/output transcripts are omitted; historical text
references to those transcripts are not runtime requirements. Historical reports can
mention the author's old paths or excluded runtime files; use current README for
portable setup. Archived README bytes preserve history and its old root-relative
links are deliberately not rewritten.

Excluded: real .env, private tokens/credentials/Postman exports, .git, .local,
.tools, .cache, .venv, Python/pytest/type/lint caches, logs, sockets, databases/dumps,
private keys/certificates, temporary uploads, IDE/machine-managed metadata and builds.
No private data is deleted or credential rotated. No publication or transmission
occurs. Filesystem retention after a different session/environment is not guaranteed;
save your final ZIP in your own trusted storage.

## Share manually

Send **only the verified ZIP** through your evaluator's approved submission channel.
Do not attach your private .env, populated Postman environment, logs or databases.
Ask the evaluator to extract into a new folder and begin with README.md. Make the
pending external MCP-host acceptance and academic-only readiness scope explicit.
No Git repository or GitHub account is needed for this handoff.
