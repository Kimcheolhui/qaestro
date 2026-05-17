"""Tests for validation-stage Agent Runtime runner wiring."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.contracts import (
    ActionType,
    BehaviourImpact,
    EventMeta,
    EventSource,
    EventType,
    FileChange,
    PROpened,
    RiskLevel,
    StrategyAction,
    StrategyResult,
    ValidationOutcome,
)
from src.runtime.agent.fake import FakeAgentRunner
from src.runtime.agent.manager import WorkflowAgentSessionManager
from src.runtime.orchestrator import PRWorkflowOrchestrator
from src.runtime.stages import WorkflowStage
from src.runtime.tools import (
    AgentFrameworkToolAdapter,
    RegisteredToolRuntime,
    StageToolPolicy,
    ToolCapability,
    ToolDefinition,
)
from src.runtime.validator import AgentRuntimePRValidator, build_agent_runtime_pr_validator


def _event_meta(event_id: str, event_type: EventType, correlation_id: str) -> EventMeta:
    return EventMeta(
        event_id=event_id,
        event_type=event_type,
        correlation_id=correlation_id,
        timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        source=EventSource.GITHUB,
    )


def _pr_opened_event(*, pr_number: int = 61, correlation_id: str = "corr-validation-runner") -> PROpened:
    return PROpened(
        meta=_event_meta("evt-validation-runner", EventType.PR_OPENED, correlation_id),
        repo_full_name="Kimcheolhui/qaestro",
        pr_number=pr_number,
        title="feat(runtime): validation runner wiring",
        body="Connects the Agent Runtime runner to validation.",
        author="Kimcheolhui",
        base_branch="main",
        head_branch="feat/runtime-validation-agent-runner",
        diff_url=f"https://github.com/Kimcheolhui/qaestro/pull/{pr_number}.diff",
        files_changed=(FileChange(path="src/runtime/validator/__init__.py", status="modified", additions=80),),
        head_sha=f"abc123validation-{pr_number}",
    )


def _strategy() -> StrategyResult:
    return StrategyResult(
        actions=(
            StrategyAction(
                action_type=ActionType.VERIFY_API_CONTRACT,
                description="Validate the API contract probe",
                target="GET /health",
                priority=2,
                rationale="The PR changes runtime validation code.",
            ),
        ),
        reasoning="API contract changed.",
        confidence=0.9,
    )


def test_validation_stage_runs_provider_neutral_agent_runner_with_bounded_tools() -> None:
    fake_runner = FakeAgentRunner(response="contract probe evidence")
    session_manager = WorkflowAgentSessionManager(runner=fake_runner)
    validator = AgentRuntimePRValidator(
        session_manager=session_manager,
        tool_adapter=_validation_tool_adapter(),
    )
    strategy = _strategy()
    event = _pr_opened_event()
    orchestrator = PRWorkflowOrchestrator(
        analyzer=_StaticAnalyzer(),
        strategy_engine=_StaticStrategy(strategy),
        validator=validator,
    )

    result = orchestrator.run(event)

    assert result.validations[0].outcome is ValidationOutcome.SKIPPED
    assert (
        result.validations[0].details == "api_contract_probe_skipped: no non-live executor configured for GET /health."
    )
    assert len(fake_runner.started_sessions) == 1
    assert fake_runner.started_sessions[0].scope.value == "workflow"
    assert fake_runner.started_sessions[0].repo_full_name == "Kimcheolhui/qaestro"
    assert fake_runner.started_sessions[0].pr_number == 61
    assert fake_runner.started_sessions[0].head_sha == "abc123validation-61"
    assert fake_runner.closed_sessions == [(fake_runner.started_sessions[0].session_id, "validation stage complete")]
    assert fake_runner.run_inputs[0].stage is WorkflowStage.VALIDATOR
    assert fake_runner.run_inputs[0].correlation_id == "corr-validation-runner"
    assert fake_runner.run_inputs[0].allowed_tool_names == ("validation.api_contract.probe",)
    assert fake_runner.run_inputs[0].max_turns == 2
    assert fake_runner.run_inputs[0].max_tool_calls == 1
    assert fake_runner.run_inputs[0].timeout_seconds == 30.0
    assert fake_runner.run_inputs[0].context == {
        "repo_full_name": "Kimcheolhui/qaestro",
        "pr_number": 61,
        "head_sha": "abc123validation-61",
        "action_type": "verify_api_contract",
        "target": "GET /health",
    }
    assert "github.pr.comment.create_or_update" not in fake_runner.run_inputs[0].allowed_tool_names


def test_validation_agent_runner_requires_pr_event_context() -> None:
    validator = AgentRuntimePRValidator(
        session_manager=WorkflowAgentSessionManager(runner=FakeAgentRunner()),
        tool_adapter=_validation_tool_adapter(),
    )

    validations = validator.validate(_strategy())

    assert validations[0].outcome is ValidationOutcome.ERROR
    assert "PR event context is required" in validations[0].details


def test_validation_agent_runner_does_not_reuse_stale_event_context() -> None:
    fake_runner = FakeAgentRunner(response="runner completed")
    validator = AgentRuntimePRValidator(
        session_manager=WorkflowAgentSessionManager(runner=fake_runner),
        tool_adapter=_validation_tool_adapter(),
    )

    first = validator.validate_for_event(
        event=_pr_opened_event(pr_number=61, correlation_id="corr-61"), strategy=_strategy()
    )
    second = validator.validate_for_event(
        event=_pr_opened_event(pr_number=62, correlation_id="corr-62"), strategy=_strategy()
    )

    assert first[0].outcome is ValidationOutcome.SKIPPED
    assert second[0].outcome is ValidationOutcome.SKIPPED
    assert [run.context["pr_number"] for run in fake_runner.run_inputs if run.context is not None] == [61, 62]
    assert [run.correlation_id for run in fake_runner.run_inputs] == ["corr-61", "corr-62"]


def test_default_agent_runtime_validator_exposes_only_validation_tool_specs() -> None:
    fake_runner = FakeAgentRunner(response="runner completed")
    validator = build_agent_runtime_pr_validator(runner=fake_runner)

    validations = validator.validate_for_event(event=_pr_opened_event(), strategy=_strategy())

    assert validations[0].outcome is ValidationOutcome.SKIPPED
    assert fake_runner.run_inputs[0].allowed_tool_names == ("validation.api_contract.probe",)


def _validation_tool_adapter() -> AgentFrameworkToolAdapter:
    validation_tool = ToolDefinition(
        name="validation.api_contract.probe",
        capabilities=(ToolCapability.EXECUTE,),
        description="Run a deterministic API contract probe",
        input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
        handler=lambda call: {"target": call.input.get("target"), "ok": True},
    )
    output_tool = ToolDefinition(
        name="github.pr.comment.create_or_update",
        capabilities=(ToolCapability.WRITE,),
        description="Write a managed PR comment",
        handler=lambda call: {"comment": "written"},
    )
    policy = StageToolPolicy(
        {
            WorkflowStage.VALIDATOR: ("validation.api_contract.probe",),
            WorkflowStage.OUTPUT: ("github.pr.comment.create_or_update",),
        }
    )
    runtime = RegisteredToolRuntime(tools=(validation_tool, output_tool), policy=policy)
    return AgentFrameworkToolAdapter(runtime=runtime, tools=(validation_tool, output_tool), policy=policy)


class _StaticAnalyzer:
    def analyze(self, context: object) -> BehaviourImpact:
        return BehaviourImpact(
            summary="runtime validation wiring change",
            areas=(),
            overall_risk=RiskLevel.MEDIUM,
        )


class _StaticStrategy:
    def __init__(self, result: StrategyResult) -> None:
        self._result = result

    def plan(self, **kwargs: object) -> StrategyResult:
        return self._result
