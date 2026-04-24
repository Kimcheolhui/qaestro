# Project Context

- **Project:** qaestro
- **Owner:** Kimcheolhui
- **Stack:** Python, uv, Microsoft Agent Framework, GitHub App, Slack/Teams connectors, self-hosted, BYOK
- **Created:** 2026-04-14

## Core Context

Trinity owns event ingress, worker execution, orchestration flow, and connector handoffs.

## Recent Updates

- Team cast from The Matrix on 2026-04-14.
- Owns the path from webhook or chat event to the orchestrated QA workflow.

## Learnings

- Correlation across chat, PR, and CI events is foundational to the product.
- Connector SDKs stay in `adapters/connectors`; orchestration logic belongs in `runtime/orchestrator`.
