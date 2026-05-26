# Step 0~6 Foundation Traceability Audit

Step 6.5의 첫 작업으로, Step 0~6 및 Step 3.5의 완료 기준이 현재 Step 6 완료 코드베이스의 코드, 테스트, 문서 근거와 어떻게 연결되는지 정리한다. 이 문서는 Step 7 ChatOps와 Step 8 Knowledge Store 확장 전에 현재 최소 QA control plane이 어디까지 신뢰 가능한지 확인하기 위한 기준선이다.

## 감사 기준

각 항목은 다음 상태로 분류한다.

- **충족됨**: milestone 완료 기준을 현재 코드와 테스트가 직접 뒷받침한다.
- **MVP stub / 의도된 제한**: 현재 단계에서 의도적으로 제한된 구현이며, 코드나 문서가 그 제한을 명시한다.
- **후속 deferred**: 별도 milestone 또는 Step 6.5 후속 이슈로 명시적으로 넘긴 작업이다.
- **mismatch / cleanup 필요**: 동작 자체보다 문서, TODO, 완료 기준 표현이 현재 구현과 어긋난다.
- **blocker**: Step 7 착수 전 반드시 해결해야 하는 기능·안전성 문제다.

## 요약 판단

Step 0~6의 최소 control plane은 **GitHub PR/CI 이벤트 수신 → worker/orchestrator → ToolRuntime 경계 → PR aggregate/strategy → Agent Runtime-backed validation → managed PR comment 및 official review output**까지 연결되어 있다. 즉 Step 7로 확장할 수 있는 최소 기능선은 마련되었다.

다만 Step 7 전에 바로 기능을 늘리기보다 Step 6.5에서 다음 영역을 먼저 보강해야 한다. 아래 항목은 모두 Step 7의 절대 blocker라는 뜻은 아니며, #91~#98에서 실제 blocker와 deferred hardening을 분리한다.

- analyzer/strategy의 low-signal 변경 noise
- runtime validation outcome 의미론과 exception sanitization
- GitHub review/inline output guardrail
- PR aggregate current-head lifecycle replay
- durable queue idempotency와 worker operational semantics
- secret safety와 verification command 정렬

이들은 Step 7의 직접 기능은 아니지만, ChatOps와 Knowledge Store가 붙으면 사용자-facing 표면이 넓어지므로 foundation 품질 문제로 먼저 다루는 편이 안전하다.

## Step별 traceability

### Step 0 — Engineering baseline

**상태: 충족됨**

근거:

- `pyproject.toml`에 uv 기반 단일 package 설정, console scripts, ruff/mypy/pytest 설정이 존재한다.
- `.github/workflows/ci.yml`가 ruff check, ruff format check, mypy, pytest를 실행한다.
- `tests/test_entrypoints.py`가 `qaestro-gateway`, `qaestro-worker` importability를 확인한다.
- `README.md`, `docs/PROJECT_STRUCTURE.md`, `docs/MODULE_REQUIREMENTS.md`가 기본 구조와 개발 방향을 설명한다.

Cleanup:

- CI는 `mypy src/`를 실행하고, `pyproject.toml`은 `files = ["src", "tests"]`를 둔다. 이 차이는 Step 6.5의 verification alignment 작업에서 명시적으로 정리한다.

### Step 1 — Contracts and replay foundation

**상태: 충족됨**

근거:

- `src/core/contracts/events.py`가 `PROpened`, `PRUpdated`, `PRCommented`, `PRReviewed`, `CICompleted`, `ChatMention`와 공통 `EventMeta`, `FileChange`를 정의한다.
- `src/core/contracts/domain.py`가 risk, strategy, validation, report domain type을 제공한다.
- `src/core/contracts/parsers.py`와 GitHub webhook adapter가 raw provider payload를 normalized event로 변환한다.
- `tests/test_contracts.py`와 `tests/replay/test_replay_github.py`가 계약과 replay 흐름을 검증한다.

MVP stub / 의도된 제한:

- `ChatMention` type은 존재하지만 Slack/Teams parser와 real connector는 Step 7 범위다.
- `PRClosed`는 `docs/BACKLOG.md`의 parking lot에 남아 있다.

### Step 2 — Event → Worker → Output skeleton

**상태: 충족됨, 일부 운영 기능 deferred**

근거:

- `src/app/gateway/*`가 GitHub webhook 수신, signature 검증, normalized event enqueue 경계를 제공한다.
- `src/app/jobs.py`, `src/app/queue_factory.py`, `src/app/worker/runner.py`가 in-memory 및 Redis Streams queue, worker processing, retry/timeout/failure logging 경계를 제공한다.
- `src/runtime/orchestrator/dispatcher.py`, `src/runtime/orchestrator/pr_workflow.py`가 event dispatch와 PR workflow skeleton을 실행한다.
- `src/adapters/connectors/github/*`와 `src/adapters/renderers/pr_comment.py`가 GitHub App/client와 PR comment payload를 제공한다.
- `tests/app/test_gateway_worker_e2e.py`, `tests/app/gateway/*`, `tests/app/worker/*`, `tests/adapters/connectors/*`가 gateway/worker/connector 경계를 검증한다.

후속 deferred:

- DLQ, worker heartbeat, long-running job observability는 Step 10 운영 안정화 영역이며, Step 6.5에서는 Step 7 전에 당길 최소 hardening 범위를 #95에서 판단한다.
- Redis Streams duplicate delivery와 output idempotency는 Step 6.5에서 더 강하게 검증해야 한다.

### Step 3 — GitHub PR analysis vertical slice

**상태: 충족됨**

근거:

- `src/core/analyzer/*`가 diff/file metadata 기반 impact facts와 path group을 산출하되 risk는 `NOT_ASSESSED`로 남긴다.
- `src/core/strategy/*`가 path/knowledge token match를 product-facing action으로 만들지 않고 context로만 노출하며, current-head CI evidence만 action 우선순위에 반영한다.
- `src/core/knowledge/memory.py`가 strategy에서 사용할 knowledge port와 in-memory mock을 제공한다.
- `src/adapters/renderers/pr_comment.py`가 Behaviour Impact Report를 managed PR comment 형태로 렌더링한다.
- `tests/core/test_analyzer.py`, `tests/core/test_strategy.py`, `tests/adapters/renderers/test_pr_comment.py`, `tests/runtime/test_orchestrator.py`가 vertical slice를 검증한다.

후속 deferred:

- 실제 backing Knowledge Store adapter는 Step 8 범위다.
- strategy 품질은 MVP first pass에서 Step 6.5-A(#91)로 정리했다. 남은 전략 고도화는 path/test-target heuristic 복구가 아니라 Agent Runtime-backed strategy planning과 Step 8 Knowledge Store evidence 품질 개선으로 다룬다.

### Step 3.5 — Tool Runtime boundary

**상태: 충족됨**

근거:

- `src/runtime/tools/types.py`, `src/runtime/tools/runtime.py`, `src/runtime/tools/policy.py`가 `ToolCall`, `ToolResult`, `ToolRuntime`, stage allowlist를 제공한다.
- `src/runtime/tools/github.py`가 GitHub PR read/write, CI/check read, review write capability를 narrow tool로 감싼다.
- `src/runtime/tools/agent_framework.py`가 Microsoft Agent Framework-facing tool spec seam을 제공하되 실제 호출은 `ToolRuntime.execute()`를 통과한다.
- `src/app/worker/factory.py`가 durable worker path에서 ToolRuntime-backed providers/poster를 주입한다.
- `tests/runtime/test_tools.py`, `tests/runtime/test_tool_pr_adapters.py`, `tests/runtime/test_github_tools.py`, `tests/runtime/test_agent_framework_tools.py`가 policy와 tool adapter 경계를 검증한다.

MVP stub / 의도된 제한:

- GitHub backend는 `gh` CLI가 아니라 기존 GitHub Client API adapter를 유지한다.
- Agent가 임의 tool을 자유 선택하는 구조가 아니라 workflow stage policy가 허용한 tool만 노출한다.

### Step 4 — CI feedback loop and PR aggregate

**상태: 충족됨, persistence hardening deferred**

근거:

- `src/runtime/orchestrator/pr_aggregate.py`, `ci_workflow.py`, `pr_context.py`, `pr_triage.py`가 PR revision, CI feedback, current-head readiness, triage depth 경계를 제공한다.
- `src/runtime/tools/github.py`와 context providers가 GitHub Actions jobs/check state read capability를 제공한다.
- `src/core/strategy/rules.py`가 CI feedback을 strategy reasoning/action에 반영한다.
- `tests/replay/test_ci_feedback_loop_replay.py`, `tests/runtime/test_pr_aggregate.py`, `tests/runtime/test_ci_context_provider.py`, `tests/runtime/test_orchestrator.py`가 CI completed, orphan CI, stale/current head, pending checks 흐름을 검증한다.

후속 deferred:

- 현재 aggregate는 in-memory 중심이다. ChatOps가 aggregate state에 의존하기 전에 stale CI/current head/manual trigger replay를 더 강하게 보강하고, durable state 필요성을 #94에서 판단한다.

### Step 5 — Agent Runtime Foundation

**상태: 충족됨, provider 확장 deferred**

근거:

- `src/shared/config.py`가 provider, endpoint/base URL, deployment/model, credential env var, execution budget, capability 설정을 typed config로 로드한다.
- `src/runtime/agent/*`가 provider-neutral `AgentRunner`, session manager, fake runner, Azure OpenAI adapter, OpenAI-compatible adapter, health check를 제공한다.
- `src/app/worker/factory.py`가 worker bootstrap에서 agent runtime health와 validation runner construction 경계를 제공한다.
- `tests/runtime/test_agent_runtime_config.py`, `test_agent_runtime.py`, `test_agent_runtime_health.py`, `test_azure_openai_provider.py`, `test_openai_compatible_provider.py`, `tests/app/test_worker_agent_runtime_health.py`가 fake/real provider boundary와 secret redaction을 검증한다.

후속 deferred:

- GitHub Copilot provider는 별도 provider 이슈로 분리한다.
- GitHub Models는 provider roadmap에서 제외되어야 하며, 현재 `docs/TECH_DECISIONS.md`도 그 방향을 명시한다.
- Microsoft Agent Framework SDK full integration은 adapter seam 뒤의 후속 구현으로 남긴다.

### Step 6 — Runtime Validation MVP

**상태: MVP 완료, semantics/output hardening 필요**

근거:

- `src/runtime/validator/agent_runtime.py`가 `AgentRuntimePRValidator`, `APIContractProbeRequest`, pluggable probe executor, validation-stage tool exposure를 제공한다.
- validation runner success는 probe verdict와 분리되어 있고, default executor는 non-live `SKIPPED`를 명시한다.
- `src/runtime/orchestrator/pr_workflow.py`가 validation 결과를 `QAReport`, managed summary comment, official review payload로 연결한다.
- `src/adapters/renderers/pr_comment.py`가 managed PR comment와 `PRReviewPayload` / inline review payload를 구분한다.
- `src/runtime/tools/github.py`와 GitHub connector client가 `github.pr.review.create`를 output-stage capability로 제공한다.
- `tests/runtime/test_validation_agent_runner.py`, `test_api_contract_probe_validator.py`, `test_github_review_output.py`, `tests/adapters/connectors/test_github_review_client.py`, `tests/runtime/test_llm_pr_review_e2e_smoke.py`, `tests/smoke/llm_pr_review_e2e.py`가 validation wiring, policy, official review output, live LLM PR review smoke path를 검증한다.

MVP stub / 의도된 제한:

- Azure OpenAI live smoke는 validation-stage provider runner가 실제 LLM call을 수행할 수 있는지 확인하는 검증이다.
- external API contract live probe는 대상 preview/staging app endpoint를 실제로 호출하는 별도 범위이며, Step 6 MVP의 기본 완료 조건이 아니다.
- write-like API method는 `SKIPPED` + `needs_approval`/`policy_denied`로 남긴다.

후속 deferred:

- runtime validation outcome semantics, sanitized details, session cleanup, missing context fail-closed edge case는 #92에서 더 강하게 보강한다.
- official review/inline output의 stale-head, duplicate marker, invalid inline mapping, PASS evidence placement는 #93에서 보강한다.

## 문서 정렬 결과

이번 PR에서 다음 mismatch를 정리한다.

- `docs/MODULE_REQUIREMENTS.md`의 개발 순서에 Step 6.5를 추가해 Step 7~10 이전 foundation hardening gate를 명시한다.
- `docs/PROJECT_STRUCTURE.md`의 “MVP 이후” 목록에서 이미 구현된 `runtime/agent`와 `runtime/validator`를 현재 구현 상태로 이동한다.
- `docs/TECH_DECISIONS.md`의 Redis Streams 운영 모니터링/DLQ 확장 시점을 Step 10 운영 안정화와 맞춘다.
- `docs/notes/PR_REVIEW_LIFECYCLE.md`의 오래된 특정 PR 진행 문구를 현재 Step 6 이후 상태에 맞게 일반화한다.

## Step 7 진입 전 남은 작업 매핑

Step 6.5의 나머지 이슈는 다음 역할로 남긴다.

- #91: analyzer/strategy golden case와 recommendation noise 정리
- #92: runtime validation outcome 의미론과 sanitization 보강
- #93: GitHub review output surface guardrail 강화
- #94: PR aggregate current-head lifecycle replay 보강
- #95: durable queue와 worker operational hardening 범위 정리
- #96: secret safety와 credential redaction 회귀 검증
- #97: CI/local verification과 packaging entrypoint smoke 정렬
- #98: Step 7 ChatOps 구현 이슈 재설계

이 목록은 Step 7을 막기 위한 형식적 checklist가 아니라, Step 7이 기존 foundation 위에 안전하게 올라가기 위해 필요한 선행 품질 기준이다.
