> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Source handoff and archive policy

The source handoff uses a separate ignored writable directory,
`.local/reviewer-submission/`, without Git commands or modification of the original
read-only .git mount. No upload or publication is performed.

Status: **CREATED AND VERIFIED**. All selected members match source/manifest bytes;
private/runtime/Git paths and credential patterns are absent. The completed archive,
SHA-256 sidecar, source-content ledger and verification receipt are in that directory.
The receipt records final file counts/sizes and checksum after the last package build.
The original public source and historical QA/reviewer artifacts remain unchanged.

Archive filename: `agentic-sentiment-intelligence-source-20261102.tar.gz`.
Checksum filename: `agentic-sentiment-intelligence-source-20261102.tar.gz.sha256`.
Receipt: `SOURCE_ARCHIVE_RECEIPT.json`; embedded contents: `SUBMISSION_MANIFEST.json`.
No archive checksum is embedded into source documentation, which would create a
circular content hash. The delivered sidecar/receipt are authoritative for its bytes.

From the project root, inspect the completed artifact without extracting over source:

```bash
cd .local/reviewer-submission
sha256sum -c agentic-sentiment-intelligence-source-20261102.tar.gz.sha256
gzip -t agentic-sentiment-intelligence-source-20261102.tar.gz
tar -tzf agentic-sentiment-intelligence-source-20261102.tar.gz
```

The archive root is agentic-sentiment-intelligence. Extract into a fresh review
folder if desired, then follow its README and docs/reviewer/FINAL_DEMO_SCRIPT.md.
Only source/docs/tests/configuration are bundled; no runnable environment/cache.

## Contents

One top-level directory, agentic-sentiment-intelligence, contains the existing
application source, all tests/helpers, documentation and test history, README,
AGENTS, pyproject.toml, uv.lock, pytest.ini, .python-version, .gitignore and the
credential-free .env.example. Only explicit public directories/root files are
selected; hidden/private directories and runtime paths are never traversed.

The embedded SUBMISSION_MANIFEST.json lists every selected source file's relative
path, byte size and SHA-256. It does not hash itself. Archive metadata is normalized
(regular files only, owner0, fixed timestamps); gzip timestamp is fixed. Actual
source contents, tests and historical reports are not rewritten for packaging.

Excluded: .git, .env and private variants, .venv, .tools, .cache and bytecode/test/
style caches; .aws/.ssh/.codex/.agents, credentials/secrets/token stores; .local and
the archive itself; databases/journals, customer upload/export files, runtime logs,
local reports, temporary directories/files and unsupported non-source artifacts.
Original raw customer data and OAuth tokens are not selected. Public historical
Groq evidence and all test/reviewer examples use synthetic feedback; fabricated
API/OAuth/signing fixtures remain necessary for the included offline tests and are
not operational credentials.

## Verification procedure

Fail closed on symlinks, special files, forbidden names/suffixes, unexpected file
types, duplicate or traversal/absolute paths, member size/content hash mismatch or
credential-pattern findings. Compare selected bytes against the current source and
embedded manifest. Confirm required app/test/docs/config entries exist and .env.example
secret fields are empty. Scan known live Groq/Google/GitHub/AWS/private-key patterns
without printing values. This bounded scan and public allowlist are evidence, not
an exhaustive DLP or security certification.

The final receipt and SHA-256 sidecar are outside the archive, avoiding a circular
archive hash. Use the sidecar against the delivered archive bytes, not a displayed
hash copied into an embedded document. The checksum detects corruption, not author
identity/authenticity. No signing/provenance claim is made through the blocked Git mount.

## Review and reproduction

Start with docs/reviewer/FINAL_PROJECT_SUMMARY.md and FINAL_DEMO_SCRIPT.md. Tests
need Python3.12 and the locked dependencies; runtimes/package caches are deliberately
not bundled. A new machine needs an approved uv installation and available package
artifacts; --offline works only when its cache/environment is already provisioned.
No real provider key or .env is needed for offline fixtures.

The existing developer README explains uv setup; no installer, network download,
new dependency or system Python change was made for this package. No Docker/hosting/
CI/CD/frontend is included or required by communicated reviewer scope. Public docs
retain original environment-specific source paths as historical evidence; follow
relative links/use your extracted project directory when working elsewhere.

Files/archive are available in the current managed environment. Cross-session or
container-restart retention is unverified; copy the completed handoff through an
authorized download/file transfer before losing the environment. No automatic
transfer is performed. Connections/jobs/tokens/dedup inside the application are
intentionally nondurable and are not part of this source archive.
