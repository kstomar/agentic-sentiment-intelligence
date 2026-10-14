# T08 implementation report

2 November 2026, Asia/Calcutta. **T08 implemented and mock verified. Release NOT READY.**
No live Google OAuth/Gmail, additional Groq inference, Git command, deployment,
frontend, database or T09 work occurred. The real .env and dependency files are
unchanged. [Gmail operating guide](../GMAIL_INTEGRATION.md).

## A. Summary

Optional server-side readonly Gmail OAuth now connects a verified mailbox to an
authenticated business, supports local status/disconnect and explicitly triggered,
bounded imports, and exposes temporary owner-scoped job status/results. T01's
existing strict classifier, evidence checks and model budgets are reused. No
Gmail-specific prompt/model, graph, remote MCP tool or persistent credential file.

## B. Files

[Complete file manifest with hashes](t08-manifest.json) lists every created/modified
public project file, including generated evidence and archived history. It excludes
private credentials, ignored runtime caches and its own self-hash.

| Production file | Change |
| --- | --- |
| app/api/v1/gmail.py | New seven thin versioned routes and state-based callback security |
| app/schemas/gmail.py | New strict OAuth/connection/import/job/result contracts |
| app/integrations/google_gmail.py | New fixed-host bounded OAuth/Gmail HTTP adapter |
| app/integrations/gmail_mime.py | New bounded metadata preflight and MIME/text extraction |
| app/services/gmail_service.py | New owner-verified OAuth/refresh/import/dedup/lifecycle coordination over T01 |
| app/storage/gmail_store.py | New bounded private temporary state/connection/job/reservation objects |
| app/main.py | Gmail composition/lifespan, safe error status mapping, private headers/access-log privacy |
| app/core/config.py | Optional masked Gmail settings and fixed callback safety checks |
| app/core/tenant_auth.py | Append three Gmail permission values, reuse unchanged registry identity proof policy |
| app/core/ingress_limits.py | Gmail pre-body auth/policy/admission and bounded state-callback query intake |
| app/core/exceptions.py | Append21 safe Gmail codes/messages |

New test/helper files: tests/t08_helpers.py, tests/security/test_gmail_oauth.py,
tests/integration/test_gmail_import.py, tests/unit/test_gmail_mime.py,
tests/unit/test_gmail_lifecycle.py. Existing tests/integration/test_api_contracts.py
adds the seven routes and callback state scheme to its inventory; old assertions
and all447 baseline case IDs remain.

New user guide: docs/GMAIL_INTEGRATION.md. Updated configuration/docs: .env.example,
AGENTS.md, README.md, docs/README.md, docs/AGENTIC_PATTERNS.md and
docs/TENANT_ISOLATION.md. All seven current QA reports updated:
PROJECT_AUDIT_REPORT.md, TEST_EXECUTION_REPORT.md, SECURITY_REVIEW.md,
AGENTIC_PATTERN_VERIFICATION.md, API_CONTRACT_REPORT.md,
RELEASE_READINESS_REPORT.md and KNOWN_ISSUES.md. This T08 report is new.

New evidence: t08-full.xml, t08-pytest-output.txt, t08-dependency-checks.txt,
t08-compatibility.json, t08-summary.json, t08-manifest.json. Updated generated
artifacts: audit_summary.json, console-summary.txt, source_inventory.json,
benchmark_results.json, openapi.json and documentation_links.json. The newly
created history/pre-t08 directory preserves the seven T07 reports and their
prior audit_summary.json, console-summary.txt, source_inventory.json,
benchmark_results.json and openapi.json; archived Markdown local links are relocated
for navigation while original issue narrative is retained. Original-audit,
QA-005, prior single-live-Groq, T06 and T07 historical evidence remain unchanged.

## C. Endpoints

All routes below start /api/v1/integrations/gmail. Six protected operations use
X-API-Key and the existing verified registry; callback authority is one-use state.

| Method/path | Permission | Response |
| --- | --- | --- |
| POST /connect | gmail:connect | 200 authorization_url and expires_in_seconds |
| GET /oauth/callback | GmailOAuthState, no API key | 200 status CONNECTED |
| GET /status | gmail:read | 200 connected/mailbox/scope/connection_status |
| DELETE /disconnect | gmail:connect | 200 status DISCONNECTED |
| POST /import | gmail:import | 202 job_id/PENDING/fixed acceptance message |
| GET /imports/{job_id} | gmail:read + verified owner | 200 status and outcome counts/error_code |
| GET /imports/{job_id}/results | gmail:read + verified owner | 200 bounded typed results |

Import accepts only max_messages as a strict integer1–100 within server maximum;
`{}` uses configured default20. There is no query/mailbox/tenant selector.32-hex
job paths: malformed422; foreign/unknown/expired404. No token/raw-body field exists.
Gmail errors reuse ErrorResponse and X-Request-ID. Disabled/unconfigured Gmail503
without preventing ordinary application startup. [API report](API_CONTRACT_REPORT.md).

## D. OAuth

32 random state bytes,64 verifier bytes, S256 challenge, digest-indexed one-use
state with600-second TTL, one flow per owner and64 global flows. Consume before
provider await; saved immutable Principal, fixed configured redirect and confidential
client prevent query-selected identity. Callback parameter duplicates/unknowns
reject; denial consumes state. Query cap8KiB; access logs suppressed/no-referrer.

Exactly gmail.readonly, offline/consent, no incremental broadening. Code exchange
uses fixed Google token host and original PKCE verifier; zero ambiguous exchange
retries. Validate token type/scope/expiry and authenticated getProfile before
committing connection ownership. No secret/token/verifier returned. Mailbox conflicts
reject safely. PKCE web-client acceptance remains unverified with real Google.

Access/refresh tokens remain RAM-only and masked. Per-connection lock prevents
concurrent refresh. Refresh responses omitting a new refresh token preserve prior
valid refresh state; fresh grants without refresh work only until access expiry.
Revocation/unsafe scope/invalid refresh clears tokens and requires reconnect.
Hard8-hour connection TTL clears credentials regardless of access lifetime.
Expired connections retain mailbox claims until authorized disconnect/reconnect.

## E. Gmail access and extraction

Fixed Gmail v1 users/me endpoints, authenticated profile, label list, messages.list
and messages.get only. The server feedback label customer-feedback must exist;
SPAM/TRASH and broad system labels are rejected. Default newer_than:7d,
includeSpamTrash=false; maximum20 messages across five pages (hard100). No arbitrary
query or mailbox scraping. Labels define the business's selection policy, not
proof that each selected message is semantically customer feedback.

Metadata-only partial fields precede body retrieval. **Skip an entire message with
an attachment/external body/nontext leaf before requesting body data.** This
conservative limitation protects the no-attachment requirement; attachment-bearing
feedback is unsupported, rather than fetching then discarding its attachments.
No attachment endpoint, decode, send/delete or label mutation capability exists.

Bound MIME depth4/64 parts/100 headers, strict Base64url and declared/actual sizes,
UTF-8/ASCII/Latin-1/Windows-1252. Prefer nonempty plain text, otherwise inert HTML;
no scripts/rendering/URL/image loads. Multipart alternatives yield one record.
Maximum16KiB and5,000 characters, reject rather than truncate. Subject/sender/time
are transient and discarded, never passed to Groq. Body text uses existing source
email; gmail appears only as integration metadata, business_type is server configured.

## F. Tenant isolation

Existing registry validates immutable Principal proof/tenant/credential/permission
at every Gmail service boundary, store.job checks ownership, and workers bind
verified principal context for shared accounting. Three scopes: gmail:connect,
gmail:import, gmail:read. Existing explicit permission lists are unchanged; omitted
lists default to ten normal scopes. No production default authority.

Authenticated getProfile supplies case-insensitive mailbox identity, one owner per
mailbox and one connection per tenant within this process. Conflict409 reveals no
other owner's metadata. Status has no owner argument; foreign/unknown jobs/results
are indistinguishable404. Rotation keys share owner quotas/dedup. Disconnect only
clears/cancels that owner, with in-flight OAuth invalidation preventing late restore.
[Detailed policy](../TENANT_ISOLATION.md).

## G. Processing

Admission reserves capacity before202 and before creating one task per job. Default
two global/one tenant pending+running imports,20/five retained jobs,120-second job
deadline, sequential records. Effective owner caps preserve headroom. Existing
T06/T07 global/owner ingress/rate/model controls remain; Gmail shares T01 model
admission with other REST consumers. No new unbounded pending queue or worker fanout.
A periodic cleanup task expires local memory only; it never polls Gmail.

PENDING → RUNNING → COMPLETED/PARTIAL_SUCCESS/FAILED. Bad/large/attachment messages
skip; controlled nonfatal row errors continue. Fatal provider/config/rate/auth/
deadline failures stop further calls; selected unattempted rows get fixed failure
outcomes. Counts reconcile success+failed+skipped+duplicate, and represent outcomes
rather than HTTP attempts. Empty/duplicate-only imports complete.

Dedup keys tenant+verified mailbox+individual message ID; atomic reservation before
retrieval.400 global/100 owner defaults, no active eviction. Failed/skipped attempts
also deduplicate until1,800-second terminal TTL; duplicate rows return no cached
analysis and do not invoke the model. Unattempted IDs after fatal stop are not
reserved. Job/results TTL is1,800 seconds from terminal completion. No exactly-once.

Google HTTP default four operations,10-second total logical deadline, one bounded
transient retry (none for code exchange),256KiB actual response limit, no redirects
or environment proxy inheritance. Fixed safe errors; no raw provider diagnostics.
Disconnect cancels/awaits owner imports, clears owner tokens/results/dedup and
invalidates flows. It neither revokes Google's grant nor undoes already-issued
provider calls. Shutdown cancels callbacks/workers and clears all private state.

## H. Privacy

Only selected extracted body text is submitted to the configured Groq provider via
unchanged T01. Business authorization and Google user-data policy review are
required before live use. OAuth tokens, codes, verifier, sender/subject/header data
never enter model prompts/results/logs. Email instructions are untrusted data.

No permanent raw-body/header archive; temporary decoded/provider objects are
released as each record finishes. Derived summaries/evidence remain private,
can quote a whole short message, expire server-side and may persist in client copies.
Reference cleanup is not secure erasure of immutable memory. Private responses
use no-store/nosniff/no-referrer. Production proxy/query/trace policy is unverified.

## I. Verification

**571 collected;571 passed;0 failed;0 skipped;0 errors;18.286 seconds JUnit,
18.28 seconds console; exit0.**32 test modules. All447 T07 case IDs retained,
124 new cases:47 OAuth/security,35 import/integration,31 MIME,11 lifecycle. No
weakened/deleted/skipped assertions. Prior baseline-only run also passed447 cases.

FastAPI startup/imports, all12 prior OpenAPI operations exactly equal, Pydantic
and exact-evidence rejection, all graph paths, CSV/XLSX/reports, HMAC, tenant
quotas and official in-process/subprocess stdio MCP pass. Actual graph, T01
service/prompt/schema and MCP implementations hash-identical to pre-T08 snapshot.
[JUnit](t08-full.xml), [console](t08-pytest-output.txt),
[execution](TEST_EXECUTION_REPORT.md), [compatibility](t08-compatibility.json),
[summary](t08-summary.json). Network-blocking fixtures and fabricated credentials
were active. No real Google/Groq/webhook request. Existing mock benchmarks only.
Coverage/Ruff/mypy/advisory scans remain unmeasured/unrun; none installed.

## J. Dependencies

None added/upgraded. pyproject.toml/uv.lock unchanged. Existing HTTPX, Pydantic and
standard library implement OAuth/parsing. Python3.12.16, uv0.13.6, official MCP2.3.0.
`uv sync --locked --offline`:77 resolved; `uv pip check`:73 installed compatible.
[Actual command output](t08-dependency-checks.txt). Compatibility is not CVE clearance.

## K. Known limitations and external verification

RAM-only single process; one ASGI worker, restart/reload/config rotation loses
tokens/connections/mailbox claims/jobs/results/dedup. No durable/distributed ownership,
permanent sync history or exactly-once. Attachment-bearing messages are skipped.
Google credential/consent/redirect/test-user setup was not provisioned or verified.
No real authorization redirect, PKCE/code exchange, Gmail profile/list/get,
refresh/revocation, restricted-scope approval or security assessment was verified.
Mocks validate local protocol handling, not Google production acceptance.

Public gmail.readonly use may require Google verification/security assessment;
review applicable Google policy and selected-text transfer authorization. Production
requires an approved encrypted credential store/lifecycle and recovery policy,
not plaintext tokens. Files exist now; cross-session/container persistence is
unverified. Git mount remains blocked/untouched; no Git commands or deployment.

## L. Release readiness

**NOT READY.** QA-001/002/003/005 remain resolved in documented scopes. QA-007's
missing implementation is locally resolved but live Google/Cloud/approval remains
OPEN. QA-004 broader live acceptance, QA-006 Git/deployment/production OAuth
operation and QA-009 optional assurance remain. Prior single T01 live strict smoke
is verified only for its sample; zero additional inference here. No comprehensive
security, Google-policy compliance or production-readiness claim.
[Release decision](RELEASE_READINESS_REPORT.md), [known issues](KNOWN_ISSUES.md).

## M. Next milestone

T08 is complete within its mocked, temporary-storage scope. T09 can be planned
and begun only after separate authorization and agreement on its requirements;
remaining live/approval/deployment gates persist. **T09 was not started.**
