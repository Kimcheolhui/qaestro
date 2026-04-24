# Module Requirements

qaestro를 구현할 때 참고할 수 있는 모듈 단위 요구사항 문서.

이 문서는 상세 구현 문서가 아니라, 각 모듈이 무엇을 책임지고 어떤 수준까지 먼저 만들어야 하는지를 정리한다.

관련 문서:

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)
- [TECH_DECISIONS.md](./TECH_DECISIONS.md)
- [BACKLOG.md](./BACKLOG.md)

## 문서 사용 방식

- 이 문서는 구현 상세보다 모듈 경계와 요구사항을 맞추기 위한 기준 문서다.
- 각 모듈은 역할, 입력/출력, 필수 요구사항, 제외 범위, 선행 조건 중심으로 정의한다.
- 모든 모듈을 동시에 구현하지 않고, core loop를 먼저 완성하는 순서로 접근한다.

## 우선순위 레벨

- `P0`: 첫 번째 end-to-end loop를 만들기 위해 필수
- `P1`: QA agent로서의 가치가 분명해지는 확장
- `P2`: 설치성, 운영성, 제품화 완성도

## 모듈 요구사항

### 1. `shared`

**우선순위**

- `P0`

**역할**

- 전체 서브모듈이 공통으로 사용하는 config, logger, tracing, util 계층

**입력 / 출력**

- 입력: 없음 (다른 모듈에 의해 import)
- 출력: config loader, logger instance, tracing context, 공통 util

**필수 요구사항**

- 환경 변수 기반 config loading
- 구조화된 로깅 (JSON 등)
- 다른 계층에서 일관되게 사용할 수 있는 공통 interface

**제외 범위**

- 다른 서브모듈에 대한 의존
- domain logic

**선행 조건**

- 없음

**완료 기준**

- `src/core/*`, `src/runtime/*`, `src/adapters/*`, `src/app/*`가 공통 설정과 로깅을 `shared`만 보고 사용할 수 있음

### 2. `core/contracts`

**우선순위**

- `P0`

**역할**

- 시스템 전체에서 사용하는 공통 이벤트와 도메인 타입의 기준점

**입력 / 출력**

- 입력: GitHub, ChatOps, CI 등 외부 source에서 정규화한 이벤트 정의
- 출력: 다른 모듈이 공통으로 사용하는 event, context, result type

**필수 요구사항**

- `PROpened`, `PRUpdated`, `PRCommented`, `PRReviewed`, `CICompleted`, `ChatMention` 이벤트 타입 정의
- risk level, validation result, strategy result, renderer payload를 위한 기본 타입 정의
- provider별 payload가 아니라 시스템 내부 표준 타입을 기준으로 삼을 것

**제외 범위**

- GitHub raw payload parsing
- Slack / Teams SDK 의존 로직

**선행 조건**

- 없음

**완료 기준**

- `app/gateway`, `runtime/orchestrator`, `core/analyzer`, `adapters/renderers`가 모두 이 모듈의 타입만 보고 연결 가능

### 3. `app/gateway`

**우선순위**

- `P0`

**역할**

- 외부 이벤트를 받아 공통 이벤트로 normalize하고 worker 또는 orchestrator 경로로 넘기는 진입점

**입력 / 출력**

- 입력: GitHub webhook, 이후 Slack/Teams webhook
- 출력: normalized event, enqueue 요청

**필수 요구사항**

- GitHub webhook 수신과 signature 검증
- 최소한 `PROpened`, `CICompleted` 이벤트 변환 지원
- correlation id 또는 context key 생성
- 재시도 가능한 방식으로 worker에 전달

**제외 범위**

- diff 분석
- 전략 판단
- runtime validation 실행

**선행 조건**

- `shared`
- `core/contracts`
- `adapters/connectors` (GitHub 검증/조회 helper)

**완료 기준**

- GitHub 이벤트 하나를 받아 `app/worker`에서 처리 가능한 입력으로 넘길 수 있음

### 4. `runtime/orchestrator`

**우선순위**

- `P0`

**역할**

- 이벤트를 받아 core loop를 어떤 순서로 실행할지 제어하는 workflow 계층

**입력 / 출력**

- 입력: normalized event, prior context
- 출력: analyzer, strategy, validation, renderer 호출 순서와 실행 결과

**필수 요구사항**

- PR 이벤트와 CI 이벤트를 같은 context로 묶을 수 있어야 함
- Behaviour Analyzer -> Strategy Engine -> Runtime Validator -> Renderer 순서를 통제할 수 있어야 함
- validation 실행 여부를 risk level, event type, policy 기준으로 분기할 수 있어야 함

**제외 범위**

- 각 모듈 내부의 판단 로직
- storage provider 세부 구현

**선행 조건**

- `shared`
- `core/contracts`

**완료 기준**

- core loop가 한 곳에서 추적 가능하고, 각 모듈이 독립 교체 가능함

### 5. `app/worker`

**우선순위**

- `P0`

**역할**

- `runtime/orchestrator`를 실제로 실행하는 background processing entrypoint

**입력 / 출력**

- 입력: queue에 적재된 event job
- 출력: 실행 로그, renderer 호출 결과, 실패 상태

**필수 요구사항**

- queue job 실행
- retry / timeout / failure reporting 기본 구조
- Microsoft Agent Framework runner를 붙일 수 있는 실행 컨텍스트 제공

**제외 범위**

- webhook 수신
- 최종 출력 포맷 정의

**선행 조건**

- `shared`
- `runtime/orchestrator`

**완료 기준**

- 단일 이벤트 기준으로 worker가 end-to-end loop를 완료할 수 있음

### 6. `core/analyzer`

**우선순위**

- `P0`

**역할**

- 변경 사실을 요약하고 영향 범위와 리스크를 추정하는 계층

**입력 / 출력**

- 입력: diff, changed files, PR metadata, 관련 이벤트 맥락
- 출력: change summary, affected area, risk classification

**필수 요구사항**

- 변경 파일 분류
- API / UI / config / infra 정도의 기본 영향 범위 분류
- High / Medium / Low 수준의 기본 risk 판단

**제외 범위**

- 어떤 검증을 수행할지 최종 결정
- 채널별 출력 문구 생성

**선행 조건**

- `shared`
- `core/contracts`

**완료 기준**

- 사람 리뷰 없이도 PR의 핵심 변경 요지를 구조화된 결과로 낼 수 있음

### 7. `core/strategy`

**우선순위**

- `P0`

**역할**

- behaviour analysis를 바탕으로 어떤 검증을 해야 할지 결정하는 계층

**입력 / 출력**

- 입력: analyzer 결과, 고객 QA knowledge, 정책 정보
- 출력: checklist, validation plan, follow-up suggestion

**필수 요구사항**

- 위험 수준에 따라 검증 강도를 다르게 제안
- MVP 범위에서 API contract, UI flow 중심 checklist 생성
- knowledge가 연결되면 과거 패턴을 반영할 수 있어야 함

**제외 범위**

- 실제 runtime validation 실행
- GitHub/Slack comment formatting

**선행 조건**

- `core/analyzer`
- `core/knowledge`

**완료 기준**

- 같은 analyzer 결과에 대해 일관된 전략 출력이 가능함

### 8. `runtime/validator`

**우선순위**

- `P1`

**역할**

- `core/strategy`가 선택한 검증을 실제 런타임에서 수행하는 계층

**입력 / 출력**

- 입력: validation plan, runtime context, policy
- 출력: probe result, evidence, failure summary

**필수 요구사항**

- MVP는 API contract probe부터 시작
- 이후 UI flow probe를 추가 가능해야 함
- timeout, partial failure, skipped result를 표현할 수 있어야 함
- destructive action 없이 bounded autonomy 정책을 따라야 함

**제외 범위**

- strategy selection
- CI event ingestion

**선행 조건**

- `core/strategy`
- Microsoft Agent Framework execution path

**완료 기준**

- 전략 결과를 실제 검증 결과로 연결할 수 있음

### 9. `core/knowledge`

**우선순위**

- `P0`

**역할**

- 고객 QA 지식 자산에 접근하는 port, query model, in-memory mock을 제공하는 논리 경계

**입력 / 출력**

- 입력: domain, repo, incident, pattern, checklist, strategy key
- 출력: matching knowledge, stored knowledge, update result

**필수 요구사항**

- `core/strategy`가 저장 위치를 모르고도 knowledge를 조회 가능해야 함
- read path와 write path를 분리해 다룰 수 있어야 함
- backing store 교체 가능성을 전제로 interface를 유지할 것
- P0 단계에서 interface와 mock/in-memory adapter를 확보하여 strategy가 즉시 연결 가능해야 함

**제외 범위**

- 실제 저장소 선택의 최종 결정
- 제품 기본 문서 자산 관리

**선행 조건**

- `shared`
- `core/contracts`

**완료 기준**

- mock adapter만으로도 `core/strategy`와 연결 가능

### 10. `adapters/knowledge`

**우선순위**

- `P1`

**역할**

- markdown, vector, database 등 실제 backing store adapter를 구현하는 외부 연동 계층

**입력 / 출력**

- 입력: `core/knowledge` port가 정의한 read/write 요청
- 출력: backing store 조회 및 저장 결과

**필수 요구사항**

- `core/knowledge` interface를 구현할 것
- 저장소별 세부사항을 `core` 밖에 가둘 것
- backing store 교체 가능성을 보장할 것

**제외 범위**

- 전략 생성
- workflow orchestration

**선행 조건**

- `core/knowledge`

**완료 기준**

- 실제 backing store adapter가 동작하고 교체 가능함

### 11. `adapters/renderers`

**우선순위**

- `P0`

**역할**

- 공통 판단 결과를 채널별 출력 형태로 변환하는 계층

**입력 / 출력**

- 입력: analysis result, strategy result, validation result
- 출력: PR comment payload, chat response payload

**필수 요구사항**

- GitHub PR comment용 구조화 출력 우선 지원
- 이후 Slack/Teams 자연어 응답 포맷 확장 가능해야 함
- 판단 로직을 넣지 않고 formatting만 담당할 것

**제외 범위**

- risk 판단
- validation 실행

**선행 조건**

- `core/contracts`
- analyzer / strategy result shape 확정

**완료 기준**

- 같은 결과를 PR / chat 채널에 맞게 다르게 표현 가능

### 12. `adapters/connectors`

**우선순위**

- `P0` (GitHub connector — gateway가 webhook 검증, diff 조회 등에 필요)
- `P1` (ChatOps, LLM, storage provider connector)

**역할**

- GitHub, Slack, Teams, LLM provider, storage provider와의 외부 연동 wrapper

**입력 / 출력**

- 입력: channel-specific request
- 출력: external API call result

**필수 요구사항**

- provider SDK를 domain logic와 분리
- GitHub connector와 ChatOps connector를 독립적으로 교체 가능해야 함
- runtime/knowledge/storage provider와의 결합을 connector 밖으로 새지 않게 할 것

**제외 범위**

- 전략 생성
- workflow orchestration

**선행 조건**

- `shared`
- `core/contracts`

**완료 기준**

- P0: GitHub connector가 동작하고 mocking이 가능함
- P1: ChatOps, LLM 등 추가 connector 교체 가능

### 13. `app/cli`

**우선순위**

- `P2`

**역할**

- 설치, 초기 설정, 로컬 점검을 위한 사용자 진입점

**입력 / 출력**

- 입력: init/configure/up 등 명령
- 출력: config 파일, bootstrap 결과, health 상태

**필수 요구사항**

- self-hosted 설치 흐름의 진입점 역할
- GitHub / ChatOps / runtime 설정 가이드를 제공
- local health check 또는 bootstrap validation 지원

**제외 범위**

- core loop의 핵심 판단 로직

**선행 조건**

- `app/gateway`
- `app/worker`
- `shared`

**완료 기준**

- repo를 직접 읽지 않아도 설치 흐름을 따라갈 수 있음

### 14. `tests/replay`

**우선순위**

- `P0`

**역할**

- 실제 이벤트 사례를 replay하여 regression을 막는 검증 자산

**입력 / 출력**

- 입력: captured event fixture, expected result
- 출력: replay test pass/fail

**필수 요구사항**

- 최소한 PR opened, CI completed 시나리오 replay 지원
- analyzer 결과와 renderer 결과를 회귀 검증할 수 있어야 함
- 새로운 버그나 edge case가 생기면 fixture로 추가 가능해야 함

**제외 범위**

- 전체 end-to-end 배포 검증 대체

**선행 조건**

- `core/contracts`
- `tests/fixtures/`에 샘플 payload가 존재

**완료 기준**

- 주요 회귀가 fixture 단에서 반복 재현 가능

## 권장 개발 순서

### 개발 순서 원칙

- 처음부터 모든 trigger source와 모든 검증 도메인을 동시에 구현하지 않는다.
- 첫 번째 vertical slice는 GitHub PR 기반 흐름으로 잡는다.
- Behaviour Analyzer와 Strategy Engine은 분리 구현하되, 초반에는 deterministic logic과 제한된 runtime 실행으로 시작한다.
- `core/knowledge`는 초기에 interface와 mock 경계부터 잡고, `adapters/knowledge` 고도화는 뒤에서 다룬다.
- replay 가능한 fixture와 통합 테스트를 초반부터 준비해 이후 변경에 흔들리지 않게 한다.
- 설치 UX와 runtime 운영은 분리한다. 제품 배포는 최종적으로 CLI + self-hosted runtime 흐름으로 수렴시킨다.

### 단계별 개발 순서

| Step | 목표                              | 주요 모듈                                                                                                | 완료 기준                                                       |
| ---- | --------------------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 0    | 엔지니어링 베이스라인 확정        | `pyproject.toml`, CI, 개발 규칙                                                                          | 빈 엔트리포인트 실행 가능, ruff/mypy/pytest 통과                |
| 1    | 공통 계약과 replay 기반 개발 틀   | `shared`, `core/contracts`, `tests/replay`                                                               | 샘플 payload → 공통 이벤트 변환, replay 테스트 1개 이상         |
| 2    | Event → Worker → Output 골격 연결 | `app/gateway`, `app/worker`, `runtime/orchestrator`, `adapters/connectors`(GitHub), `adapters/renderers` | PR 이벤트 → worker → stub 결과 반환                             |
| 3    | GitHub PR 분석 vertical slice     | `core/analyzer`, `core/strategy`, `core/knowledge`(interface+mock), `adapters/renderers`                 | PR 오픈 시 Behaviour Impact Report 자동 생성                    |
| 4    | CI 결과 피드백 루프               | `runtime/orchestrator`, `core/strategy`, `adapters/renderers`                                            | CI 실패를 PR 맥락에 엮어 설명 가능                              |
| 5    | Runtime Validation MVP            | `runtime/validator`, Microsoft Agent Framework 연결                                                      | 선택된 PR에 대해 runtime validation 실행 및 결과 반영           |
| 6    | ChatOps 흐름 연결                 | `app/gateway`(chat), `adapters/connectors`(ChatOps), `adapters/renderers`                                | `@qaestro` 호출 시 전략 제안, PR 맥락과 연결                    |
| 7    | Knowledge Store 실 adapter 적용   | `adapters/knowledge`, `core/strategy`                                                                    | 실제 backing store 연결, 과거 패턴 조회 가능, adapter 교체 가능 |
| 8    | CLI와 self-hosted 설치 흐름       | `app/cli`                                                                                                | repo 소스 이해 없이 CLI로 설치/실행 가능                        |
| 9    | 운영 안정화 및 베타 준비          | telemetry, permission, 문서                                                                              | 내부 dogfooding 또는 design partner 테스트 가능                 |

### 병렬 개발 권장 구간

- Step 0 ~ 2는 가급적 순차 진행
- Step 3부터는 `core/analyzer`, `core/strategy`, `adapters/renderers`를 병렬 진행 가능
- Step 5와 Step 6은 공통 orchestration이 잡힌 뒤 병렬 진행 가능
- Step 7(`adapters/knowledge`)은 Step 5 ~ 6과 병렬 진행 가능 (`core/knowledge` interface는 Step 3에서 확보됨)
- Step 8 ~ 9는 제품 기능이 일정 수준 붙은 뒤 진행

### 권장 마일스톤

| 마일스톤                   | 범위       | 결과                                     |
| -------------------------- | ---------- | ---------------------------------------- |
| A. GitHub-only 분석 MVP    | Step 0 ~ 4 | PR과 CI 결과에 대해 구조화된 QA 코멘트   |
| B. Runtime Validation MVP  | Step 5     | 전략 판단을 실제 runtime 검증까지 연결   |
| C. ChatOps + Knowledge MVP | Step 6 ~ 7 | 채널 호출과 지식 조회를 포함한 협업 흐름 |
| D. Self-hosted 베타        | Step 8 ~ 9 | CLI 기반 설치와 내부 운영 가능           |

### 각 단계의 Definition of Done

- 해당 단계의 핵심 플로우를 재현하는 replay 또는 integration 테스트가 존재한다.
- 로그와 에러 메시지만으로 실패 원인을 추적할 수 있다.
- 다음 단계 진행에 필요한 문서와 샘플 fixture가 남아 있다.
- 기능은 들어갔지만 운영할 수 없는 상태로 넘기지 않는다.

## 모듈 정의 시 계속 확인할 질문

- 이 모듈은 사실을 분석하는가, 판단을 하는가, 실행을 하는가, 출력만 하는가?
- 이 모듈이 외부 provider 세부사항을 알아야 하는가?
- 이 모듈은 교체 가능한가, 아니면 core policy를 담고 있는가?
- 이 모듈은 지금 `P0`인가, 아니면 나중에 붙여도 되는가?
- 이 모듈의 결과를 replay 테스트로 고정할 수 있는가?
