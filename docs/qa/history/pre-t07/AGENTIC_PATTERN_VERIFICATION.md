# Agentic pattern verification — T06

The mandatory reference is [awesome-agentic-patterns](https://github.com/nibzard/awesome-agentic-patterns).
Verification refers to the described local implementation/adaptation, not all
capabilities of a catalogue entry or live-model correctness. Full source mapping:
[AGENTIC_PATTERNS.md](../../../AGENTIC_PATTERNS.md).

| Pattern | Actual source and evidence | Current scope |
| --- | --- | --- |
| Multi-Platform Webhook Triggers | api/v1/webhooks.py; core/webhook_security.py; services/ingestion_service.py, webhook_service.py; storage/event_store.py. Tests verify HMAC/raw bytes/time, normalized T01 input, atomic duplicates/conflicts, fixed workers, truthful ack, failures/expiry/cancellation | VERIFIED generic one-integration adaptation; no vendor adapters/durable/distributed delivery |
| Dual-Use Tool Design | ingestion_service.py delegates to same T01 instance from direct REST and workers; existing REST/LangGraph/MCP callers remain | VERIFIED locally; no new classifier/client/prompt/graph |
| LLM-Friendly API Design | schemas/ingestion.py; three typed versioned routes; distinct API-key/HMAC security, fixed errors, actual OpenAPI inventory and accepted/duplicate/status semantics | VERIFIED; JSON 413 policy change explicitly approved and documented |
| Structured Output Specification | existing sentiment_service.py factory/native strict json_schema and SentimentResponse; ingestion revalidates evidence; existing actual ChatGroq MockTransport checks | VERIFIED locally; prior single live T01 strict request passed, no T06 live call |
| Action-Selector | agents/action_selector.py and existing feedback_graph.py; all four bounded paths and question-only input tests | VERIFIED; graph unchanged, shared admission added |
| LLM Map-Reduce | existing batch mapper/service/reporting/statistics; independent row calls and deterministic reconciliation tests | VERIFIED documented adaptation; no new map/reduce implementation |
| Output Verification Loop | existing evidence tools and investigation/report validators; fabricated quotes/counts/IDs reject | VERIFIED deterministic integrity-gate adaptation; no critic/automatic repair loop |
| Tool Capability Compartmentalization | unchanged MCP two-tool registration and call boundary; official in-process/stdio tests | VERIFIED narrow registered capability surface, not OS sandbox/policy engine |

Eight scoped patterns/adaptations now have local verification. The hybrid LLM/code
coordination principle remains applied by T02, not a complete configurable
coordinator. Webhook support is one generic trigger, not multiple implemented
platform integrations. No additional autonomous agent or model formatting call
was introduced. HMAC authentication, resource controls and ownership are Python
security boundaries, not delegated model decisions.

Evidence: 330 passing offline tests, [JUnit](../../t06-full.xml), unchanged official MCP
checks, and [prior single-live-T01 result](../../LIVE_GROQ_VERIFICATION_REPORT.md).
New webhook/direct tests use actual services with mocked model interfaces.
Provider-native strict acceptance was demonstrated only by the earlier authorized
one-case smoke; broad classification quality/live webhook workflows remain unverified.

Full relevant references:
[webhook triggers](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/multi-platform-webhook-triggers.md),
[dual-use](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/dual-use-tool-design.md),
[API design](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/llm-friendly-api-design.md),
[structured output](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/structured-output-specification.md).
[Pre-T06 assessment](../pre-t06/AGENTIC_PATTERN_VERIFICATION.md) and
[original audit](../original-audit/AGENTIC_PATTERN_VERIFICATION.md) preserve
historical NOT_IMPLEMENTED webhook status and verification limits.
