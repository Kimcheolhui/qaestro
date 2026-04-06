# Technical Decisions

devclaw의 배포 모델, Agent Runtime, 운영 경계 같은 기술 선택 사항을 정리하는 문서.

아키텍처 문서는 컴포넌트 구조와 흐름을 설명하고, 이 문서는 "어떤 기술적 방향을 택할지"를 정리한다. 기술 선택은 이후 변경 가능성이 높기 때문에 별도 문서로 관리한다.

관련 문서:

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)
- [BACKLOG.md](./BACKLOG.md)

## 현재 방향

### 1. 배포 모델: self-hosted

devclaw는 self-hosted 배포를 기준으로 설계한다.

### 2. 구현 언어 및 애플리케이션 베이스: TypeScript / Node.js

devclaw의 구현 언어와 애플리케이션 베이스는 `TypeScript / Node.js`를 기준으로 한다.

- GitHub, Slack/Teams, CI 같은 외부 이벤트를 받아 처리하는 서버형 제품 구조와 잘 맞는다.
- `apps/*`, `packages/*`로 나누는 monorepo 구조에서 계약, orchestration, connector 경계를 일관되게 유지하기 쉽다.
- `GitHub Copilot SDK`를 runtime으로 둘 때 session orchestration과 주변 서비스 계층을 같은 언어로 묶기 좋다.

### 3. Agent Runtime: GitHub Copilot SDK

devclaw의 Agent Runtime은 `GitHub Copilot SDK`를 사용한다.

Agent Runtime은 Copilot SDK를 사용하되, 이벤트 해석, workflow 제어, validation sequencing을 담당하는 orchestration layer는 MVP 단계에서 직접 구현한다.

- Copilot CLI 기반 agent runtime 사용
- tool 호출 지원
- session 생성, 재개, 조회, 삭제 지원
- permission handler, hooks 지원
- custom tools, MCP server, custom agent/skill 연결 지원
- streaming, telemetry 지원

runtime SDK는 core logic와 분리한다.

- `apps/worker`: SDK session orchestration
- `packages/runtime-validator`: runtime probe 실행
- 필요 시 `packages/agent-runtime`: Copilot SDK wrapper 계층 추가

### 4. 모델 제공 방식: BYOK

- `BYOK`를 전제로 설계
- provider 선택은 추후 결정
- core package는 특정 provider에 직접 종속되지 않도록 유지

## Copilot SDK 적용 시 고려 사항

- Public Preview / Technical Preview 단계
- Copilot CLI server mode 의존
- runtime SDK와 core business logic 분리 필요

## 추후 논의
