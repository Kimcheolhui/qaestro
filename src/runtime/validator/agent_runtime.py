"""Agent Runtime-backed PR validation wiring."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.contracts import PREvent, StrategyAction, StrategyResult, ValidationOutcome, ValidationResult
from src.runtime.agent.manager import WorkflowAgentSessionManager
from src.runtime.agent.types import AgentRunInput, AgentRunner, AgentRunStatus, AgentSessionHandle
from src.runtime.stages import WorkflowStage
from src.runtime.tools import (
    AgentFrameworkToolAdapter,
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCall,
    ToolCapability,
    ToolDefinition,
)

_VALIDATION_API_CONTRACT_PROBE = "validation.api_contract.probe"


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


class AgentRuntimePRValidator:
    """Run PR validation actions through the provider-neutral Agent Runtime.

    This is the first Step 6 wiring slice: it connects selected strategy actions
    to the existing workflow-scoped ``WorkflowAgentSessionManager`` and passes
    only validation-stage tool specs exposed by ``AgentFrameworkToolAdapter``.

    The concrete API-contract probe verdict is intentionally not implemented in
    this class yet. A successful agent turn proves the runner/session/tool seam
    executed, but it is reported as ``SKIPPED`` until #62 adds deterministic probe
    verdict parsing/execution so callers do not mistake runner completion for a
    real validation pass.
    """

    def __init__(
        self,
        *,
        session_manager: WorkflowAgentSessionManager,
        tool_adapter: AgentFrameworkToolAdapter,
        budget: RuntimeValidationBudget | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._tool_adapter = tool_adapter
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
            return ValidationResult(action=action, outcome=ValidationOutcome.ERROR, details=str(exc))

        if result.status is AgentRunStatus.SUCCEEDED:
            return ValidationResult(
                action=action,
                outcome=ValidationOutcome.SKIPPED,
                details="Agent Runtime validation runner completed; concrete probe verdict is deferred to #62.",
            )
        return ValidationResult(
            action=action,
            outcome=ValidationOutcome.ERROR,
            details=result.error or f"Agent Runtime validation ended with status {result.status.value}.",
        )


def build_agent_runtime_pr_validator(*, runner: AgentRunner) -> AgentRuntimePRValidator:
    """Build the default provider-neutral validation runner wiring."""
    return AgentRuntimePRValidator(
        session_manager=WorkflowAgentSessionManager(runner=runner),
        tool_adapter=build_default_validation_tool_adapter(),
    )


def build_default_validation_tool_adapter() -> AgentFrameworkToolAdapter:
    """Expose validation-stage tool specs through the ToolRuntime seam.

    The API contract probe handler is a deliberate placeholder for #62. It is
    policy-gated and auditable, but returns an explicit skipped marker rather
    than pretending to perform a live API contract check.
    """
    validation_tool = ToolDefinition(
        name=_VALIDATION_API_CONTRACT_PROBE,
        capabilities=(ToolCapability.EXECUTE,),
        description="Run a deterministic API contract probe",
        input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
        handler=_api_contract_probe_not_implemented,
    )
    policy = StageToolPolicy({WorkflowStage.VALIDATOR: (_VALIDATION_API_CONTRACT_PROBE,)})
    runtime = RegisteredToolRuntime(tools=(validation_tool,), policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=(validation_tool,), policy=policy)


def _api_contract_probe_not_implemented(call: ToolCall) -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": "api_contract_probe_not_implemented",
        "target": call.input.get("target", ""),
    }


def _validation_prompt(action: StrategyAction) -> str:
    return (
        "Run the validation action through qaestro's validation-stage tools only.\n"
        "If the concrete probe tool reports that its implementation is not ready, report it as skipped.\n"
        f"Action type: {action.action_type.value}\n"
        f"Target: {action.target}\n"
        f"Description: {action.description}\n"
        f"Rationale: {action.rationale}"
    )
