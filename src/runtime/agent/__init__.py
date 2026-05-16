"""Provider-neutral Agent Runtime public API."""

from __future__ import annotations

from .fake import FakeAgentRunner
from .health import (
    AgentRuntimeHealthResult,
    AgentRuntimeHealthStatus,
    LiveSmokeProbeStatus,
    check_agent_runtime_health,
)
from .manager import WorkflowAgentSessionManager
from .openai_compatible import (
    OpenAICompatibleAgentRunner,
    OpenAICompatibleChatClient,
    OpenAICompatibleClientResponse,
    UnsupportedAgentRuntimeProviderError,
    build_agent_runner,
)
from .types import (
    AgentRunInput,
    AgentRunResult,
    AgentRunStatus,
    AgentSessionHandle,
    AgentSessionRecord,
    AgentSessionScope,
    AgentSessionStatus,
    AgentSessionTurn,
)

__all__ = [
    "AgentRunInput",
    "AgentRunResult",
    "AgentRunStatus",
    "AgentRuntimeHealthResult",
    "AgentRuntimeHealthStatus",
    "AgentSessionHandle",
    "AgentSessionRecord",
    "AgentSessionScope",
    "AgentSessionStatus",
    "AgentSessionTurn",
    "FakeAgentRunner",
    "LiveSmokeProbeStatus",
    "OpenAICompatibleAgentRunner",
    "OpenAICompatibleChatClient",
    "OpenAICompatibleClientResponse",
    "UnsupportedAgentRuntimeProviderError",
    "WorkflowAgentSessionManager",
    "build_agent_runner",
    "check_agent_runtime_health",
]
