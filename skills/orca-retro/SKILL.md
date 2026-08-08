---
name: orca-retro
description: Use right after an orca-workflow invocation ends (retro runs regardless of how the run ended) — analyzes only that run's logs under ~/.local/state/orca-workflows/logs/ (assignments/outcome events, spawn-failures, term transcripts) through four defect lenses (documented-schema violations, repeated FAILs attributable to skill prose, preventable escalations or human interventions, new spawn-failure signatures) and files at most 3 evidence-backed skill-defect issues on the sleeptimegrt-skills repo, deduplicating against open issues via recurrence comments. Never edits skills directly — output is issues only; fixes flow through the normal /orca-workflow pipeline later. Best-effort by contract: no retro failure may block the run. Self-relative.
---

# Orca Retro

방금 끝난 orca-workflow invocation 하나의 로그만 분석해 **스킬 결함 이슈**를 만든다.
환경(orca-* 스킬군) 자체를 개선하는 피드백 루프의 관측→이슈 단계다. 코드를 만들지 않고, 스킬 파일을
직접 수정하지 않는다 — 산출물은 sleeptimegrt-skills 이슈(또는 기존 이슈의 재발 코멘트)뿐이며, 수정
자체는 나중에 그 이슈를 평소의 `/orca-workflow` 파이프라인이 집어 처리한다.

## 0. 입력·전제

- 입력 3개: root issue 번호, 대상 repo, skills repo(sleeptimegrt-skills)의 GitHub slug.
- 큐 issue 목록: 호출자(`orca-workflow` §2)가 spec_text로 넘긴 목록을 그대로 쓴다. 목록 자체가 안
  넘어온 경우에만 `~/.agents/orca-workflows/issue-trackers/selection.md` 절차로 백엔드를 정해
  `list_children(root-num)`으로 해석한다(child 없는 issue면 빈 목록). root issue ∪ 이 목록(중복 제거)이
  이번 분석의 issue 집합이다 — size-1 큐면 root 1건이다.
- 로그 루트 `~/.local/state/orca-workflows/logs/`가 없거나 비어 있으면 §5 요약(filed=[])으로 즉시
  종료한다 — harness 밖에서 처리된 실행은 정상 케이스다.

## 1. 수집

날짜 분할 규칙 때문에 항상 glob으로 읽는다(`~/.agents/orca-workflows/logging.md` §1의
`find | sort | xargs cat` 레시피 — zsh nomatch 회피 포함):

```bash
logs="$HOME/.local/state/orca-workflows/logs"
# issue 집합(root ∪ 큐 목록)으로 필터한 assignments/waves 레코드
# assignments.jsonl(미날짜 레거시)은 항상 dated 파일보다 오래된 레코드만 담고 있는데,
# 단순 `-name 'assignments*.jsonl' | sort`는 ASCII상 '.'(0x2e) > '-'(0x2d)라 레거시 파일을
# 맨 뒤로 보낸다 — 그래서 명시적으로 먼저 읽는다(logging.md §1 "Reading across dates" 참고, issue #55).
{ [ -f "$logs/assignments.jsonl" ] && cat "$logs/assignments.jsonl"; \
  find "$logs" -name 'assignments-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null; \
} 2>/dev/null \
  | jq -c --argjson set '["<root-num>","<child-1>","<child-2>"]' 'select(.issue as $i | $set | index($i))'
find "$logs" -name 'waves*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null \
  | jq -c --argjson set '["<root-num>","<child-1>","<child-2>"]' 'select(.issue as $i | $set | index($i))'
cat "$logs/spawn-failures.jsonl" 2>/dev/null
# term 전사: meta 라인(1행)의 issue가 집합에 드는 파일만 통째로 읽는다
for f in "$logs"/term-*.jsonl; do
  [ -f "$f" ] || continue
  head -1 "$f" | jq -e --argjson set '["<root-num>","<child-1>","<child-2>"]' \
    'select(.type=="meta" and (.issue as $i | $set | index($i)))' >/dev/null 2>&1 && cat "$f"
done
```

**날짜 범위**: issue 필터에 걸린 레코드의 최소 `ts`부터 현재까지. §2 렌즈 1은 이 범위의 dated 파일
전체 내용을 대상으로 한다(아래).

**필터 공집합**: issue 필터에 걸린 레코드가 0개면 여기서 §5 요약(`filed=[]`)으로 즉시 종료한다 — 로그
루트에 다른 실행의 기록만 있는 경우가 이에 해당한다. `spawn-failures.jsonl`에는 `issue` 필드가
없으므로 렌즈 4도 이 날짜 범위(`ts` 기준)로 한정한다 — 범위 밖 항목은 이번 실행의 후보가 아니다.

## 2. 결함 후보 — 렌즈 4개

각 렌즈의 표적은 "스킬 문서를 고치면 사라질 결함"이다. 에이전트의 일회성 실수는 표적이 아니다 —
같은 지점에서 재발했거나, 스킬 문구가 그 실수를 유도·방치했다는 근거가 있어야 한다.

1. **문서화된 스키마 위반** — 각 스킬과 `~/.agents/orca-workflows/logging.md`가 명시한 스키마(enum
   값, 이벤트명, 필드 타입)를 벗어난 로그 레코드. **이 렌즈만은 issue 필터를 거치지 않고** §1 날짜
   범위의 dated 파일 전체를 스캔한다 — `issue` 필드 자체가 드리프트된 레코드는 필터로 잡히지 않는다.
2. **스킬 문구 기인 반복 FAIL** — 같은 FAIL 사유가 task·재시도에 걸쳐 반복되고, term 전사에서
   worker가 스킬 지시를 오독·누락한 정황이 보이는 경우.
3. **예방 가능했던 ESCALATE·인간 개입** — `ESCALATE`·`*_HUMAN_DECISION` 계열 outcome 중, 전사를 보면
   스킬 문구 보강으로 막을 수 있었던 것.
4. **spawn-failure 신규 시그니처** — `spawn-failures.jsonl`에서 `known_issue` 매칭이 없는 항목.

## 3. 증거 기준·상한

- 후보마다 **로그 파일 경로 + 원문 인용(레코드 라인 그대로) 최소 1개**. 인용을 못 붙이는 후보는
  이슈화하지 않고 폐기 카운트에만 넣는다.
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
   아닐 때만 유효하다 — 구 로그(Task 1 이전 배포분)는 meta에 버전 필드가 없거나, 1행이 애초에 meta가
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
- spawn-failure 후보는 `~/.agents/orca-workflows/spawn-failures.md`가 이미 부여한 known_issue
  번호와도 대조한다.
- 신규 결함이면, 라벨은 `retro` 그대로 쓴다 — orca-retro 전용이 아니라 앞으로 다른 경로로 스킬 결함
  이슈를 파일링할 때도 재사용하는 일반 컨벤션이다(다만 현재 `gh issue create`를 실제로 호출하는
  스킬은 orca-retro뿐이다):

  ```bash
  gh issue create --repo <skills-repo-slug> --label retro \
    --title "<대상 스킬>: <결함 한 줄>" \
    --body "<대상 스킬 파일 경로 / 증거 인용(로그 경로+레코드 라인) / root issue 번호 / 참조한 로그 경로 / 수정 방향 1문단(diff 금지) / 위에서 조립한 ## 환경/버전 섹션>"
  ```

## 5. 보고

코디네이터에 요약 한 줄만 보낸다(리포트 파일 없음 — 이슈가 곧 산출물):

```
RETRO filed=[#12,#13] commented=[#7] discarded=2
```

수집·분석·gh 어느 단계가 실패해도 가능한 데까지의 카운트와 실패 사실을 같은 형식으로 보고한다 —
이 스킬은 best-effort이며, 실패를 실행 완료로 전파하지 않을 책임은 호출자(`orca-workflow` §2)에 있다.
