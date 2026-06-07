"""Agent Runtime-backed PR validation wiring."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from src.core.contracts import (
    ActionType,
    PREvent,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
    ValidationResult,
)
from src.runtime.agent.manager import WorkflowAgentSessionManager
from src.runtime.agent.types import AgentRunInput, AgentRunner, AgentRunStatus, AgentSessionHandle
from src.runtime.prompts import PromptId, render_prompt
from src.runtime.stages import WorkflowStage
from src.runtime.tools import (
    AgentFrameworkToolAdapter,
    AgentFrameworkToolSpec,
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCall,
    ToolCapability,
    ToolDefinition,
)
from src.shared.redaction import redact_text, redact_value

_VALIDATION_API_CONTRACT_PROBE = "validation.api_contract.probe"
_SUPPORTED_API_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_AUTO_RUN_API_METHODS = ("GET", "HEAD", "OPTIONS")
_DENIED_PROBE_CAPABILITIES = frozenset({ToolCapability.WRITE, ToolCapability.DESTRUCTIVE})


@dataclass(frozen=True)
class RuntimeValidationBudget:
    """Bounded execution budget for one validation-stage agent turn."""

    max_turns: int = 2
    max_tool_calls: int = 1
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")


@dataclass(frozen=True)
class APIContractProbeRequest:
    """Deterministic request handed to an API contract probe executor."""

    action: StrategyAction
    target: str
    method: str
    path: str
    repo_full_name: str
    pr_number: int
    head_sha: str
    correlation_id: str
    timeout_seconds: float


@dataclass(frozen=True)
class APIContractProbeResult:
    """Normalized API contract probe result mapped into ValidationResult."""

    outcome: ValidationOutcome
    details: str
    duration_seconds: float = 0.0
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be >= 0")


class APIContractProbeExecutor(Protocol):
    """Pluggable API contract probe executor.

    Implementations must be deterministic and non-destructive by default. The
    default MVP executor intentionally skips live external API calls; tests and
    later adapters can inject fake or opt-in live executors behind this seam.
    Executor-provided ``APIContractProbeResult.details`` may be rendered into PR
    comments, so live executors must return sanitized details and put sensitive
    raw evidence behind redacted artifact handles instead.
    """

    def execute(self, request: APIContractProbeRequest) -> APIContractProbeResult: ...


class SkippingAPIContractProbeExecutor:
    """Default non-live API contract probe executor.

    This is a real executor seam, not the final probe implementation: it returns
    an explicit SKIPPED result so the PR report shows unsupported execution
    instead of silently passing. Concrete fake/pluggable executors can be injected
    by tests, smoke scripts, or later provider/probe hardening work.
    """

    def execute(self, request: APIContractProbeRequest) -> APIContractProbeResult:
        return APIContractProbeResult(
            outcome=ValidationOutcome.SKIPPED,
            details=(
                f"api_contract_probe_skipped: no non-live executor configured for {request.method} {request.path}."
            ),
        )


class AgentRuntimePRValidator:
    """Run PR validation actions through the provider-neutral Agent Runtime.

    The validator keeps the Step 5 runner/session/tool boundary and now maps the
    API-contract strategy action into a deterministic pluggable probe executor.
    Live external API calls are intentionally not performed by default: callers
    must inject an executor when they want concrete probe semantics.
    """

    def __init__(
        self,
        *,
        session_manager: WorkflowAgentSessionManager,
        tool_adapter: AgentFrameworkToolAdapter,
        api_contract_probe_executor: APIContractProbeExecutor | None = None,
        budget: RuntimeValidationBudget | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._tool_adapter = tool_adapter
        self._api_contract_probe_executor = api_contract_probe_executor or SkippingAPIContractProbeExecutor()
        self._budget = budget or RuntimeValidationBudget()

    def validate(self, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
        """Fail closed when called without PR event context."""
        return tuple(
            ValidationResult(
                action=action,
                outcome=ValidationOutcome.ERROR,
                details="PR event context is required before Agent Runtime validation can run.",
            )
            for action in strategy.actions
        )

    def validate_for_event(self, *, event: PREvent, strategy: StrategyResult) -> tuple[ValidationResult, ...]:
        """Run validation for one PR event without storing mutable event state."""
        if not _has_complete_pr_event_context(event):
            return tuple(
                ValidationResult(
                    action=action,
                    outcome=ValidationOutcome.ERROR,
                    details="complete PR event context is required before API contract probes can run.",
                )
                for action in strategy.actions
            )

        session = self._session_manager.start_workflow_session(
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            head_sha=event.head_sha,
            trigger=event.meta.event_type.value,
            correlation_id=event.meta.correlation_id,
        )
        try:
            return tuple(
                self._run_action(event=event, action=action, session_handle=session.handle)
                for action in strategy.actions
            )
        finally:
            self._session_manager.close_pr_sessions(
                repo_full_name=event.repo_full_name,
                pr_number=event.pr_number,
                reason="validation stage complete",
            )

    def _run_action(
        self,
        *,
        event: PREvent,
        action: StrategyAction,
        session_handle: AgentSessionHandle,
    ) -> ValidationResult:
        if action.action_type is not ActionType.VERIFY_API_CONTRACT:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details=f"unsupported validation action: {action.action_type.value}",
            )

        probe_request = _api_contract_probe_request(
            event=event,
            action=action,
            timeout_seconds=self._budget.timeout_seconds,
        )
        if probe_request is None:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details=f"invalid_target: API contract target must be '<METHOD> /path'; got {action.target!r}.",
            )

        target_policy_denial = _api_contract_target_policy_denial(probe_request)
        if target_policy_denial:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details=target_policy_denial,
            )

        allowed_tool_exposure = self._tool_adapter.tool_exposure_for_stage(WorkflowStage.VALIDATOR)
        probe_exposure = _find_tool_exposure(allowed_tool_exposure, _VALIDATION_API_CONTRACT_PROBE)
        if probe_exposure is None:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.ERROR,
                details=f"{_VALIDATION_API_CONTRACT_PROBE} is not allowed during validator stage.",
            )
        probe_spec, probe_denial_reason = probe_exposure
        probe_policy_denial = _probe_definition_policy_denial(probe_spec, probe_denial_reason)
        if probe_policy_denial:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details=probe_policy_denial,
            )

        run_result = self._run_agent_selection(event=event, action=action, session_handle=session_handle)
        if run_result is not None:
            return run_result

        return self._run_api_contract_probe(action=action, request=probe_request)

    def _run_agent_selection(
        self,
        *,
        event: PREvent,
        action: StrategyAction,
        session_handle: AgentSessionHandle,
    ) -> ValidationResult | None:
        run_input = AgentRunInput(
            stage=WorkflowStage.VALIDATOR,
            prompt=_validation_prompt(action),
            correlation_id=event.meta.correlation_id,
            allowed_tools=self._tool_adapter.tool_specs_for_stage(WorkflowStage.VALIDATOR),
            context={
                "repo_full_name": event.repo_full_name,
                "pr_number": event.pr_number,
                "head_sha": event.head_sha,
                "action_type": action.action_type.value,
                "target": action.target,
            },
            max_turns=self._budget.max_turns,
            max_tool_calls=self._budget.max_tool_calls,
            timeout_seconds=self._budget.timeout_seconds,
        )
        try:
            result = self._session_manager.run_stage(session_handle, run_input)
        except Exception as exc:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.ERROR,
                details=_agent_runner_error_details(kind="agent_runner_exception", exc=exc),
            )

        if result.status is AgentRunStatus.SUCCEEDED:
            return None
        return ValidationResult(
            action=action,
            outcome=ValidationOutcome.ERROR,
            details=_agent_runner_status_details(result.status),
        )

    def _run_api_contract_probe(self, *, action: StrategyAction, request: APIContractProbeRequest) -> ValidationResult:
        start = monotonic()
        try:
            result = self._api_contract_probe_executor.execute(request)
        except TimeoutError as exc:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.ERROR,
                details=_probe_error_details(kind="timeout", exc=exc),
                duration_seconds=monotonic() - start,
            )
        except Exception as exc:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.ERROR,
                details=_probe_error_details(kind="exception", exc=exc),
                duration_seconds=monotonic() - start,
            )

        elapsed = monotonic() - start
        return ValidationResult(
            action=action,
            outcome=result.outcome,
            details=_sanitize_pr_facing_details(result.details),
            duration_seconds=result.duration_seconds or elapsed,
            artifacts=_sanitize_pr_facing_artifacts(result.artifacts),
        )


def build_agent_runtime_pr_validator(
    *,
    runner: AgentRunner,
    api_contract_probe_executor: APIContractProbeExecutor | None = None,
) -> AgentRuntimePRValidator:
    """Build the default provider-neutral validation runner wiring."""
    return AgentRuntimePRValidator(
        session_manager=WorkflowAgentSessionManager(runner=runner),
        tool_adapter=build_default_validation_tool_adapter(),
        api_contract_probe_executor=api_contract_probe_executor,
    )


def build_default_validation_tool_adapter() -> AgentFrameworkToolAdapter:
    """Expose validation-stage tool specs through the ToolRuntime seam.

    The API contract probe handler is deliberately non-live. It provides the
    policy-gated Agent Framework-facing tool shape while concrete probe verdicts
    are executed through the pluggable executor seam in ``AgentRuntimePRValidator``.
    """
    validation_tool = ToolDefinition(
        name=_VALIDATION_API_CONTRACT_PROBE,
        capabilities=(ToolCapability.EXECUTE,),
        description="Run a deterministic API contract probe",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "method": {"type": "string"},
                "path": {"type": "string"},
            },
        },
        handler=_api_contract_probe_not_configured,
    )
    policy = StageToolPolicy({WorkflowStage.VALIDATOR: (_VALIDATION_API_CONTRACT_PROBE,)})
    runtime = RegisteredToolRuntime(tools=(validation_tool,), policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=(validation_tool,), policy=policy)


def _api_contract_probe_not_configured(call: ToolCall) -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": "api_contract_probe_executor_not_configured",
        "target": call.input.get("target", ""),
    }


def _has_complete_pr_event_context(event: PREvent) -> bool:
    return bool(
        event.repo_full_name.strip()
        and event.pr_number > 0
        and event.head_sha.strip()
        and event.meta.correlation_id.strip()
    )


def _find_tool_exposure(
    exposures: tuple[tuple[AgentFrameworkToolSpec, str], ...], name: str
) -> tuple[AgentFrameworkToolSpec, str] | None:
    return next((exposure for exposure in exposures if exposure[0].name == name), None)


def _api_contract_target_policy_denial(request: APIContractProbeRequest) -> str:
    if request.method in _AUTO_RUN_API_METHODS:
        return ""
    allowed = ", ".join(_AUTO_RUN_API_METHODS)
    return (
        "needs_approval: write-like API contract probe is not auto-run in Step 6 MVP; "
        f"method {request.method} for {request.path} requires explicit approval or a later safe executor policy. "
        f"Auto-run methods: {allowed}."
    )


def _probe_definition_policy_denial(spec: AgentFrameworkToolSpec, policy_denial_reason: str) -> str:
    if policy_denial_reason:
        return f"policy_denied: {policy_denial_reason}."
    denied = sorted(capability.value for capability in spec.capabilities if capability in _DENIED_PROBE_CAPABILITIES)
    if not denied:
        return ""
    return (
        "policy_denied: validation probe definition includes "
        f"{', '.join(denied)} capability; Step 6 MVP only auto-runs read-only execution probes."
    )


def _probe_error_details(*, kind: str, exc: Exception) -> str:
    # Do not copy raw executor exception messages into externally rendered PR
    # comments. Future live executors may include response bodies, tokens, or
    # endpoint details in exception strings.
    return f"{kind}: {type(exc).__name__} raised by API contract probe executor."


def _agent_runner_error_details(*, kind: str, exc: Exception) -> str:
    # Keep provider/transport exception strings out of rendered validation
    # details. They may include endpoints, token fragments, or credential hints.
    return f"{kind}: {type(exc).__name__} raised during Agent Runtime validation."


def _agent_runner_status_details(status: AgentRunStatus) -> str:
    return f"agent_runner: Agent Runtime validation ended with status {status.name}."


def _sanitize_pr_facing_details(details: str) -> str:
    """Remove credential and endpoint fragments from PR-facing details."""
    return redact_text(details, redact_urls=True)


def _sanitize_pr_facing_artifacts(artifacts: tuple[str, ...]) -> tuple[str, ...]:
    redacted = redact_value(artifacts, redact_urls=True)
    if not isinstance(redacted, tuple):
        return ()
    return tuple(str(item) for item in redacted)


def _api_contract_probe_request(
    *,
    event: PREvent,
    action: StrategyAction,
    timeout_seconds: float,
) -> APIContractProbeRequest | None:
    parsed = _parse_api_contract_target(action.target)
    if parsed is None:
        return None
    method, path = parsed
    return APIContractProbeRequest(
        action=action,
        target=action.target,
        method=method,
        path=path,
        repo_full_name=event.repo_full_name,
        pr_number=event.pr_number,
        head_sha=event.head_sha,
        correlation_id=event.meta.correlation_id,
        timeout_seconds=timeout_seconds,
    )


def _parse_api_contract_target(target: str) -> tuple[str, str] | None:
    parts = target.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    method, path = parts[0].upper(), parts[1].strip()
    if method not in _SUPPORTED_API_METHODS:
        return None
    if not path.startswith("/"):
        return None
    return method, path


def _validation_prompt(action: StrategyAction) -> str:
    return render_prompt(
        PromptId.VALIDATION_API_CONTRACT_PROBE_SELECTION,
        action_type=action.action_type.value,
        target=action.target,
        description=action.description,
        rationale=action.rationale,
    )
