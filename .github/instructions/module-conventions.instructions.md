---
applyTo: "src/**/*.py"
---

# Python 모듈 규약

## 의존 방향

- `src/app/*` → `src/core/*`, `src/runtime/*`, `src/adapters/*`, `src/shared` 방향으로만 import한다.
- `src/runtime/orchestrator`만 여러 core 서브모듈과 output adapter를 동시에 import할 수 있다.
- core 서브모듈 간 직접 import는 최소화한다. 필요하면 `src/core/contracts`의 공통 타입을 통해 소통한다.
- `src/core/strategy`는 `src/core/knowledge`의 interface를 통해서만 지식 자산에 접근한다. `src/adapters/knowledge` 구현을 직접 import하지 않는다.

## 금지되는 의존

- `src/core/*`, `src/runtime/*`, `src/adapters/*` → `src/app/*` import 금지
- `src/adapters/connectors` 안에 domain logic 금지 (외부 SDK wrapper만)
- `src/adapters/renderers` 안에 판단 로직 금지 (출력 포맷 변환만)
- `src/shared` → 다른 서브모듈 import 금지

## Import 규칙

- 같은 서브모듈 내부: 상대 import (`from . import`, `from .. import`)
- 다른 서브모듈: `from src.core.contracts import ...`, `from src.shared import ...`, `from src.runtime.orchestrator import ...` 등
- 외부 SDK 호출은 `src/adapters/connectors` 안에서만 한다

## 타입 규칙

- 공통 이벤트와 도메인 타입은 `src/core/contracts`에 정의한다
- 이벤트 타입: `PROpened`, `PRCommented`, `PRReviewed`, `CICompleted`, `ChatMention`
- core 서브모듈이 provider별 payload type을 직접 참조하지 않는다. `src/core/contracts`의 시스템 내부 표준 타입만 사용한다
