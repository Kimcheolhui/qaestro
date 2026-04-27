"""Rule-based Behaviour Analyzer for PR diffs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from src.core.contracts import BehaviourImpact, ImpactArea, RiskLevel

from .types import PRAnalysisContext, PRFileDiff, PRFileStatus


class RuleBasedPRBehaviourAnalyzer:
    """Deterministic first-pass PR analyzer for the Step 3 vertical slice.

    These heuristics produce transparent review context, not customer-specific
    QA knowledge. Long-term risk learning belongs in knowledge/agent workflows.
    """

    def analyze(self, context: PRAnalysisContext) -> BehaviourImpact:
        areas = tuple(_build_impact_areas(context.files))
        overall_risk = _max_risk((area.risk_level for area in areas), default=RiskLevel.LOW)
        stats = _diff_stats(context.files)
        return BehaviourImpact(
            summary=_summary(context, areas, overall_risk, stats),
            areas=areas,
            overall_risk=overall_risk,
            raw_diff_stats=stats,
        )


def _build_impact_areas(files: tuple[PRFileDiff, ...]) -> list[ImpactArea]:
    """Group files into coarse, portable impact surfaces."""
    grouped: dict[str, list[PRFileDiff]] = defaultdict(list)
    for file in files:
        grouped[_surface_for_file(file.path)].append(file)

    areas: list[ImpactArea] = []
    for surface in _sorted_surfaces(grouped):
        surface_files = tuple(grouped[surface])
        risk = _risk_for_surface_files(surface, surface_files)
        areas.append(
            ImpactArea(
                module=surface,
                description=_area_description(surface, surface_files),
                risk_level=risk,
                affected_files=tuple(file.path for file in surface_files),
            )
        )
    return areas


def _sorted_surfaces(grouped: dict[str, list[PRFileDiff]]) -> list[str]:
    """Keep report ordering stable without implying org-specific ownership."""
    order = {"api": 0, "ui": 1, "config": 2, "infra": 3, "source": 4, "tests": 90, "docs": 91}
    return sorted(grouped, key=lambda surface: (order.get(surface, 50), surface))


def _surface_for_file(path: str) -> str:
    """Classify a path into a generic impact surface.

    The returned value is stored in ``ImpactArea.module`` for the existing domain
    contract, but it is intentionally not a company/team module name.
    """
    lowered = path.lower()
    parts = lowered.split("/")
    filename = parts[-1] if parts else lowered

    if lowered.startswith(("docs/", "readme", "changelog")) or filename.endswith((".md", ".rst")):
        return "docs"
    if lowered.startswith(("tests/", "test/")) or "/tests/" in lowered or filename.startswith("test_"):
        return "tests"
    if lowered.startswith((".github/workflows/", "infra/", "terraform/", "k8s/", "deploy/", "deployment/")):
        return "infra"
    if lowered.startswith(("config/", "configs/")) or filename.endswith((".toml", ".yaml", ".yml", ".ini", ".env")):
        return "config"
    if "/api/" in lowered or lowered.startswith(("api/", "src/api/")) or "router" in lowered or "endpoint" in lowered:
        return "api"
    if lowered.startswith(("src/web/", "web/", "frontend/", "ui/")) or filename.endswith(
        (".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss")
    ):
        return "ui"
    if lowered.startswith("src/"):
        return "source"
    return _fallback_surface(path)


def _fallback_surface(path: str) -> str:
    """Fallback for repo roots outside common source/test/doc layouts."""
    parts = path.split("/")
    if len(parts) >= 1 and parts[0]:
        return parts[0]
    return "unknown"


def _risk_for_surface_files(surface: str, files: tuple[PRFileDiff, ...]) -> RiskLevel:
    """Estimate initial risk from change size, deletion, and risky diff signals.

    This is a transparent default for Step 3, not a learned product risk model.
    Future agent/knowledge flows should replace these static thresholds when
    customer-specific risk history is available.
    """
    changed_lines = sum(file.additions + file.deletions for file in files)
    removed_files = any(file.status is PRFileStatus.REMOVED for file in files)
    risky_patch = any(_patch_contains_risky_signal(file.patch or "") for file in files)

    if surface in {"infra", "config"} and (changed_lines >= 40 or removed_files):
        return RiskLevel.HIGH
    if surface == "api" and (removed_files or changed_lines >= 180):
        return RiskLevel.HIGH
    if risky_patch and surface in {"api", "infra", "config"}:
        return RiskLevel.HIGH
    if surface in {"api", "ui", "source", "infra", "config"}:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _patch_contains_risky_signal(patch: str) -> bool:
    """Detect small, high-signal tokens in a per-file unified diff hunk."""
    lowered = patch.lower()
    return any(
        signal in lowered
        for signal in (
            "permission",
            "auth",
            "token",
            "secret",
            "migration",
            "drop table",
            "delete from",
        )
    )


def _diff_stats(files: tuple[PRFileDiff, ...]) -> dict[str, int]:
    """Aggregate provider-neutral file counts for report metadata."""
    return {
        "files_changed": len(files),
        "additions": sum(file.additions for file in files),
        "deletions": sum(file.deletions for file in files),
        "files_added": sum(1 for file in files if file.status is PRFileStatus.ADDED),
        "files_modified": sum(1 for file in files if file.status in {PRFileStatus.MODIFIED, PRFileStatus.CHANGED}),
        "files_removed": sum(1 for file in files if file.status is PRFileStatus.REMOVED),
        "files_renamed": sum(1 for file in files if file.status is PRFileStatus.RENAMED),
    }


def _summary(
    context: PRAnalysisContext,
    areas: tuple[ImpactArea, ...],
    overall_risk: RiskLevel,
    stats: dict[str, int],
) -> str:
    """Build a compact top-level summary for humans and later strategy input."""
    surfaces = ", ".join(area.module for area in areas) or "no classified areas"
    lead_files = ", ".join(file.path for file in context.files[:3]) or "no files"
    return (
        f"PR #{context.pr_number} ({context.title}) changes {stats['files_changed']} files "
        f"(+{stats['additions']}/-{stats['deletions']}) across {surfaces}. "
        f"Overall risk is {overall_risk.value}. Lead files: {lead_files}."
    )


def _area_description(surface: str, files: tuple[PRFileDiff, ...]) -> str:
    """Describe one impact surface without adding validation judgment."""
    statuses = ", ".join(sorted({file.status.value for file in files}))
    changed_lines = sum(file.additions + file.deletions for file in files)
    return f"{statuses} {len(files)} {surface} file(s), {changed_lines} changed line(s)"


def _max_risk(risks: Iterable[RiskLevel], *, default: RiskLevel) -> RiskLevel:
    """Return the highest risk while keeping empty inputs deterministic."""
    order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
    risk_values = tuple(risks)
    if not risk_values:
        return default
    return max(risk_values, key=lambda risk: order[risk])
