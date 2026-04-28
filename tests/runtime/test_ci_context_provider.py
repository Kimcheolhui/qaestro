"""Tests for CI context enrichment through ToolRuntime."""

from __future__ import annotations

from datetime import UTC, datetime

from src.adapters.connectors.github import ActionsJobResult
from src.core.contracts import CICompleted, EventMeta, EventSource, EventType
from src.runtime.orchestrator import ToolRuntimeCIContextProvider
from src.runtime.stages import WorkflowStage
from src.runtime.tools import ToolAuditEntry, ToolCall, ToolResult


class RecordingToolRuntime:
    def __init__(self, output: object) -> None:
        self.calls: list[ToolCall] = []
        self._output = output

    @property
    def audit_log(self) -> tuple[ToolAuditEntry, ...]:
        return ()

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call=call, ok=True, output=self._output)


def _ci_event(*, failed_jobs: tuple[str, ...] = (), run_id: int | None = 99) -> CICompleted:
    return CICompleted(
        meta=EventMeta(
            event_id="evt-ci",
            event_type=EventType.CI_COMPLETED,
            correlation_id="corr-ci",
            timestamp=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
            source=EventSource.GITHUB,
        ),
        repo_full_name="octocat/hello-world",
        pr_number=42,
        commit_sha="abc123",
        workflow_name="Tests",
        conclusion="failure",
        run_url="https://github.com/octocat/hello-world/actions/runs/99",
        failed_jobs=failed_jobs,
        run_id=run_id,
    )


def test_tool_runtime_ci_context_provider_enriches_failed_jobs_from_actions_jobs() -> None:
    runtime = RecordingToolRuntime(
        (
            ActionsJobResult(name="tests", conclusion="failure", html_url="https://example.com/tests"),
            ActionsJobResult(name="lint", conclusion="success", html_url="https://example.com/lint"),
            ActionsJobResult(name="types", conclusion="timed_out", html_url="https://example.com/types"),
        )
    )
    provider = ToolRuntimeCIContextProvider(runtime)

    enriched = provider.load(_ci_event())

    assert enriched.failed_jobs == ("tests", "types")
    assert runtime.calls == [
        ToolCall(
            stage=WorkflowStage.CONTEXT,
            name="github.actions.run.jobs",
            input={"repo_full_name": "octocat/hello-world", "run_id": 99},
            correlation_id="corr-ci",
        )
    ]


def test_tool_runtime_ci_context_provider_preserves_fixture_failed_jobs_without_fetch() -> None:
    runtime = RecordingToolRuntime(())
    provider = ToolRuntimeCIContextProvider(runtime)
    event = _ci_event(failed_jobs=("fixture-job",))

    enriched = provider.load(event)

    assert enriched is event
    assert runtime.calls == []


def test_tool_runtime_ci_context_provider_preserves_event_without_run_id() -> None:
    runtime = RecordingToolRuntime(())
    provider = ToolRuntimeCIContextProvider(runtime)
    event = _ci_event(run_id=None)

    enriched = provider.load(event)

    assert enriched is event
    assert runtime.calls == []


def test_tool_runtime_ci_context_provider_preserves_orphan_ci_without_fetch() -> None:
    runtime = RecordingToolRuntime(())
    provider = ToolRuntimeCIContextProvider(runtime)
    event = _ci_event()
    event = CICompleted(
        meta=event.meta,
        repo_full_name=event.repo_full_name,
        pr_number=None,
        commit_sha=event.commit_sha,
        workflow_name=event.workflow_name,
        conclusion=event.conclusion,
        run_url=event.run_url,
        run_id=event.run_id,
    )

    enriched = provider.load(event)

    assert enriched is event
    assert runtime.calls == []
