"""Worker factory used by the console entrypoint."""

from __future__ import annotations

from pathlib import Path

from src.adapters.connectors.github import GitHubAppAuth, GitHubClient
from src.runtime.orchestrator import (
    CIWorkflowOrchestrator,
    EventOrchestrator,
    PRWorkflowOrchestrator,
    ToolRuntimeCIContextProvider,
    ToolRuntimePRCommentPoster,
    ToolRuntimePRContextProvider,
)
from src.runtime.stages import WorkflowStage
from src.runtime.tools import RegisteredToolRuntime, StageToolPolicy
from src.runtime.tools.github import build_github_pr_tools
from src.shared.config import AppConfig

from .runner import Worker


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
    return Worker(
        orchestrator=EventOrchestrator(
            pr_orchestrator=PRWorkflowOrchestrator(context_provider=ToolRuntimePRContextProvider(tool_runtime)),
            ci_orchestrator=CIWorkflowOrchestrator(context_provider=ToolRuntimeCIContextProvider(tool_runtime)),
        ),
        output_poster=ToolRuntimePRCommentPoster(tool_runtime),
    )


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
