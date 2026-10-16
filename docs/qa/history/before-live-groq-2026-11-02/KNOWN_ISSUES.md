# Known issues and delivery gaps

Audit date: 30 October 2026; updated after targeted QA-005 remediation. The
original audit did not change production code and recorded 209 passed / 1 failed.
QA-005 is now RESOLVED by a minimal upload-route correction: the unchanged
original test and the full expanded suite pass (220/220). Other issues remain open.
Original evidence is preserved in [history](../../history/original-audit/KNOWN_ISSUES.md).
Severity reflects the requested delivery scope, not only T01–T05 development.

| ID | Severity | Kind | Finding | Release impact |
| --- | --- | --- | --- | --- |
| QA-001 | HIGH | Security / missing capability | No principal or tenant-scoped batch ownership | Blocks multi-business delivery |
| QA-002 | HIGH | Missing required functionality | T06 external ingestion and signed webhooks absent | Blocks requested complete scope |
| QA-003 | HIGH | Security / capacity | No JSON byte limit or global REST admission/rate control | Blocks public exposure without compensating controls |
| QA-004 | HIGH | Verification gap | Live Groq integration and model behavior unverified | Blocks claiming working live AI integration |
| QA-005 | MEDIUM | Resolved defect | Explicit blank upload source now rejected with 422 | RESOLVED; original assertion unchanged, 220 tests pass |
| QA-006 | MEDIUM | Release engineering | Git unavailable; production deployment/recovery unverified | Blocks reproducible release handoff until resolved |
| QA-007 | MEDIUM | Scope gap | Planned Gmail integration absent | Delivery impact depends on explicit scope decision |
| QA-008 | LOW | Documentation | Historical test/scope language and planned architecture entries need reconciliation | Onboarding confusion |
| QA-009 | LOW | Verification/tooling gap | Coverage, lint/type checks, and vulnerability database scan absent | Additional assurance unavailable |

There are **0 CRITICAL** findings. There are **2 HIGH security findings**
(QA-001 and QA-003); QA-002 and QA-004 are additional HIGH delivery blockers.
No claim is made that an exhaustive penetration test or CVE assessment occurred.

## QA-001 — No tenant isolation or job ownership

- **Severity:** HIGH.
- **Affected files:** `app/core/security.py::require_api_key`,
  `app/storage/job_store.py::JobStore`, `app/api/v1/batch.py`, and all batch lookup
  methods in `app/services/batch_service.py`.
- **Reproduction:** Run
  `uv run --locked --offline pytest -q tests/security/test_data_privacy.py::test_characterize_shared_key_job_access_without_tenant_ownership`.
  Client A uploads fabricated feedback. A separate client with the same shared
  development key retrieves the job's results using its ID.
- **Expected for multi-business delivery:** Authenticated principal identity and
  ownership checks prevent another business accessing the job, even with a known ID.
- **Actual:** HTTP 200; the other client's response includes source evidence.
  No tenant/principal/owner field is derived from authentication. Opaque UUIDs
  reduce guessing but do not enforce ownership.
- **Cause:** Intentional single-development-key architecture; metadata hint
  `business_type` is not an identity. This is a planned missing capability rather
  than an authentication bypass against the documented development key policy.
- **Suggested resolution:** Introduce principal-scoped authentication and enforce
  tenant ownership in every store/service lookup before multi-business use. Keep
  MCP batch access deferred until those checks exist. Do not merely add a
  caller-supplied business identifier.
- **Delivery impact:** Blocks multi-business acceptance. Local single-operator
  demonstrations remain possible with the documented limitation.

## QA-002 — Required T06 ingestion and signed webhooks are absent

- **Severity:** HIGH.
- **Affected areas:** `app/integrations/__init__.py` is only a package stub;
  `app/main.py` registers no ingestion/webhook router. `docs/WEBHOOK_INTEGRATION.md`
  does not exist.
- **Reproduction:** Inspect `openapi.json`, `source_inventory.json`, and
  `tests/integration/test_api_contracts.py`. Neither
  `/api/v1/ingest/feedback` nor `/api/v1/webhooks/feedback` exists.
- **Expected:** Authenticated ingestion and signed webhook processing under the
  requested delivery requirements, with bounded workers and replay/idempotency checks.
- **Actual:** No implementation of HMAC verification, timestamp tolerance,
  delivery IDs, replay/conflict detection, event status, or webhook workers.
- **Cause:** Development stopped at T05 as previously instructed.
- **Suggested resolution:** Schedule a separately authorized T06 implementation,
  then add actual signature/replay/concurrency tests. No fake passing webhook
  tests were created in this audit.
- **Delivery impact:** Blocks complete requested scope; webhook workflow I is
  NOT_APPLICABLE to this source revision.

## QA-003 — REST resource controls are incomplete

- **Severity:** HIGH for a public or shared deployment.
- **Affected files:** `app/main.py`, `app/core/upload_limits.py`, and direct
  sentiment/investigation/chat routes.
- **Reproduction:** Run
  `uv run --locked --offline pytest -q tests/security/test_input_validation.py::test_characterize_missing_json_body_byte_limit`.
  A valid small JSON request padded with just over 2 MiB of whitespace still
  returns HTTP 200 and invokes the mocked provider. The bounded experiment is
  evidence of missing byte enforcement, not a destructive stress test.
- **Expected before public deployment:** Enforce a documented whole-body byte
  limit before JSON parsing, plus authenticated rate/admission controls and
  request/connection timeouts at the application or deployment boundary.
- **Actual:** The size middleware covers only batch upload. Field lengths are
  bounded after parsing but JSON bytes are not. Direct T01/T02/T03 operations
  have per-request budgets but no shared model permit/rate limiter. Batch upload
  buffers/parses multipart before its analysis reservation and normal route auth;
  its per-request byte limit does not bound aggregate concurrent intake memory.
- **Cause:** Development limits apply selectively to batch/MCP, not all ingress.
- **Suggested resolution:** Establish ingress limits and per-principal quotas,
  bound concurrent intake/model calls, and verify them under a bounded local
  concurrency check. Gateway controls may compensate only if configured and tested.
- **Delivery impact:** Public-service resource/cost exposure remains unresolved.
  No memory exhaustion, denial of service, or real provider spending was attempted.

## QA-004 — LIVE_GROQ_VERIFICATION = BLOCKED

- **Severity:** HIGH as a release verification gap.
- **Affected files:** `app/services/sentiment_service.py`,
  `app/agents/action_selector.py`, and release acceptance evidence.
- **Reproduction:** Review the offline guard, mock HTTP adapter test, and
  `TEST_EXECUTION_REPORT.md`. No authorized live request is present.
- **Expected:** A separately authorized request demonstrates account/model access,
  real strict-output acceptance, and useful representative classifications.
- **Actual:** Local adapter construction, strict schema forwarding, retry/error
  policy, and Pydantic verification pass with mocks. Real provider acceptance,
  account permissions/quotas, latency, and sentiment accuracy remain unverified.
- **Cause/history:** The original audit did not authorize live/paid requests.
  A subsequent separately authorized single-call check found GROQ_API_KEY not
  configured; zero provider requests were made. Verification remains BLOCKED.
- **Suggested resolution:** Obtain explicit live-call approval and configure
  credentials privately; run a small documented smoke/acceptance set. Do not
  interpret a mocked positive/negative fixture as model-quality evidence.
- **Delivery impact:** Cannot claim fully verified live Groq integration.

## QA-005 — Blank multipart source silently becomes its default (RESOLVED)

- **Severity:** MEDIUM.
- **Original failing test, retained unchanged:**
  `tests/integration/test_batch_api.py::test_explicit_blank_source_is_rejected`.
- **Affected files:** `app/api/v1/batch.py::upload`,
  `app/schemas/batch.py::UploadOptions`, README upload contract.
- **Reproduction:** Multipart POST with fabricated `review\na` CSV,
  `text_column=review`, and an explicitly supplied `source=` empty form field.
- **Expected:** HTTP 422, because supplied source labels must be nonblank.
- **Original actual result:** HTTP 202; the audit preserved the failed assertion
  (`202 != 422`). The original 210/209/1 evidence remains in the audit history.
- **Confirmed root cause:** FastAPI's `_get_multidict_value` maps an empty FormData
  string to Undefined; `_validate_value_with_model_field` substitutes the optional
  default before `UploadOptions.nonblank` runs. Pydantic was not accepting blanks.
- **Production correction:** Only `app/api/v1/batch.py` changed. The existing raw
  blank-ID/date guard now includes source. Explicit empty/whitespace source returns
  the existing controlled 422 response before a job or provider call; omitted
  source still defaults to file_upload. Existing schema/allowlist rules are intact.
- **Source-contract clarification:** Batch metadata accepts any nonblank label
  up to 64 characters; T01's allowlisted source is a separate unchanged contract.
  Overlong and non-text multipart source values remain rejected. No new batch
  allowlist or business-type behavior was introduced.
- **Test evidence:** Original focused test unchanged: 1 passed (0.09 s console).
  Full suite: 220 passed in 9.39 s; all original 210 cases plus ten new source
  regressions. OpenAPI matches the pre-fix snapshot exactly; dependencies unchanged.
- **Final status:** RESOLVED. See [remediation report](../../QA005_REMEDIATION_REPORT.md).
  QA-001, QA-003, and the other unresolved delivery gaps still block release.

## QA-006 — Repository and production operation are not release-verified

- **Severity:** MEDIUM.
- **Affected areas:** Read-only `.git`, release packaging/CI, deployment and
  process-restart operation. Existing README describes a local reload server.
- **Reproduction:** Read-only filesystem inspection found `.git` empty and its
  mount marked read-only; no Git command or write was attempted. Source inventory
  has no Dockerfile, CI workflow, or demonstrated production deployment artifacts.
- **Expected:** A reproducible versioned handoff, deployment configuration,
  documented resource/auth/TLS controls, and explicit recovery expectations.
- **Actual:** Locked dependencies reproduce locally, but commits/versioned
  release status and production deployment/recovery cannot be verified. Batch
  jobs/results are intentionally lost on restart and inconsistent across workers.
- **Suggested resolution:** Have the environment owner restore normal repository
  access without bypassing the mount; define and verify a production deployment
  plan. Until architecture changes, enforce one worker and document job loss.
- **Delivery impact:** Release handoff and production readiness remain blocked;
  Docker itself is not asserted to be mandatory.

## QA-007 — Planned Gmail integration is not delivered

- **Severity:** MEDIUM; scope-dependent delivery gap.
- **Affected areas:** `app/integrations/`, README planned integration scope.
- **Reproduction:** Source/module and OpenAPI inventories contain no Gmail adapter,
  OAuth/token lifecycle, ingestion workflow, or corresponding documentation.
- **Expected:** Explicit agreement whether Gmail belongs in the 6 November delivery.
- **Actual:** NOT_IMPLEMENTED. Earlier milestones defer it; the audit request
  lists it as planned rather than providing a completed acceptance contract.
- **Suggested resolution:** Confirm inclusion or explicit deferral. If required,
  authorize a separate implementation and mocked verification task. No Gmail
  connection, credentials, or external messaging was attempted.
- **Delivery impact:** Cannot claim Gmail support. If it remains in agreed scope,
  it is an additional release blocker.

## QA-008 — Documentation needs an audit-era update

- **Severity:** LOW.
- **Affected files:** `README.md`, `AGENTS.md`, `docs/README.md`,
  `docs/AGENTIC_PATTERNS.md`.
- **Reproduction:** Historical instructions still describe permanent tests as
  outside scope; architecture's mixed planned/implemented table mentions webhook,
  tenant, and Gmail responsibilities. A T02 paragraph says no MCP is implemented,
  while the later T05 section correctly documents MCP.
- **Expected:** Clear historical labels, current test commands, and explicit
  implemented/planned boundaries.
- **Actual:** Current capabilities are mostly described accurately, with local
  MCP launch/privacy instructions and batch limitations present. No broken local
  Markdown targets were found, but stale scope language can confuse onboarding.
- **Suggested resolution:** Link this QA bundle and reconcile historical wording
  in a reviewed documentation update. The latest audit request explicitly
  authorizes the new tests despite older instructions.
- **Delivery impact:** Low; these existing documents were not silently rewritten.

## QA-009 — Optional quality and vulnerability assurance is incomplete

- **Severity:** LOW; verification limitation, not proof of an insecure dependency.
- **Affected areas:** Development tooling and release assurance.
- **Reproduction:** `environment.json`/`audit_summary.json` show coverage, Ruff,
  and mypy absent; no mypy configuration exists. No dependency advisory scanner
  was installed or run.
- **Expected:** Record unperformed checks and decide which assurance gates are
  necessary before release.
- **Actual:** Coverage percentage is not measured. Ruff/mypy/CVE clearance are
  not verified. `uv pip check` verifies dependency compatibility, not known CVEs.
- **Suggested resolution:** Separately approve any desired tooling, then measure
  coverage and run the selected checks. No unapproved package was added.
- **Delivery impact:** Does not invalidate executed functional tests; limits
  claims about completeness, static correctness, and dependency security.
