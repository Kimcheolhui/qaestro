"""LLM-backed PR review E2E smoke runner."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from src.adapters.connectors.github import (
    ActionsJobResult,
    CheckRunResult,
    CommentResult,
    FileDiff,
    GitHubAppAuth,
    GitHubClient,
    PRMeta,
    ReviewCommentInput,
    ReviewResult,
    UrllibTransport,
)
from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    CIFeedbackContext,
    CIObservation,
    CIReadinessState,
    EventMeta,
    EventSource,
    EventType,
    PREvent,
    PROpened,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)
from src.runtime.agent import AzureOpenAIChatClient, build_agent_runner
from src.runtime.agent.types import AgentRunInput, AgentRunner, AgentRunResult, AgentSessionHandle, AgentSessionScope
from src.runtime.orchestrator import (
    InMemoryPRAggregateStore,
    PRWorkflowDepth,
    PRWorkflowOrchestrator,
    PRWorkflowTriage,
    ToolRuntimePRContextProvider,
    ToolRuntimePROutputPoster,
)
from src.runtime.stages import WorkflowStage
from src.runtime.tools import RegisteredToolRuntime, StageToolPolicy, ToolAuditEntry, ToolCall, ToolResult
from src.runtime.tools.github import build_github_pr_tools
from src.shared.config import AgentRuntimeProvider, AppConfig


@dataclass(frozen=True)
class LLMPRE2ESmokeResult:
    """Result summary for the live-provider PR review E2E smoke."""

    status: str
    repo_full_name: str = ""
    pr_number: int = 0
    head_sha: str = ""
    correlation_id: str = ""
    comment_url: str = ""
    review_url: str = ""
    inline_comment_submitted: bool = False
    provider_output_marker: str = ""
    provider_request_count: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


class SmokeGitHubAuth:
    """Static-token auth shim for manual smoke runs.

    This is intentionally not used by production worker construction. It lets the
    smoke exercise the same GitHubClient/ToolRuntime boundaries with a temporary
    token when GitHub App key material is unavailable in a local or VM
    verification environment.
    """

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("GitHub token must not be empty")
        self._token = token

    def installation_token(self) -> str:
        return self._token


@dataclass(frozen=True)
class _OutputEvidence:
    comment_url: str = ""
    review_url: str = ""


class _SmokeRuntime:
    def __init__(self, runtime: RegisteredToolRuntime) -> None:
        self._runtime = runtime
        self.comment_url = ""
        self.review_url = ""
        self.review_comment_url = ""

    @property
    def audit_log(self) -> tuple[ToolAuditEntry, ...]:
        return self._runtime.audit_log

    def execute(self, call: ToolCall) -> ToolResult:
        result = self._runtime.execute(call)
        if result.ok:
            if isinstance(result.output, CommentResult):
                self.comment_url = result.output.html_url
            elif isinstance(result.output, ReviewResult):
                self.review_url = result.output.html_url
        return result

    def output_evidence(self) -> _OutputEvidence:
        return _OutputEvidence(
            comment_url=self.comment_url,
            review_url=self.review_url,
        )


class _SmokeReviewClient:
    def __init__(self, delegate: GitHubClient) -> None:
        self._delegate = delegate
        self.inline_comment_submitted = False

    def get_pull_request(self, owner: str, repo: str, number: int) -> PRMeta:
        return self._delegate.get_pull_request(owner, repo, number)

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[FileDiff]:
        return self._delegate.list_pull_request_files(owner, repo, number)

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        return self._delegate.get_pull_request_diff(owner, repo, number)

    def list_workflow_run_jobs(self, owner: str, repo: str, run_id: int) -> list[ActionsJobResult]:
        return self._delegate.list_workflow_run_jobs(owner, repo, run_id)

    def list_check_runs_for_ref(self, owner: str, repo: str, ref: str) -> list[CheckRunResult]:
        return self._delegate.list_check_runs_for_ref(owner, repo, ref)

    def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> CommentResult:
        return self._delegate.create_issue_comment(owner, repo, number, body)

    def list_issue_comments(self, owner: str, repo: str, number: int) -> list[CommentResult]:
        return self._delegate.list_issue_comments(owner, repo, number)

    def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> CommentResult:
        return self._delegate.update_issue_comment(owner, repo, comment_id, body)

    def list_pull_request_reviews(self, owner: str, repo: str, number: int) -> list[ReviewResult]:
        return self._delegate.list_pull_request_reviews(owner, repo, number)

    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        body: str,
        commit_id: str,
        event: str = "COMMENT",
        comments: tuple[ReviewCommentInput, ...] = (),
    ) -> ReviewResult:
        result = self._delegate.create_pull_request_review(
            owner, repo, number, body=body, commit_id=commit_id, event=event, comments=comments
        )
        self.inline_comment_submitted = bool(comments)
        return result


class _SmokeStrategyEngine:
    def plan(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        title: str,
        impact: BehaviourImpact,
        ci_feedback: CIFeedbackContext | None = None,
    ) -> StrategyResult:
        _ = (repo_full_name, pr_number, title, impact, ci_feedback)
        return StrategyResult(
            actions=(
                StrategyAction(
                    action_type=ActionType.VERIFY_API_CONTRACT,
                    description="Run live-provider E2E smoke validation marker",
                    target="GET /qaestro-llm-pr-review-e2e-smoke",
                    priority=5,
                    rationale="The Step 6 completion gate must prove live LLM inference in the PR review path.",
                ),
            ),
            reasoning="Live-provider E2E smoke forces one Agent Runtime validation turn.",
            confidence=1.0,
        )


class _RecordingAgentRunner:
    def __init__(self, delegate: AgentRunner) -> None:
        self._delegate = delegate
        self.output_text = ""
        self.run_count = 0

    def start_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        return self._delegate.start_session(handle)

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        result = self._delegate.run(session=session, run_input=run_input)
        self.run_count += 1
        self.output_text = result.output_text
        return result

    def close_session(self, handle: AgentSessionHandle, *, reason: str) -> None:
        self._delegate.close_session(handle, reason=reason)


@dataclass(frozen=True)
class _LLMPRReview:
    body: str
    provider_marker: str


class _LLMPRReviewValidator:
    def __init__(
        self,
        *,
        runner: _RecordingAgentRunner,
        pr_meta: PRMeta,
        repo_full_name: str,
        pr_number: int,
        files: tuple[FileDiff, ...],
        checks: tuple[CheckRunResult, ...],
    ) -> None:
        self._runner = runner
        self._pr_meta = pr_meta
        self._repo_full_name = repo_full_name
        self._pr_number = pr_number
        self._files = files
        self._checks = checks

    def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
        return tuple(
            ValidationResult(action=action, outcome=ValidationOutcome.ERROR, details="PR event context is required.")
            for action in strategy.actions
        )

    def validate_for_event(self, *, event: PREvent, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
        review = _run_unified_llm_review(
            runner=self._runner,
            pr_meta=self._pr_meta,
            repo_full_name=self._repo_full_name,
            pr_number=self._pr_number,
            files=self._files,
            checks=self._checks,
            correlation_id=event.meta.correlation_id,
        )
        return tuple(
            ValidationResult(
                action=action,
                outcome=ValidationOutcome.PASS,
                details=f"llm_provider_inference_completed: {review.provider_marker}\n\n{review.body}",
                artifacts=("agent-runtime://live-provider-pr-review",),
            )
            for action in strategy.actions
        )


def run_llm_pr_review_e2e_smoke(
    *,
    config: AppConfig,
    repo_full_name: str,
    pr_number: int,
    correlation_id: str = "",
    github_client: GitHubClient | None = None,
    azure_openai_client: AzureOpenAIChatClient | None = None,
    environ: dict[str, str] | None = None,
    opt_in_live_smoke: bool = False,
) -> LLMPRE2ESmokeResult:
    """Run a live-provider PR review E2E smoke when explicitly opted in."""

    if not opt_in_live_smoke:
        return LLMPRE2ESmokeResult(status="not_requested", repo_full_name=repo_full_name, pr_number=pr_number)
    if config.agent_runtime.provider is not AgentRuntimeProvider.AZURE_OPENAI:
        return LLMPRE2ESmokeResult(
            status="failed",
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            error="LLM PR review E2E smoke requires QAESTRO_AGENT_PROVIDER=azure-openai",
        )
    if pr_number <= 0:
        return LLMPRE2ESmokeResult(
            status="failed",
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            error="pr_number must be a positive integer",
        )

    env = os.environ if environ is None else environ
    correlation = correlation_id or f"qaestro-llm-pr-review-e2e-{int(datetime.now(tz=UTC).timestamp())}"

    try:
        client = github_client or _build_smoke_github_client(config=config, environ=env)
        owner, repo = _split_repo(repo_full_name)
        pr_meta = client.get_pull_request(owner, repo, pr_number)
        runner = _RecordingAgentRunner(
            build_agent_runner(config.agent_runtime, environ=env, azure_openai_client=azure_openai_client)
        )
        files = client.list_pull_request_files(owner, repo, pr_number)
        checks = client.list_check_runs_for_ref(owner, repo, pr_meta.head_sha)
        review_client = _SmokeReviewClient(client)
        smoke_runtime = _SmokeRuntime(_build_smoke_tool_runtime(review_client))
        aggregate_store = InMemoryPRAggregateStore()

        def ci_feedback(event: PREvent) -> CIFeedbackContext:
            aggregate = aggregate_store.apply_pr_event(event)
            return _ci_feedback_from_checks(head_sha=event.head_sha, checks=tuple(checks), aggregate=aggregate)

        event = PROpened(
            meta=EventMeta(
                event_id=correlation,
                event_type=EventType.PR_OPENED,
                correlation_id=correlation,
                timestamp=datetime.now(tz=UTC),
                source=EventSource.REPLAY,
            ),
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            title=pr_meta.title,
            body=pr_meta.body,
            author=pr_meta.author,
            base_branch=pr_meta.base_ref,
            head_branch=pr_meta.head_ref,
            diff_url=f"https://github.com/{repo_full_name}/pull/{pr_number}.diff",
            head_sha=pr_meta.head_sha,
        )
        result = PRWorkflowOrchestrator(
            context_provider=ToolRuntimePRContextProvider(smoke_runtime),
            triage_classifier=lambda _context: PRWorkflowTriage(
                depth=PRWorkflowDepth.NORMAL,
                rationale="Live-provider E2E smoke forces the full unified PR review path.",
                allowed_stages=(WorkflowStage.ANALYZER, WorkflowStage.STRATEGY, WorkflowStage.VALIDATOR),
            ),
            strategy_engine=_SmokeStrategyEngine(),
            validator=_LLMPRReviewValidator(
                runner=runner,
                pr_meta=pr_meta,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                files=tuple(files),
                checks=tuple(checks),
            ),
            ci_feedback_provider=ci_feedback,
        ).run(event)
        if result.comment_payload is None:
            return LLMPRE2ESmokeResult(
                status="failed",
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=pr_meta.head_sha,
                correlation_id=correlation,
                error="PR workflow did not produce a comment payload",
            )
        ToolRuntimePROutputPoster(smoke_runtime).post_outputs(
            result.comment_payload,
            review_payload=result.review_payload,
            correlation_id=correlation,
        )
        output = smoke_runtime.output_evidence()
        return LLMPRE2ESmokeResult(
            status="succeeded",
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=pr_meta.head_sha,
            correlation_id=correlation,
            comment_url=output.comment_url,
            review_url=output.review_url,
            inline_comment_submitted=review_client.inline_comment_submitted,
            provider_output_marker=_provider_output_marker(runner=runner, result=result),
            provider_request_count=runner.run_count,
        )
    except Exception as exc:
        return LLMPRE2ESmokeResult(
            status="failed",
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            correlation_id=correlation,
            error=type(exc).__name__,
        )


def _run_unified_llm_review(
    *,
    runner: _RecordingAgentRunner,
    pr_meta: PRMeta,
    repo_full_name: str,
    pr_number: int,
    files: tuple[FileDiff, ...],
    checks: tuple[CheckRunResult, ...],
    correlation_id: str,
) -> _LLMPRReview:
    session = AgentSessionHandle(
        session_id=f"llm-pr-review-smoke-{correlation_id}",
        scope=AgentSessionScope.STAGE,
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        head_sha=pr_meta.head_sha,
        trigger="llm-pr-review-e2e-smoke",
        correlation_id=correlation_id,
    )
    started = runner.start_session(session)
    try:
        result = runner.run(
            session=started,
            run_input=AgentRunInput(
                stage=WorkflowStage.VALIDATOR,
                prompt=_unified_review_prompt(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    pr_meta=pr_meta,
                    files=files,
                    checks=checks,
                ),
                correlation_id=correlation_id,
                max_turns=1,
                max_tool_calls=0,
            ),
        )
    finally:
        runner.close_session(started, reason="llm PR review smoke complete")
    if not result.ok or not result.output_text.strip():
        raise RuntimeError("live LLM PR review did not produce review text")
    return _LLMPRReview(
        body=_render_llm_review_body(result.output_text),
        provider_marker="qaestro-live-provider-output-present",
    )


def _ci_feedback_from_checks(
    *,
    head_sha: str,
    checks: tuple[CheckRunResult, ...],
    aggregate: object,
) -> CIFeedbackContext:
    observations = tuple(
        CIObservation(
            workflow_name=check.name,
            conclusion=check.conclusion or check.status,
            run_url=check.html_url,
            commit_sha=check.head_sha,
        )
        for check in checks
        if check.head_sha == head_sha and check.status == "completed"
    )
    pending = tuple(check.name for check in checks if check.head_sha == head_sha and check.status != "completed")
    failed = any((check.conclusion or "").lower() in {"failure", "timed_out", "startup_failure"} for check in checks)
    readiness = (
        CIReadinessState.WAITING_FOR_CHECKS
        if pending
        else CIReadinessState.CHECKS_FAILED
        if failed
        else CIReadinessState.READY
    )
    historical = getattr(
        aggregate,
        "to_ci_feedback_context",
        lambda **_: CIFeedbackContext(current_head_sha=head_sha, readiness=readiness),
    )(
        readiness=getattr(aggregate, "evaluate_readiness", lambda **_: object)(current_check_snapshot=()),
        current_check_snapshot=(),
    ).historical_evidence
    return CIFeedbackContext(
        current_head_sha=head_sha,
        readiness=readiness,
        current_observations=observations,
        historical_evidence=historical,
        pending_checks=pending,
    )


def _build_smoke_tool_runtime(client: _SmokeReviewClient) -> RegisteredToolRuntime:
    return RegisteredToolRuntime(
        tools=build_github_pr_tools(client),
        policy=StageToolPolicy(
            {
                WorkflowStage.CONTEXT: (
                    "github.pr.view",
                    "github.pr.files",
                    "github.pr.diff",
                ),
                WorkflowStage.OUTPUT: (
                    "github.pr.view",
                    "github.pr.comment.create_or_update",
                    "github.pr.review.list",
                    "github.pr.review.create",
                ),
            }
        ),
    )


def _unified_review_prompt(
    *,
    repo_full_name: str,
    pr_number: int,
    pr_meta: PRMeta,
    files: tuple[FileDiff, ...],
    checks: tuple[CheckRunResult, ...],
) -> str:
    return "\n".join(
        (
            "You are qaestro reviewing a GitHub pull request from a QA perspective.",
            "Use the unified PR context below: PR description, changed files/diff summary, and CI/check feedback.",
            "Return a concise review that can be posted directly as a PR comment/review. Do not mention secrets.",
            "",
            f"Repository: {repo_full_name}",
            f"Pull request: #{pr_number}",
            f"Title: {pr_meta.title}",
            "",
            "PR description:",
            _bounded_text(pr_meta.body or "(empty)", limit=2000),
            "",
            "Changed files:",
            *_file_context_lines(files),
            "",
            "CI/check feedback:",
            *_check_context_lines(checks),
        )
    )


def _file_context_lines(files: tuple[FileDiff, ...]) -> tuple[str, ...]:
    if not files:
        return ("- No changed files returned by GitHub.",)
    return tuple(
        f"- {file.filename} ({file.status}, +{file.additions}/-{file.deletions})\n{_bounded_text(file.patch or '(patch unavailable)', limit=1200)}"
        for file in files[:10]
    )


def _check_context_lines(checks: tuple[CheckRunResult, ...]) -> tuple[str, ...]:
    if not checks:
        return ("- No check runs returned for the current head.",)
    return tuple(f"- {check.name}: {check.status}/{check.conclusion or 'pending'}" for check in checks[:20])


def _render_llm_review_body(output_text: str) -> str:
    return "\n".join(("## LLM PR Review", "", output_text.strip()))


def _bounded_text(value: str, *, limit: int) -> str:
    clean = value.strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit].rstrip()}\n... [truncated]"


def _build_smoke_github_client(*, config: AppConfig, environ: os._Environ[str] | dict[str, str]) -> GitHubClient:
    token = environ.get("QAESTRO_SMOKE_GITHUB_TOKEN")
    if token:
        return GitHubClient(auth=cast(GitHubAppAuth, SmokeGitHubAuth(token)), transport=UrllibTransport())
    if config.github_app_id <= 0 or config.github_app_installation_id <= 0 or not config.github_app_private_key_path:
        raise ValueError("GitHub App config or QAESTRO_SMOKE_GITHUB_TOKEN is required for live E2E smoke")
    private_key = Path(config.github_app_private_key_path).read_text(encoding="utf-8")
    return GitHubClient(
        auth=GitHubAppAuth(
            app_id=config.github_app_id,
            installation_id=config.github_app_installation_id,
            private_key=private_key,
        ),
        transport=UrllibTransport(),
    )


def _split_repo(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/", maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("repo_full_name must be 'owner/repo'")
    return parts[0], parts[1]


def _provider_output_marker(*, runner: _RecordingAgentRunner, result: object) -> str:
    if runner.output_text:
        return "qaestro-live-provider-output-present"
    return _provider_output_from_result(result)


def _provider_output_from_result(result: object) -> str:
    validations = getattr(result, "validations", ())
    for validation in validations:
        if isinstance(validation, ValidationResult) and validation.details:
            return validation.details
    return ""
