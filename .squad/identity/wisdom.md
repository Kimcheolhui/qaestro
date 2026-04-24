---
last_updated: 2026-04-14T07:47:53+00:00
---

# Team Wisdom

Reusable patterns and heuristics learned through work. NOT transcripts — each entry is a distilled, actionable insight.

## Patterns

**Pattern:** Route work by architecture boundary, not by generic frontend or backend labels. **Context:** qaestro is an embedded QA agent platform whose main risks are orchestration, analysis quality, validation trust, and self-hosted operations.

**Pattern:** Keep fact analysis, strategy judgment, and runtime validation as separate owners. **Context:** collapsing those layers into one opaque agent weakens reviewability and makes QA signal drift harder to detect.
