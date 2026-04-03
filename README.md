# devclaw

**Embedded QA Agent for Agentic Development Environments**

Agentic 개발 환경에서 코드 변경의 의도를 이해하고, System Behaviour 정합성을 자율적으로 검증하며, QA 전략을 지속적으로 진화시키는 QA Agent.

---

## Problem

Agentic Development 환경에서 AI 코드 생성, PR 속도, 리팩토링 빈도가 급증하고 있다. 그러나 QA는 여전히 `PR → Test Execution` 형태의 CI 중심 Validation에 머물러 있다.

CI 기반 테스트는 Function 단위 검증에는 효과적이지만, System Behaviour의 정합성을 충분히 보장하지 못한다. 이 한계는 예전부터 존재했으나, Agentic 개발로 변경 빈도가 급증하면서 사람의 QA 작업이 병목이 되었다.

- QA를 줄이고 빠르게 배포 → **Behaviour Drift가 Production에서 발견됨**
- QA를 충실히 수행 → **개발 속도 대비 QA가 병목**

## Goal

Agentic 개발 환경(ChatOps + PR + CI Loop)에 참여하여, Repository의 변화 방향을 지속적으로 모니터링·학습하고, System Behaviour의 정합성을 평가하는 **Embedded QA Agent**를 설계 및 구현한다.

- 기존의 Test Code 기반 CI + Human QA 작업을 QA Agent에게 위임
- 개발자는 QA 엔지니어와 협업하듯 QA Agent와 자연스럽게 일할 수 있음
- Agentic 개발 속도에 Human QA가 병목이 되지 않으면서, System Behaviour 수준의 품질 검증을 유지

## Agent의 역할

이 Agent는 테스트의 **실행 도구**가 아니라 **전략 레이어**다.

API contract 검증이나 UI flow 검증 자체는 기존 도구(Pact, Playwright 등)로 충분하다. 이 Agent가 풀어야 할 것:

- 코드 변경 시 **어떤 테스트가 필요한지, 부족한지, 깨질 수 있는지를 추론**
- 그 판단을 repo 히스토리와 과거 패턴 기반으로 **점점 정밀하게** 만드는 것
- QA 전략을 반영하여 테스트를 **dynamic하게 추가하거나, 자가 개선을 제안**

API contract, UI flow 등은 전략이 **적용되는 도메인**이며, Agent의 역할 자체와는 구분된다.

## Conceptual Scope

### 1. Development Phase
- 개발자가 Slack/Teams 협업 채널에서 `@devclaw` 태그 시, 쓰레드 전체를 읽고 변경 의도 파악
- QA Risk 논의 참여, Validation 전략 제안

### 2. CI Phase
- PR/commit 발생 시 repo evolution 기반 영향 추정
- CI 파이프라인 실행 결과 확인 및 분석
- Validation 전략을 기반으로 System Behaviour 정합성 검증 수행

### 3. Agent Loop
```
Code Authoring → Dev Chat (Slack/Teams) → PR 생성 → CI Trigger
→ Execution Feedback → Strategy Adaptation → Memory Update → (반복)
```

### 4. Strategy Evolution
- QA 수행 과정에서 발견된 패턴, 실패 이력, 제품별 특성을 전략으로 메모리화
- 축적된 전략을 이후 검증에 자동 적용하여 Agent의 QA 정밀도가 점진적으로 향상

Slack/Teams는 Test Control Channel이 아닌 **QA Strategy Alignment Interface** 역할을 수행한다.

## MVP

전체 Agent Loop를 단일 repo에서 E2E로 동작시키는 것이 목표. 개발 레이어:

| Layer | Scope | 비고 |
|-------|-------|------|
| 1 | PR diff 분석 → Behaviour Impact Report 생성 | GitHub App 단독으로 동작 가능 |
| 2 | CI 결과 연동 → 실패 원인 추정 + 누락 테스트 제안 | |
| 3 | Slack/Teams 채널 참여 → 변경 의도 파악 + 전략 제안 | |
| 4 | Knowledge store 축적 → Strategy 자동 강화 | 자가 개선 루프 |

**MVP 제외:**
- 다중 repo 지원
- 테스트 코드 자동 생성/실행
- IDE 내 실시간 Agent 패널

## Architecture

```
Core (MIT License)
├── GitHub App / GitLab Webhook
├── Behaviour Analyzer (repo evolution 분석)
├── Strategy Engine (validation 전략 생성/진화)
└── Connectors
    ├── slack / teams
    ├── openai / anthropic / azure-ai / ollama
    └── postgres / mongodb / redis
```

## License

MIT
