# 제품 포지셔닝

qaestro는 agentic development 환경을 위한 QA orchestration layer다. Pull request,
CI/check 결과, runtime validation, ChatOps 요청을 하나의 추적 가능한 QA lifecycle로
묶어 코드 변경의 품질 판단을 조율한다.

qaestro는 범용 coding agent, 기존 agent runtime의 prompt/config 모음, 또는 독립적인
테스트 자동화 플랫폼으로 포지셔닝하지 않는다. 이러한 시스템은 qaestro가 사용할 수
있는 실행 계층 또는 통합 대상이 될 수 있지만, qaestro의 제품 경계는 “무엇을 검증해야
하는가”, “언제 충분한 근거가 모였는가”, “어떤 표면에 어떤 형태로 결과를 남길 것인가”를
결정하는 QA workflow에 있다.

## 문제 배경

AI coding 도구는 코드 작성과 변경 속도를 높인다. 그만큼 품질 판단이 필요한 변경도 더
자주 발생한다. 기존 CI는 미리 정의된 check의 성공 여부를 알려주고, human review는
설계와 구현상의 문제를 일부 포착한다. 그러나 PR history, CI timing, stale commit,
manual review request, runtime validation strategy를 하나의 lifecycle로 다루는 지속적인
QA workflow는 별도로 필요하다.

예를 들어 PR에 새 commit이 올라온 뒤 이전 commit의 CI 결과가 뒤늦게 도착할 수 있다.
이때 qaestro는 그 결과를 historical evidence로 보존하되, current head의 최종 판단에는
섞지 않아야 한다. 반대로 사용자가 checks가 끝나기 전에 `@qaestro review`를 요청하면,
조용히 기다리는 대신 현재 aggregate state를 기준으로 interim response를 제공하고 어떤
checks가 아직 남아 있는지 알려야 한다.

qaestro는 이 조율 계층에 집중한다.

```text
PR / CI / comment / ChatOps events
→ PR-level aggregate state
→ current-head readiness decision
→ behaviour analysis and validation strategy
→ managed PR summary, inline review, or interactive response
```

목표는 단순히 diff를 리뷰하는 것이 아니다. 무엇이 변경됐고, 어떤 근거가 이미 있으며,
무엇이 아직 검증되지 않았고, 현재 시점에 어떤 응답이 적절한지를 신뢰할 수 있는 형태로
유지하는 것이다.

## 범용 agent runtime과의 차이

범용 agent runtime은 messaging gateway, tool execution, memory, skill, scheduled job,
sandbox, model/provider abstraction 같은 기반 기능을 제공한다. 이런 기능은 qaestro를
구현하는 데 유용하지만, 그 자체가 QA 제품 의미론을 정의하지는 않는다.

qaestro는 agent runtime 위에 다음 도메인 workflow를 추가한다.

- PR, CI, review/comment, ChatOps 요청을 normalized event로 수신한다.
- 이벤트를 repository와 PR 단위로 durable하게 처리하고 correlation한다.
- 여러 commit과 review run을 PR aggregate state로 관리한다.
- current head 기준 readiness를 판단해 최신 근거와 stale CI를 구분한다.
- context acquisition, analysis, validation, output 단계별 tool policy를 적용한다.
- PR comment, review, ChatOps 응답을 idempotent한 output lifecycle로 관리한다.
- repository history와 기존 QA finding을 바탕으로 validation strategy를 점진적으로 개선한다.

범용 agent는 “이 PR을 살펴봐”라는 요청에 응답할 수 있다. qaestro는 그 응답이 PR
lifecycle의 어느 단계에 속하는지, 어떤 근거가 충분하거나 부족한지, 그 결과를 어디에
어떻게 남겨야 하는지를 책임진다.

## coding agent와의 차이

Coding agent는 repository 조사, 변경 계획, 파일 수정, test 실행, branch/PR 생성, review
feedback 반영 같은 software engineering 작업에 최적화되어 있다. qaestro는 이런 agent를
실행 backend로 활용할 수 있지만, 제품 정체성은 코드 생산이 아니라 QA control에 둔다.

| Coding agent | qaestro |
| --- | --- |
| 변경을 구현하거나 issue를 해결한다 | 변경의 품질 영향과 검증 필요성을 평가한다 |
| 개발자를 보조하는 작업자에 가깝다 | PR lifecycle을 조율하는 QA coordinator에 가깝다 |
| task 완료를 위해 tool을 실행한다 | workflow stage와 policy에 따라 tool 사용을 제한한다 |
| commit, patch, PR 같은 산출물을 만든다 | review evidence, validation strategy, QA output을 만든다 |
| prompt나 assigned issue에 응답한다 | PR, CI, comments, ChatOps를 가로질러 state를 유지한다 |

이 구분은 qaestro가 coding agent와 경쟁하기보다 보완하도록 만든다. Coding agent가 구현이나
validation probe 실행을 맡을 수 있다면, qaestro는 그 probe가 언제 필요한지, 결과가 review
readiness를 어떻게 바꾸는지, 결과를 어떤 output surface에 반영할지를 결정한다.

## AI PR reviewer와의 차이

AI PR reviewer는 diff를 요약하고, 개선 제안을 만들고, review comment를 남긴다. qaestro도
이러한 기능을 포함할 수 있지만, 범위는 단일 review pass보다 넓다.

qaestro는 PR을 diff가 아니라 lifecycle로 다룬다.

- `pull_request` event는 PR context를 시작하거나 갱신한다.
- 새 head commit은 final judgment에서 이전 revision evidence를 supersede한다.
- `workflow_run completed` event는 하나의 signal일 뿐이며, final readiness는 current
  head의 check/workflow snapshot으로 판단한다.
- stale CI 결과는 historical evidence로 남길 수 있지만 current verdict를 오염시키지 않는다.
- manual `@qaestro` 요청은 final review가 checks를 기다리는 중이어도 즉시 interim answer를
  받을 수 있어야 한다.
- final review는 behaviour analysis, CI/check evidence, validation result, prior context를
  하나의 managed output으로 종합할 수 있다.

따라서 qaestro가 답하려는 질문은 “이 diff에 어떤 문제가 보이는가?”에 그치지 않는다.
더 중요한 질문은 “이 PR을 책임 있게 판단하려면 어떤 근거가 필요하고, 지금 무엇을
전달해야 하는가?”이다.

## test automation platform과의 차이

Test automation platform은 browser flow, API test, mobile test, visual check, self-healing
selector, reporting 같은 실행 기능을 제공한다. qaestro의 초기 제품 형태는 이런 시스템을
대체하기보다 조율하는 쪽에 가깝다.

qaestro는 특정 변경에 어떤 기존 test, runtime probe, 외부 QA tool이 관련되는지 판단하고,
policy가 허용하는 runtime tool을 통해 실행한 뒤, 그 결과를 PR-level review state에 다시
반영할 수 있어야 한다. 이렇게 하면 qaestro는 validation strategy와 lifecycle coordination에
집중하고, 각 validation domain의 전문 test platform은 실행 계층으로 활용할 수 있다.

## 제품 원칙

### 1. Agent freedom보다 QA workflow를 우선한다

qaestro는 structured workflow와 bounded tool autonomy를 따른다. Orchestrator는 context
acquisition, triage/readiness, analysis, strategy, validation, rendering, output의 순서를
관리한다. Agent 또는 deterministic runner는 현재 stage policy가 허용하는 tool만 선택할 수
있다.

### 2. Current head를 판단의 기준으로 삼는다

PR은 계속 변한다. 이전 commit의 CI나 분석 결과는 history를 설명하는 데 유용하지만,
current verdict는 current head의 diff와 current head의 CI/check state에 근거해야 한다.

### 3. Review output은 noisy하지 않고 managed되어야 한다

PR-level summary comment는 lifecycle 변화에 따라 idempotent하게 update되어야 한다. Inline
review comment는 file/line/range에 직접 연결되는 finding에 사용하고, 가능하면 unified review
시점에 batch로 남긴다. ChatOps 응답은 같은 aggregate state를 사용하되, 명시적인 질문에 맞춰
짧고 즉각적으로 답한다.

### 4. Validation strategy는 시간이 지날수록 정밀해져야 한다

qaestro는 repository history, 반복되는 실패, 과거 review finding, 팀별 품질 기대치를 관찰하며
더 정밀해져야 한다. 장기적 가치는 고정 checklist가 아니라 review 대상 시스템에 적응하는 QA
strategy에 있다.

### 5. 외부 agent와 tool은 replaceable substrate다

Model provider, agent framework, MCP server, GitHub API, CI system, QA test platform은 모두
교체 가능한 기반 계층이다. qaestro의 지속적인 제품 가치는 그 위에 놓이는 event model,
workflow policy, aggregate state, validation strategy, output lifecycle에 있다.

## 요약

qaestro는 agentic development team을 위한 QA control plane이다. PR, CI/check, runtime
validation, developer request를 하나의 lifecycle로 연결해, AI-assisted development 속도에 맞는
품질 판단을 unstructured prompt workflow가 아니라 추적 가능한 QA workflow로 제공한다.
