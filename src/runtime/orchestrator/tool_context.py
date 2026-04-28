"""ToolRuntime-backed PR context collection."""

from __future__ import annotations

from dataclasses import replace
from typing import overload

from src.adapters.connectors.github import ActionsJobResult, FileDiff, PRMeta
from src.core.analyzer import PRAnalysisContext, PRFileDiff, PRFileStatus
from src.core.contracts import CICompleted, PREvent
from src.runtime.stages import WorkflowStage
from src.runtime.tools import ToolCall, ToolResult, ToolRuntime


class ToolRuntimePRContextProvider:
    """Collect PR metadata/files/diff through stage-approved GitHub read tools."""

    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def load(self, event: PREvent) -> PRAnalysisContext:
        common_input = {"repo_full_name": event.repo_full_name, "pr_number": event.pr_number}
        meta = _expect_output(
            self._runtime.execute(
                ToolCall(
                    stage=WorkflowStage.CONTEXT,
                    name="github.pr.view",
                    input=common_input,
                    correlation_id=event.meta.correlation_id,
                )
            ),
            PRMeta,
        )
        files = _expect_file_tuple(
            self._runtime.execute(
                ToolCall(
                    stage=WorkflowStage.CONTEXT,
                    name="github.pr.files",
                    input=common_input,
                    correlation_id=event.meta.correlation_id,
                )
            ).output
        )
        unified_diff = _expect_output(
            self._runtime.execute(
                ToolCall(
                    stage=WorkflowStage.CONTEXT,
                    name="github.pr.diff",
                    input=common_input,
                    correlation_id=event.meta.correlation_id,
                )
            ),
            str,
        )
        return PRAnalysisContext(
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            title=meta.title or event.title,
            body=event.body,
            base_branch=meta.base_ref or event.base_branch,
            head_branch=meta.head_ref or event.head_branch,
            files=tuple(_normalize_file(file) for file in files),
            unified_diff=unified_diff,
        )


class ToolRuntimeCIContextProvider:
    """Enrich CI events through stage-approved GitHub Actions read tools."""

    def __init__(self, runtime: ToolRuntime) -> None:
        self._runtime = runtime

    def load(self, event: CICompleted) -> CICompleted:
        if event.pr_number is None or event.failed_jobs or event.run_id is None:
            return event

        jobs = _expect_actions_job_tuple(
            self._runtime.execute(
                ToolCall(
                    stage=WorkflowStage.CONTEXT,
                    name="github.actions.run.jobs",
                    input={"repo_full_name": event.repo_full_name, "run_id": event.run_id},
                    correlation_id=event.meta.correlation_id,
                )
            ).output
        )
        failed_jobs = tuple(
            job.name
            for job in jobs
            if job.name and job.conclusion.lower() in {"failure", "timed_out", "startup_failure"}
        )
        if not failed_jobs:
            return event
        return replace(event, failed_jobs=failed_jobs)


@overload
def _expect_output(result: object, expected_type: type[PRMeta]) -> PRMeta: ...


@overload
def _expect_output(result: object, expected_type: type[str]) -> str: ...


def _expect_output(result: object, expected_type: type[object]) -> object:
    if not isinstance(result, ToolResult):
        raise TypeError("runtime returned a non-ToolResult object")
    if not result.ok:
        raise RuntimeError(result.error or f"tool {result.call.name!r} failed")
    if not isinstance(result.output, expected_type):
        raise TypeError(f"tool {result.call.name!r} returned unexpected output type")
    return result.output


def _expect_file_tuple(output: object) -> tuple[FileDiff, ...]:
    if not isinstance(output, tuple) or not all(isinstance(item, FileDiff) for item in output):
        raise TypeError("github.pr.files returned unexpected output type")
    return output


def _expect_actions_job_tuple(output: object) -> tuple[ActionsJobResult, ...]:
    if not isinstance(output, tuple) or not all(isinstance(item, ActionsJobResult) for item in output):
        raise TypeError("github.actions.run.jobs returned unexpected output type")
    return output


def _normalize_file(file: FileDiff) -> PRFileDiff:
    return PRFileDiff(
        path=file.filename,
        status=PRFileStatus.normalize(file.status),
        additions=file.additions,
        deletions=file.deletions,
        patch=file.patch,
        previous_filename=file.previous_filename,
    )
