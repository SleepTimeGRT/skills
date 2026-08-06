# spawn-failures.md: evaluator mid-run 크래시 신규 시그니처 등록 — Design

**Date**: 2026-08-05
**Status**: Approved (brainstorming phase) — pending implementation plan
**Related**: GitHub issue #61 (SleepTimeGRT/skills)

## Context

이슈 #61은 `orca-retro`가 epic MediCount#466 (child #470 R2) 로그에서 찾은 결함을
보고한다: evaluator 세션이 재평가 라운드 도중 `Agent exited with code -1
mid-session (dispatch status=failed, terminal status=exited)`로 크래시했는데,
`spawn-failures.md`의 known-signature 표에 이 패턴과 매칭되는 row가 없어
`known_issue: null`로 기록됐다. 이슈 본문은 이 문구를 그대로 `failure_signature`
literal substring으로 등록하자고 제안한다.

**검증 결과, 이 제안은 그대로 채택할 수 없다.** 실제 크래시가 일어난 터미널의
로그(`~/.local/state/orca-workflows/logs/term-term_2b1827fe-....jsonl`)를 열어보면
`sent` 이벤트 하나뿐이고 `recv`가 전혀 없다 — 이건 크래시의 증거가 아니라
`orca-workflow` SKILL.md §2a의 설계상 정상이다: evaluator 터미널은
dispatch-verify의 opaque liveness probe 외엔 애초에 `terminal read`를 하지
않고, 결과는 `worker_done`이나 report 파일로 도착하는 구조다. 즉
"Agent exited with code -1 (dispatch status=failed, terminal status=exited)"는
`terminal read` raw 출력에서 나온 문자열이 아니라, 아마도 `orca terminal show`
또는 `orca orchestration worker-show --dispatch` 같은 구조화된 상태 조회 JSON의
값을 사람이 조합해 적은 서술이다 — 그런데 이번 사건에서 그 조회를 정확히 어떤
명령으로 했는지, raw JSON이 무엇이었는지는 어디에도 남아 있지 않다. 이 표
자신의 규칙("짧고 리터럴한 substring — paraphrase면 다음번 grep이 못 찾는다",
73-77번 줄)에 이 문구를 그대로 넣으면 위배된다.

한편 이슈가 주장하는 "재시도 예산을 소모하지 않았다"는 부분은
`assignments-2026-08-04.jsonl`으로 실측 검증됐다: 크래시 후 respawn
(`task_0763488e098e`, mode `diff-eval-r2-respawn`)은 `retry` 필드를 건드리지
않고 같은 `round:2`로만 재기록되며, 최종 PASS의 `retry:1`은 이 크래시와 무관한
이전 FAIL/fix 사이클에서 온 값이다.

부수적으로, 표를 열어보다가 별개의 구조 결함을 발견했다: 69번 줄(#43 row)과
71번 줄(#60 row) 사이에 빈 줄이 하나 있다. GitHub Markdown 표는 빈 줄에서
끊기므로 #60 row는 실제로는 헤더 없는 orphan 블록으로 렌더링된다 — grep-first
절차("아래 표에서 failure_signature 열을 grep")가 전제하는 "표 하나"가 사실은
두 조각이다. 같은 표에 row를 추가하는 이번 작업 범위에 포함한다.

## 결정

### 1. 새 row는 `#60` 패턴(no-signature, 근거 불충분 시 업그레이드 예약)을 따른다

`#43`/`#60` row가 이미 정의한 두 가지 no-signature 예외 중 `#60` 쪽 — "리터럴
substring이 원칙적으로 존재하긴 하지만 이번 환경에서 아직 정확히 캡처되지
않았다" — 이 이번 케이스와 정확히 같은 모양이다. 71번 줄(`#60` row) 바로 뒤에
추가:

| `failure_signature` | root cause | fix | known_issue |
|---|---|---|---|
| *(no signature captured yet — see root cause)* | An evaluator terminal (REPL, no scheduled `terminal read` per `orca-workflow` SKILL.md §2a's by-design read-nothing-until-`worker_done` model) went unresponsive mid-session and was inferred crashed via structured status ("dispatch status=failed" / "terminal status=exited") rather than any `terminal read` output — this term log has zero `recv` events by design, so no literal on-screen substring exists to grep. Root cause of the crash itself is unconfirmed; even the exact command/JSON that produced the "failed"/"exited" status pair wasn't captured this occurrence | fresh evaluator terminal re-spawn + re-dispatch — this consumes no task-level retry budget (`assignments.jsonl`'s `retry` counter is untouched by a spawn-failure respawn; verified against issue #470's log, where the crash-respawn kept `round:2` without bumping `retry`) since it isn't a FAIL verdict. Next occurrence: before respawning, run `orca terminal show --terminal <handle> --json` and `orca orchestration worker-show --dispatch <dispatch_id> --json`, capture the raw JSON verbatim, and attempt one `orca terminal read` even if expected empty — upgrade this row to a literal substring once actually observed | #61 |

`## Adding a new row` 섹션의 no-signature 예외 설명(79-88번 줄)에 이 row도
`#60`과 같은 이유("substring이 원칙적으로 존재, 미포착")로 묶인다는 언급을
한 문장 추가한다.

### 2. 표 끊김 버그 수정

69번 줄과 71번 줄 사이의 빈 줄(70번 줄)을 제거해 표를 하나로 합친다. 내용
변경은 없다 — 렌더링만 고친다.

## 검토 후 기각한 대안

- **이슈 원문 그대로 리터럴 substring row 등록**: 이번 사건에서 그 문구가 어떤
  명령의 raw 출력인지 확인할 근거가 없고(터미널이 crash 전용 read를 하지 않는
  구조), 표 자신의 "리터럴 substring만" 규칙과 충돌한다. 다음번 같은 크래시가
  나도 grep이 실제 관측 문자열과 일치한다는 보장이 없어, 오히려
  "known signature인데 안 걸린다"는 잘못된 확신을 줄 위험이 있다.

## 테스트 계획

- 수정 후 `orca-workflows/spawn-failures.md`를 마크다운 프리뷰(또는
  `awk -F'|' '/^\|/{print NF}'`로 각 표 라인의 열 개수가 일정한지)로 확인해
  69~72번 줄이 하나의 연속된 표로 렌더링되는지 검증한다.
- `## Adding a new row`의 no-signature 예외 문단이 `#43`/`#60`/신규 row 세
  케이스를 모두 정확히 구분해 설명하는지 재독한다(모순·중복 없는지).

## 범위 경계

- `orca-workflows/spawn-failures.md` 한 파일, 커밋 1개. 다른 스킬 파일이나
  대상 저장소(MediCount 등)는 건드리지 않는다 — 이슈 #61은 skill 결함이라
  이 레포 내부 수정으로 완결된다.
- `issue-64-2` 워크트리는 이 파일을 건드리지 않은 clean 상태(main과 동일
  commit)임을 확인했다 — 병합 충돌 없음.
