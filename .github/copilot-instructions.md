# devclaw — Copilot Instructions

Embedded QA Agent for Agentic Development Environments. 단일 Python 코드 루트.

## 프로젝트 구조

```
src/            — 단일 Python 코드 루트. 아래 그룹으로 구성
  app/          — 진입점 계층
    gateway/    — webhook 수신, 이벤트 normalize
    worker/     — background job 실행
    cli/        — 설치, 설정, 로컬 점검
  core/         — 도메인 판단 계층
    contracts/  — 공통 이벤트, 도메인 타입
    analyzer/   — diff 분석, 영향 범위, 리스크 분류
    strategy/   — 검증 전략, checklist 생성
    knowledge/  — QA 지식 자산 port, query model
  runtime/      — 실행 흐름 계층
    orchestrator/ — workflow 제어, 맥락 묶기
    validator/    — 런타임 검증 실행 (probes)
  adapters/     — 외부 연동 / 출력 계층
    connectors/ — 외부 SDK wrapper (GitHub, Slack, LLM 등)
    renderers/  — 채널별 출력 포맷
    knowledge/  — knowledge backing store adapter
  shared/       — config, logger, tracing, util
tests/          — fixtures, integration, e2e, replay
docs/           — 설계 문서
```

## 아키텍처 레이어 매핑

| 레이어             | 서브모듈                                                  |
| ------------------ | --------------------------------------------------------- |
| Event Ingestion    | `app/gateway`, `core/contracts`, `runtime/orchestrator`   |
| Behaviour Analyzer | `core/analyzer`                                           |
| Strategy Engine    | `core/strategy`                                           |
| Runtime Validation | `runtime/validator`                                       |
| Knowledge Store    | `core/knowledge`, `adapters/knowledge`                    |
| Output             | `adapters/renderers`, `adapters/connectors`, `app/worker` |

## 의존 방향

- `src/app/*` → `src/core/*`, `src/runtime/*`, `src/adapters/*`, `src/shared`. app이 다른 계층을 사용한다.
- `src/runtime/orchestrator`만 여러 core 서브모듈과 output adapter를 동시에 호출한다.
- `src/core/*` 간 직접 의존은 최소화한다.
- `src/core/strategy` → `src/core/knowledge` interface를 통해서만 지식 자산에 접근한다.
- `src/adapters/connectors`는 외부 SDK wrapper 역할만 한다. domain logic을 넣지 않는다.
- `src/adapters/renderers`는 출력 포맷 변환만 한다. 판단 로직에 개입하지 않는다.

## 기술 스택

- 언어: Python
- 구조: 단일 코드 루트 (`src`) + 그룹형 서브모듈 (`app/core/runtime/adapters/shared`)
- Agent Framework: Microsoft Agent Framework
- 배포: self-hosted
- 모델: BYOK (특정 provider에 직접 종속하지 않음)

## 설계 문서 참조

상세 설계 결정이 필요하면 아래 문서를 참고한다.

- `docs/ARCHITECTURE.md` — 컴포넌트 구조, 이벤트 흐름
- `docs/PROJECT_STRUCTURE.md` — 폴더 구조, 의존 방향, 그룹/서브모듈별 책임
- `docs/TECH_DECISIONS.md` — 배포 모델, 언어, runtime, 모델 제공 방식
- `docs/MODULE_REQUIREMENTS.md` — 모듈별 요구사항, 우선순위
- `docs/BACKLOG.md` — 미결 사항, 확장축
