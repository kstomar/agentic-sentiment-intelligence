# Security review

Audit scope: source inspection and bounded offline tests on 30 October 2026.
No production changes, real customer data, live inference, external webhooks,
Gmail connections, deployment, or destructive stress testing occurred.

## Assessment

**Not ready for public multi-business operation.** No CRITICAL issue was
demonstrated. Two HIGH security findings remain: tenant ownership is absent
(QA-001), and ingress/rate/admission controls are incomplete (QA-003). These are
separate from the missing T06 feature and blocked live-provider verification.
See [known issues](KNOWN_ISSUES.md) for reproduction and remediation details.

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
