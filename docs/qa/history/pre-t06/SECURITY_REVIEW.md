# Security review

Original audit: source inspection and bounded offline tests on 30 October 2026,
without production changes. This report now includes the authorized QA-005
remediation: one upload-route validation change and 220 passing mocked tests.
No real customer data, live inference, external webhooks, Gmail connections,
deployment, or destructive stress testing occurred in this remediation.

## Assessment

**Not ready for public multi-business operation.** No CRITICAL issue was
demonstrated. Two HIGH security findings remain: tenant ownership is absent
(QA-001), and ingress/rate/admission controls are incomplete (QA-003). These are
separate from the missing T06 feature and blocked live-provider verification.
See [known issues](../../KNOWN_ISSUES.md) for reproduction and remediation details.

QA-005 is RESOLVED; its original test is unchanged and now passes. That metadata
correction does not address either HIGH issue. Historical audit reports remain
in [history](../original-audit/SECURITY_REVIEW.md).

## HIGH finding endpoint/file mapping and minimal corrective designs

### QA-001 — Tenant ownership (OPEN; multi-business milestone)

The direct cross-caller disclosure affects these four object lookup operations:

- `GET /api/v1/batch/jobs/{job_id}`
- `GET /api/v1/batch/jobs/{job_id}/report`
- `GET /api/v1/batch/jobs/{job_id}/results`
- `GET /api/v1/batch/jobs/{job_id}/download`

`POST /api/v1/batch/upload` is the affected creation boundary: jobs currently
receive no trusted owner. The three other protected POST operations (sentiment,
investigation, chat) likewise lack caller identity/accounting, although they do
not look up another caller's retained jobs. `/health` contains no tenant data.
MCP batch retrieval is deliberately absent; trusted local MCP launching is not
tenant authentication and must not be treated as a remote multi-business boundary.

| Affected file | Current implementation / missing control |
| --- | --- |
| `app/core/security.py::require_api_key` | Constant-time shared-key verification; no principal/tenant context returned |
| `app/api/v1/batch.py` | Authenticated creation and reads; no principal passed to services |
| `app/services/batch_service.py::submit/status/report/results/download` | Job access by opaque ID, without ownership arguments/checks |
| `app/storage/job_store.py::Job` and `JobStore.add/get` | No owner field or scoped retrieval |
| Other REST adapters and `app/main.py` | Trusted caller context would need consistent propagation, not business_type inference |

Implemented controls are a development key, unpredictable job IDs, bounded
retention, and sanitized errors. Missing object authorization permits a second
caller with the shared key and a known ID to read sensitive results. The existing
characterization test still reproduces that behavior after QA-005 remediation.

Proposed minimal design: derive an immutable principal/tenant identifier from
server-validated credentials; attach it at job creation; require the trusted
context in every store/service lookup and result/download path. Scope lookup by
both owner and ID, and use a consistent non-disclosing not-found response for
foreign/unknown jobs. Test cross-owner reads and creation-context propagation.
Do not rely on an untrusted payload tenant label or business_type. This is
multi-business milestone work. T06 should consume the same identity/ownership
contract for future integration events rather than invent a separate identity.
If T06 precedes that milestone, it must explicitly remain single-operator and
must not claim tenant isolation.

This follows object-level authorization guidance; opaque identifiers alone do
not establish permission. [OWASP API1:2023](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/)

### QA-003 — Ingress/resource controls (OPEN; T06 foundation plus multi-business quotas)

Primary body/cost-bearing endpoints:

- `POST /api/v1/sentiment/analyze`
- `POST /api/v1/agent/investigate`
- `POST /api/v1/chat`
- `POST /api/v1/batch/upload`

The four batch GET operations above should also receive request-rate limits,
especially report/result/download serialization; their record and page bounds
do not impose a request rate. No webhook/ingestion endpoints exist yet. Local MCP
already has an independent two-active-call default; it is not a global REST or
cross-process model quota. Public health can retain a lightweight separate policy.

| Affected file | Implemented control / remaining gap |
| --- | --- |
| `app/core/upload_limits.py` | Streams/counts upload envelope bytes, but only for batch upload; buffers accepted bodies before route auth/admission |
| `app/main.py` | Composes upload guard and per-request boundary; no JSON byte/rate/admission policy |
| `app/api/v1/sentiment.py`, `investigation.py`, `chat.py` | Pydantic field bounds after parsing; no aggregate body-byte or concurrent intake limit |
| `app/api/v1/batch.py` | File/mapping validation; upload multipart parsing precedes analysis reservation |
| `app/services/batch_service.py` | Bounded parse/job reservations and batch permits begin after body intake; do not cover every incoming request |
| `app/services/sentiment_service.py`, `app/agents/action_selector.py` | Bounded per-call retries/timeouts; no shared all-interface provider admission quota |
| `app/core/config.py` and deployment configuration | New ingress/quotas require explicit settings/policy and tested deployment enforcement |

The suite still reproduces acceptance of a valid T01 JSON request padded with
more than 2 MiB of whitespace. No memory-exhaustion attempt was made. Concurrent
intake and model-cost exposure remain a code/deployment control gap; no global
REST concurrency claim is inferred from the batch semaphore.

Proposed minimal corrective design, **not implemented here**:

1. Establish documented per-endpoint body-byte limits, checked against declared
   and actually streamed bytes before JSON/multipart parsing. Choose limits that
   accommodate all existing valid bounded payloads, including Unicode escapes,
   rather than confusing character limits with encoded byte limits.
2. Bound active body reads/parses and reject excess intake immediately rather
   than building an unbounded waiting queue. Apply body/connection timeouts at a
   tested ingress boundary. Verify proxy limits if used; do not assume they exist.
3. Reuse trusted authentication as early as practical before expensive buffering.
   Future signed webhook intake must still read only bounded bytes and verify
   signatures/metadata before accepting work.
4. Add shared bounded model admission and request-rate/spend controls across
   direct analysis, investigation/selector calls, batch workers, and future T06
   workers. Avoid holding a request-level permit across nested calls to the same
   limiter. Define busy/retry semantics and test cancellation/timeout release.
5. Add per-principal quotas when multi-business identity exists. Shared-process
   limits and per-tenant quotas complement each other; neither replaces the other.

Place the common ingress/admission foundation in the next authorized T06
security work before exposing new ingestion endpoints, then integrate tenant
accounting in the multi-business milestone. Introducing byte/rate policies and
new 413/429/503 behavior for currently accepted requests needs explicit policy/
contract review. It is not necessary for QA-005, so no extra production patch
was applied. Minimum future tests include chunked/declared JSON limits, accepted
boundary payloads, aggregate intake pressure, all-interface admission, and cleanup.

These proposed controls address resource and cost exposure, consistent with
[OWASP API4:2023](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/).

## Authentication and authorization

- Eight protected HTTP operations reject absent/incorrect keys with 401.
  `/health` is public. `test_authentication.py` exercises every protected route.
- `require_api_key` compares UTF-8 byte strings with `secrets.compare_digest`.
  Configured key material is held in Pydantic `SecretStr`; no key value is a
  response field. An unconfigured expected key with a supplied key returns 503.
- `MULTI_TENANT_ISOLATION = NOT_IMPLEMENTED`. No principal, tenant, or ownership
  is derived from the key. A second client holding the same key can retrieve a
  known batch job and its sensitive derived evidence: reproduced in
  `test_characterize_shared_key_job_access_without_tenant_ownership`.
- API docs are enabled outside production by default; `Settings.docs_enabled`
  disables them by default in production. The health endpoint exposes liveness
  only. Actual route traversal found no undocumented debug or MCP HTTP endpoint.

## Input and resource protection

Verified tests cover field lengths, enums, extra fields, malformed JSON,
duplicate IDs, job-ID format, pagination, UTF-8 errors, strict CSV quoting,
filename/path manipulation, archive corruption, expansion ratio, macros/DTD,
and Excel formulas. Formula text is never evaluated; mapped text formulas fail,
ID formulas reject uploads, and formula dates are invalid metadata.

The batch middleware enforces declared and streamed multipart bytes before
parsing, with an envelope allowance. File/record/text/extraction limits then
apply independently. Tests show three active jobs, two shared batch model
permits, bounded retained jobs, and cancellation-safe parser reservations.

Limits are not uniform across interfaces. JSON field lengths do not bound
whole request bytes before JSON parsing: a valid request with more than 2 MiB
of whitespace was accepted by T01 with mocked inference. Direct REST calls have
no shared admission/rate limiter. Batch multipart intake precedes job admission
and normal route authentication; concurrent incoming bodies can consume more
aggregate resources than the three-job processing cap. No reverse-proxy limits
were verified. These observations support QA-003; no real DoS was attempted.

## MCP boundary

Official SDK clients verified both tools in-process and over stdio. Discovery
contains exactly `analyze_feedback` and `investigate_feedback`, with no resources
or prompts. Invalid names including shell execution and batch lookup return
controlled tool errors without provider calls. No remote listener is started.

MCP validates full existing request models before SDK coercion, preserves known
service error codes, suppresses unsafe SDK/provider diagnostics, and limits
active calls. Tests cover cancellation releasing capacity, busy rejection,
missing configuration, unexpected errors, clean shutdown, valid protocol-only
stdout, and stderr without fabricated private sentinels at DEBUG configuration.

Local authorization is the trusted process launcher and its environment, not a
REST key argument or `business_type`. Tools send supplied text to Groq in normal
configured operation. Registration restriction is not a policy engine, OS
sandbox, tenant identity system, or network firewall. Other client hosts were
not tested and may retain arguments, responses, and full evidence independently.

## Prompt injection and agent control flow

`test_prompt_injection.py` proves review text never enters action selection and
cannot add graph capabilities: only question/business hint reach the selector,
only allowlisted actions pass validation, and there is no tool-output feedback
edge into selection. Unknown action output fails before record analysis.
The sentiment prompt keeps trusted instructions separate from serialized review
data, and the model has no shell/filesystem execution tools.

This is dataflow/capability evidence, not a demonstration of semantic immunity
from adversarial inputs. Mocked classifications cannot establish that a live
model will resist every attack, avoid harmful summaries, or classify accurately.
Do not treat prompt wording or exact-quote checks as a full security guarantee.

## Secrets, logging, and privacy

Production source was inspected without printing process secrets or reading
credential files. `.env.example` contains empty key placeholders; `.gitignore`
excludes `.env`, local credentials/databases, tools, uploads, and temporary data.
No real `.env` or persistent feedback storage path was created by this audit.
Fake keys/sentinels in tests are labeled fabricated and never usable credentials.

Tests verify rejected values, provider failures, and unexpected exceptions do
not enter HTTP/MCP errors or captured application logs. Debug logging for provider
libraries is suppressed, and LangSmith tracing is disabled within analysis/graph
execution. This is not an exhaustive host-wide logging or instrumentation audit.

Raw mapped batch text is cleared after settlement; terminal records are removed.
Lazy and periodic expiry remove derived results; shutdown clears the store.
Parser cancellation retains its slot until thread completion, then clears data.
The framework may temporarily spool uploads over 1 MiB; an explicit failure-path
test confirms uploaded resources close. No permanent server-side exports exist.

Successful summaries and evidence may contain private customer content. T02 may
return full supplied review text. Batch endpoints use no-store/nosniff headers;
client copies and host retention are outside server control. Dropping Python
references is not cryptographic erasure, and process restarts lose memory jobs.

## Webhook security and unperformed assurance

`WEBHOOK_SECURITY = NOT_APPLICABLE`: T06 is NOT_IMPLEMENTED. No HMAC, timestamp,
replay/idempotency, or delivery-worker claims can be verified. No synthetic
passing tests were added for absent components.

Coverage, Ruff, mypy, and dependency advisory scanning were not performed because
the corresponding tools were absent/not configured and not authorized for
installation. Compatibility checks are not CVE clearance. TLS, ingress controls,
host/container configuration, production rate limits, and external client
privacy settings remain deployment verification gaps.
