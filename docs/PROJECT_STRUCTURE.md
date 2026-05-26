# Project Structure

qaestro 구현을 위한 레포 구조. 아키텍처 레이어(Event Ingestion → Behaviour Analyzer → Strategy Engine → Runtime Validation → Output)를 실제 폴더 구조로 매핑한다.

코드 루트는 `src/`로 두고, 그 아래를 `app`, `core`, `runtime`, `adapters`, `shared`로 묶어 책임별로 구분한다. 서브모듈 간 경계는 디렉터리 구조와 import 규약으로 유지한다.

고객 QA 지식 자산의 논리 경계는 `src/core/knowledge`에 두고, 실제 backing store adapter는 `src/adapters/knowledge`에 둔다.

관련 문서:

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [TECH_DECISIONS.md](./TECH_DECISIONS.md)
- [BACKLOG.md](./BACKLOG.md)

> **참고:** 이 문서의 설계 원칙, 의존 방향, 모듈 규약은 `.github/copilot-instructions.md` 및 `.github/instructions/` 하위 instruction 파일로도 등록되어 있다. Copilot이 개발 시 자동으로 참조한다. 규약을 변경하면 instruction 파일도 함께 업데이트할 것.

## 설계 원칙

- 코드 루트 `src/` 아래를 `app`, `core`, `runtime`, `adapters`, `shared`로 묶어 책임별로 나눈다.
- `app`은 진입점, `core`는 도메인 판단, `runtime`은 실행 흐름, `adapters`는 외부 연동/표현, `shared`는 공통 유틸을 담당한다.
- 외부 연동 코드와 핵심 판단 로직을 분리한다.
- 고객 QA 지식 자산의 논리 경계는 `src/core/knowledge`, 실제 저장소 구현은 `src/adapters/knowledge`로 분리한다.
- uv로 의존성을 관리하고, 루트에 단일 `pyproject.toml`만 둔다.
- Microsoft Agent Framework 관련 코드는 `src/app/worker`와 `src/runtime` 근처에 국한하고, `core` 서브모듈로 직접 새지 않게 한다.

## 권장 구조

```text
.
├── pyproject.toml
├── uv.lock
├── src/
│   ├── __init__.py
│   ├── app/
│   │   ├── gateway/        # webhook 수신, 이벤트 normalize
│   │   ├── worker/         # background job 실행, MAF runner host
│   │   └── cli/            # 설치, 설정, 로컬 점검, 설치 매니페스트
│   ├── core/
│   │   ├── contracts/      # 공통 이벤트, 도메인 타입
│   │   ├── analyzer/       # diff 분석, 영향 범위, 리스크 분류
│   │   ├── strategy/       # 검증 전략, checklist 생성
│   │   └── knowledge/      # QA knowledge port, query model, in-memory mock
│   ├── runtime/
│   │   ├── orchestrator/   # workflow 제어, 맥락 묶기
│   │   ├── agent/          # BYOK provider/session/runner foundation
│   │   ├── tools/          # stage policy와 ToolRuntime capability boundary
│   │   └── validator/      # 런타임 검증 실행 (probes)
│   ├── adapters/
│   │   ├── connectors/     # GitHub, Slack, LLM 등 외부 SDK wrapper
│   │   ├── renderers/      # PR/Chat 등 채널별 출력 포맷
│   │   └── knowledge/      # markdown/vector/database backing store adapter
│   └── shared/             # config, logger, tracing, util
├── tests/
│   ├── fixtures/
│   ├── integration/
│   ├── e2e/
│   └── replay/
├── scripts/
└── docs/
```

## 아키텍처 매핑

| 아키텍처 레이어       | 서브모듈                                                  |
| --------------------- | --------------------------------------------------------- |
| Event Ingestion Layer | `app/gateway`, `core/contracts`, `runtime/orchestrator`   |
| Behaviour Analyzer    | `core/analyzer`                                           |
| Strategy Engine       | `core/strategy`                                           |
| Runtime Validation    | `runtime/validator`                                       |
| Knowledge Store       | `core/knowledge`, `adapters/knowledge`                    |
| Output Interface      | `adapters/renderers`, `adapters/connectors`, `app/worker` |

## 런타임 흐름

```text
GitHub (현재) / Slack·Teams (Step 7 ChatOps)
    → src.app.gateway
    → src.core.contracts
    → src.runtime.orchestrator
    → src.core.analyzer
    → src.core.strategy
    → src.runtime.validator
    → src.adapters.renderers
    → GitHub (managed summary / official review) / Slack·Teams (Step 7)
```

`app/gateway`는 외부 payload를 받아 공통 이벤트로 바꾸고, `runtime/orchestrator`는 그 이벤트를 하나의 workflow로 묶어 core 서브모듈들을 호출한다. 현재 Step 6 이후 구현 범위는 GitHub PR/CI payload와 GitHub output surface이고, Slack/Teams parser·connector·response write는 Step 7 ChatOps에서 `ChatMention` contract 위에 붙인다.

## 의존 방향

기본 규칙: `app` → `runtime`/`core`/`adapters`/`shared`. `core`는 도메인 판단만 담당하고, 외부 연동과 출력 포맷은 `adapters`로 밀어낸다.

```text
# app → runtime/core/adapters/shared
app.gateway → core.contracts, adapters.connectors, runtime.orchestrator, shared
app.worker  → runtime.orchestrator, adapters.renderers, adapters.connectors, shared
app.cli     → runtime.orchestrator, runtime.validator, shared

# runtime → core/adapters/shared
runtime.orchestrator → core.analyzer, core.strategy, runtime.validator, adapters.renderers, core.contracts
runtime.agent         → runtime.tools, runtime.stages, shared
runtime.tools         → core.contracts, adapters.connectors, adapters.renderers, shared
runtime.validator    → core.contracts, shared

# core → shared
core.analyzer  → core.contracts, shared
core.strategy  → core.contracts, shared, core.knowledge
core.knowledge → shared

# adapters → core/shared
adapters.renderers  → core.contracts, shared
adapters.connectors → core.contracts, shared
adapters.knowledge  → core.knowledge, shared
```

의존 방향 규칙, 금지되는 의존, import 규칙의 상세 내용은 [`.github/instructions/package-conventions.instructions.md`](../.github/instructions/package-conventions.instructions.md) 참고.

## 서브모듈별 책임

### `app/`

- `app/gateway`: 현재 GitHub webhook payload를 받아 공통 이벤트로 normalize한다. Slack/Teams gateway/parser는 `ChatMention` contract 위에 붙는 Step 7 범위다.
- `app/worker`: `runtime/orchestrator`를 실행하는 background processing entrypoint이자 Agent Runtime/Microsoft Agent Framework runner host
- `app/cli`: 로컬 replay, fixture 실행, 수동 검증용 엔트리포인트. GitHub App manifest, ChatOps app 설정 등 설치 매니페스트도 CLI 리소스로 관리

### `core/`

- `core/contracts`: `PROpened`, `PRUpdated`, `PRCommented`, `PRReviewed`, `CICompleted`, `ChatMention` 같은 공통 이벤트 스키마와 domain type
- `core/analyzer`: diff 분석, 영향 범위 추정, 리스크 분류
- `core/strategy`: Behaviour Checklist 생성, 검증 전략 선택, 누락 테스트 제안
- `core/knowledge`: 고객 QA 지식 자산 접근을 위한 port, query model, in-memory mock

### `runtime/`

- `runtime/orchestrator`: Event Router, correlation id, PR/채널/CI 맥락 묶기, workflow state 관리
- `runtime/agent`: BYOK provider/session 설정, runner factory, fake/real provider 경계를 관리하는 Agent Runtime foundation
- `runtime/validator`: 실제 런타임 검증 실행. 현재 MVP는 API contract probe executor seam과 non-live default executor를 제공하고, concrete live probe executor, `ui_flow`, multi-step behaviour probe는 이후 확장

### `adapters/`

- `adapters/connectors`: GitHub connector가 현재 P0 구현이며, Slack/Teams/추가 provider connector는 이후 확장
- `adapters/renderers`: PR managed summary comment와 official GitHub review payload를 분리해 렌더링한다. Slack/Teams 응답 포맷은 Step 7에서 확장
- `adapters/knowledge`: markdown, vector, database 등 backing store adapter 구현

### `shared/`

- `shared`: config, logger, tracing, 공통 util

### `tests/`

- `tests/fixtures/`: 현재 GitHub/CI raw payload fixture 중심이며, Slack/Teams fixture는 Step 7 ChatOps connector와 함께 추가
- `tests/integration/`: connector + orchestration 통합 테스트
- `tests/e2e/`: PR 오픈 → 전략 생성 → 검증 → 출력까지 전체 플로우 테스트
- `tests/replay/`: 실제 PR/채널/CI 사례를 replay하여 regression 방지

## Bounded Autonomy

qaestro는 자유롭게 모든 것을 실행하는 agent가 아니라, 정해진 가이드라인과 권한 범위 안에서 자율적으로 동작하는 QA Agent를 목표로 한다.

이 관점은 그룹 구조에도 반영된다.

- `core/strategy`: 관측된 evidence와 agent/repo knowledge 안에서 검증 전략을 선택하는 계층
- `core/knowledge`: Agent가 참고하는 고객별 QA 지식 자산 접근 경계
- `runtime/validator`: 허용된 probe만 실행하는 계층
- `runtime/orchestrator`: triage 결과, validation policy, action type에 따라 제안, 검증, 승인 대기 흐름을 통제하는 계층
- `adapters/*`: 외부 세계와 포맷을 연결하지만 core policy를 소유하지 않는 계층

confidence 값이 존재하더라도 hand-picked numeric heuristic을 자동 실행 정책의 근거로 사용하지 않는다. 검증 실행 여부는 현재 head CI/check evidence, 명시적 triage 결과, validation policy, 사용자/운영 승인 경계에 의해 결정되어야 한다. 예를 들면 다음과 같은 정책이 가능하다.

- Agent/repo knowledge가 특정 runtime probe 필요성을 설명하고 policy가 허용하면 런타임 검증까지 수행
- current-head CI failure나 failed job처럼 관측된 evidence는 validation 우선순위에 반영
- agent triage가 실패하거나 malformed response를 내면 path/token rule로 lightweight/deep을 찍지 않고 normal workflow로 보수적 fallback
- destructive action: 수행하지 않음

즉, 이 구조는 단순 기능 분리가 아니라 판단, 규칙, 실행, 통제를 서로 분리해 QA Agent의 자율성을 안전하게 제한하기 위한 구조다.

## MVP에서 먼저 채울 서브모듈

초기에는 모든 서브모듈을 한 번에 다 채우지 않고 P0 모듈부터 구현한다. 각 모듈의 우선순위는 [MODULE_REQUIREMENTS.md](./MODULE_REQUIREMENTS.md) 참고.

```text
src/shared/
src/core/contracts/
src/core/analyzer/
src/core/strategy/
src/core/knowledge/         # interface + in-memory mock (P0)
src/runtime/orchestrator/
src/adapters/connectors/    # GitHub connector (P0)
src/adapters/renderers/
src/app/gateway/
src/app/worker/
src/runtime/agent/          # provider/session/runner foundation
src/runtime/tools/          # ToolRuntime, stage allowlist, provider capability seam
src/runtime/validator/      # API contract probe MVP and validation runner wiring
tests/replay/
```

아래는 MVP 이후 시점에 확장한다.

```text
src/adapters/connectors/    # ChatOps, LLM connector (P1)
src/adapters/knowledge/     # concrete backing store adapter (P1)
src/app/cli/                # P2
tests/e2e/
```

## 설계 포인트

- 채널/provider별 코드는 `app/gateway`에 박아 넣기보다 `adapters/connectors/`로 분리하는 편이 확장에 유리하다.
- 고객별 QA knowledge는 `core/knowledge` port 뒤로 숨기고, 실제 저장소 구현은 `adapters/knowledge`로 미루는 편이 현재 배포 모델과 맞다.
- Agent Runtime은 `runtime/agent`로 분리해 provider/session/runner 준비를 먼저 다룬다. validation workflow는 이 foundation 없이 먼저 확장하지 않는다.
- Runtime Validation은 `runtime/validator`로 분리해야 이후 DB 정합성, 성능, multi-step behaviour probe를 붙이기 쉽다.
- Agent Framework 전용 객체 타입과 설정은 `app/worker`와 `runtime/agent` 근처에 두고, `core/*`에는 직접 퍼뜨리지 않는다.
- `tests/replay/`는 이 프로젝트의 성격상 중요하다. 단순 unit test보다 실제 event bundle replay가 더 많은 가치를 준다.
- GitHub App manifest, ChatOps app 설정 등 설치 매니페스트는 `app/cli`가 참조하는 리소스로 관리한다. 설치 = CLI가 전부 책임지는 구조.
