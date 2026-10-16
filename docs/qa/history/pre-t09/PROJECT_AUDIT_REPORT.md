# Project audit — T08

2 November 2026, Asia/Calcutta. **T00–T08 implemented; release NOT READY.**
The [T07 snapshot](../pre-t08/PROJECT_AUDIT_REPORT.md), earlier milestone
snapshots and original findings are retained. This assessment covers local
implementation and mocked verification, not Google approval or deployment.

T08 adds optional server-side Gmail authorization-code OAuth with single-use
owner-bound state, S256 PKCE, exact readonly scope checks, authenticated mailbox
identity, temporary token/refresh lifecycle and conflicting-owner rejection.
Seven typed versioned endpoints expose connection/import/status/results while
service/store boundaries enforce verified owner permissions. Import workers bind
the saved principal and share the existing T01 model budget and classifier.

Selection uses one configured existing feedback label and a bounded date filter;
no arbitrary query, broad scrape or polling. Pagination/message/response/MIME/text/
HTTP/model/job/dedup capacities and deadlines bound work. Metadata-first preflight
skips attachment-bearing messages before body retrieval, a documented conservative
limitation. Plaintext/inert HTML yields only text to existing T01, source=email;
no extra prompt/classifier/graph or remote MCP capability exists. Subject/sender
are transient. Temporary results contain validated analysis/message references,
not a raw-body field; evidence may quote short messages and remains sensitive.

Disconnect invalidates in-flight state, clears owner credentials/results/dedup and
cancels owner imports without affecting others. Shutdown clears private stores.
Tokens have an8-hour hard connection TTL; jobs/results/dedup have30-minute terminal
TTLs. No database, plaintext token file, new dependency, frontend or T09 work.

## Verification

**571 collected; 571 passed; 0 failed, 0 skipped, 0 errors; 18.286 seconds JUnit
(console18.28s), exit0.** All447 T07 case IDs remain plus124 new Gmail cases in
four test modules. One existing API-contract inventory test was extended for the
seven new routes and callback state scheme; assertions were not weakened.

Tests cover state entropy/single-use/replay/expiry/PKCE, fixed redirect, denial,
scopes, code exchange, verified mailbox conflicts, revoked/expired/missing refresh,
refresh serialization, direct service/store denials, jobs/results foreign404,
selection/pagination/MIME, attachment avoidance, schema/evidence failures, privacy,
capacity/headroom/shared model budgets, deduplication and lifecycle/cancellation.
Existing startup/OpenAPI, T01–T07 and official in-process/subprocess MCP pass.

Python3.12.16 / uv0.13.6 / official MCP2.3.0. Offline locked sync77resolved;
73 installed packages all compatible. pyproject.toml and uv.lock unchanged.
All12 existing OpenAPI operation objects compare equal to the pre-T08 snapshot;
only the existing ErrorCode schema gains21 Gmail values. Seven paths and their
Gmail schemas/state scheme are additive. Three permissions are appended. Private
responses add no-referrer; Uvicorn access logging is suppressed to protect query
secrets. [Tests](../../TEST_EXECUTION_REPORT.md), [comparison](../../t08-compatibility.json),
[full A–M report](../../T08_IMPLEMENTATION_REPORT.md).

## Findings and gates

QA-001 business ownership, QA-002 ingestion, QA-003 scoped resource controls and
QA-005 remain resolved; Gmail extends those controls with mock evidence. No
remaining demonstrated HIGH security finding from the original scoped pair is
claimed; this is not exhaustive certification. QA-007's missing implementation
is resolved locally, but Google Cloud setup/live acceptance/restricted-scope
verification remain OPEN external gates. QA-004 wider provider acceptance,
QA-006 Git/deployment and QA-009 optional assurance remain unresolved.

No live Google OAuth/Gmail or additional Groq request occurred. Prior one-sample
T01 native strict smoke remains verified only for that sample. Memory-only state,
mailbox claims and deduplication disappear on restart; no distributed/exactly-once
or secure memory overwrite guarantee. Files are available now; cross-session or
container persistence remains unverified. Git mount untouched, no Git commands or
deployment. T09 may begin only as separately authorized work; it was not started.
