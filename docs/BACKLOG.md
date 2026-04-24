# Backlog

## Parking Lot (추후 논의)

### 고객 QA knowledge 저장소

- 고객 QA 지식 자산의 실제 backing store를 무엇으로 둘지
- Git repo, mounted directory, database, object storage, vector store 중 어떤 구성이 적절한지
- 고객별 / workspace별 / repo별 scope를 어떻게 나눌지
- import/export, backup, versioning, migration을 어떤 방식으로 다룰지
- CLI 초기 설정 시 knowledge source를 어떻게 연결할지

### 확장축 방향

- 이 프로젝트의 핵심 차별화는 "무엇을 검증할지를 스스로 판단하고, 그 판단을 진화시키는 것"
- 확장축 후보:
  - **검증 도메인** — MVP에서 API contract, UI flow 시작 → DB 정합성, 성능 등으로 확장
  - **맥락 이해의 깊이** — 단일 PR → 연속된 PR 흐름에서 누적 drift 감지
  - **전략 정밀도** — 범용 제안 → repo 히스토리 기반 맞춤 제안
  - **자율성 수준** — 제안만 → 테스트 코드 자동 생성/수정

### PRClosed 이벤트

- 현재 이벤트 스키마에 `PRClosed`가 없음 (`EventType`에도 해당 멤버 부재)
- 필요해질 수 있는 시나리오:
  - **merged vs closed 구분** (`action=closed` + `merged=true/false`) — merged PR의 QA 리포트를 Knowledge Store에 영구 저장할지 결정
  - **진행 중 validation 취소** — PR이 닫히면 running job 중단, 임시 artifact 정리
  - **correlation_id 수명 관리** — 종료 시점에 리소스 정리
- 결정 보류: Step 2 orchestrator + Knowledge Store 설계가 확정된 뒤에 추가 (그 때 `merged: bool` 필드와 함께)

### MVP 성공 지표

- Agent의 Risk 판단 정확도를 어떻게 측정할 것인지
- False positive 과다 시 개발자가 무시하게 되는 문제
- Precision/Recall 등 정량 지표 또는 "Agent가 잡은 이슈 중 실제 문제 비율" 측정 구조 필요
