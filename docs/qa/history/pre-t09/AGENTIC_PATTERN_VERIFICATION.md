# Agentic pattern verification — T08

The eight scoped patterns/adaptations previously verified remain. T08 adapts
existing shared/structured/API/verification mechanisms to Gmail, not a new graph
or ninth catalogue implementation. [Detailed mapping](../../../AGENTIC_PATTERNS.md),
[T07 snapshot](../pre-t08/AGENTIC_PATTERN_VERIFICATION.md).

| Pattern | Current implementation/evidence |
| --- | --- |
| Dual-Use Tool Design | GmailService → existing IngestionService/T01; shared classifier/model admission, explicit owner policy in REST and service/store; no Gmail MCP tool |
| Structured Output Specification | New typed Gmail contracts embed unchanged SentimentResponse; native strict adapter, Pydantic and exact-evidence validation remain; invalid output fails |
| LLM-Friendly API Design | Seven versioned Gmail operations, explicit state/API-key authority, three permissions, bounded inputs and safe errors;12 old operations identical |
| Output Verification Loop | T01 evidence grounding plus deterministic job snapshots/count reconciliation; no critic or autonomous repair model |
| Action-Selector | Existing graph/four actions untouched, question-only selection and owner graph/model budgets retain passing regressions |
| LLM Map-Reduce | Existing independent batch classification/Python aggregates remain; Gmail independently classifies selected text and computes outcome counts in code |
| Multi-Platform Webhook Triggers | Existing generic HMAC adapter retained; Gmail has no polling or push trigger and is not claimed as a new webhook pattern |
| Tool Capability Compartmentalization | Official MCP keeps exactly two stateless tools and no remote/owned lookup/registry/tenant argument |

The **hybrid LLM/code workflow principle** is also applied: Google HTTP, OAuth,
selection, MIME, dedup, quota/lifecycle and status are deterministic Python. Only
sentiment extraction uses the LLM. This does not claim a complete configurable
hybrid coordinator or an additional full pattern implementation. Security policy
and identity never come from email instructions or model outputs.

**571 collected/passed; 0 failed/skipped/errors; 18.286 seconds JUnit.** All447
baseline and124 new Gmail cases use mocked Google/Groq and blocked network.
Official MCP in-process/stdio, all graph paths and evidence/report checks pass.
[T01 implementation remains hash-identical](../../t08-compatibility.json). Live Google/
policy approval and broader live model-quality acceptance are outside this local
verification; prior single T01 live smoke remains narrowly verified only.
