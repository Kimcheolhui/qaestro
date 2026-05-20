"""Rule-based Behaviour Analyzer for PR diffs."""

from __future__ import annotations

from pathlib import PurePosixPath

from src.core.contracts import BehaviourImpact, ImpactArea, RiskLevel

from .types import PRAnalysisContext, PRFileDiff, PRFileStatus


class RuleBasedPRBehaviourAnalyzer:
    """Deterministic first-pass PR analyzer for the Step 3 vertical slice.

    The analyzer reports observed path groups and provider-neutral diff stats.
    It deliberately does not turn path names, changed-line thresholds, or patch
    tokens into risk judgments; strategy/agent layers can interpret these facts
    with repository knowledge and runtime evidence.
    """

    def analyze(self, context: PRAnalysisContext) -> BehaviourImpact:
        areas = tuple(_build_impact_areas(context.files))
        overall_risk = RiskLevel.NOT_ASSESSED
        stats = _diff_stats(context.files)
        return BehaviourImpact(
            summary=_summary(context, areas, overall_risk, stats),
            areas=areas,
            overall_risk=overall_risk,
            raw_diff_stats=stats,
        )


def _build_impact_areas(files: tuple[PRFileDiff, ...]) -> list[ImpactArea]:
    """Group files by observed repository path prefixes without judging risk."""
    grouped: dict[str, list[PRFileDiff]] = {}
    for file in files:
        grouped.setdefault(_path_group_for_file(file.path), []).append(file)

    areas: list[ImpactArea] = []
    for path_group in sorted(grouped):
        group_files = tuple(grouped[path_group])
        areas.append(
            ImpactArea(
                module=path_group,
                description=_area_description(path_group, group_files),
                risk_level=RiskLevel.NOT_ASSESSED,
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


def _diff_stats(files: tuple[PRFileDiff, ...]) -> dict[str, int | str]:
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
        "primary_file": _primary_changed_file(files),
        "primary_line": _primary_added_line(files) or 0,
    }


def _primary_changed_file(files: tuple[PRFileDiff, ...]) -> str:
    for file in files:
        if file.patch:
            return file.path
    return files[0].path if files else ""


def _primary_added_line(files: tuple[PRFileDiff, ...]) -> int | None:
    for file in files:
        if file.first_added_line is not None and file.first_added_line > 0:
            return file.first_added_line
        if file.patch:
            line = _first_added_line_from_patch(file.patch)
            if line is not None:
                return line
    return None


def _first_added_line_from_patch(patch: str) -> int | None:
    new_line: int | None = None
    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            new_line = _new_line_start_from_hunk(raw_line)
            continue
        if new_line is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            return new_line
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        new_line += 1
    return None


def _new_line_start_from_hunk(header: str) -> int | None:
    try:
        segment = header.split(" +", maxsplit=1)[1].split(" ", maxsplit=1)[0]
    except IndexError:
        return None
    start = segment.split(",", maxsplit=1)[0].removeprefix("+")
    try:
        return int(start)
    except ValueError:
        return None


def _summary(
    context: PRAnalysisContext,
    areas: tuple[ImpactArea, ...],
    overall_risk: RiskLevel,
    stats: dict[str, int | str],
) -> str:
    """Build a compact top-level summary for humans and later strategy input."""
    path_groups = ", ".join(area.module for area in areas) or "no path groups"
    lead_files = ", ".join(file.path for file in context.files[:3]) or "no files"
    return (
        f"PR #{context.pr_number} ({context.title}) changes {stats['files_changed']} files "
        f"(+{stats['additions']}/-{stats['deletions']}) across {path_groups}. "
        f"Risk is not assessed by the path-group analyzer. Lead files: {lead_files}."
    )


def _area_description(path_group: str, files: tuple[PRFileDiff, ...]) -> str:
    """Describe one observed path group without adding validation judgment."""
    statuses = ", ".join(sorted({file.status.value for file in files}))
    changed_lines = sum(file.additions + file.deletions for file in files)
    return f"{statuses} {len(files)} file(s) under {path_group}, {changed_lines} changed line(s)"
