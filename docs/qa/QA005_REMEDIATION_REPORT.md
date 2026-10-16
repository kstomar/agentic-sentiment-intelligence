# QA-005 remediation and security readiness review

Date: 30 October 2026. **QA-005: RESOLVED. Release: NOT READY.**

## Root cause and smallest correction

FastAPI 0.162.0's `_get_multidict_value` treats an empty FormData string as
`Undefined`. `_validate_value_with_model_field` then substitutes the optional
field's default. Consequently, `source=""` reached `upload` as `file_upload`;
the existing `UploadOptions.nonblank` validator never saw the empty input.
Whitespace-only strings were already rejected by the existing model validator.
This was a request-extraction/defaulting defect, not permissive Pydantic validation.

The only production file changed is `app/api/v1/batch.py`. Its existing raw-form
blank check, already used for optional ID/date mappings, now also checks `source`.
It rejects explicitly empty or whitespace-only source parts before parsing the
file or scheduling a job, using the existing controlled HTTP 422 error path.
Omitted source still receives `file_upload`. Normalization, lengths, schemas,
defaults, error envelopes, and successful response fields are unchanged.

Batch source is an existing free-form nonblank metadata label, up to 64
characters; it does not have T01's source enumeration. Custom labels remain
accepted. Overlong and non-text values remain unsupported and return 422.
T01/MCP retain their original source allowlist, and the batch mapper still uses
T01's manual source while retaining the upload label as report metadata.

## Executed evidence

1. Applied the route correction, then ran the original failing test before
   adding tests. Its function body and assertion were unchanged: **1 passed**
   (pytest console 0.09 seconds; JUnit 0.098 seconds).
2. Added ten parameterized/integration cases in the existing batch test module:
   omitted/default/custom/trimmed/64-character labels, whitespace variants,
   overlong labels, and a file-valued source. Invalid cases verify no model
   invocation and no accepted job; successful cases verify report metadata and
   unchanged T01 source delegation.
3. Ran `uv run pytest -q --junitxml=docs/qa/qa005-full.xml`: **220 passed in
   9.39 seconds**, zero failures, skips, and errors. All original 210 collected
   cases remain present and pass; ten new cases account for the count increase.
4. Compared the complete generated OpenAPI document with its pre-fix snapshot:
   exact match. The original QA-005 test text also matches its saved snapshot.
5. Locked offline synchronization and `uv pip check` passed; dependency files
   and all other application modules are unchanged.

Full regressions exercise FastAPI startup/imports, Pydantic validation, T01/T02/
T03 APIs, all four LangGraph paths, CSV/XLSX batch processing/reports, provider
error policy, privacy/lifecycle checks, and official in-process/stdio MCP clients.
Provider inference remains mocked; no live Groq request was made.

Evidence: [focused output](qa005-focused.txt), [focused XML](qa005-focused.xml),
[full output](qa005-full.txt), [full XML](qa005-full.xml),
[compatibility checks](qa005-dependency-checks.txt), and
[integrity summary](qa005-summary.json).

The original audit's 210/209/1 result and issue text remain in
[history/original-audit](history/original-audit/KNOWN_ISSUES.md), alongside the
original XML/console artifacts. No assertion was deleted, skipped, or weakened.

## High-security review and scope

QA-001 and QA-003 remain **OPEN / HIGH**. The detailed endpoint/file mapping and
minimal proposed designs are in [SECURITY_REVIEW.md](SECURITY_REVIEW.md).

- Tenant identity and owner-enforced lookup belong to the multi-business
  milestone. T06 must consume that trusted identity design for any future event
  ownership; a payload business_type is not an identity.
- Shared ingress limits, early bounded intake, and model/request admission
  should be established in a T06 security-foundation change before exposing new
  ingestion. Per-principal quota/ownership integration belongs to multi-business.
- No additional ingress production fix was applied: selecting new byte/rate/
  concurrency policies and rejection behavior would extend this task and affect
  currently accepted requests. The demonstrated gaps remain documented blockers.

Live Groq verification remains BLOCKED: the preceding authorized smoke check
found no configured provider key and made zero requests. T06/Gmail/tenant work,
public deployment controls, and repository/release handoff remain unresolved.
Green mocked tests do not establish live AI or multi-business release readiness.

T06 was not started. Security/ownership planning can be commissioned separately;
implementation remains subject to the previously requested live-Groq prerequisite
and separate T06 authorization, unless that prerequisite is explicitly deferred.
