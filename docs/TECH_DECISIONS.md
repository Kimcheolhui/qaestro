# Technical Decisions

qaestro의 배포 모델, Agent Runtime, 운영 경계 같은 기술 선택 사항을 정리하는 문서.

아키텍처 문서는 컴포넌트 구조와 흐름을 설명하고, 이 문서는 "어떤 기술적 방향을 택할지"를 정리한다. 기술 선택은 이후 변경 가능성이 높기 때문에 별도 문서로 관리한다.

관련 문서:

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)
- [BACKLOG.md](./BACKLOG.md)

## 현재 방향

### 1. 배포 모델: self-hosted

qaestro는 self-hosted 배포를 기준으로 설계한다.

### 2. 구현 언어: Python

qaestro의 구현 언어는 `Python`을 기준으로 한다.

- AI/ML 생태계와의 통합이 자연스럽다. LLM SDK, embedding, vector store 등 핵심 의존성을 같은 언어로 묶기 좋다.
- 코드 루트 `src/` 아래를 `app`, `core`, `runtime`, `adapters`, `shared`로 나눠 아키텍처 경계를 구성한다.
- `Microsoft Agent Framework`를 적용할 수 있고, agent/tooling 계층을 같은 언어로 묶기 좋다.

### 3. 패키지 관리: uv

의존성 관리에 `uv`를 사용한다.

- 루트에 단일 `pyproject.toml`만 둔다. workspace를 쓰지 않는다.
- 코드 루트는 `src/` 하나로 유지한다.
- `uv sync`로 가상환경을 관리하고, `uv.lock`으로 의존성을 고정한다.
- 진입점은 `[project.scripts]`로 등록한다 (`gateway = "src.app.gateway:main"`, `worker = "src.app.worker:main"` 등).

### 4. Agent Framework: Microsoft Agent Framework

qaestro의 1차 agent execution framework는 `Microsoft Agent Framework`를 사용한다.

Microsoft Agent Framework는 agent 실행, tool 호출, streaming, hosting을 담당하고, 이벤트 해석, workflow 제어, validation sequencing 같은 도메인 로직은 qaestro의 `runtime/orchestrator`가 계속 책임진다.

- self-hosted HTTP server 패턴으로 배포 가능한 구조를 우선한다.
- `src.app.worker`: Agent Framework runner와 execution context host
- `src.runtime.validator`: runtime probe를 Agent Framework tool/executor path와 연결
- `src.runtime.orchestrator`: framework 호출 순서와 도메인 workflow를 연결하는 실행 제어 계층
- core domain logic는 Framework 객체 타입에 직접 종속되지 않도록 유지한다.

### 5. 모델 제공 방식: BYOK

- `BYOK`를 전제로 설계
- provider 선택은 추후 결정
- core 계층은 특정 provider에 직접 종속되지 않도록 유지

## Microsoft Agent Framework 적용 시 고려 사항

- preview 단계 SDK이므로 버전 pinning 필요
- framework type과 core business logic 분리 필요
- self-hosted HTTP server 패턴과 worker 실행 모델을 함께 설계할 것

## 추후 논의
