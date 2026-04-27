"""Rule-based Behaviour Analyzer for PR diffs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from src.core.contracts import BehaviourImpact, ImpactArea, RiskLevel

from .types import PRAnalysisContext, PRFileDiff


class RuleBasedPRBehaviourAnalyzer:
    """Deterministic first-pass PR analyzer for the Step 3 vertical slice.

    The analyzer intentionally uses transparent file/path/diff heuristics. It
    does not choose validation actions; that remains the Strategy Engine's job.
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
    grouped: dict[str, list[PRFileDiff]] = defaultdict(list)
    for file in files:
        grouped[_module_for_file(file.path)].append(file)

    areas: list[ImpactArea] = []
    for module in _sorted_modules(grouped):
        module_files = tuple(grouped[module])
        risk = _risk_for_module_files(module, module_files)
        areas.append(
            ImpactArea(
                module=module,
                description=_area_description(module, module_files),
                risk_level=risk,
                affected_files=tuple(file.path for file in module_files),
            )
        )
    return areas


def _sorted_modules(grouped: dict[str, list[PRFileDiff]]) -> list[str]:
    order = {"api": 0, "ui": 1, "config": 2, "infra": 3, "runtime": 4, "core": 5, "tests": 90, "docs": 91}
    return sorted(grouped, key=lambda module: (order.get(module, 50), module))


def _module_for_file(path: str) -> str:
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
    if lowered.startswith("src/runtime/"):
        return "runtime"
    if lowered.startswith("src/core/"):
        return "core"
    return _fallback_module(path)


def _fallback_module(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    if len(parts) >= 1 and parts[0]:
        return parts[0]
    return "unknown"


def _risk_for_module_files(module: str, files: tuple[PRFileDiff, ...]) -> RiskLevel:
    changed_lines = sum(file.additions + file.deletions for file in files)
    removed_files = any(file.status == "removed" for file in files)
    risky_patch = any(_patch_contains_risky_signal(file.patch or "") for file in files)

    if module in {"infra", "config"} and (changed_lines >= 40 or removed_files):
        return RiskLevel.HIGH
    if module in {"api", "runtime"} and (removed_files or changed_lines >= 180):
        return RiskLevel.HIGH
    if risky_patch and module in {"api", "infra", "config"}:
        return RiskLevel.HIGH
    if module in {"api", "ui", "runtime", "core", "infra", "config"}:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _patch_contains_risky_signal(patch: str) -> bool:
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
    return {
        "files_changed": len(files),
        "additions": sum(file.additions for file in files),
        "deletions": sum(file.deletions for file in files),
        "files_added": sum(1 for file in files if file.status == "added"),
        "files_modified": sum(1 for file in files if file.status == "modified"),
        "files_removed": sum(1 for file in files if file.status == "removed"),
        "files_renamed": sum(1 for file in files if file.status == "renamed"),
    }


def _summary(
    context: PRAnalysisContext,
    areas: tuple[ImpactArea, ...],
    overall_risk: RiskLevel,
    stats: dict[str, int],
) -> str:
    modules = ", ".join(area.module for area in areas) or "no classified areas"
    lead_files = ", ".join(file.path for file in context.files[:3]) or "no files"
    return (
        f"PR #{context.pr_number} ({context.title}) changes {stats['files_changed']} files "
        f"(+{stats['additions']}/-{stats['deletions']}) across {modules}. "
        f"Overall risk is {overall_risk.value}. Lead files: {lead_files}."
    )


def _area_description(module: str, files: tuple[PRFileDiff, ...]) -> str:
    statuses = ", ".join(sorted({file.status for file in files}))
    changed_lines = sum(file.additions + file.deletions for file in files)
    return f"{statuses} {len(files)} {module} file(s), {changed_lines} changed line(s)"


def _max_risk(risks: Iterable[RiskLevel], *, default: RiskLevel) -> RiskLevel:
    order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
    risk_values = tuple(risks)
    if not risk_values:
        return default
    return max(risk_values, key=lambda risk: order[risk])
