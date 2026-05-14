# Technical Decisions

qaestro의 배포 모델, Agent Runtime, 운영 경계 같은 기술 선택 사항을 정리하는 문서.

아키텍처 문서는 컴포넌트 구조와 흐름을 설명하고, 이 문서는 "어떤 기술적 방향을 택할지"를 정리한다. 제품 포지셔닝과 다른 agent/runtime 대비 경계는 [PRODUCT_POSITIONING.md](./PRODUCT_POSITIONING.md)에 둔다. 기술 선택은 이후 변경 가능성이 높기 때문에 별도 문서로 관리한다.

관련 문서:

- [README.md](../README.md)
- [PRODUCT_POSITIONING.md](./PRODUCT_POSITIONING.md)
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
- 진입점은 `[project.scripts]`로 등록한다 (`qaestro-gateway = "src.app.gateway:main"`, `qaestro-worker = "src.app.worker:main"` 등).

### 4. Agent Framework: Microsoft Agent Framework

qaestro의 1차 agent execution framework는 `Microsoft Agent Framework`를 사용한다.

Microsoft Agent Framework는 agent 실행, tool 호출, streaming, hosting을 담당하고, 이벤트 해석, workflow 제어, validation sequencing 같은 도메인 로직은 qaestro의 `runtime/orchestrator`가 계속 책임진다.

- self-hosted HTTP server 패턴으로 배포 가능한 구조를 우선한다.
- `src.app.worker`: Agent Framework runner와 execution context host
- `src.runtime.validator`: runtime probe를 Agent Framework tool/executor path와 연결
- `src.runtime.orchestrator`: framework 호출 순서와 도메인 workflow를 연결하는 실행 제어 계층
- core domain logic는 Framework 객체 타입에 직접 종속되지 않도록 유지한다.

qaestro의 autonomy model은 완전 자율 agent가 아니라, **bounded tool autonomy**를 기준으로 한다. Orchestrator가 PR 분석, 전략 수립, 검증, 출력 같은 큰 흐름과 단계별 policy를 정하고, agent는 해당 단계에서 허용된 GitHub/ChatOps/knowledge/runtime tool을 선택적으로 사용한다. 예를 들어 PR 분석 단계에서는 PR metadata, diff, comments, related chat thread를 읽을 수 있지만, comment 작성 같은 write action은 output 단계와 write policy를 거쳐 수행한다.

Step 3.5의 ToolRuntime 전환은 이 방향을 코드 경계로 고정하기 위한 중간 단계다. 외부 webhook input event는 계속 gateway가 normalized event로 변환하며, tool call로 대체하지 않는다. GitHub backend도 당분간 기존 GitHub Client API adapter를 유지한다. 이번 결정의 핵심은 API transport를 CLI로 바꾸는 것이 아니라, `Worker`/workflow가 `GitHubClient`, PR context provider, comment poster 같은 concrete read/write dependency를 직접 들고 있지 않도록 narrow tool capability 뒤로 이동시키는 것이다. Agent Framework runner가 들어오기 전까지 tool 선택은 deterministic sequence로 구현해도 되지만, 모든 read/write는 같은 `ToolRuntime` contract와 stage allowlist를 통과해야 한다.

### 5. PR review lifecycle: deferred unified review + manual trigger first

qaestro는 PR opened, PR synchronize, workflow_run completed, GitHub comment/review, ChatOps mention을 별도 이벤트로 수신하되, 판단과 출력은 PR 단위 aggregate state에서 종합한다. 권장 MVP는 manual-trigger first다. 사용자가 PR 또는 channel에서 `@qaestro review`처럼 명시적으로 요청하면 current PR aggregate를 만들고, current `head_sha` 기준 CI/check snapshot을 확인한 뒤 가능한 경우 unified review를 수행한다. 자동 리뷰는 이후 repo 설정으로 opt-in/optional하게 확장한다.

공식 final review는 관련 CI/check가 완료된 뒤 내는 것을 기본으로 한다. `workflow_run completed` 이벤트 하나는 한 workflow가 끝났다는 신호일 뿐이므로, final review readiness는 current head의 check runs/workflow runs를 다시 조회해 pending/queued/in-progress 항목이 남았는지 확인해야 한다. 5~10분 대기는 정상 범위로 보고, 장시간 pending은 timeout 후 partial review로 표시한다. 사용자가 직접 호출한 경우에는 조용히 기다리지 말고 현재 상태 기준의 interim response를 즉시 제공하되, 남은 workflow/check와 최종 판단 보류를 명시한다.

PR aggregate는 PR 전체 수명과 대화 history를 유지하고, 그 안에 `PRRevisionState(head_sha)`와 `ReviewRun`을 여러 개 둔다. 새 commit은 새 revision을 만들며 이전 revision의 분석/CI는 stale로 표시한다. 이전 결과는 “같은 실패가 반복되는가”, “이전 finding이 해소됐는가” 같은 historical evidence로 참고할 수 있지만, current verdict의 source of truth는 current head diff와 current head CI/check 결과다.

출력은 세 가지 surface로 구분한다. PR-level managed summary comment는 qaestro의 대표 리포트로 create/update되고, CI/check 요약과 주요 finding을 포함한다. GitHub review/inline comment는 final unified review 시점에 file/line/range 단위로 batch 작성한다. ChatOps 응답은 같은 aggregate state를 사용하지만 대화형 질문에 맞춰 짧게 답한다.

### 6. 모델 제공 방식: BYOK

- `BYOK`를 전제로 설계
- provider 선택은 추후 결정
- core 계층은 특정 provider에 직접 종속되지 않도록 유지

### 7. Queue backend: Redis Streams for process separation

Step 2의 기본 local/test 구현은 `InMemoryJobQueue`를 유지한다. 단일 프로세스에서 gateway와 worker contract를 검증하기 쉽기 때문이다. 하지만 실제 배포에서는 `qaestro-gateway`와 `qaestro-worker`가 별도 프로세스로 실행되므로 메모리 queue는 공유되지 않는다.

별도 프로세스 연결에는 Redis Streams를 사용한다.

- gateway는 normalized `EventJob`을 stream에 `XADD`한다.
- worker는 consumer group으로 job을 읽고, 처리 후 `XACK`한다.
- worker 재시작/장애 후에는 stale pending message를 claim해서 재처리할 수 있다. 기본 claim idle은 300000ms(5분)로 두며, 운영에서는 정상 처리 중인 long-running job이 중복 claim되지 않도록 최대 처리 시간보다 크게 잡는다.
- Step 2에서는 worker process를 long-lived consumer로 실행한다. `memory` backend만 local drain-and-exit 모드로 동작한다.
- 실패 job은 retry가 모두 끝난 뒤 ack하고 `correlation_id`, `delivery_id`, `attempts`, `error`를 포함한 structured error log를 남긴다. dead-letter 저장소와 운영 모니터링은 Step 9에서 확장한다.

Redis Streams를 우선 선택한 이유는 Step 2 목표인 gateway/worker process 분리를 가장 낮은 운영 부담으로 검증할 수 있고, NATS JetStream보다 현재 self-hosted MVP의 도입면이 작기 때문이다. NATS JetStream은 이벤트 버스 중심 구조가 커질 때 다시 검토한다.

## Microsoft Agent Framework 적용 시 고려 사항

- preview 단계 SDK이므로 버전 pinning 필요
- framework type과 core business logic 분리 필요
- self-hosted HTTP server 패턴과 worker 실행 모델을 함께 설계할 것

## 추후 논의

- [PR aggregate와 unified review lifecycle](./notes/PR_REVIEW_LIFECYCLE.md)
