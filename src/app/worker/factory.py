"""Worker factory used by the console entrypoint."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from src.adapters.connectors.github import GitHubAppAuth, GitHubClient
from src.core.contracts import CIFeedbackContext, PREvent
from src.runtime.agent import AgentRuntimeHealthResult, AgentRuntimeHealthStatus, check_agent_runtime_health
from src.runtime.orchestrator import (
    CIWorkflowOrchestrator,
    EventOrchestrator,
    InMemoryPRAggregateStore,
    PRCheckSnapshotProvider,
    PRWorkflowOrchestrator,
    ToolRuntimeCIContextProvider,
    ToolRuntimePRCheckSnapshotProvider,
    ToolRuntimePRCommentPoster,
    ToolRuntimePRContextProvider,
)
from src.runtime.stages import WorkflowStage
from src.runtime.tools import RegisteredToolRuntime, StageToolPolicy
from src.runtime.tools.github import build_github_pr_tools
from src.shared.config import AppConfig

from .runner import Worker


class AgentRuntimeUnavailableError(RuntimeError):
    """Raised when worker bootstrap rejects Agent Runtime configuration."""


def check_worker_agent_runtime_health(
    cfg: AppConfig,
    *,
    environ: Mapping[str, str] | None = None,
    opt_in_live_smoke: bool = False,
) -> AgentRuntimeHealthResult:
    """Validate worker Agent Runtime readiness before validation stages use it."""

    health = check_agent_runtime_health(
        cfg.agent_runtime,
        environ=environ,
        opt_in_live_smoke=opt_in_live_smoke,
    )
    if health.status is AgentRuntimeHealthStatus.UNSUPPORTED:
        detail = "; ".join(health.actionable_errors)
        raise AgentRuntimeUnavailableError(f"Agent Runtime configuration is unsupported: {detail}")
    return health


def build_worker(cfg: AppConfig) -> Worker:
    """Build a worker with the appropriate output poster for the queue mode.

    In-memory mode remains side-effect free for local smoke runs. Durable queue
    modes must be wired to GitHub before jobs are acknowledged; otherwise a
    worker could silently consume Redis jobs without publishing review output.
    """
    if cfg.queue_backend == "memory":
        return Worker()

    client = _build_github_client(cfg)
    tool_runtime = _build_github_tool_runtime(client)
    pr_aggregate_store = InMemoryPRAggregateStore()
    return Worker(
        orchestrator=EventOrchestrator(
            pr_orchestrator=PRWorkflowOrchestrator(
                context_provider=ToolRuntimePRContextProvider(tool_runtime),
                ci_feedback_provider=lambda event: _load_ci_feedback_for_pr_event(
                    event=event,
                    aggregate_store=pr_aggregate_store,
                    check_provider=ToolRuntimePRCheckSnapshotProvider(tool_runtime),
                ),
            ),
            ci_orchestrator=CIWorkflowOrchestrator(
                context_provider=ToolRuntimeCIContextProvider(tool_runtime),
                aggregate_store=pr_aggregate_store,
            ),
        ),
        output_poster=ToolRuntimePRCommentPoster(tool_runtime),
    )


def _load_ci_feedback_for_pr_event(
    *,
    event: PREvent,
    aggregate_store: InMemoryPRAggregateStore,
    check_provider: PRCheckSnapshotProvider,
) -> CIFeedbackContext:
    """Update PR aggregate and export current-head CI/check feedback.

    This is Step 4 wiring for strategy input only. The in-memory aggregate store
    is a temporary durable-worker seam; later persistence can replace it without
    changing the Strategy Engine CI feedback contract.
    """
    aggregate = aggregate_store.apply_pr_event(event)
    checks = check_provider.load(
        repo_full_name=event.repo_full_name,
        head_sha=aggregate.current_head_sha,
        correlation_id=event.meta.correlation_id,
    )
    readiness = aggregate.evaluate_readiness(current_check_snapshot=checks)
    return aggregate.to_ci_feedback_context(readiness=readiness, current_check_snapshot=checks)


def _build_github_tool_runtime(client: GitHubClient) -> RegisteredToolRuntime:
    return RegisteredToolRuntime(
        tools=build_github_pr_tools(client),
        policy=StageToolPolicy(
            {
                WorkflowStage.CONTEXT: (
                    "github.pr.view",
                    "github.pr.files",
                    "github.pr.diff",
                    "github.actions.run.jobs",
                    "github.checks.runs_for_ref",
                ),
                WorkflowStage.OUTPUT: ("github.pr.comment.create_or_update",),
            }
        ),
    )


def _build_github_client(cfg: AppConfig) -> GitHubClient:
    if cfg.github_app_id <= 0:
        raise ValueError("QAESTRO_GITHUB_APP_ID must be set for durable worker queues")
    if cfg.github_app_installation_id <= 0:
        raise ValueError("QAESTRO_GITHUB_APP_INSTALLATION_ID must be set for durable worker queues")
    if not cfg.github_app_private_key_path:
        raise ValueError("QAESTRO_GITHUB_APP_PRIVATE_KEY_PATH must be set for durable worker queues")

    private_key_path = Path(cfg.github_app_private_key_path)
    private_key = private_key_path.read_text(encoding="utf-8")
    auth = GitHubAppAuth(
        app_id=cfg.github_app_id,
        installation_id=cfg.github_app_installation_id,
        private_key=private_key,
    )
    return GitHubClient(auth=auth)
