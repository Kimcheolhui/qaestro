## Step 7 ChatOps 구현 이슈 재설계

Step 7은 `@qaestro` 호출을 받는 채팅 표면을 추가하지만, MVP에서 Slack/Teams SDK와 전체 대화형 제품 경험을 한 번에 구현하는 단계가 아니다. Step 0~6에서 만든 PR aggregate, current-head CI/readiness, validation evidence, managed summary comment, official review lifecycle을 채널에서 짧게 조회하거나 명시적으로 트리거할 수 있게 만드는 것이 핵심이다.

따라서 Step 7의 첫 구현 단위는 특정 채팅 제품 SDK가 아니라 provider-neutral ChatOps contract와 fake connector여야 한다. `ChatMention` event, thread context, reply target, response payload, write policy를 qaestro 내부 contract로 먼저 고정하면 Slack 또는 Teams connector는 같은 contract 뒤에 붙일 수 있다. 반대로 Slack/Teams payload parsing부터 시작하면 workflow와 renderer가 특정 플랫폼 shape에 끌려가고, 이후 connector 교체 가능성이 문서 요구사항으로만 남을 위험이 크다.

ChatOps manual trigger도 Step 6.6 activation policy를 우회하면 안 된다. `@qaestro review`는 새로운 activation rule을 만드는 기능이 아니라, 이미 정해진 reviewer-request activation/current-head readiness를 읽고 현재 상태를 응답하거나, 허용된 경우 기존 PR review lifecycle에 manual trigger event를 추가하는 표면이다. Pending check가 있으면 channel 응답은 즉시 interim 상태를 알려야 하지만, final official review는 기존 deferred lifecycle을 따라야 한다.

Step 7 구현 이슈는 다음 경계로 나눈다.

1. Provider-neutral ChatOps contract와 fake connector를 만든다. Chat mention input, thread context read, response write를 platform-neutral type으로 표현하고 fake connector 기반 테스트로 gateway/worker 없이도 workflow를 검증할 수 있게 한다.
2. ChatMention parser와 PR reference resolution을 구현한다. `@qaestro review`, `@qaestro status`, PR URL/번호, thread context에서 PR을 찾는 최소 parsing/resolution을 다루되 Slack/Teams SDK payload 전체를 한꺼번에 모델링하지 않는다.
3. Chat workflow를 PR aggregate/current-head lifecycle에 연결한다. Chat mention이 current aggregate를 조회하고 readiness/pending/final 상태를 짧게 응답하며, review trigger는 Step 6.6 activation gate와 existing review lifecycle을 따라야 한다.
4. Chat renderer와 output write policy를 분리한다. 같은 analysis/strategy/validation evidence를 PR comment/review와 다르게 짧은 channel response로 렌더링하고, write action은 ToolRuntime/output policy 경계를 통과하도록 한다.
5. 첫 실제 connector를 선택해 얇게 붙인다. Slack과 Teams를 동시에 시작하지 않고, fake connector contract가 안정된 뒤 하나의 실제 connector를 선택해 webhook verification, event conversion, response write만 구현한다.

이 분해는 Step 7을 작은 PR 단위로 유지하기 위한 계획이다. Persistent aggregate store, cross-process ChatOps history, rich interactive UI, multi-connector 동시 지원, 운영 metrics/heartbeat는 Step 10 또는 별도 후속 이슈로 미룬다.
