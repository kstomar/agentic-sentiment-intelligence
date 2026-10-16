> Historical pre-T09 reviewer package (2 November 2026). For the current PostgreSQL/Gmail/evidence implementation and pending real external MCP client test, use [the final submission audit](../qa/FINAL_SUBMISSION_AUDIT.md). Original evidence below is retained.

# Reviewer demonstration checklist — local API-only

This demonstrates the communicated provisional scope; it is not a substitute for
the missing original rubric. Deadline communicated by the user:6 November2026.
Use synthetic text and fabricated fixtures; do not show .env, settings objects,
API/signing keys, OAuth URLs/state/code/verifiers or provider headers in a recording.
No real Google or new Groq request is authorized by this checklist.

## Prepare the local environment

Use README's project-local uv/Python/cache/.venv exports. Verify Python3.12.16,
uv0.13.6 and the locked environment. No installation beyond the existing lock:

```bash
uv sync --locked --offline
uv pip check
GROQ_API_KEY='' APP_API_KEY='' TENANT_CREDENTIALS_JSON='' WEBHOOK_INTEGRATIONS_JSON='' GOOGLE_OAUTH_CLIENT_ID='' GOOGLE_OAUTH_CLIENT_SECRET='' uv run --locked --offline pytest -q
.venv/bin/python docs/reviewer/verify_workflows.py
```

The full suite571/571 and independent scenarios A–I have already run successfully.
The scenario script blocks sockets/DNS/real HTTP, clears Settings environment and
disables .env loading in its own process. It exercises the actual app/adapters,
not a replacement API. It records only sanitized synthetic outcomes. Its imported
test fixtures contain conspicuously fabricated credentials, not secrets to deploy.

The existing suite regenerates docs/qa/benchmark_results.json. During this audit
that output was captured here and the earlier artifact restored; if preserving a
historical snapshot during a repeat, copy that one artifact before/after the run.
Do not modify or weaken tests. Some managed sandboxes need supported execution for
thread/subprocess checks. No Git workaround or live network is necessary.

## Practical sequence

| Step | Demonstration | Expected observation / evidence | Dependency classification |
| --- | --- | --- | --- |
|1 | Show FastAPI route inventory and typed input/output in saved openapi.json or Swagger using an explicitly mocked development fixture |19 business operations; versioned schemas; API key vs HMAC vs OAuth-state authority. Production docs are normally disabled. Do not paste a real credential. | FULLY LOCAL schemas; provider behavior MOCKED |
|2 | POST sentiment/analyze with excellent quality, late delivery, neutral arrival and mixed feedback |Four200 responses; all four sentiment labels; category/aspects/urgency/summary/next-step/evidence shape. Inspect the native strict format assertion in script. | MOCKED provider outputs; actual adapter/API |
|3 | Investigate the same four records using the four selected actions |Different conditional tool paths; sentiment1/1/1/1; delivery complaints2; source IDs/quotes reconcile | MOCKED selector/classifier; real LangGraph |
|4 | Call chat in each explicit mode with current feedback |Correct exclusive response, same services/findings, no memory claim | MOCKED providers; real API/coordinator |
|5 | Upload CSV and XLSX with id/review columns |202 → COMPLETED; four results;25% each class; aspect/issue counts; JSON report/results/download | FULLY LOCAL parsing/reduction; MOCKED inference |
|6 | Use official MCP Client tools/list then call both tools; show subprocess stdio tests |Exactly analyze_feedback/investigate_feedback; structured data, safe errors; protocol-only stdout | REAL LOCAL MCP protocol; MOCKED inference |
|7 | POST ingest/feedback with external_api channel |Authenticated200 and normalized T01 analysis | FULLY LOCAL auth/API; MOCKED inference |
|8 | Sign exact synthetic webhook bytes, submit, retry and read status |202, COMPLETED, then200 DUPLICATE with no second model call; changed bytes/signature rejected in tests | FULLY LOCAL HMAC/replay/workers; MOCKED inference |
|9 | Create Alpha batch data, request as Beta, then as Alpha |Same resource: foreign404, owner200; suite also covers reports/results/downloads/events/Gmail | FULLY LOCAL verified tenants, fabricated credentials |
|10 | Run mock Gmail connect/callback/profile/filter/import/status/results/disconnect |One successful temporary import; foreign404; cleared connection after disconnect. Show mocks before outcomes. | MOCKED GOOGLE AND GROQ, actual integration code |
|11 | Show existing historical Groq report separately |One previously recorded real strict service request,1.4903s/1,371tokens; current schema/evidence revalidation passed | PREVIOUSLY LIVE VERIFIED for one T01 sample only |
|12 | State external/model/retention limitations and provisional verdict |No live Gmail/public approval or measured accuracy; no claim that attachment-bearing messages are processed; restart loses state | DISCLOSURE; any new live acceptance REQUIRES SEPARATE AUTHORIZATION |

The one-command script exercises steps2–10 over in-process HTTPX ASGI requests.
The generated OpenAPI and response ledger are suitable to inspect without a live
server. If Swagger is desired for a visual API demonstration, use the existing
create_app test fixture with mocked providers and explicitly enabled docs in the
reviewer's test runner; stock `uvicorn app.main:app` uses private configured provider
settings and is not an authorized offline inference demo. Do not represent a mock
response as a new real provider response. No frontend implementation is necessary.

## Acceptance checks before presenting

- [ ] Read the exact original assignment if it becomes available; reconcile it to
  the matrix and confirm required live-demo and quality standard.
- [ ] Show all four LangGraph routes and their different tools, not just sentiment.
- [ ] Distinguish mathematical report correctness from preassigned mock model labels.
- [ ] Explain five verified pattern applications, three adaptations and the hybrid
  principle; do not claim the whole catalogue or full external fact checking.
- [ ] Explain readonly Gmail, tenant ownership, attachment skips, temporary memory
  and local-disconnect/no-Google-revocation behavior.
- [ ] State MCP is local stateless two-tool stdio, without a remote owned-report tool.
- [ ] Use the fresh571-test and A–I artifacts, not earlier counts as current evidence.
- [ ] Keep deployment/frontend out of the reviewer score; mention production concerns
  separately only if relevant to discussion.

The checklist describes a proposed presentation, not a claim that a human reviewer
has already seen or accepted it. Audit workflows themselves are executed and linked
in [END_TO_END_VERIFICATION.md](END_TO_END_VERIFICATION.md). No deployment work begins.
