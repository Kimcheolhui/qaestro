"""Tests for deterministic API contract probe validation."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.contracts import (
    ActionType,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    PROpened,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
)
from src.runtime.agent.fake import FakeAgentRunner
from src.runtime.agent.types import AgentRunInput, AgentRunResult, AgentRunStatus, AgentSessionHandle
from src.runtime.stages import WorkflowStage
from src.runtime.tools import (
    AgentFrameworkToolAdapter,
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCapability,
    ToolDefinition,
)
from src.runtime.validator import (
    APIContractProbeRequest,
    APIContractProbeResult,
    build_agent_runtime_pr_validator,
)


def _event_meta(event_id: str, event_type: EventType, correlation_id: str) -> EventMeta:
    return EventMeta(
        event_id=event_id,
        event_type=event_type,
        correlation_id=correlation_id,
        timestamp=datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


def _pr_opened_event(*, pr_number: int = 62, correlation_id: str = "corr-api-probe") -> PROpened:
    return PROpened(
        meta=_event_meta("evt-api-probe", EventType.PR_OPENED, correlation_id),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=pr_number,
        title="feat(validator): API contract probe MVP",
        body="Adds deterministic API contract probe execution.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/api-contract-probe-mvp",
        diff_url=f"https://github.com/Kimcheolhui/qaestro/pull/{pr_number}.diff",
        files_changed=(FileChange(path="src/runtime/validator/agent_runtime.py", status="modified", additions=80),),
        head_sha=f"abc123probe-{pr_number}",
    )


def _strategy(*actions: StrategyAction) -> StrategyResult:
    return StrategyResult(actions=actions, reasoning="Probe selected by test strategy.", confidence=0.92)


def _api_contract_action(target: str = "GET /health") -> StrategyAction:
    return StrategyAction(
        action_type=ActionType.VERIFY_API_CONTRACT,
        description="Validate API contract for health endpoint",
        target=target,
        priority=3,
        rationale="API surface changed.",
    )


class RecordingProbeExecutor:
    def __init__(self, result: APIContractProbeResult | BaseException) -> None:
        self._result = result
        self.requests: list[APIContractProbeRequest] = []

    def execute(self, request: APIContractProbeRequest) -> APIContractProbeResult:
        self.requests.append(request)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class FailingAgentRunner(FakeAgentRunner):
    def __init__(self, *, error: str) -> None:
        super().__init__()
        self._error = error

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        self.run_inputs.append(run_input)
        return AgentRunResult(
            session=session,
            stage=run_input.stage,
            status=AgentRunStatus.FAILED,
            error=self._error,
            allowed_tool_names=run_input.allowed_tool_names,
        )


class RaisingAgentRunner(FakeAgentRunner):
    def __init__(self, *, error: str) -> None:
        super().__init__()
        self._error = error

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        self.run_inputs.append(run_input)
        raise RuntimeError(self._error)


class StatusAgentRunner(FakeAgentRunner):
    def __init__(self, *, status: AgentRunStatus, error: str) -> None:
        super().__init__()
        self._status = status
        self._error = error

    def run(self, *, session: AgentSessionHandle, run_input: AgentRunInput) -> AgentRunResult:
        self.run_inputs.append(run_input)
        return AgentRunResult(
            session=session,
            stage=run_input.stage,
            status=self._status,
            error=self._error,
            allowed_tool_names=run_input.allowed_tool_names,
        )


def test_agent_runner_errors_are_sanitized_before_validation_details() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    failing_runner = FailingAgentRunner(error="provider failed token=secret-token endpoint=https://private.example")
    validator = build_agent_runtime_pr_validator(runner=failing_runner, api_contract_probe_executor=executor)

    failed_result = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[
        0
    ]

    assert failed_result.outcome is ValidationOutcome.ERROR
    assert "agent_runner" in failed_result.details
    assert "FAILED" in failed_result.details
    assert "secret-token" not in failed_result.details
    assert "private.example" not in failed_result.details
    assert executor.requests == []

    raising_runner = RaisingAgentRunner(error="transport crashed password=hunter2 endpoint=https://private.example")
    validator = build_agent_runtime_pr_validator(runner=raising_runner, api_contract_probe_executor=executor)

    raised_result = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[
        0
    ]

    assert raised_result.outcome is ValidationOutcome.ERROR
    assert "agent_runner_exception" in raised_result.details
    assert "RuntimeError" in raised_result.details
    assert "hunter2" not in raised_result.details
    assert "private.example" not in raised_result.details


def test_agent_runner_timeout_and_cancelled_statuses_are_validation_errors() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    for status in (AgentRunStatus.TIMEOUT, AgentRunStatus.CANCELLED):
        runner = StatusAgentRunner(status=status, error="token=secret-token endpoint=https://private.example")
        validator = build_agent_runtime_pr_validator(runner=runner, api_contract_probe_executor=executor)

        validation = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[
            0
        ]

        assert validation.outcome is ValidationOutcome.ERROR
        assert status.name in validation.details
        assert "secret-token" not in validation.details
        assert "private.example" not in validation.details
        assert executor.requests == []


def test_validation_session_closes_after_runner_failure_and_exception() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))

    failing_runner = FailingAgentRunner(error="provider failed token=secret-token")
    failing_validator = build_agent_runtime_pr_validator(runner=failing_runner, api_contract_probe_executor=executor)
    failing_validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))

    assert failing_runner.closed_sessions == [
        (failing_runner.started_sessions[0].session_id, "validation stage complete")
    ]

    raising_runner = RaisingAgentRunner(error="transport crashed password=hunter2")
    raising_validator = build_agent_runtime_pr_validator(runner=raising_runner, api_contract_probe_executor=executor)
    raising_validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))

    assert raising_runner.closed_sessions == [
        (raising_runner.started_sessions[0].session_id, "validation stage complete")
    ]


def test_validation_session_closes_after_executor_timeout_and_exception() -> None:
    timeout_runner = FakeAgentRunner(response="agent selected validation.api_contract.probe")
    timeout_validator = build_agent_runtime_pr_validator(
        runner=timeout_runner,
        api_contract_probe_executor=RecordingProbeExecutor(TimeoutError("token=secret-token")),
    )
    timeout_validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))

    assert timeout_runner.closed_sessions == [
        (timeout_runner.started_sessions[0].session_id, "validation stage complete")
    ]

    exception_runner = FakeAgentRunner(response="agent selected validation.api_contract.probe")
    exception_validator = build_agent_runtime_pr_validator(
        runner=exception_runner,
        api_contract_probe_executor=RecordingProbeExecutor(RuntimeError("password=hunter2")),
    )
    exception_validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))

    assert exception_runner.closed_sessions == [
        (exception_runner.started_sessions[0].session_id, "validation stage complete")
    ]


def test_executor_supplied_details_are_sanitized_before_pr_facing_validation_result() -> None:
    executor = RecordingProbeExecutor(
        APIContractProbeResult(
            outcome=ValidationOutcome.FAIL,
            details="probe failed token=secret-token endpoint=https://private.example password=hunter2",
        )
    )
    validator = build_agent_runtime_pr_validator(
        runner=FakeAgentRunner(response="agent selected validation.api_contract.probe"),
        api_contract_probe_executor=executor,
    )

    validation = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[0]

    assert validation.outcome is ValidationOutcome.FAIL
    assert "probe failed" in validation.details
    assert "secret-token" not in validation.details
    assert "private.example" not in validation.details
    assert "hunter2" not in validation.details


def test_successful_probe_uses_wall_clock_duration_when_executor_duration_is_missing() -> None:
    executor = RecordingProbeExecutor(
        APIContractProbeResult(
            outcome=ValidationOutcome.PASS,
            details="probe passed but executor did not report duration",
        )
    )
    validator = build_agent_runtime_pr_validator(
        runner=FakeAgentRunner(response="agent selected validation.api_contract.probe"),
        api_contract_probe_executor=executor,
    )

    validation = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[0]

    assert validation.outcome is ValidationOutcome.PASS
    assert validation.duration_seconds > 0.0


def test_api_contract_action_executes_pluggable_probe_and_maps_pass_result() -> None:
    executor = RecordingProbeExecutor(
        APIContractProbeResult(
            outcome=ValidationOutcome.PASS,
            details="probe passed: GET /health returned 200 with expected schema",
            duration_seconds=0.42,
            artifacts=("probe://api-contract/health-pass",),
        )
    )
    fake_runner = FakeAgentRunner(response="agent selected validation.api_contract.probe")
    validator = build_agent_runtime_pr_validator(runner=fake_runner, api_contract_probe_executor=executor)
    event = _pr_opened_event()
    action = _api_contract_action()

    validations = validator.validate_for_event(event=event, strategy=_strategy(action))

    assert len(validations) == 1
    result = validations[0]
    assert result.outcome is ValidationOutcome.PASS
    assert result.details == "probe passed: GET /health returned 200 with expected schema"
    assert result.duration_seconds == 0.42
    assert result.artifacts == ("probe://api-contract/health-pass",)
    assert fake_runner.run_inputs[0].allowed_tool_names == ("validation.api_contract.probe",)
    assert len(executor.requests) == 1
    request = executor.requests[0]
    assert request.method == "GET"
    assert request.path == "/health"
    assert request.target == "GET /health"
    assert request.repo_full_name == "Kimcheolhui/qaestro"
    assert request.pr_number == 62
    assert request.head_sha == "abc123probe-62"
    assert request.correlation_id == "corr-api-probe"
    assert request.action is action


def test_unsupported_strategy_action_is_skipped_without_probe_execution() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    validator = build_agent_runtime_pr_validator(runner=FakeAgentRunner(), api_contract_probe_executor=executor)
    unsupported = StrategyAction(
        action_type=ActionType.RUN_LINTER,
        description="Run linter",
        target="src/",
        priority=1,
        rationale="Non-probe action should be handled elsewhere.",
    )

    validations = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(unsupported))

    assert validations[0].outcome is ValidationOutcome.SKIPPED
    assert "unsupported validation action" in validations[0].details
    assert "run_linter" in validations[0].details
    assert executor.requests == []


def test_invalid_api_contract_target_is_skipped_before_executor_runs() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    validator = build_agent_runtime_pr_validator(runner=FakeAgentRunner(), api_contract_probe_executor=executor)

    validations = validator.validate_for_event(
        event=_pr_opened_event(), strategy=_strategy(_api_contract_action(target="health endpoint"))
    )

    assert validations[0].outcome is ValidationOutcome.SKIPPED
    assert "invalid_target" in validations[0].details
    assert executor.requests == []


def test_write_like_api_contract_target_needs_approval_before_probe_execution() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    fake_runner = FakeAgentRunner(response="agent should not be asked to select a denied probe")
    validator = build_agent_runtime_pr_validator(runner=fake_runner, api_contract_probe_executor=executor)

    validation = validator.validate_for_event(
        event=_pr_opened_event(), strategy=_strategy(_api_contract_action(target="POST /api/users"))
    )[0]

    assert validation.outcome is ValidationOutcome.SKIPPED
    assert "needs_approval" in validation.details
    assert "write-like API contract probe" in validation.details
    assert "GET, HEAD, OPTIONS" in validation.details
    assert executor.requests == []
    assert fake_runner.run_inputs == []


def test_write_capable_validation_probe_definition_is_policy_denied_before_executor_runs() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    fake_runner = FakeAgentRunner(response="agent should not be asked to select a denied probe")
    validator = build_agent_runtime_pr_validator(runner=fake_runner, api_contract_probe_executor=executor)
    validator._tool_adapter = _write_capable_validation_tool_adapter()

    validation = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[0]

    assert validation.outcome is ValidationOutcome.SKIPPED
    assert "policy_denied" in validation.details
    assert "write capability" in validation.details
    assert executor.requests == []
    assert fake_runner.run_inputs == []


def test_probe_failures_timeouts_and_partial_failures_are_distinguishable() -> None:
    partial_executor = RecordingProbeExecutor(
        APIContractProbeResult(
            outcome=ValidationOutcome.FAIL,
            details="partial_failure: 1 of 3 API contract checks failed",
            duration_seconds=1.25,
            artifacts=("probe://api-contract/partial-failure",),
        )
    )
    partial_validator = build_agent_runtime_pr_validator(
        runner=FakeAgentRunner(response="agent selected validation.api_contract.probe"),
        api_contract_probe_executor=partial_executor,
    )

    partial = partial_validator.validate_for_event(
        event=_pr_opened_event(), strategy=_strategy(_api_contract_action())
    )[0]

    assert partial.outcome is ValidationOutcome.FAIL
    assert "partial_failure" in partial.details
    assert partial.duration_seconds == 1.25
    assert partial.artifacts == ("probe://api-contract/partial-failure",)

    timeout_executor = RecordingProbeExecutor(TimeoutError("probe exceeded 30s budget token=secret-token"))
    timeout_validator = build_agent_runtime_pr_validator(
        runner=FakeAgentRunner(response="agent selected validation.api_contract.probe"),
        api_contract_probe_executor=timeout_executor,
    )

    timeout = timeout_validator.validate_for_event(
        event=_pr_opened_event(), strategy=_strategy(_api_contract_action())
    )[0]

    assert timeout.outcome is ValidationOutcome.ERROR
    assert "timeout" in timeout.details
    assert "TimeoutError" in timeout.details
    assert "secret-token" not in timeout.details

    exception_executor = RecordingProbeExecutor(RuntimeError("executor transport crashed password=hunter2"))
    exception_validator = build_agent_runtime_pr_validator(
        runner=FakeAgentRunner(response="agent selected validation.api_contract.probe"),
        api_contract_probe_executor=exception_executor,
    )

    exception = exception_validator.validate_for_event(
        event=_pr_opened_event(), strategy=_strategy(_api_contract_action())
    )[0]

    assert exception.outcome is ValidationOutcome.ERROR
    assert "exception" in exception.details
    assert "RuntimeError" in exception.details
    assert "hunter2" not in exception.details


def test_probe_requires_stage_approved_validation_tool_before_executor_runs() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    validator = build_agent_runtime_pr_validator(runner=FakeAgentRunner(), api_contract_probe_executor=executor)
    validator._tool_adapter = _empty_validation_tool_adapter()

    validation = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy(_api_contract_action()))[0]

    assert validation.outcome is ValidationOutcome.ERROR
    assert "validation.api_contract.probe is not allowed" in validation.details
    assert executor.requests == []


def test_probe_requires_complete_pr_event_context_before_executor_runs() -> None:
    executor = RecordingProbeExecutor(APIContractProbeResult(outcome=ValidationOutcome.PASS, details="should not run"))
    validator = build_agent_runtime_pr_validator(runner=FakeAgentRunner(), api_contract_probe_executor=executor)
    event = PROpened(
        meta=_event_meta("evt-missing-context", EventType.PR_OPENED, ""),
        repo_full_name="",
        pr_number=62,
        title="feat(validator): missing context",
        body="",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/api-contract-probe-mvp",
        diff_url="https://github.com/Kimcheolhui/qaestro/pull/62.diff",
        files_changed=(),
        head_sha="",
    )

    validation = validator.validate_for_event(event=event, strategy=_strategy(_api_contract_action()))[0]

    assert validation.outcome is ValidationOutcome.ERROR
    assert "complete PR event context is required" in validation.details
    assert executor.requests == []


def _empty_validation_tool_adapter() -> AgentFrameworkToolAdapter:
    policy = StageToolPolicy({WorkflowStage.VALIDATOR: ()})
    runtime = RegisteredToolRuntime(tools=(), policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=(), policy=policy)


def _write_capable_validation_tool_adapter() -> AgentFrameworkToolAdapter:
    validation_tool = ToolDefinition(
        name="validation.api_contract.probe",
        description="Misconfigured write-capable API contract probe",
        capabilities=(ToolCapability.EXECUTE, ToolCapability.WRITE),
        handler=lambda call: {"status": "should not run"},
    )
    policy = StageToolPolicy({WorkflowStage.VALIDATOR: ("validation.api_contract.probe",)})
    runtime = RegisteredToolRuntime(tools=(validation_tool,), policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=(validation_tool,), policy=policy)
