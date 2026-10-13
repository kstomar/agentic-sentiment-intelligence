# Business authentication and isolation — T07/T08

T07 provides business-level API credentials, permissions, owner-scoped temporary
resources and process-local quotas. It is not a user login system, account CRUD,
OAuth/RBAC platform, database isolation system, distributed authorization service,
or production deployment. All in-process application code and configuration
operators are trusted; this is not a Python sandbox.

## Identity and authority

Each protected REST request presents one `X-API-Key`. The bounded server registry
compares SHA256 credential digests using constant-time comparison across its full
credential set. It issues an immutable Principal containing the configured tenant,
credential ID and permissions, plus a private proof. Credentials and proof values
are never response fields. Sensitive services/stores validate the principal's
proof and claims against their authoritative registry before accessing data.

There is no tenant selector in JSON, query parameters, review IDs, source labels,
CSV cells, arbitrary headers, model outputs or business_type. Existing request
schemas still reject extra body fields. Unrecognized query/header hints do not
change authority. Tenant information is not added to sentiment/selector prompts.

The ASGI middleware authenticates REST before reading bodies, checks permissions
and quotas, and binds the verified principal task-locally. Routes pass principals
explicitly to batch and event-status services. Background workers bind the saved
verified owner explicitly. ContextVar reset/finally blocks isolate concurrent
requests and release counters on errors, deadlines and cancellation.

Stateless T01/T02/T03 classification and graph operations retain their existing
inputs/results; their REST boundaries require authentication/permission and share
tenant model/request quotas. No new model client, prompt, graph or formatter call
was introduced. No default production principal exists.

## Private configuration

Use the existing Pydantic Settings/environment/.env mechanism. Real values belong
in private configuration, never .env.example, reports, shell history or logs.
Settings store the JSON registry strings as SecretStr. Invalid configuration fails
closed with fixed messages; raw secret input is masked in ordinary and structured
Pydantic error diagnostics. Do not deliberately unwrap/serialize secrets for logging.

Example production configuration, **placeholders only**:

```dotenv
APP_ENV=production
DEVELOPMENT_AUTH_ENABLED=false
TENANT_CREDENTIALS_JSON='[{"tenant_id":"business_alpha","key_id":"alpha_v1","api_key":"<GENERATE_ALPHA_API_KEY_PRIVATELY>"},{"tenant_id":"business_beta","key_id":"beta_v1","api_key":"<GENERATE_BETA_API_KEY_PRIVATELY>"}]'
WEBHOOK_INTEGRATIONS_JSON='[{"integration_id":"alpha-shop","tenant_id":"business_alpha","shared_secret":"<GENERATE_ALPHA_WEBHOOK_SECRET_PRIVATELY>"},{"integration_id":"beta-support","tenant_id":"business_beta","shared_secret":"<GENERATE_BETA_WEBHOOK_SECRET_PRIVATELY>"}]'
```

Replace placeholders privately before starting. The bracketed placeholders are
intentionally invalid secret syntax; copying them is not a working configuration.
T07 did not create credentials or alter the real .env file.

Generate each secret independently from at least 32 cryptographically random
bytes, e.g. in a private credential provisioning workflow:

```python
import secrets
new_credential = secrets.token_urlsafe(32)
# Store privately; do not print/log it or commit it to project files.
```

New registry API/HMAC secrets must be 43–128 URL-safe ASCII characters and have
at least ten distinct characters. These checks reject short/simple strings;
they cannot prove randomness. Operators must generate secrets, not choose passwords.
Legacy development secrets keep their existing validation for compatibility.

Registry rules:

- JSON arrays only; each at most 65,536 UTF-8 bytes and 128 records. Duplicate JSON
  properties, malformed JSON, unexpected fields and nonfinite constants reject.
- Tenant/key/integration IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,99}`, case-sensitive.
- At most 32 configured businesses and eight API credentials per business.
- Credential key_id is globally unique. API secret values cannot be reused across
  entries, owners, or an enabled legacy key. Multiple distinct keys may map to
  the same business for controlled rotation.
- Integration IDs are globally unique and each references a configured business.
  Shared secrets cannot be reused across registry integrations or API credentials.
- `development` and `legacy-app-key` are reserved internal identities.
- Malformed/ambiguous security configuration prevents startup; it never activates
  legacy fallback. No configured API credentials returns controlled503 to supplied
  keys; missing credentials401. Public health remains liveness only in a valid app.

## Development compatibility

Legacy APP_API_KEY authenticates only tenant **development**, credential
legacy-app-key. Legacy WEBHOOK_INTEGRATION_ID/WEBHOOK_SHARED_SECRET also belong
only to development. Neither is a superuser or can access business registry data.

For existing nonproduction setups without TENANT_CREDENTIALS_JSON, leaving
DEVELOPMENT_AUTH_ENABLED unset preserves previous development behavior. Set it
explicitly false to disable compatibility. With a business registry present,
legacy compatibility requires explicit **true**, including in development/test.
.env.example shows that explicit development setting. **APP_ENV=production always
disables both legacy mechanisms, even if the flag is true.** Production should
set the flag false and configure business registries. A legacy key does not
become valid merely because it remains in APP_API_KEY.

When both modes are enabled in development, the development principal has the
same ownership/tenant quotas as any other owner. It cannot retrieve business
jobs/events, and business keys cannot retrieve development jobs/events. Clients
sharing the legacy key share that one development owner; there is no user-level
separation among them. Legacy-only development retains T06 global capacities.

## Small permission policy

Credentials default to all ten normal permissions (seven T07 plus three T08). An optional permissions
array may restrict them; an empty array authenticates but authorizes no operation.
Unknown/duplicate permissions reject configuration. Body fields never grant scopes.

| Permission | REST operation |
| --- | --- |
| sentiment:analyze | POST /api/v1/sentiment/analyze |
| feedback:investigate | POST /api/v1/agent/investigate |
| chat:analyze | POST /api/v1/chat, either explicit mode |
| batch:create | POST /api/v1/batch/upload |
| batch:read | GET /api/v1/batch/jobs/{job_id} and /report, /results, /download |
| feedback:ingest | POST /api/v1/ingest/feedback |
| events:read | GET /api/v1/ingest/events/{delivery_id} and /result (includes original feedback and analysis) |
| gmail:connect | POST /api/v1/integrations/gmail/connect; DELETE /disconnect |
| gmail:import | POST /api/v1/integrations/gmail/import |
| gmail:read | GET /api/v1/integrations/gmail/status, /imports/{job_id}, /imports/{job_id}/results |

Signed integration principals have only feedback:ingest. Normalization/graph
suboperations do not demand additional route scopes beyond the entry operation;
all still use the verified tenant for model accounting. No admin/superuser
permission or public credential-management endpoint is implemented.

Errors retain existing ErrorResponse and X-Request-ID: missing/invalid authority
401; missing permission403; foreign/unknown/expired resource404; tenant quota429.
Unknown integration/bad HMAC401; no integration configuration503. Error bodies
omit registry details, rejected secrets and provider diagnostics. The existing
APP_AUTH_NOT_CONFIGURED message now refers to server credentials generally.

## Batch ownership and direct Python contracts

The server records the creating principal's tenant on each job before scheduling
work. Status, report, paginated results and download all authorize in the service
and store before returning a job/derived data. Owner is a business ID, not a key
ID, feedback ID or business_type. Different keys for the same tenant share access
and quotas. Unknown and foreign IDs use the identical controlled404 error.

Public job/event lookup and inspection maps require authority; maps are filtered
by owner and read-only. Global store cleanup/terminal transitions are private
maintenance operations. No unrestricted public all-job/event lookup is available.
Caller-owned stores cannot be rebound around existing jobs to a registry that
fails to validate their saved ownership proofs.

Direct callers must authenticate with the authoritative registry and either pass
principal explicitly or bind it in principal_context. Omitting both fails401;
passing a bare tenant string or forged principal does not authenticate. Example
using an existing privately obtained credential (never a body field):

```python
principal = registry.authenticate(private_api_key)
status = batch_service.status(job_id, principal=principal)
# Equivalent for a trusted internal call chain:
with principal_context(principal):
    report = batch_service.report(job_id)
```

Applications inject the same authoritative registry into stores/services.
Standalone empty JobStore instances bind to the first verified caller's registry;
they hold no resources before that binding. Do not create independent registries
from untrusted configuration or treat Python code as an untrusted tenant sandbox.

Job parsing reservations, processing, result validation, raw-text cleanup, terminal
TTL and shutdown erasure remain. Expiration removes owner-sensitive derived data
and frees retained capacity. The shared provider-wide fatal-error latch still
stops unsafe additional batch calls for every tenant when provider configuration
or authentication fails; it does not expose another tenant's results.

## Webhook ownership, status and idempotency

HMAC continues to cover `integration.timestamp.delivery.` plus exact original
bytes. There is no tenant ID in the signature format or payload. The verifier
selects the configured integration's secret and tenant, checks HMAC/time and
issues its immutable ingestion principal. A signature for Alpha cannot authorize
Beta by changing the integration ID. Public worker admission revalidates the typed
signed delivery, including original bytes, so a modified context cannot transplant
previously verified authority. See [signing guide](WEBHOOK_INTEGRATION.md).

Two identities are deliberately distinct:

- Public status/storage key: **tenant ID + delivery ID**. This preserves the
  existing GET route without adding a caller-selected integration/tenant field.
- Idempotency identity: **verified tenant + integration + delivery + exact-body
  digest**. Timestamp is excluded from the digest, allowing fresh signed retries.

Delivery IDs must be unique across a tenant's integrations during retention.
Same integration/ID/bytes returns 200 DUPLICATE; changed bytes409. Another integration
of the same tenant attempting that ID returns 409 WEBHOOK_DELIVERY_COLLISION,
including identical bytes. It cannot claim or overwrite the first event.
Different tenants may reuse IDs safely and retrieve only their own status.
Invalid signatures are rejected before all duplicate checks. Reservation remains
atomic on one event loop, bounded and expiring. Active events never evict.

Event status exposes only delivery_id, state and controlled error_code. Foreign,
unknown and expired events return the same 404. This was the T07 memory-only policy.
The current PostgreSQL ingestion implementation retains original feedback and
validated analysis in owner-scoped feedback_events; the separate result endpoint
requires events:read. Default terminal retention is indefinite, bounded by quotas;
optional expiry removes retained records. Fixed workers, deadlines and cancellation
remain bounded. Persistence is not an exactly-once guarantee.

## Global, tenant and provider limits

T06 actual-byte caps remain: JSON 4 MiB (approved intentional413 policy), webhook 16 KiB,
file 2 MiB plus 64 KiB multipart envelope. Raw webhook bytes are preserved. Global
protected intake 16, admitted requests 120/minute, body-read15s, batch jobs 3/retained 20,
batch model permits 2, shared REST model operations 4, webhook workers 2/pending20/
retained 100 all remain. Provider deadlines/retries and graph bounds are unchanged.

Business registry mode additionally uses these settings:

| Setting | Default |
| --- | --- |
| TENANT_MAX_CONCURRENT_REQUESTS | 4 active protected requests |
| TENANT_REQUESTS_PER_MINUTE | 60 admissions per rolling minute |
| TENANT_MAX_CONCURRENT_INVESTIGATIONS | 1 whole graph, including chat investigation mode |
| TENANT_MAX_CONCURRENT_MODELS | 2 shared classifier/selector operations, retries included |
| TENANT_MAX_ACTIVE_BATCH_JOBS | 1 active job or retained parsing reservation |
| TENANT_MAX_RETAINED_BATCH_JOBS | 5 active/terminal jobs plus parse reservations |
| TENANT_MAX_PENDING_EVENTS | 5 queued webhook events |
| TENANT_MAX_CONCURRENT_WEBHOOK_ANALYSES | 1 active webhook worker |
| TENANT_MAX_RETAINED_EVENTS | 20 active/terminal delivery reservations |

Effective tenant caps are clipped below the corresponding global capacity, leaving
headroom for another business. Active batch jobs are also capped below global
batch model permits, preventing one owner from holding every batch permit. Business
mode requires relevant global budgets of at least two; unsafe headroom settings
fail configuration. Legacy-only development uses existing global capacities.

All admission is immediate; there are no unlimited queues. A tenant's pending
webhooks cannot occupy every fixed worker: workers scan the bounded queue past
owners already at worker capacity. Other eligible tenants can run. Counters are
keyed only by verified tenant, shared across rotating credentials, removed when
idle or bounded by the registry. Rolling rate windows expire lazily at admission;
retained capacity expires with its store. Cancellation and deadlines release
active counters; an abandoned parse retains its owner's reservation until its
thread actually finishes and raw data is wiped.

Signed headers alone do not establish tenant authority. Before full HMAC, webhook
body reads use global caps/deadlines only; invalid HMAC cannot charge tenant/model/
queue quotas. Valid REST credentials authenticate before body reads. These app
controls are not transport-level DoS protection, fair internet connection scheduling
or a distributed rate limiter. Authorized callers can still contend for shared
global/provider budgets; there is no guaranteed simultaneous capacity for every
configured tenant. Provider-imposed429 differs from local tenant/global429 codes.
MCP is a separate process and retains its own two-call global cap.

## Rotation, revocation and restart

API-key rotation: generate a new secret privately; append a new key_id for the
same tenant; restart with validated configuration; migrate clients; remove the
old row and restart. No public rotation API exists. Overlap keys share tenant
ownership/quotas; the revoked key no longer authenticates in the new registry.
Permission changes also require a restart. Do not change tenant IDs to rotate keys.

For HMAC, coordinate a secret cutover with the sender or configure a new integration
ID mapped to the same tenant during transition. Duplicate integration IDs/secret
reuse are rejected. Delivery collisions across same-tenant integrations still409.

**Current persistence:** PostgreSQL batches/events/results/idempotency and Gmail
processed-message metadata survive application restart. Gmail OAuth/jobs/results
remain process-local. Rotation tests establish ownership within an overlap registry;
separate PostgreSQL restart tests establish durable retention. Authenticated retained
delivery identities prevent identical signed retries from repeating inference after
restart. Unfinished ingestion is marked interrupted without automatic replay;
unfinished batch work has bounded recovery. This supersedes T07's memory-only
limitations. There is no distributed-worker or exactly-once guarantee.

## Verification and remaining scope

Use README's local Python3.12/uv exports, then run the full offline suite with
provider keys blank; fixtures use fabricated business/API/HMAC credentials and
block sockets/real HTTP transports. Cross-business cases cover all batch reads,
service/store access, status, signatures, same-ID collisions, rotation, permissions,
quotas and lifecycle cleanup. Existing REST, graph, reports and official MCP
in-process/stdio checks are retained. See [current execution](qa/TEST_EXECUTION_REPORT.md).

Local MCP remains trusted-launcher stateless analysis only, with no tenant_id or
key arguments, owned lookups, credential registry tools or remote transport.
A future tenant MCP deployment must receive verified identity from a trusted host/
launcher binding outside model/tool arguments and pass it into policy/accounting.
That deployment is not implemented. See [MCP boundary](MCP_INTEGRATION.md).

T07 makes no live Groq calls and changes no provider prompt/strict-output contract
or dependencies. Prior one-case T01 live verification remains limited evidence.
T08 now adds the Gmail ownership boundary below. No user accounts, persistent
database, frontend, deployment or distributed identity/quota service exists. Production TLS/proxy/connection/
resource policy, Git/release handoff and wider acceptance remain unverified.

Design references: [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
[Python context-local state](https://docs.python.org/3.12/library/contextvars.html),
[Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
Local automated evidence establishes the scoped implementation; it is not an
exhaustive security or infrastructure certification.


## T08 Gmail ownership extension

Explicit existing permission lists remain unchanged: add gmail:connect/import/read
only for businesses authorized to access selected Gmail feedback. Credentials with
omitted permissions default to all ten normal scopes; an empty list still grants
none. Gmail scopes are application permissions, distinct from Google's readonly grant.

The callback has no X-API-Key requirement. Its atomically consumed, expiring state
captures the verified initiating Principal; query parameters cannot substitute an
owner. Grant validation plus authenticated getProfile establishes mailbox identity.
One tenant holds one connection and one mailbox has one process-local owner;
conflicts cannot overwrite or disclose another owner. Expired connections clear
tokens while reserving the mailbox until owner disconnect/reconnect. There is no
remote registry/connection inspection or user-selected mailbox lookup.

Service methods validate principal proofs and permissions before work, store.job
checks owner before return, and workers bind verified principal_context explicitly.
Foreign and unknown import IDs both return404 GMAIL_JOB_NOT_FOUND. Rotation keys
share owner quotas and deduplication. Dedup keys include owner+verified mailbox+
message ID. Per-owner pending/running/retained/dedup limits leave global headroom;
Gmail uses the same existing global and tenant model admission as other REST work.
Defaults are two global/one owner imports and 20/five retained jobs. The later
PostgreSQL ledger defaults to 10,000 global/1,000 owner message identities.

Disconnect cancels only owner work, invalidates pending/in-flight state and removes
owner tokens and process-local results. Durable successful-message identities remain;
failed identities keep the configured retry policy. It cannot revoke or undo Google operations
already issued. Other businesses remain untouched. In-memory connections/mailbox
claims disappear on restart, so this is not durable cross-process ownership.
See [Gmail lifecycle, privacy and Google acceptance gates](GMAIL_INTEGRATION.md).
T08 uses mocks only and adds no persistent credential storage or remote MCP tool.


## T09 durable batch ownership

PostgreSQL stores tenant ownership, not API-key identifiers or proofs. All public
batch reads query tenant+public job ID in SQL before loading child rows. Recovery
requires current verified batch:create authority; read-only/removed owners remain
paused without inference, while current batch:read credentials can inspect their
permitted resources. Rotation keys for the same tenant share durable history and
quotas. Foreign/unknown404 and permission403 remain unchanged.

A create-only credential can process a job but cannot read status/report/results/
download or the public store lookup. Worker-only outcome projections are private.
Default completed retention is indefinite; explicit TTL deletion cascades records.
Existing quotas remain and can fill, returning429 without evicting history. Incomplete
authority-paused jobs still consume capacity. PostgreSQL's idle advisory-lock session
allows one app coordinator; no distributed identity/rate/Gmail/event persistence
is added. See [batch persistence](BATCH_PERSISTENCE.md) and
[executed real-PostgreSQL tests](qa/T09_IMPLEMENTATION_REPORT.md).


## Durable ingestion ownership

Persistent ingestion stores tenant+delivery under a unique constraint. Both status
and result retrieval require events:read and SQL owner filtering before returning
feedback/results. This permission now includes the sensitive original text and
analysis through the new result route; ingest-only keys cannot read them. Signed
integration principals still have only feedback:ingest and cannot authenticate
business GET requests. The separate legacy development owner cannot read business
records. Same-tenant credential rotation preserves access after restart.

Idempotency persists integration ID plus exact-byte digest, never its secret or
signature. A different integration colliding within the same tenant gets409;
another tenant can independently use the same delivery ID. Only the verified
server registry determines ownership. Completed events/digests survive rotation
and restart; unfinished events become FAILED/INGESTION_INTERRUPTED without replay.
Private credentials/Gmail connections remain outside database scope. See
[persistent ingestion contract](WEBHOOK_INTEGRATION.md).
