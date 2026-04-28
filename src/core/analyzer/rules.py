"""Rule-based Behaviour Analyzer for PR diffs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath

from src.core.contracts import BehaviourImpact, ImpactArea, RiskLevel

from .types import PRAnalysisContext, PRFileDiff, PRFileStatus


class RuleBasedPRBehaviourAnalyzer:
    """Deterministic first-pass PR analyzer for the Step 3 vertical slice.

    The analyzer reports observed path groups and simple diff signals. It does
    not try to define customer modules; adaptive ownership/risk learning belongs
    in later knowledge/agent workflows.
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
    """Group files by observed repository path prefixes."""
    grouped: dict[str, list[PRFileDiff]] = defaultdict(list)
    for file in files:
        grouped[_path_group_for_file(file.path)].append(file)

    areas: list[ImpactArea] = []
    for path_group in sorted(grouped):
        group_files = tuple(grouped[path_group])
        risk = _risk_for_path_group_files(group_files)
        areas.append(
            ImpactArea(
                module=path_group,
                description=_area_description(path_group, group_files),
                risk_level=risk,
                affected_files=tuple(file.path for file in group_files),
            )
        )
    return areas


def _path_group_for_file(path: str) -> str:
    """Return a stable path prefix without imposing a product module taxonomy."""
    clean_path = path.strip("/")
    if not clean_path:
        return "unknown"

    posix_path = PurePosixPath(clean_path)
    parts = posix_path.parts
    if len(parts) == 1:
        return parts[0]
    if parts[0] in {"src", "tests"}:
        return "/".join(parts[:-1]) if len(parts) > 2 else parts[0]
    if parts[0] == ".github" and len(parts) >= 2:
        return "/".join(parts[:2])
    if len(parts) > 2:
        return "/".join(parts[:-1])
    return parts[0]


def _risk_for_path_group_files(files: tuple[PRFileDiff, ...]) -> RiskLevel:
    """Estimate initial risk from file status, size, and diff content only."""
    changed_lines = sum(file.additions + file.deletions for file in files)
    removed_files = any(file.status is PRFileStatus.REMOVED for file in files)
    risky_patch = any(_patch_contains_risky_signal(file.patch or "") for file in files)

    if removed_files or changed_lines >= 120 or risky_patch:
        return RiskLevel.HIGH
    if changed_lines >= 40:
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
        "files_copied": sum(1 for file in files if file.status is PRFileStatus.COPIED),
        "files_unchanged": sum(1 for file in files if file.status is PRFileStatus.UNCHANGED),
        "files_unknown": sum(1 for file in files if file.status is PRFileStatus.UNKNOWN),
    }


def _summary(
    context: PRAnalysisContext,
    areas: tuple[ImpactArea, ...],
    overall_risk: RiskLevel,
    stats: dict[str, int],
) -> str:
    """Build a compact top-level summary for humans and later strategy input."""
    path_groups = ", ".join(area.module for area in areas) or "no path groups"
    lead_files = ", ".join(file.path for file in context.files[:3]) or "no files"
    return (
        f"PR #{context.pr_number} ({context.title}) changes {stats['files_changed']} files "
        f"(+{stats['additions']}/-{stats['deletions']}) across {path_groups}. "
        f"Overall risk is {overall_risk.value}. Lead files: {lead_files}."
    )


def _area_description(path_group: str, files: tuple[PRFileDiff, ...]) -> str:
    """Describe one observed path group without adding validation judgment."""
    statuses = ", ".join(sorted({file.status.value for file in files}))
    changed_lines = sum(file.additions + file.deletions for file in files)
    return f"{statuses} {len(files)} file(s) under {path_group}, {changed_lines} changed line(s)"


def _max_risk(risks: Iterable[RiskLevel], *, default: RiskLevel) -> RiskLevel:
    """Return the highest risk while keeping empty inputs deterministic."""
    order = {
        RiskLevel.NOT_ASSESSED: -1,
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }
    risk_values = tuple(risks)
    if not risk_values:
        return default
    return max(risk_values, key=lambda risk: order[risk])
