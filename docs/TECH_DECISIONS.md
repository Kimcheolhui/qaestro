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

### 5. Queue backend: Redis Streams for process separation

Step 2의 기본 local/test 구현은 `InMemoryJobQueue`를 유지한다. 단일 프로세스에서 gateway와 worker contract를 검증하기 쉽기 때문이다. 하지만 실제 배포에서는 `qaestro-gateway`와 `qaestro-worker`가 별도 프로세스로 실행되므로 메모리 queue는 공유되지 않는다.

별도 프로세스 연결에는 Redis Streams를 사용한다.

- gateway는 normalized `EventJob`을 stream에 `XADD`한다.
- worker는 consumer group으로 job을 읽고, 처리 후 `XACK`한다.
- worker 재시작/장애 후에는 stale pending message를 claim해서 재처리할 수 있다.
- Step 2에서는 worker process를 long-lived consumer로 실행한다. `memory` backend만 local drain-and-exit 모드로 동작한다.
- 실패 job은 retry가 모두 끝난 뒤 ack하고 실패 상태를 로그로 남긴다. dead-letter 저장소와 운영 모니터링은 Step 9에서 확장한다.

Redis Streams를 우선 선택한 이유는 Step 2 목표인 gateway/worker process 분리를 가장 낮은 운영 부담으로 검증할 수 있고, NATS JetStream보다 현재 self-hosted MVP의 도입면이 작기 때문이다. NATS JetStream은 이벤트 버스 중심 구조가 커질 때 다시 검토한다.

## Microsoft Agent Framework 적용 시 고려 사항

- preview 단계 SDK이므로 버전 pinning 필요
- framework type과 core business logic 분리 필요
- self-hosted HTTP server 패턴과 worker 실행 모델을 함께 설계할 것

## 추후 논의
