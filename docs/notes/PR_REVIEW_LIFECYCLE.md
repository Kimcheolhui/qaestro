## PR aggregate와 unified review lifecycle

Step 4 논의 과정에서 정리된 PR/CI/ChatOps 통합 모델이다. 구현 순서는 Step 4 이후 이슈로 나누되, 제품 방향은 다음을 기준으로 한다. 현재 PR #53은 `CICompleted` enrichment와 초기 CI workflow boundary까지만 다루며, 아래 aggregate/revision/readiness lifecycle의 본 구현은 #54에서 별도 추적한다.

- PR, CI, GitHub comment/review, ChatOps mention은 event source별로 따로 수신하되, 판단은 PR 단위 `PRAggregateState`로 모은다.
- `PRAggregateState` 내부에는 current PR metadata와 대화 history를 두고, head commit별 `PRRevisionState(head_sha)`와 여러 `ReviewRun`을 둔다.
- 새 commit이 올라오면 새 revision을 만들고 이전 revision은 stale/superseded로 표시한다. 이전 CI 실패와 분석 결과는 historical evidence로 참고할 수 있지만, current verdict의 source of truth는 current `head_sha`의 diff와 CI/check 결과다.
- 자동 final review는 CI/check 완료를 기다리는 deferred unified review를 기본으로 한다. `workflow_run completed` 이벤트는 특정 workflow run 하나의 완료 신호이므로, final review 직전에는 current head의 check/workflow snapshot을 조회해 pending/queued/in-progress 항목을 확인해야 한다.
- 사용자가 GitHub comment나 channel에서 명시적으로 `@qaestro review`를 요청하면 manual-trigger first 흐름으로 처리한다. 이때는 조용히 기다리지 말고 current aggregate state 기준 interim response를 즉시 제공하되, 남은 CI/check와 최종 판단 보류를 명시한다.
- PR-level managed summary comment와 GitHub review/inline comment는 다른 output surface다. summary comment는 stable marker로 create/update하고, line/range comment는 final unified review 시점에 batch로 작성한다.
