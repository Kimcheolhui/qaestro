"""Worker factory used by the console entrypoint."""

from __future__ import annotations

from pathlib import Path

from src.adapters.connectors.github import GitHubAppAuth, GitHubClient
from src.app.worker.github import GitHubCommentPoster
from src.app.worker.runner import NoopCommentPoster, Worker
from src.shared.config import AppConfig


def build_worker(cfg: AppConfig) -> Worker:
    """Build a worker with the appropriate comment poster for the queue mode.

    In-memory mode remains side-effect free for local smoke runs. Durable queue
    modes must be wired to GitHub before jobs are acknowledged; otherwise a
    worker could silently consume Redis jobs without publishing review comments.
    """
    if cfg.queue_backend == "memory":
        return Worker(comment_poster=NoopCommentPoster())

    return Worker(comment_poster=GitHubCommentPoster(_build_github_client(cfg)))


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
