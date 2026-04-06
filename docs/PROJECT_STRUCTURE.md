# Project Structure

devclaw 구현을 위한 권장 레포 구조. 아키텍처 레이어(Event Ingestion → Behaviour Analyzer → Strategy Engine → Runtime Validation → Output)를 실제 폴더 구조로 매핑한다.

이 구조는 현재 기준으로 `TypeScript / Node.js` monorepo 구현을 전제로 한다.

고객 QA 지식 자산의 실제 저장 위치는 이 문서에서 고정하지 않고, `packages/knowledge-store` 경계로만 다룬다.

관련 문서:

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [TECH_DECISIONS.md](./TECH_DECISIONS.md)
- [BACKLOG.md](./BACKLOG.md)

## 설계 원칙

- deployable unit와 reusable module을 분리한다.
- 외부 연동 코드와 핵심 판단 로직을 분리한다.
- 고객 QA 지식 자산은 `packages/knowledge-store` 경계 뒤에서 관리한다.
- 이벤트 수집, orchestration, connector, runtime session 제어를 같은 언어 경계 안에서 유지한다.

## 권장 구조

```text
.
├── apps/
│   ├── gateway/
│   │   └── src/
│   │       ├── github/
│   │       ├── chat/
│   │       ├── http/
│   │       └── bootstrap/
│   ├── worker/
│   │   └── src/
│   │       ├── jobs/
│   │       ├── flows/
│   │       └── runners/
│   └── cli/
│       └── src/
├── packages/
│   ├── contracts/
│   ├── orchestrator/
│   ├── behaviour-analyzer/
│   ├── strategy-engine/
│   ├── runtime-validator/
│   │   └── src/
│   │       └── probes/
│   │           ├── api-contract/
│   │           └── ui-flow/
│   ├── knowledge-store/
│   │   └── src/
│   │       └── adapters/
│   │           ├── markdown/
│   │           ├── vector/
│   │           └── database/
│   ├── renderers/
│   ├── connectors/
│   └── shared/
├── tests/
│   ├── fixtures/
│   ├── integration/
│   ├── e2e/
│   └── replay/
├── infra/
│   ├── github-app/
│   ├── chatops/
│   └── storage/
├── scripts/
└── docs/
```

## 아키텍처 매핑

| 아키텍처 레이어       | 주요 폴더                                                     |
| --------------------- | ------------------------------------------------------------- |
| Event Ingestion Layer | `apps/gateway`, `packages/contracts`, `packages/orchestrator` |
| Behaviour Analyzer    | `packages/behaviour-analyzer`                                 |
| Strategy Engine       | `packages/strategy-engine`                                    |
| Runtime Validation    | `packages/runtime-validator`                                  |
| Knowledge Store       | `packages/knowledge-store`                                    |
| Output Interface      | `packages/renderers`, `packages/connectors`, `apps/worker`    |

## 런타임 흐름

```text
GitHub / Slack / Teams
	-> apps/gateway
	-> packages/contracts
	-> packages/orchestrator
	-> packages/behaviour-analyzer
	-> packages/strategy-engine
	-> packages/runtime-validator
	-> packages/renderers
	-> GitHub / Slack / Teams
```

`apps/gateway`는 외부 payload를 받아 공통 이벤트로 바꾸고, `packages/orchestrator`는 그 이벤트를 하나의 workflow로 묶어 core package들을 호출한다.

## 의존 방향

기본 규칙은 `apps/* -> packages/*`다. deployable app이 reusable module을 사용하고, core package끼리의 의존은 최소화한다.

```text
apps/gateway -> contracts, connectors, orchestrator, shared
apps/worker -> orchestrator, renderers, connectors, shared
apps/cli -> orchestrator, runtime-validator, shared

orchestrator -> behaviour-analyzer, strategy-engine, runtime-validator, renderers, contracts
behaviour-analyzer -> contracts, shared
strategy-engine -> contracts, shared, knowledge-store
runtime-validator -> contracts, shared
renderers -> contracts, shared
connectors -> contracts, shared
knowledge-store -> shared
```

### pointing 규칙

- `apps/gateway`는 이벤트를 받아 `packages/contracts` 형태로 normalize한 뒤 `packages/orchestrator`에 전달한다.
- `packages/orchestrator`만 여러 core package를 동시에 호출한다.
- `packages/strategy-engine`은 고객 QA 지식 자산의 저장 위치나 포맷을 직접 알지 않고 `packages/knowledge-store` interface를 통해 접근한다.
- `packages/renderers`는 판단 결과를 PR 코멘트나 Slack/Teams 메시지로 변환만 하고 판단 로직에 개입하지 않는다.
- `packages/connectors`는 외부 SDK wrapper 역할만 하고 domain logic를 넣지 않는다.
- 기본 제공 규칙이나 체크리스트가 필요하면 이를 소비하는 package 내부 asset으로 포함한다.

## 폴더별 책임

### apps/

- `apps/gateway`: GitHub, Slack/Teams에서 들어오는 payload를 받아 공통 이벤트로 normalize
- `apps/worker`: `packages/orchestrator`를 실행하는 background processing entrypoint
- `apps/cli`: 로컬 replay, fixture 실행, 수동 검증용 엔트리포인트

### packages/

- `packages/contracts`: `PROpened`, `PRCommented`, `PRReviewed`, `CICompleted`, `ChatMention` 같은 공통 이벤트 스키마와 domain type
- `packages/orchestrator`: Event Router, correlation id, PR/채널/CI 맥락 묶기, workflow state 관리
- `packages/behaviour-analyzer`: diff 분석, 영향 범위 추정, 리스크 분류
- `packages/strategy-engine`: Behaviour Checklist 생성, 검증 전략 선택, 누락 테스트 제안. 기본 제공 전략 규칙이 필요하면 package 내부 asset으로 포함
- `packages/runtime-validator`: 실제 런타임 검증 실행. MVP는 `api-contract`, `ui-flow` probe부터 시작
- `packages/knowledge-store`: 고객 QA 지식 자산 read/write interface와 adapter 구현. 실제 backing store는 추후 결정
- `packages/renderers`: PR 코멘트, Slack/Teams 응답 등 채널별 출력 포맷
- `packages/connectors`: GitHub, Slack, Teams, LLM, storage provider SDK wrapper
- `packages/shared`: config, logger, tracing, 공통 util

### tests/

- `tests/fixtures/`: GitHub/Slack/CI raw payload fixture
- `tests/integration/`: connector + orchestration 통합 테스트
- `tests/e2e/`: PR 오픈 → 전략 생성 → 검증 → 출력까지 전체 플로우 테스트
- `tests/replay/`: 실제 PR/채널/CI 사례를 replay하여 regression 방지

### infra/

- `infra/github-app/`: GitHub App manifest, webhook 관련 설정
- `infra/chatops/`: Slack/Teams app 설정
- `infra/storage/`: DB, vector store, object store 등 저장소 provisioning

## Bounded Autonomy

devclaw는 자유롭게 모든 것을 실행하는 agent가 아니라, 정해진 가이드라인과 권한 범위 안에서 자율적으로 동작하는 QA Agent를 목표로 한다.

이 관점은 폴더 구조에도 반영된다.

- `packages/strategy-engine`: 자유 판단 계층이 아니라, 규칙과 맥락 안에서 검증 전략을 선택하는 계층
- `packages/knowledge-store`: Agent가 참고하는 고객별 QA 지식 자산 접근 계층
- `packages/runtime-validator`: 허용된 probe만 실행하는 계층
- `packages/orchestrator`: confidence와 action type에 따라 제안, 검증, 승인 대기 흐름을 통제하는 계층

예를 들면 다음과 같은 정책이 가능하다.

- 낮은 confidence: 전략 제안만 수행
- 중간 confidence: 런타임 검증까지 수행
- 높은 confidence: CI 반영 후보까지 제안하되 자동 반영은 승인 후 수행
- destructive action: 수행하지 않음

즉, 이 구조는 단순 기능 분리가 아니라 판단, 규칙, 실행, 통제를 서로 분리해 QA Agent의 자율성을 안전하게 제한하기 위한 구조다.

## MVP에서 먼저 채울 폴더

초기에는 모든 폴더를 한 번에 다 채우지 않고 아래부터 구현하는 것이 적절하다.

```text
apps/gateway/
apps/worker/
packages/contracts/
packages/orchestrator/
packages/behaviour-analyzer/
packages/strategy-engine/
packages/runtime-validator/
packages/knowledge-store/
packages/renderers/
tests/replay/
```

`packages/connectors/`, `infra/`, `tests/e2e/`는 MVP 진행 중 필요해지는 시점에 확장해도 된다.

## 설계 포인트

- chat provider별 코드는 `apps/gateway` 안에 깊게 박아 넣기보다 `packages/connectors/`로 분리하는 편이 확장에 유리하다.
- 고객별 QA knowledge는 `packages/knowledge-store` 뒤로 숨기고, 기본 제공 규칙은 consuming package 내부 asset으로 두는 편이 현재 배포 모델과 맞다.
- Runtime Validation은 처음부터 별도 package로 분리해야 이후 DB 정합성, 성능, multi-step behaviour probe를 붙이기 쉽다.
- `tests/replay/`는 이 프로젝트의 성격상 중요하다. 단순 unit test보다 실제 event bundle replay가 더 많은 가치를 준다.
