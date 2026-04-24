# Work Routing

How to decide who handles what for qaestro.

## Routing Table

| Work Type                                 | Route To | Examples                                                                                    |
| ----------------------------------------- | -------- | ------------------------------------------------------------------------------------------- |
| Architecture and scope                    | Morpheus | Module boundaries, phased delivery, ADRs, issue triage, reviewer gating                     |
| Event ingestion and orchestration         | Trinity  | GitHub or chat webhooks, connector handoffs, worker wiring, context correlation             |
| Behaviour analysis and strategy           | Neo      | Contracts, diff analysis, risk classification, checklist generation, strategy outputs       |
| Validation, knowledge, and replay quality | Oracle   | Validation plans, runtime probes, knowledge-store patterns, replay and regression design    |
| Platform and operations                   | Tank     | Self-hosted deployment, CI wiring, GitHub App manifest, ChatOps setup, local storage config |
| Code review                               | Morpheus | Cross-layer review, dependency direction checks, architectural risk review                  |
| Testing                                   | Oracle   | Validation evidence, replay fixtures, regression coverage, false-positive control           |
| Scope and priorities                      | Morpheus | MVP cuts, backlog ordering, trade-off calls                                                 |
| Session logging                           | Scribe   | Automatic - never needs routing                                                             |

## Issue Routing

| Label          | Action                                               | Who          |
| -------------- | ---------------------------------------------------- | ------------ |
| `squad`        | Triage: analyze issue, assign `squad:{member}` label | Lead         |
| `squad:{name}` | Pick up issue and complete the work                  | Named member |

### How Issue Assignment Works

1. When a GitHub issue gets the `squad` label, the **Lead** triages it — analyzing content, assigning the right `squad:{member}` label, and commenting with triage notes.
2. When a `squad:{member}` label is applied, that member picks up the issue in their next session.
3. Members can reassign by removing their label and adding another member's label.
4. The `squad` label is the "inbox" — untriaged issues waiting for Lead review.

## Rules

1. **Eager by default** — spawn all agents who could usefully start work, including anticipatory downstream work.
2. **Route by architecture boundary first.** qaestro is not a frontend-heavy product, so prefer system ownership over generic app roles.
3. **Scribe always runs** after substantial work, always as `mode: "background"`. Never blocks.
4. **Quick facts -> coordinator answers directly.** Don't spawn an agent for "what port does the server run on?"
5. **When a task crosses 3 or more layers, bring in Morpheus plus the primary owner.** The lead keeps seams explicit before implementation fans out.
6. **When two agents could handle it,** pick the one whose layer owns the primary risk.
7. **"Team, ..." -> fan-out.** Spawn all relevant agents in parallel as `mode: "background"`.
8. **Anticipate Oracle early.** If work changes analyzer, strategy, or runtime behavior, bring Oracle in to shape validation and replay coverage.
9. **Issue-labeled work** — when a `squad:{member}` label is applied to an issue, route to that member. The Lead handles all `squad` (base label) triage.
