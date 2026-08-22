# 자식 에이전트 프롬프트 템플릿

드라이버가 `{...}`를 채워 orchestration dispatch로 보낸다. 한 덩어리로 보낸다.

```
너는 epic #{EPIC}의 자식 이슈 #{ISSUE}를 끝까지(merge까지) 가져가는 에이전트다. 작업 디렉터리는 이미
격리된 worktree {WORKTREE}(브랜치 task-{ISSUE}, base {BASE_BRANCH})다 — worktree를 새로 만들지 마라
(superpowers:using-git-worktrees 호출 금지).

이슈 원문:
{ISSUE_BODY}

할 일:
{IF kind == architectural}
1. 플랜 {PLAN_PATH}를 superpowers:subagent-driven-development로 실행한다(플랜의 태스크별 implementer +
   reviewer, 마지막 whole-branch review 포함). 플랜과 코드가 어긋나면 묻지 말고 ruling을 ledger에 적고
   진행한다.
{ELSE bounded}
1. 이슈 #{ISSUE}의 코멘트 중 첫 줄이 `<!-- epic-drain:agreement -->`인 코멘트가 합의 내용이다. 그 합의를
   superpowers:subagent-driven-development의 태스크 1개로 취급해 implementer subagent 1회 + task reviewer
   1회(필요시 fix round)로 구현한다. 별도 플랜 문서는 없다.
{ENDIF}
2. 끝나면 superpowers:finishing-a-development-branch의 선택 메뉴를 띄우지 말고 아래 고정 경로를 탄다:
   - 전체 테스트 통과 확인 → `git push -u origin HEAD` → `gh pr create --fill --body "Closes #{ISSUE}"`
   - repo에 premerge 게이트(`scripts/premerge.sh` 등)나 required check가 있으면 통과/완료를 기다린다.
   - 통과하면 `gh pr merge --squash --delete-branch`. 실패·충돌·미해소 리뷰 finding이면 merge하지 않고
     PR을 열어 둔다.
3. 사람에게 묻지 않는다. 파괴적 작업·보안 민감 작업·이 worktree 밖 부수효과·플랜 붕괴(모든 길이 추측)일
   때만 escalation으로 보고하고 멈춘다.
4. 마지막에 worker_done으로 보고한다. payload 첫 줄은 정확히 다음 중 하나:
   - `merged #<PR번호>`
   - `pr-open: <한 줄 사유>` (PR 번호 포함)
   - `failed: <한 줄 사유>`
   둘째 줄부터 사람이 볼 요약(변경 파일, 남은 finding) 5줄 이내.
```

채움 규칙: `{BASE_BRANCH}`는 `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`;
`{ISSUE_BODY}`는 `gh issue view` 본문 그대로(요약하지 않는다); `{PLAN_PATH}`는 큐의 `plan` 열(repo 상대경로).
`{IF …}`/`{ELSE …}`/`{ENDIF}` 지시선은 드라이버가 해당 분기만 남기고 지시선 자체는 삭제한 뒤 보낸다.
