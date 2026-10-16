> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Requirement gaps and limitations — PROVISIONAL

**No missing or nonfunctional feature was demonstrated among the six identified
provisional core requirements.** All19 REST operations, both MCP tools and workflows
A–I have executable local evidence.571 tests and nine additional scenario checks
pass. This does not establish100% original-reviewer compliance: the original
assignment is unavailable. [Traceability](REQUIREMENTS_TRACEABILITY_MATRIX.md).

Severity below describes the stated consequence. It does not turn an unconfirmed
reviewer expectation or optional enhancement into a mandatory feature gap.

## RG-001 — Original reviewer specification unavailable

- Requirement: definitive comparison against the original reviewer/manager assignment.
  No original requirement ID/wording can be supplied honestly.
- Current evidence: user confirms unavailability; provisional scope and milestone
  plans exist. [Source record](REQUIREMENTS_SOURCE_RECORD.md).
- Missing evidence: original assignment, deliverables/grading rubric, exact live-demo
  standard and any named MCP/Gmail/pattern/accuracy conditions.
- Severity: **BLOCKER for a definitive compliance verdict**, not a demonstrated
  missing application feature. Affected artifacts: traceability/compliance reports;
  no specific production source requires a fix on present evidence.
- Exact next action: provide the identifiable original assignment/rubric; reconcile
  each original MUST to the existing code/test ledger, and recompute only that
  denominator. Do not replace it with T01–T08 plans.
- Acceptance impact: prevents claiming REVIEWER_REQUIREMENTS_MET definitively.
  The provisional functional audit is complete and does not wait for this document.

## RG-002 — Live Gmail acceptance outstanding

- Provisional scope: agreed Gmail code/integration demonstration; original live-account
  requirement is unconfirmed. Related supporting rows SUP-055 onward, EXT-001.
- Current implementation: readonly OAuth/state/PKCE, verified provider-profile mailbox
  ownership, selection/MIME/import/results/refresh/cleanup in gmail.py, google_gmail.py,
  gmail_mime.py, gmail_service.py and gmail_store.py.124 mocked cases and workflow I pass.
- Missing behavior/evidence: no real account consent/redirect/token exchange, profile/
  message retrieval, refresh/revocation acceptance or Google public-app approval verified.
- Severity: **MEDIUM external-verification limitation**, not an established mandatory
  reviewer blocker. Do not report Gmail as NOT_IMPLEMENTED or live VERIFIED.
- Exact next action if reviewer requires live use: separately authorize a controlled
  test-account acceptance plan, configure Cloud API/consent/client/fixed redirect
  privately, verify approved readonly operations and sanitize evidence. No new
  framework is justified. No such request is made or executed in this audit.
- Acceptance impact: only blocking if original criteria require that live standard.
  Public-user verification/security assessment remains a distinct production concern.

## RG-003 — Additional MCP reporting tools are not a proved requirement

- Requirement wording: earlier planning mentioned “sentiment analysis and reporting
  tools”; the user cannot confirm a specific original reporting-tool mandate.
- Current implementation: official MCP2.3.0 exposes analyze_feedback and
  investigate_feedback only, with grounded investigation counts/issues/evidence.
  Batch reports/results/downloads exist in REST. Source: mcp_server/server.py and
  tools.py; api/v1/batch.py. Official protocol/stdio tests pass and reject get_batch_report.
- Missing behavior: no MCP owned-job/report lookup tool, by explicit security design.
- Severity: **LOW scope uncertainty**, not an established missing reviewer MUST.
- Exact next action: ask for specific reviewer tool names/semantics only if required
  by the original assignment. Any owned-resource MCP expansion would need a separately
  authorized trusted identity design; do not add a tenant_id argument as authority.
- Acceptance impact: none established in the communicated provisional scope.

## RG-004 — Semantic model quality is not measured accuracy

- Requirement: useful sentiment/feedback insights (REQ-005). No original labeled
  dataset, accuracy threshold, calibration or adversarial acceptance criterion supplied.
- Current implementation: native strict schema, source-exact quotations, deterministic
  record/count/evidence checks and one historical live T01 smoke; all four sentiment
  response paths and calculations pass with fixtures.
- Missing evidence: labeled statistical accuracy, live selector intent generalization,
  urgency calibration and broad summary/recommendation truthfulness. Source:
  schemas/sentiment.py, services/sentiment_service.py, agents/action_selector.py and
  tools/evidence.py. Text summary/next-step fields are bounded strings, not full
  semantic claim-verification outputs; plausible or source-exact evidence does not
  prove every generated sentence true. No invented record IDs/counts pass tested checks.
- Severity: **LOW demonstration/assurance limitation**, unless the original rubric
  specifies a stronger standard. No accuracy percentage is claimed.
- Exact next action if needed: agree an authorized labeled synthetic/deidentified
  evaluation set and acceptance criteria, then evaluate classifications/selector/
  grounded summaries separately. Do not infer accuracy from571 deterministic tests.
- Acceptance impact: no missing core feature demonstrated at the current local-demo
  standard; original quality thresholds remain unknown.

## RG-005 — Full catalogue mechanisms are not all implemented

- Requirement: use/document relevant patterns, not every catalogue pattern (REQ-003/004).
- Current implementation: five verified core applications, three scoped adaptations,
  plus a hybrid principle. [Exact mapping](AGENTIC_AI_VERIFICATION.md).
- Missing catalogue mechanisms: per-claim trust scoring/external evidence verification,
  named multi-platform webhook adapters, reader/processor/writer runtime zones and
  switchable LLM/script coordinator. These were not identified as mandatory deliverables.
- Severity: **LOW claim-scope clarification**, not a missing-pattern blocker.
- Exact corrective action: retain precise scope in reviewer presentation; do not
  label adaptations as full implementations. No additional graph/framework/agents
  should be added merely to inflate a pattern count.
- Acceptance impact: no mandatory relevant-pattern gap demonstrated.

## RG-006 — Explicit temporary-storage/attachment limitations

- Current behavior: whole attachment-bearing messages are skipped before body-data
  retrieval; no attachment endpoint/decoding. Gmail tokens/connections/claims/jobs/
  results/dedup are RAM-only and disappear on restart. Chat is stateless. Local
  disconnect clears state, does not revoke Google grants or undo issued requests.
- Source: gmail_mime.preflight, GmailService lifecycle, GmailStore and
  ConversationService; MIME/lifecycle/stateless tests pass. These are intentional,
  documented scope limits, not test failures or hidden partial implementations.
- Severity: **LOW demonstration limitation** under the communicated scope.
- Exact next action: demonstrate skips and restart limitations clearly. Implement
  broader message extraction or persistence only if subsequently required and
  authorized. Do not add permanent raw feedback or plaintext token files.
- Acceptance impact: no original criterion proving a mandatory gap is available.

## Functional security findings versus optional operation

No new functional HIGH/CRITICAL security defect was demonstrated by source review,
261 passing security cases, negative service/store checks and scenario denials.
This is not exhaustive security certification. API keys/permissions/owner proofs,
size/rate/intake/model caps, original-byte HMAC/replay/idempotency, state/PKCE/token
privacy, narrow MCP capabilities and temporary cleanup have actual evidence.
Earlier QA-001/003/005 remain resolved in their documented scopes; no audit fix was made.

Docker, hosting, TLS/proxy infrastructure, CI/CD, monitoring, scale and Git/deployment
handoff are **not mandatory reviewer gaps** under current instructions. Frontend
is optional. Encrypted durable OAuth storage, distributed ownership/recovery and
Google public-app approval concern production operation, which is separately
unverified. They carry no provisional reviewer-completion penalty.

No production source, existing API contract or test assertion was changed. No
unrelated remediation, feature, framework, live provider request or deployment begun.
