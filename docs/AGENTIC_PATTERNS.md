# Implemented agentic mechanisms and catalogue adaptations

Current review: 6 November 2026. Required reference:
[awesome-agentic-patterns](https://github.com/nibzard/awesome-agentic-patterns).
Eight relevant pattern files were read during the final audit; URLs/blob hashes
are recorded in docs/qa/final-submission/pattern-references.json. The catalogue is
an external design reference, not an independently verified reviewer rubric.

The application is a **bounded, tool-using agentic workflow**. It does not implement
all catalogue patterns or claim autonomous planning, durable memory or generalized
self-reflection. Ordinary sentiment classification and MCP exposure alone are not
proof of agency. The actual graph and tools supply the multi-step workflow.

| Catalogue pattern | Application evidence | Scope / honest status |
| --- | --- | --- |
| [Structured Output Specification](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/structured-output-specification.md) | app/schemas/sentiment.py; sentiment_service.create_sentiment_service; ActionSelection and strict selector | Implemented mechanism: native json_schema strict=True, closed required output and complete Pydantic validation. This constrains structure, not semantic truth. |
| [Action-Selector](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/action-selector-pattern.md) | app/agents/action_selector.py, prompts/investigation.py, feedback_graph.py | Implemented: question/hint → allowlisted action/validated arguments; deterministic execution; corpus/tool outputs never return to selector. No iterative replanning. |
| [LLM Map-Reduce](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/llm-map-reduce-pattern.md) | tools/feedback_analysis.py, batch_analysis.py, aggregation.py, services/reporting_service.py | Applied per-record prompt isolation plus deterministic reduction. Sequential/bounded calls are not OS-sandboxed subagents or a distributed map framework. |
| [Dual-Use Tool Design](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/dual-use-tool-design.md) | REST routes, graph and app/mcp_server/tools.py use shared services/contracts | Reuse adaptation. REST uses business authentication; local MCP uses trusted-launcher authority. Permissions are explicitly different transport boundaries, not universal tenant equivalence. |
| [LLM-Friendly API Design](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/llm-friendly-api-design.md) | /api/v1, Pydantic/OpenAPI, descriptive MCP tools and fixed safe errors | Applied: versioned typed interface and narrow discoverable tools. No measured reduction in model tool-use errors is claimed. |
| [Output Verification Loop](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/output-verification-loop.md) | tools/evidence.verify_findings; InvestigationService final verification; sentiment grounding/correction/sanitization | Partial adaptation: source IDs/quotes/counts are verified and one correction is bounded. No external claim extraction, per-claim trust scores, critic model or verification receipts. |
| [Hybrid LLM/Code Workflow Coordinator](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/hybrid-llm-code-workflow-coordinator.md) | LLM selector/classifier plus reviewed Python graph/reducers | Hybrid separation principle only. Catalogue's configurable llm/script coordinator migration mechanism is absent. |
| [Multi-Platform Webhook Triggers](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/multi-platform-webhook-triggers.md) | HMAC webhook, persistent reservation/idempotency, bounded worker queue | Generic signed trigger adaptation. No Slack/Notion/Jira integrations, emoji triggers or scheduler. Current webhook invokes shared sentiment, not an arbitrary autonomous agent. |

## Real runtime graph

build_feedback_graph compiles StateGraph with select_action, analyze_feedback,
aggregate_issues, retrieve_evidence, verify_evidence and generate_insights nodes.
After one selected action and all record analyses, conditional edges choose:

- SENTIMENT_OVERVIEW → verify_evidence → generate_insights.
- EVIDENCE_SEARCH → retrieve_evidence → verify_evidence → generate_insights.
- ISSUE_FREQUENCY or GENERAL_FEEDBACK_SUMMARY → aggregate_issues → retrieve_evidence
  → verify_evidence → generate_insights.

Both issue actions share topology, with different deterministic response logic.
Returned tools_used omits the control/verification nodes and lists executed domain
tools; it is not the complete node trace. The selector sees no feedback/IDs/tool
results. Later observations inform counts, issue groups, evidence and recommendations,
not another selector decision. Compiled state is request-scoped with no checkpoint,
store or cache; the whole graph has a deadline and recursion limit 12.

## Grounding and privacy limits

T01's original exact-evidence validator remains. One correction can be followed
by exact-phrase filtering only when the corrected result is otherwise valid. Full
revalidation is mandatory; no fuzzy repair or third generation. Empty model evidence
is allowed but provides no retained model quotation or independent support for
classification/summary. Graph evidence retrieval instead returns verified original
request records under validated IDs/filters; that does not make classifications
independently true. Batch reports omit absent model evidence rather than invent it.

Prompt boundaries, control-flow separation, schemas and narrow tools constrain
injection effects; they are not proof of semantic correctness or an OS sandbox.
No external operational records, history, web search or business actions are used
by the investigation workflow. See [final source/test evidence and three examples](qa/FINAL_SUBMISSION_AUDIT.md).
