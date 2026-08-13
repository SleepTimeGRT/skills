---
name: orca-retro
description: >-
  Use right after an orca-workflow invocation ends, regardless of how it ended — analyzes that
  invocation's logs under ~/.local/state/orca-workflows/logs/ (assignments/outcome events,
  spawn-failures, term transcripts) through six defect lenses (documented-schema violations,
  repeated FAILs attributable to skill prose, preventable escalations or human interventions, new
  spawn-failure signatures, false-PASS regressions: tracker issues with a regressed-by trailer
  pointing back at merged PASS verdicts — the one lens crossing invocation boundaries, and
  contract-verdict mismatches: approved or plan_coverage-only contract verdicts contradicted by
  downstream eval-report FAILs or human escalation) and files at
  most 3 evidence-backed skill-defect issues on the sleeptimegrt-skills repo, deduplicating against
  open issues via recurrence comments. Never edits skills directly — output is issues only; fixes
  flow through the normal /orca-workflow pipeline later. Best-effort by contract: no retro failure
  may block the invocation. Self-relative. Do NOT use for general retrospectives or ad-hoc log
  analysis — runs only as the closing step of an orca-workflow invocation.
compatibility: Requires the `orca` CLI (skill set last verified against Orca app 1.4.180), the `~/.agents/orca-workflows/` symlink to this repo's orca-workflows/, and the `gh` CLI. Reads logs under ~/.local/state/orca-workflows/logs/.
---

# Orca Retro

방금 끝난 orca-workflow invocation 하나의 로그만 분석해 **스킬 결함 이슈**를 만든다.
환경(orca-* 스킬군) 자체를 개선하는 피드백 루프의 관측→이슈 단계다. 코드를 만들지 않고, 스킬 파일을
직접 수정하지 않는다 — 산출물은 sleeptimegrt-skills 이슈(또는 기존 이슈의 재발 코멘트)뿐이며, 수정
자체는 나중에 그 이슈를 평소의 `/orca-workflow` 파이프라인이 집어 처리한다.

## 0. 입력·전제

- 입력 3개: root issue 번호, 대상 repo, skills repo(sleeptimegrt-skills)의 GitHub slug.
- **이슈 트래커 해석**(실행 시작 시 1회): `~/.agents/orca-workflows/issue-trackers/selection.md`
  절차로 백엔드를 정한다 — §2 렌즈 5의 `find_regressions`가 항상 쓰고, 큐 목록 해석이 필요할 때
  `list_children`도 쓴다.
- 큐 issue 목록: 호출자(`orca-workflow` §2)가 spec_text로 넘긴 목록을 그대로 쓴다. 목록 자체가 안
  넘어온 경우에만 `list_children(root-num)`으로 해석한다(child 없는 issue면 빈 목록). root issue ∪
  이 목록(중복 제거)이 이번 분석의 issue 집합이다 — size-1 큐면 root 1건이다.
- 로그 루트 `~/.local/state/orca-workflows/logs/`가 없거나 비어 있으면 §5 요약(filed=[])으로 즉시
  종료한다 — harness 밖에서 처리된 실행은 정상 케이스다. 단 렌즈 5·6은 로그가 아니라 트래커·
  CONTRACT_DIR 기반이므로, 로그 공집합 종료 전에 렌즈 5·6 스캔만은 수행한다(§2 해당 렌즈의 스코프
  예외).

## 1. 수집

날짜 분할 규칙 때문에 항상 glob으로 읽는다(`~/.agents/orca-workflows/logging.md` §1의
`find | sort | xargs cat` 레시피 — zsh nomatch 회피 포함):

```bash
logs="$HOME/.local/state/orca-workflows/logs"
# (repo, issue) 복합 키로 필터한 assignments/waves 레코드 — 로그 루트는 여러 저장소가 공유하고
# issue 번호는 저장소 간에 충돌하므로, issue 단일 키 매칭은 무관한 저장소의 레코드를 섞는다
# (issue #158 실측). $repo는 §0 입력의 "대상 repo" 문자열 그대로 — writer들도 같은 문자열을 spec
# 체인으로 받아 기록하므로(logging.md §1 repo 필드) 문자열 동일성 비교로 충분하다.
# assignments.jsonl(미날짜 레거시)은 항상 dated 파일보다 오래된 레코드만 담고 있는데,
# 단순 `-name 'assignments*.jsonl' | sort`는 ASCII상 '.'(0x2e) > '-'(0x2d)라 레거시 파일을
# 맨 뒤로 보낸다 — 그래서 명시적으로 먼저 읽는다(logging.md §1 "Reading across dates" 참고, issue #55).
{ [ -f "$logs/assignments.jsonl" ] && cat "$logs/assignments.jsonl"; \
  find "$logs" -name 'assignments-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null; \
} 2>/dev/null \
  | jq -c --arg repo '<대상-repo>' --argjson set '["<root-num>","<child-1>","<child-2>"]' \
      'select(.repo == $repo and (.issue as $i | $set | index($i)))'
find "$logs" -name 'waves*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null \
  | jq -c --arg repo '<대상-repo>' --argjson set '["<root-num>","<child-1>","<child-2>"]' \
      'select(.repo == $repo and (.issue as $i | $set | index($i)))'
cat "$logs/spawn-failures.jsonl" 2>/dev/null
# term 전사: meta 라인(1행)의 (repo, issue)가 집합에 드는 파일만 통째로 읽는다
for f in "$logs"/term-*.jsonl; do
  [ -f "$f" ] || continue
  head -1 "$f" | jq -e --arg repo '<대상-repo>' --argjson set '["<root-num>","<child-1>","<child-2>"]' \
    'select(.type=="meta" and .repo == $repo and (.issue as $i | $set | index($i)))' >/dev/null 2>&1 && cat "$f"
done
```

**`repo` 필드 없는 레코드**(#158 이전 버전이 남긴 기록)는 복합 키에 매칭되지 않아 그대로 제외된다 —
`worktree` 경로 휴리스틱으로 저장소를 역추정하지 않는다(outcome 레코드 대부분이 `worktree:null`이라
커버리지가 없고, 나머지도 추정 오염을 다른 오염으로 바꿀 뿐이다). 이 제외는 렌즈 2~4의 분석 집합과
아래 날짜 범위 계산에 반영된다 — 렌즈 1도 그 날짜 범위를 쓰므로 스캔 범위가 함께 좁아지는데, 그것이
바로 #158이 지적한 왜곡(오염된 최소 ts로 2주+ 과대 확장)의 수정이다. 렌즈 5·6(로그 비의존)만 무관하다.

**날짜 범위**: (repo, issue) 필터에 걸린 레코드의 최소 `ts`부터 현재까지. §2 렌즈 1은 이 범위의 dated 파일
전체 내용을 대상으로 한다(아래).

**필터 공집합**: (repo, issue) 필터에 걸린 레코드가 0개면 렌즈 1~4를 건너뛴다 — 로그 루트에 다른 실행의
기록만 있는 경우가 이에 해당한다. 이때도 렌즈 5·6은 수행한 뒤 §5로 간다. `spawn-failures.jsonl`에는 `issue` 필드가
없으므로 렌즈 4도 이 날짜 범위(`ts` 기준)로 한정한다 — 범위 밖 항목은 이번 실행의 후보가 아니다.

## 2. 결함 후보 — 렌즈 6개

각 렌즈의 표적은 "스킬 문서를 고치면 사라질 결함"이다. 에이전트의 일회성 실수는 표적이 아니다 —
같은 지점에서 재발했거나, 스킬 문구가 그 실수를 유도·방치했다는 근거가 있어야 한다(예외: 렌즈 5 —
아래).

1. **문서화된 스키마 위반** — 각 스킬과 `~/.agents/orca-workflows/logging.md`가 명시한 스키마(enum
   값, 이벤트명, 필드 타입)를 벗어난 로그 레코드. **이 렌즈만은 (repo, issue) 필터를 거치지 않고** §1 날짜
   범위의 dated 파일 전체를 스캔한다 — `issue` 필드 자체가 드리프트된 레코드는 필터로 잡히지 않는다.
   `outcome`/`action_taken`이 `UNMAPPED_BRANCH`이고 `schema_gap_issue` 필드가 채워진 레코드는 위반이
   아니라 추적 중인 알려진 구멍으로 읽고 후보에서 제외한다 — `UNMAPPED_BRANCH`이면서 `schema_gap_issue`가
   비어 있거나 없는 레코드, 그리고 enum에 없는 값이 `UNMAPPED_BRANCH` 리터럴 자체가 아닌 레코드는
   그대로 위반 후보다. 예외: `outcome`이 리터럴 `CONTRACT_APPROVED_ROUND1` 또는
   `CONTRACT_APPROVED_ROUND2`인 레코드는 `schema_gap_issue` 유무와 무관하게 위반 후보에서 제외한다 —
   `CONTRACT_APPROVED`로의 일반화(#86) 이전에는 그 시점 스키마 기준으로 정상 기록된 legacy 값이다.
   같은 이유로 `repo` 필드 부재도 위반 후보로 잡지 않는다 — #158 이전 버전 레코드는 정상적으로 이
   필드가 없고, 레코드만으로는 기록 시점 버전을 판별할 수 없다.
2. **스킬 문구 기인 반복 FAIL** — 같은 FAIL 사유가 task·재시도에 걸쳐 반복되고, term 전사에서
   worker가 스킬 지시를 오독·누락한 정황이 보이는 경우.
3. **예방 가능했던 ESCALATE·인간 개입** — `ESCALATE`·`*_HUMAN_DECISION` 계열 outcome 중, 전사를 보면
   스킬 문구 보강으로 막을 수 있었던 것. 예외: `outcome`이 `CONTRACT_SCHEMA_STALE`인 레코드는 후보에서
   제외한다 — 이미 스킬 문구가 보강돼 처리되는 마이그레이션 범주다(issue #160, ADR 0001의
   `UNMAPPED_BRANCH` carve-out과 같은 근거).
4. **spawn-failure 신규 시그니처** — `spawn-failures.jsonl`에서 `known_issue` 매칭이 없는 항목.
5. **false PASS (사후 결함 회귀, issue #157)** — evaluator가 PASS를 줘서 머지됐는데 사후 결함으로
   판명된 경우. false FAIL은 재시도·escalate로 렌즈 2·3에 잡히지만 false PASS는 어떤 로그에도 남지
   않는 비대칭이 있고, 이 신호 없이는 evaluator 판정 기준의 보정이 원천적으로 불가능하다. **이
   렌즈만은 이번 invocation 경계를 넘는다** — false PASS는 머지 뒤에야 드러나므로, 표적은 과거
   invocation들의 산출물이고 입력은 로그가 아니라 트래커와 CONTRACT_DIR이다:

   1. 대상 repo 트래커에서 `find_regressions()`(adapter 문서의 오퍼레이션 — `regressed-by` trailer
      컨벤션도 그쪽이 정의)로 (결함 이슈, 지목된 task issue `<n>`) 쌍을 수집한다.
   2. 각 `<n>`이 이 파이프라인의 PASS로 머지된 것인지 CONTRACT_DIR로 확인한다 — PASS eval-report가
      없으면 파이프라인 밖 머지이므로 후보가 아니다:

      ```bash
      cdir="$HOME/.local/state/orca-workflows/contracts/<project-slug>/issue-<n>"
      for k in 1 2 3; do   # attempt 상한 3 (orca-workflow-task §4의 FAIL 재시도 예산)
        f="$cdir/eval-report-a$k.json"
        [ -f "$f" ] && jq -e '.verdict=="PASS"' "$f" >/dev/null 2>&1 && echo "$f"
      done
      ```

   3. PASS 파일이 있으면 후보다 — 대상 스킬은 `orca-evaluate`, 프레임은 "PASS를 준
      `eval-report-a<k>.json`의 findings·리뷰 범위가 이 결함을 왜 못 봤는가". 단건이라도 후보다
      (재발 요건의 예외) — evaluator 오판은 파이프라인에서 가장 비싼 결함 종류이고, 이 렌즈가
      유일한 관측 경로다. 수집된 사례를 evaluator 판정 지침으로 되먹이는 것은 별도 단계다(#157의
      2번) — 이 렌즈는 관측·이슈화까지만 한다.
6. **contract-verdict 오판 대조**: 이 invocation이 다룬 issue들 중 `verdict-r*.json`이
   `approved` 또는 `plan_coverage`-only `override`로 종결된 것을 골라, 같은 issue의 최종
   `eval-report-a*.json`의 FAIL findings 또는 human escalation 기록과 대조한다. 다운스트림에서
   같은 결함(같은 `ac_id` 또는 같은 지적 내용)이 실제로 재현되면, evidence-backed defect issue로
   파일링한다(기존 "invocation당 최대 3건" 한도, 기존 중복 방지 — open issue에 recurrence 코멘트
   — 규칙 그대로 적용).

## 3. 증거 기준·상한

- 후보마다 **로그 파일 경로 + 원문 인용(레코드 라인 그대로) 최소 1개**. 인용을 못 붙이는 후보는
  이슈화하지 않고 폐기 카운트에만 넣는다. 렌즈 5·6은 로그 대신 다음이 같은 기준을 충족한다 —
  렌즈 5: **결함 이슈의 `regressed-by` 라인 인용 + PASS `eval-report-a<k>.json` 절대경로와 그
  `verdict` 라인**; 렌즈 6: **`verdict-r<n>.json` 절대경로와 해당 `reasons`/`status` 라인 +
  대조된 `eval-report-a<k>.json` 절대경로와 그 finding 라인**.
- 신규 이슈는 **실행(root issue)당 최대 3개**. 우선순위: 재발 횟수 → 영향 범위(걸린 스킬·사이트 수). 4번째
  이하 후보는 가장 우선순위 높은 신규 이슈 본문의 "부록" 섹션에 목록으로 넣는다.

## 4. 중복 대조 → 이슈/코멘트

```bash
gh issue list --repo <skills-repo-slug> --state open --json number,title,labels --limit 100
```

새 이슈를 만들든 기존 이슈에 재발 코멘트를 달든 공통으로, 먼저 "## 환경/버전" 섹션을 조립한다 —
우선순위 2단계:

1. 이 후보의 증거로 인용한 term 로그(`term-<handle>.jsonl`)가 있으면, 그 경로를 `$term_log`에
   바인딩한다(§1에서 읽은 파일 경로). 1행에서 뽑되 `type=="meta"`이고 세 버전 필드가 전부 null/누락이
   아닐 때만 유효하다 — 버전 필드가 없는 로그도 존재한다 — meta에 버전 필드가 없거나, 1행이 애초에 meta가
   아닐 수 있다:

   ```bash
   sv="$(head -1 "$term_log" \
     | jq -c 'select(.type=="meta") | {skill, terminal, skill_version, orca_workflows_commit, orca_app_version}' \
     2>/dev/null)"
   # $sv가 비어 있거나 skill_version/orca_workflows_commit/orca_app_version이 전부 null이면
   # (구 로그, 또는 1행이 meta가 아님) 아래 우선순위 2로 넘어간다 — null을 그대로 붙이지 않는다.
   ```

   `sv.skill`이 이 후보의 **대상 스킬**(`<대상 스킬>`)과 다르면 — term 로그의 meta는 그 터미널을
   **스폰한** 스킬을 적기 때문에 흔히 벌어진다(예: `orca-workflow-task`가 `skill="orca-workflow-task",
   role="task-runner"`로 `orca-task-runner` 터미널을 스폰) — 뽑은 값을 "스폰한 스킬(`sv.skill`)의
   버전"이라고 명시하고, 대상 스킬 자체 버전은 아래 우선순위 2를 **추가로** 돌려 함께 싣는다.

2. term 로그가 없거나(렌즈 1·4처럼 assignments/spawn-failures만으로 나온 경우) 위 1이 폴백 조건에
   걸리면, 대상 스킬의 **현재** 배포 버전을 쓰고, 이슈/코멘트 본문에
   "분석 시점 기준 — 실행 당시와 다를 수 있음"이라고 명시한다:

   ```bash
   version_file="$HOME/.agents/skills/<대상 스킬>/.installed-version.json"
   [ -f "$version_file" ] && jq -c '{version, commit}' "$version_file"
   ```

- 기존 open 이슈가 같은 결함을 다루면 **새 이슈 대신 그 이슈에 재발 코멘트**를 단다(증거 인용 +
  root issue 번호 + 위에서 조립한 "## 환경/버전" 섹션): `gh issue comment <num> --repo <skills-repo-slug>
  --body "..."`. 재발 코멘트 횟수가 이 루프의 우선순위 신호다.
- **렌즈 5 전용 대조**: 같은 (결함 이슈, task issue) 쌍은 "재발"이 없다 — 한 번 관측되면 끝이다.
  skills repo를 `--state all`로 결함 이슈 참조 문자열(`<target-repo>#<결함 이슈 번호>`)까지 검색해,
  open이든 closed든 그 쌍을 이미 다룬 이슈가 있으면 코멘트 없이 폐기한다. 신규 이슈 본문에는 그
  대조가 기계적으로 되도록 `false-pass: <target-repo>#<결함>→#<task>` 한 줄을 넣는다.
- spawn-failure 후보는 `~/.agents/orca-workflows/spawn-failures.md`가 이미 부여한 known_issue
  번호와도 대조한다.
- 신규 결함이면, 라벨은 `retro`를 쓴다:

  ```bash
  gh issue create --repo <skills-repo-slug> --label retro \
    --title "<대상 스킬>: <결함 한 줄>" \
    --body "<대상 스킬 파일 경로 / 증거 인용(로그 경로+레코드 라인) / root issue 번호 / 참조한 로그 경로 / 수정 방향 1문단(diff 금지) / 위에서 조립한 ## 환경/버전 섹션>"
  ```

## 5. 보고

호출자(`orca-workflow`)에 요약 한 줄만 보낸다(리포트 파일 없음 — 이슈가 곧 산출물):

```
RETRO filed=[#12,#13] commented=[#7] discarded=2
```

수집·분석·gh 어느 단계가 실패해도 가능한 데까지의 카운트와 실패 사실을 같은 형식으로 보고한다 —
이 스킬은 best-effort이며, 실패를 실행 완료로 전파하지 않을 책임은 호출자(`orca-workflow` §2)에 있다.
