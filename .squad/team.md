# Squad Team

> Embedded QA agent for agentic development environments.

## Coordinator

| Name  | Role        | Notes                                              |
| ----- | ----------- | -------------------------------------------------- |
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name     | Role                            | Charter                             | Status  |
| -------- | ------------------------------- | ----------------------------------- | ------- |
| Morpheus | Lead Architect                  | `.squad/agents/morpheus/charter.md` | Active  |
| Trinity  | Runtime & Integration Engineer  | `.squad/agents/trinity/charter.md`  | Active  |
| Neo      | Behaviour & Strategy Engineer   | `.squad/agents/neo/charter.md`      | Active  |
| Oracle   | Validation & Knowledge Engineer | `.squad/agents/oracle/charter.md`   | Active  |
| Tank     | Platform & Operations Engineer  | `.squad/agents/tank/charter.md`     | Active  |
| Scribe   | Session Logger                  | `.squad/agents/scribe/charter.md`   | Silent  |
| Ralph    | Work Monitor                    | `.squad/agents/ralph/charter.md`    | Monitor |

## Coding Agent

<!-- copilot-auto-assign: false -->

| Name     | Role         | Charter | Status    |
| -------- | ------------ | ------- | --------- |
| @copilot | Coding Agent | -       | Available |

### Capabilities

**Good fit - route when the task is well-bounded:**

- Small features inside an existing layer boundary
- Test and replay coverage additions
- Connector wrappers that follow established contracts
- Documentation, type definitions, and scaffolding

**Needs review - route, then hand back to a squad reviewer:**

- Medium-sized features spanning 2 layers with clear acceptance criteria
- Refactors guarded by replay or integration coverage
- New validation probes following an agreed interface

**Not suitable - keep with the named squad member instead:**

- Architecture decisions and role boundary changes
- Ambiguous product behavior or QA policy questions
- Security-critical integration changes
- Cross-cutting work that needs orchestration across 3 or more layers

## Project Context

- **Owner:** Kimcheolhui
- **Stack:** Python, uv, Microsoft Agent Framework, GitHub App, Slack/Teams connectors, self-hosted, BYOK model providers
- **Description:** Embedded QA agent that analyzes repo change intent, proposes validation strategy, and verifies system behaviour across chat, PR, and CI loops
- **Cast Universe:** The Matrix
- **Created:** 2026-04-14
