# Orca Workflow Issue Tracker Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple `orca-workflow`/`orca-task-runner`/`orca-evaluate` from GitHub Issues so they work against any issue tracker (starting with Jira, for `~/Projects/vprop`), per `docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`.

**Architecture:** A 3-tier resolution replaces today's hardcoded `gh issue` calls: (1) backend selection from the target repo's own AGENTS.md/CLAUDE.md "Issue tracker" pointer, with an onboarding sub-flow for undocumented non-GitHub repos; (2) a generic per-platform adapter (`orca-workflows/issue-trackers/{github,jira}.md`) implementing 7 named operations (`get_issue`, `get_issue_type`, `list_children`, `get_child_order`, `is_open`, `close_issue`, `link_pr_for_close`) using each platform's structural fields — no repo-specific values baked in; (3) a repo-doc override for the handful of facts no API can supply (acceptance-criteria section name, the "done" transition's name). `orca-task-runner`/`orca-evaluate` stop hardcoding the `## Acceptance criteria` GitHub heading and instead trust whatever section name `orca-workflow` resolved and forwarded.

**Tech Stack:** Markdown skill files (`SKILL.md`) with YAML frontmatter, Python/pytest for structural validation (these are prose/instruction files, not executable code — tests check structure, not runtime behavior), bash for `orca` CLI orchestration examples.

## Global Constraints

- Issue-tracker specifics (project key, transition IDs, cloudId, site URL) are never hardcoded in `orca-workflow`/`orca-task-runner`/`orca-evaluate` **or** in the shared adapter files (`orca-workflows/issue-trackers/{github,jira}.md`) — always resolved from the target repo's own tracker doc at run start.
- No caching of tracker resolution, anywhere (not in-repo, not `~/.local/state`) — re-read fresh every `orca-workflow` run.
- PR/code hosting (`gh pr create/merge`) stays GitHub-only and unmodified — issue tracking and code hosting are separate axes.
- The onboarding sub-flow (undocumented non-GitHub repo) requires explicit user approval before committing a new tracker doc to the target repo — never silently guessed or auto-committed.
- `close_issue` never selects a transition outside the repo doc's documented workflow table — transitions like Duplicate/Won't Do are human-triage-only and must never be an agent's automated completion target.
- Linear adapter is out of scope for this plan — do not create `orca-workflows/issue-trackers/linear.md`.
- `orca-workflows/` needs no deploy step (plain symlink per `AGENTS.md`'s #22 decision) — only `skills/orca-workflow`, `skills/orca-task-runner`, `skills/orca-evaluate` go through `scripts/deploy-skills.sh`.

---

### Task 1: Extend the structural validator (red)

**Files:**
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing (pure filesystem/text checks)
- Produces: new pytest tests that later tasks must satisfy — `test_issue_tracker_file_exists`, `test_issue_tracker_adapter_defines_all_operations`, `test_jira_adapter_has_no_vprop_specific_values`, `test_jira_adapter_uses_structural_fields`, `test_github_adapter_uses_gh_cli`, `test_selection_doc_defines_backend_choice_and_onboarding_trigger`, `test_orca_workflow_no_hardcoded_gh_issue_calls`, `test_orca_workflow_references_issue_tracker_selection`, `test_orca_workflow_has_onboarding_subflow`, `test_orca_workflow_uses_abstract_tracker_operations`, `test_no_hardcoded_acceptance_criteria_heading`

- [ ] **Step 1: Append the new tests to the existing file**

Append this to the end of `tests/test_orca_skills.py` (keep everything already in the file — just add below it):

```python
ISSUE_TRACKERS_DIR = REPO_ROOT / "orca-workflows" / "issue-trackers"
TRACKER_ADAPTER_FILES = ["github.md", "jira.md"]
TRACKER_ALL_FILES = ["selection.md", "github.md", "jira.md"]
TRACKER_OPERATIONS = [
    "get_issue",
    "get_issue_type",
    "list_children",
    "get_child_order",
    "is_open",
    "close_issue",
    "link_pr_for_close",
]
VPROP_SPECIFIC_LEAKS = ["VP-", "voyagerx", "fb59360c"]


@pytest.mark.parametrize("filename", TRACKER_ALL_FILES)
def test_issue_tracker_file_exists(filename):
    assert (ISSUE_TRACKERS_DIR / filename).is_file(), (
        f"orca-workflows/issue-trackers/{filename} missing"
    )


@pytest.mark.parametrize("filename", TRACKER_ADAPTER_FILES)
def test_issue_tracker_adapter_defines_all_operations(filename):
    text = (ISSUE_TRACKERS_DIR / filename).read_text()
    for op in TRACKER_OPERATIONS:
        assert f"`{op}(" in text, f"{filename}: must define operation '{op}'"


@pytest.mark.parametrize("term", VPROP_SPECIFIC_LEAKS)
def test_jira_adapter_has_no_vprop_specific_values(term):
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    assert term not in text, (
        f"jira.md must stay repo-agnostic — found vprop-specific value '{term}'"
    )


def test_jira_adapter_uses_structural_fields():
    text = (ISSUE_TRACKERS_DIR / "jira.md").read_text()
    for field in ("hierarchyLevel", "parent", "statusCategory", "getTransitionsForJiraIssue"):
        assert field in text, f"jira.md must use the structural field/tool '{field}'"


def test_github_adapter_uses_gh_cli():
    text = (ISSUE_TRACKERS_DIR / "github.md").read_text()
    for call in ("gh issue view", "gh issue list", "gh issue close"):
        assert call in text, f"github.md must define '{call}'"


def test_selection_doc_defines_backend_choice_and_onboarding_trigger():
    text = (ISSUE_TRACKERS_DIR / "selection.md").read_text()
    assert "Issue tracker" in text, (
        "selection.md must describe the AGENTS.md/CLAUDE.md pointer lookup"
    )
    assert "온보딩" in text, (
        "selection.md must reference the onboarding trigger for undocumented repos"
    )


def test_orca_workflow_no_hardcoded_gh_issue_calls():
    text = _read_skill("orca-workflow")
    for term in ("gh issue view", "gh issue list", "gh issue close"):
        assert term not in text, (
            f"orca-workflow must not call '{term}' directly — route through the issue-tracker adapter"
        )
    assert "gh pr" in text, (
        "orca-workflow must keep gh pr calls — code hosting stays GitHub-specific"
    )


def test_orca_workflow_references_issue_tracker_selection():
    text = _read_skill("orca-workflow")
    assert "issue-trackers/selection.md" in text, (
        "orca-workflow §0 must resolve the backend via issue-trackers/selection.md"
    )


def test_orca_workflow_has_onboarding_subflow():
    text = _read_skill("orca-workflow")
    assert "온보딩" in text, (
        "orca-workflow §0 must define the onboarding subflow for undocumented repos"
    )


def test_orca_workflow_uses_abstract_tracker_operations():
    text = _read_skill("orca-workflow")
    for op in ("get_issue", "list_children", "get_child_order", "is_open", "close_issue"):
        assert op in text, f"orca-workflow must route issue-tracker access through '{op}'"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_hardcoded_acceptance_criteria_heading(name):
    text = _read_skill(name)
    assert "## Acceptance criteria" not in text, (
        f"{name}: acceptance-criteria heading must come from the resolved tracker marker, "
        "not a hardcoded GitHub heading"
    )
    assert "## What to build" not in text, (
        f"{name}: 'what to build' heading must not be hardcoded either"
    )
```

- [ ] **Step 2: Run it to confirm it fails for the right reason (red)**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest tests/test_orca_skills.py -v`

(Run the whole file, not a `-k` subset — several of the new test names don't share a common substring, e.g. `test_jira_adapter_uses_structural_fields` and `test_github_adapter_uses_gh_cli` have nothing in common with each other or with `test_issue_tracker_file_exists`, so no single `-k` expression would select all of them without also risking missing one.)

Expected: all pre-existing tests still PASS; these new ones FAIL — `test_issue_tracker_file_exists` (all 3 parametrized cases, the files don't exist yet), `test_issue_tracker_adapter_defines_all_operations` (both parametrized cases), `test_jira_adapter_has_no_vprop_specific_values` (all 3 parametrized cases), `test_jira_adapter_uses_structural_fields`, `test_github_adapter_uses_gh_cli`, `test_selection_doc_defines_backend_choice_and_onboarding_trigger` (all six because `orca-workflows/issue-trackers/` doesn't exist yet), `test_orca_workflow_no_hardcoded_gh_issue_calls` (the old `gh issue view/list/close` calls are still present), `test_orca_workflow_references_issue_tracker_selection`, `test_orca_workflow_has_onboarding_subflow`, `test_orca_workflow_uses_abstract_tracker_operations` (the referenced text doesn't exist yet), `test_no_hardcoded_acceptance_criteria_heading[orca-workflow]` and `[orca-task-runner]` and `[orca-evaluate]` (the old literal headings are still present). This confirms every new test is actually checking something, not vacuously passing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_orca_skills.py
git commit -m "test: add structural validator coverage for issue-tracker decoupling"
```

---

### Task 2: Write `orca-workflows/issue-trackers/selection.md`

**Files:**
- Create: `orca-workflows/issue-trackers/selection.md`

**Interfaces:**
- Consumes: the target repo's AGENTS.md/CLAUDE.md (read at `orca-workflow` run start) and the issue identifier passed to `orca-workflow`
- Produces: the backend name (`github` or `jira`) and the onboarding trigger condition, consumed by `orca-workflow` §0 and by Task 5's rewrite of that section

- [ ] **Step 1: Write the file**

```markdown
# Issue Tracker Selection

`orca-workflow` §0에서 실행 시작 시 1회 수행한다. **캐싱 없음** — 매 실행마다 새로 읽는다(대상 repo의
tracker 컨벤션이 바뀌어도 즉시 반영하기 위해서. 근거: `docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`).

## 1. 문서에서 백엔드 찾기

대상 repo의 AGENTS.md/CLAUDE.md에서 "Issue tracker" 섹션(예: `### Issue tracker` 헤딩, 별도 문서를 가리키는
링크 — vprop의 `docs/agents/issue-tracker.md` 패턴)을 찾는다. 있으면 그 문서가 명시하는 백엔드를 쓴다 —
아래 3으로.

## 2. 문서가 없을 때 — issue 식별자 모양으로 판단

곧바로 GitHub 기본값으로 넘어가지 않고, 먼저 이슈 식별자의 모양을 본다:

- 순수 숫자(`123`) → GitHub Issues 기본값(현재 동작과 동일). 아래 3의 `github.md`로.
- `PROJECT-숫자` 형태(`VP-456`, `ENG-789`)인데 tracker 문서가 없음 → **온보딩**으로 넘어간다
  (`skills/orca-workflow/SKILL.md` §0의 온보딩 서브플로우). cloudId 같은 값은 추측으로 채울 수 없다 —
  여기서 GitHub로 조용히 넘어가면 안 된다. 온보딩이 끝나면(문서가 생기면) 다시 1로 돌아가 해석한다.

## 3. 백엔드별 adapter 로드

- GitHub → `github.md`
- Jira → `jira.md`

adapter가 정의하는 오퍼레이션은 모든 백엔드에서 이름과 시그니처가 동일하다 — `orca-workflow`/
`orca-task-runner`/`orca-evaluate`는 어느 백엔드가 선택됐는지와 무관하게 같은 이름으로 호출한다:

- `get_issue(id)` — 타입/제목/본문/상태 조회
- `get_issue_type(id)` — epic vs task 판별
- `list_children(epic_id)` — child 목록+상태
- `get_child_order(epic_id, children)` — 실행 순서
- `is_open(id)` — 열림/닫힘 확인
- `close_issue(id, note)` — 종료 처리
- `link_pr_for_close(pr_number, id)` — PR 머지가 issue를 자동으로 닫아주는지

Linear 등 세 번째 백엔드가 필요해지면 이 파일의 1·2·3은 그대로 두고 `linear.md`만 추가한다 — 이 문서와
`orca-workflow` 쪽 변경은 필요 없다.
```

- [ ] **Step 2: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest tests/test_orca_skills.py::test_selection_doc_defines_backend_choice_and_onboarding_trigger "tests/test_orca_skills.py::test_issue_tracker_file_exists[selection.md]" -v`

Expected: both PASS.

- [ ] **Step 3: Commit**

```bash
git add orca-workflows/issue-trackers/selection.md
git commit -m "feat: add issue-tracker backend selection algorithm"
```

---

### Task 3: Write `orca-workflows/issue-trackers/github.md`

**Files:**
- Create: `orca-workflows/issue-trackers/github.md`

**Interfaces:**
- Consumes: `gh` CLI, the issue/epic id
- Produces: the 7 operations for the GitHub backend — extracted from today's `orca-workflow` behavior, no behavior change

- [ ] **Step 1: Write the file**

```markdown
# Issue Tracker Adapter — GitHub Issues

기본값 — repo에 별도 tracker 문서가 없고 issue 식별자가 숫자 형태이거나, 문서가 GitHub Issues를 명시할 때
쓴다. `gh` CLI만 사용, repo 고유 값 없음(label/body 컨벤션은 있지만 이건 GitHub Issues 자체의 구조적 한계지
특정 repo의 값이 아니다 — GitHub Issues엔 애초에 네이티브 계층 필드가 없다).

## `get_issue(id)`

```bash
gh issue view <id> --json number,title,body,state,labels
```

## `get_issue_type(id)`

GitHub Issues엔 네이티브 epic/task 계층이 없다 — `get_issue`가 반환한 `labels`/`body`로 판별한다(예: `epic`
label, 또는 body에 하위 이슈 목록 섹션이 있는지).

## `list_children(epic_id)`

```bash
gh issue list --search "epic:<epic_id> in:body" --json number,title,state
```

search가 못 잡으면 epic body에 나열된 child 번호를 직접 파싱하는 것도 동일 정보다.

## `get_child_order(epic_id, children)`

명시적 의존(`Blocked by #N`/`Refs #N`)이 있으면 그 그래프 순서. 없으면 epic body에 나열된 순서 그대로.

## `is_open(id)`

```bash
gh issue view <id> --json state -q .state
```

`"OPEN"`이면 열림.

## `close_issue(id, note)`

```bash
gh issue close <id> --comment "<note>"
```

## `link_pr_for_close(pr_number, id)`

**merge-magic 있음** — PR 머지가 "Closes #id" 키워드로 issue를 자동으로 닫아준다.

```bash
gh pr view "<pr_number>" --json body -q .body | grep -qiE "(closes|fixes|resolves) #<id>" \
  || gh pr edit "<pr_number>" --body "$(gh pr view "<pr_number>" --json body -q .body)

Closes #<id>"
```

키워드가 확인/보강되면 그걸로 충분하다. 단 base가 default branch가 아니면 키워드가 동작하지 않으므로,
`close_issue`로 머지 후 상태를 한 번 더 확인하는 것이 안전망이 된다(호출자인 `orca-workflow` §2d 참고).
```

- [ ] **Step 2: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest "tests/test_orca_skills.py::test_issue_tracker_file_exists[github.md]" "tests/test_orca_skills.py::test_issue_tracker_adapter_defines_all_operations[github.md]" tests/test_orca_skills.py::test_github_adapter_uses_gh_cli -v`

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add orca-workflows/issue-trackers/github.md
git commit -m "feat: add GitHub Issues adapter (extracted from orca-workflow, no behavior change)"
```

---

### Task 4: Write `orca-workflows/issue-trackers/jira.md`

**Files:**
- Create: `orca-workflows/issue-trackers/jira.md`

**Interfaces:**
- Consumes: Atlassian MCP tools (`mcp__claude_ai_Atlassian__*`), `cloudId` + workflow-transition facts read from the target repo's own tracker doc (never from this file)
- Produces: the 7 operations for the Jira backend, using only Jira's structural API fields — validated read-only against `~/Projects/vprop` during design (see the design spec's "세션 중 실측" section)

- [ ] **Step 1: Write the file**

```markdown
# Issue Tracker Adapter — Jira

Atlassian MCP 툴(`mcp__claude_ai_Atlassian__*`) 사용. **repo의 tracker 문서 없이는 이 adapter가 아예
동작하지 않는다** — `getJiraIssue`/`searchJiraIssuesUsingJql`/`transitionJiraIssue` 등 모든 호출이
`cloudId`를 필수 파라미터로 받는데, 그 값은 대상 repo의 tracker 문서에만 있다(예: vprop의
`docs/agents/issue-tracker.md`). 이 파일에는 project key·transition ID 같은 repo 고유 값을 넣지 않는다 —
전부 대상 repo의 tracker 문서에서 온다.

## 전제 — repo 문서에서 읽어야 하는 값

- `cloudId` (필수 — 이게 없으면 아래 오퍼레이션을 하나도 호출할 수 없다)
- 정식 워크플로 transition 표, 그중 "완료"에 해당하는 이름
- acceptance-criteria가 적히는 섹션 이름

## `get_issue(id)`

```
getJiraIssue(cloudId, issueIdOrKey=id)
```

`fields.issuetype`, `fields.summary`, `fields.description`, `fields.status`를 본다.

## `get_issue_type(id)`

```
fields.issuetype.hierarchyLevel == 1  →  epic
```

프로젝트 지역화(한국어 "에픽"/영어 "Epic" 등)와 무관하게 구조적으로 판별한다 — 이름 문자열을 매칭하지 않는다.

## `list_children(epic_id)`

```
searchJiraIssuesUsingJql(cloudId, jql="parent = <epic_id>")
```

## `get_child_order(epic_id, children)`

명시적 issue link(blocks/is blocked by)가 있으면 그 그래프. 없으면(흔하다 — Jira epic이 의존 링크 없이
설명 본문에 표/목록만 나열하는 경우가 많다) epic description에 나열된 순서 그대로.

## `is_open(id)`

```
getJiraIssue(cloudId, issueIdOrKey=id).fields.status.statusCategory.key != "done"
```

## `close_issue(id, note)`

repo 문서의 워크플로 표에서 "완료" transition 이름을 찾아 그 transition id로 전환한다:

```
transitionJiraIssue(cloudId, issueIdOrKey=id, transition={id: <완료 transition id>})
addCommentToJiraIssue(cloudId, issueIdOrKey=id, comment=note)
```

`getTransitionsForJiraIssue`가 `statusCategory.key == "done"`인 후보를 여러 개 반환할 수 있다(예: 완료/
Duplicate/Won't Do). **repo 문서의 워크플로 표에 없는 transition은 고려하지 않는다.** Duplicate/Won't Do류는
사람이 티켓을 나중에 리뷰하며 "더 이상 안 한다"고 판단할 때 쓰는 것이라, agent의 완료 처리 후보가 아니다 —
매 완료 처리마다 여럿 중 고를 문제가 아니다. repo 문서에 "완료" transition이 명시돼 있지 않으면(워크플로
표 자체가 없거나 애매하면) 조용히 아무거나 고르지 않고 `orca-workflow`가 사용자에게 확인을 요청한다.

## `link_pr_for_close(pr_number, id)`

**merge-magic 없음** — GitHub PR 머지로 Jira 티켓이 자동으로 닫히지 않는다. PR 머지 직후
`close_issue(id, note)`를 명시 호출한다(`note` 예: `"Merged via PR #<pr_number>"`).
```

- [ ] **Step 2: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest tests/test_orca_skills.py -v -k "jira"`

(Passing the whole file plus `-k "jira"` — rather than explicit node IDs plus `-k` — is what lets pytest discover and filter *all* matching tests, including the 3 parametrized `test_jira_adapter_has_no_vprop_specific_values` cases, instead of only the tests named as positional args.)

Expected: all PASS, including all 3 `test_jira_adapter_has_no_vprop_specific_values` parametrized cases.

- [ ] **Step 3: Commit**

```bash
git add orca-workflows/issue-trackers/jira.md
git commit -m "feat: add generic Jira adapter (structural fields only, no repo-specific values)"
```

---

### Task 5: Rewrite `skills/orca-workflow/SKILL.md`

**Files:**
- Modify: `skills/orca-workflow/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/issue-trackers/{selection,github,jira}.md` (Tasks 2–4)
- Produces: an `orca-workflow` that resolves its issue tracker once per run via `selection.md`, runs the onboarding sub-flow for undocumented non-GitHub repos, and routes epic/PASS logic through the 7 abstract operations instead of literal `gh issue` calls. `gh pr` calls are unchanged.

- [ ] **Step 1: Update the frontmatter description and H1 intro**

Find:
```
description: Invoke explicitly via `/orca-workflow` — do not rely on phrase-matching, which collides with Orca's built-in `orchestration` skill (multi-agent coordination, task dispatch, coordinator loops). Picks up a GitHub issue and drives it through its full lifecycle — branches on issue type (epic vs task), runs issue-drain validation for epics, builds an issue-graph task-queue, and for each task relays the orca-task-runner/orca-evaluate contract negotiation, routes PASS/FAIL/ESCALATE (and GATE_FAIL straight to inspecting), and escalates to a human inspection checkpoint. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative.
```

Replace:
```
description: Invoke explicitly via `/orca-workflow` — do not rely on phrase-matching, which collides with Orca's built-in `orchestration` skill (multi-agent coordination, task dispatch, coordinator loops). Picks up an issue (GitHub Issues or Jira, resolved per repo — see `~/.agents/orca-workflows/issue-trackers/selection.md`) and drives it through its full lifecycle — branches on issue type (epic vs task), runs issue-drain validation for epics, builds an issue-graph task-queue, and for each task relays the orca-task-runner/orca-evaluate contract negotiation, routes PASS/FAIL/ESCALATE (and GATE_FAIL straight to inspecting), and escalates to a human inspection checkpoint. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative.
```

Find:
```
GitHub issue 하나를 받아 끝까지(merge까지) 가져가는 최상위 오케스트레이터다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.
```

Replace:
```
이슈 하나를 받아 끝까지(merge까지) 가져가는 최상위 오케스트레이터다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.
```

- [ ] **Step 2: Replace §0 issue-type detection with the 3-tier resolution + onboarding**

Find:
```
- `orca status --json` ready. 실패 시 아래 "폴백".
- `gh issue view <num>`으로 issue 타입 확인(label 또는 body 구조로 epic/task 판별).
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. 기본 posture는 `-a never -s workspace-write`.
```

Replace:
```
- `orca status --json` ready. 실패 시 아래 "폴백".
- **이슈 트래커 해석** (실행 시작 시 1회, 캐싱 없이 — 매 실행마다 새로 읽는다): `~/.agents/orca-workflows/issue-trackers/selection.md`가 정의하는 절차로 백엔드를 정하고, 그 백엔드의 `~/.agents/orca-workflows/issue-trackers/{github,jira}.md`가 정의하는 `get_issue`/`get_issue_type`/`list_children`/`get_child_order`/`is_open`/`close_issue`/`link_pr_for_close`를 이후 전체 실행에서 쓴다. 구체 값(project key, transition id 등)은 이 스킬에 복제하지 않는다 — 항상 selection.md가 가리키는 대상 repo의 tracker 문서에서 얻는다.
- **온보딩** — selection.md가 "문서 없음 + GitHub 형식이 아닌 이슈 ID"로 판정하면, 곧바로 GitHub로 넘어가지 않고 사용자에게 직접 묻는다: ①어떤 tracker를 쓰는지 + 그 API를 부르는 데 필요한 최소 정보(Jira라면 site·cloudId·project key) ②"완료" transition/상태 이름, acceptance-criteria 섹션 이름. 받은 답으로 `docs/agents/issue-tracker.md` 형식의 초안을 작성해 보여주고, 승인되면 별도의 작은 커밋으로 대상 repo에 반영한 뒤 이번 실행을 이어간다. 이후 실행부터는 문서가 있으므로 다시 트리거되지 않는다.
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. 기본 posture는 `-a never -s workspace-write`.
```

- [ ] **Step 3: Replace §1 epic-path `gh issue` calls with abstract operations**

Find:
```
- 각 child issue가 self-contained한지(`## What to build` + `## Acceptance criteria`)
- `Blocked by` / `Refs` 관계가 실제로 존재하고 방향이 맞는지
- 그래프상 빠진 child나 순환 의존이 없는지

```bash
gh issue view <epic-num> --json body,title
gh issue list --search "epic:<epic-num> in:body" --json number,title,body   # 또는 epic body에 나열된 child 번호 파싱
```

검증 실패 → 사용자에게 보고하고 멈춘다(수정 후 재호출). 통과 → **1b**.

**1b. task-queue 확정** — child issue 그래프(`Blocked by`/`Refs`/epic body 나열 순서)로 실행 순서를 정한다. file-overlap이 아니라 **issue 그래프 기준**이다(구현 전이라 파일 목록을 아직 모른다).

**1c. 순회** — ready task마다 아래 "2. Task 경로"를 실행. 완료되면 dequeue하고 의존이 풀린 다음 task로 진행. 이번 큐가 비었다고 바로 epic을 닫지 않는다 — 이번 실행 밖에서 처리된 child가 있을 수 있으므로, 닫기 전에 child 전체가 실제로 닫혀 있는지 확인한다(GitHub는 child issue 완료를 자동으로 epic에 반영하지 않으므로 이 확인·종료는 항상 명시적으로 한다):

```bash
gh issue list --search "epic:<epic-num> in:body" --json number,state -q '.[] | select(.state=="OPEN")'
# 위 출력이 비어 있을 때만(=열린 child가 없을 때만) epic을 닫는다
gh issue close <epic-num> --comment "All child tasks complete: <child-num-1>, <child-num-2>, ..."
```
```

Replace:
```
- 각 child issue가 self-contained한지(§0에서 해석한 acceptance-criteria 섹션 + "무엇을 만들지"가 본문에 있는지)
- 의존 관계(`get_child_order`가 참고하는 것과 같은 그래프)가 실제로 존재하고 방향이 맞는지
- 그래프상 빠진 child나 순환 의존이 없는지

```
get_issue(epic-num)
list_children(epic-num)
```

검증 실패 → 사용자에게 보고하고 멈춘다(수정 후 재호출). 통과 → **1b**.

**1b. task-queue 확정** — `get_child_order(epic-num, children)`로 실행 순서를 정한다. file-overlap이 아니라 **issue 그래프 기준**이다(구현 전이라 파일 목록을 아직 모른다).

**1c. 순회** — ready task마다 아래 "2. Task 경로"를 실행. 완료되면 dequeue하고 의존이 풀린 다음 task로 진행. 이번 큐가 비었다고 바로 epic을 닫지 않는다 — 이번 실행 밖에서 처리된 child가 있을 수 있으므로, 닫기 전에 child 전체가 실제로 닫혀 있는지 확인한다(child 완료가 epic에 자동 반영되지 않는 tracker일 수 있으므로 이 확인·종료는 항상 명시적으로 한다):

```
list_children(epic-num)의 각 항목에 is_open() 확인
# 전부 닫혀 있을 때만(=열린 child가 없을 때만) epic을 닫는다
close_issue(epic-num, "All child tasks complete: <child-num-1>, <child-num-2>, ...")
```
```

- [ ] **Step 4: Add the acceptance-criteria marker to both §2a dispatch specs**

Find:
```
orca orchestration task-create --spec "<issue 번호 + 제안서/구현 모드>" --json
```

Replace:
```
orca orchestration task-create --spec "<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드>" --json
```

Find:
```
orca orchestration task-create --spec "<diff 또는 제안서 경로 + issue 번호 + 요청 모드>" --json
```

Replace:
```
orca orchestration task-create --spec "<diff 또는 제안서 경로 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드>" --json
```

- [ ] **Step 5: Replace the §2d PASS-routing block's `gh issue`/keyword logic with abstract operations**

Find:
```
  ```bash
  # task 브랜치에 열린 PR이 있는지 확인 — 없으면 여기서 만든다(할당 로그의 worktree/branch 사용)
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  if [ -z "$pr_num" ]; then
    gh pr create --head "<task-branch>" --title "<task 제목>" --body "Closes #<task-issue-num>"
    pr_num="$(gh pr view "<task-branch>" --json number -q .number)"  # gh pr create는 URL만 출력, --json 미지원
  fi
  # 기존 PR이면 closing 키워드가 있는지 확인 — 없으면 squash merge로도 issue가 자동으로 닫히지 않는다
  gh pr view "$pr_num" --json body -q .body | grep -qiE "(closes|fixes|resolves) #<task-issue-num>" \
    || gh pr edit "$pr_num" --body "$(gh pr view "$pr_num" --json body -q .body)

  Closes #<task-issue-num>"

  # premerge 게이트 — orca-evaluate의 PASS는 "코드가 acceptance criteria를 충족하는가"만 보고,
  # "지금 이 브랜치를 origin/main에 얹어도 안전한가"(stale-main, gate-integrity 자기수정 여부)는
  # 안 본다. 그건 lifecycle-gate-policy의 premerge.sh 몫이라 merge 직전에 따로 불러야 한다.
  # 이 레포가 그 컨벤션을 아직 안 썼으면(scripts/premerge.sh 자체가 없으면) 예전처럼 바로 merge —
  # 여기서 새로 강제하지 않는다.
  if [ -f scripts/premerge.sh ]; then
    # --review-done: orca-evaluate §3의 code review가 이미 그 review 통과를 의미한다.
    if ! bash scripts/premerge.sh --review-done; then
      premerge_exit=$?
      printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"PREMERGE_FAIL","retry":0,"premerge_exit":%s}\n' \
        "$(date -u +%FT%TZ)" "$premerge_exit" >> ~/.local/state/orca-workflows/logs/assignments.jsonl
      # 여기서 merge하지 않는다 — gh pr merge를 건너뛰고 바로 아래 "3. Inspecting"으로 분기한다
      # (GATE_FAIL과 같은 원칙: 여기서 추가 재시도 걸지 않음).
      # premerge.sh exit code: 2=precondition(stale-main 등) 3=PROTECTED 4=REVIEW 5=MIGRATION_ESCALATE
      # 그 외=verify/e2e 실패 통과값. Inspecting 보고에 이 exit code와 마지막 stderr 몇 줄을 그대로 첨부한다.
    else
      gh pr merge "$pr_num" --squash --delete-branch
      # closing 키워드는 base가 default branch일 때만 자동 종료를 트리거한다(예: task PR이 epic 통합
      # 브랜치로 들어가는 구성이면 키워드가 아예 동작하지 않는다) — 그래서 아래 확인·폴백이 부수적
      # 안전장치가 아니라 실질적으로 issue를 닫는 유일한 경로일 수 있다. 상태 확인 후에도 항상 실행한다.
      [ "$(gh issue view <task-issue-num> --json state -q .state)" = "OPEN" ] \
        && gh issue close <task-issue-num> --comment "Merged via PR #$pr_num"
    fi
  else
    gh pr merge "$pr_num" --squash --delete-branch
    [ "$(gh issue view <task-issue-num> --json state -q .state)" = "OPEN" ] \
      && gh issue close <task-issue-num> --comment "Merged via PR #$pr_num"
  fi
  ```
```

Replace:
```
  ```bash
  # task 브랜치에 열린 PR이 있는지 확인 — 없으면 여기서 만든다(할당 로그의 worktree/branch 사용)
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  if [ -z "$pr_num" ]; then
    # link_pr_for_close가 "머지가 자동으로 닫아줌"(GitHub)이면 body에 "Closes #<task-issue-num>" 포함.
    # 아니면(Jira 등 merge-magic 없음) 참고용으로 티켓 키만 적고 자동-닫힘 키워드는 넣지 않는다 —
    # 그 트래커에선 의미가 없는 텍스트다.
    gh pr create --head "<task-branch>" --title "<task 제목>" --body "<link_pr_for_close 결과에 따른 본문>"
    pr_num="$(gh pr view "<task-branch>" --json number -q .number)"  # gh pr create는 URL만 출력, --json 미지원
  fi
  # link_pr_for_close가 자동-닫힘이라고 답할 때만(GitHub) 키워드 존재를 확인·보강한다 — 그 외(Jira 등)는
  # 이 단계를 건너뛴다. issue 종료는 트래커 무관하게 머지 후 한 경로(아래)로 처리된다.
  if <link_pr_for_close(pr_num, task-issue-num) == 자동-닫힘>; then
    gh pr view "$pr_num" --json body -q .body | grep -qiE "(closes|fixes|resolves) #<task-issue-num>" \
      || gh pr edit "$pr_num" --body "$(gh pr view "$pr_num" --json body -q .body)

  Closes #<task-issue-num>"
  fi

  # premerge 게이트 — orca-evaluate의 PASS는 "코드가 acceptance criteria를 충족하는가"만 보고,
  # "지금 이 브랜치를 origin/main에 얹어도 안전한가"(stale-main, gate-integrity 자기수정 여부)는
  # 안 본다. 그건 lifecycle-gate-policy의 premerge.sh 몫이라 merge 직전에 따로 불러야 한다.
  # 이 레포가 그 컨벤션을 아직 안 썼으면(scripts/premerge.sh 자체가 없으면) 예전처럼 바로 merge —
  # 여기서 새로 강제하지 않는다.
  if [ -f scripts/premerge.sh ]; then
    # --review-done: orca-evaluate §3의 code review가 이미 그 review 통과를 의미한다.
    if ! bash scripts/premerge.sh --review-done; then
      premerge_exit=$?
      printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"PREMERGE_FAIL","retry":0,"premerge_exit":%s}\n' \
        "$(date -u +%FT%TZ)" "$premerge_exit" >> ~/.local/state/orca-workflows/logs/assignments.jsonl
      # 여기서 merge하지 않는다 — gh pr merge를 건너뛰고 바로 아래 "3. Inspecting"으로 분기한다
      # (GATE_FAIL과 같은 원칙: 여기서 추가 재시도 걸지 않음).
      # premerge.sh exit code: 2=precondition(stale-main 등) 3=PROTECTED 4=REVIEW 5=MIGRATION_ESCALATE
      # 그 외=verify/e2e 실패 통과값. Inspecting 보고에 이 exit code와 마지막 stderr 몇 줄을 그대로 첨부한다.
    else
      gh pr merge "$pr_num" --squash --delete-branch
      # 코드호스팅(PR 머지)은 GitHub 전용이라 미변경. issue 종료는 트래커 무관하게 이 한 경로로
      # 처리된다 — GitHub는 보통 위 키워드로 이미 닫혀 있어 아래는 안전망(no-op)이고, Jira 등
      # merge-magic이 없는 트래커는 이 호출이 유일한 종료 경로다.
      is_open(<task-issue-num>) && close_issue(<task-issue-num>, "Merged via PR #$pr_num")
    fi
  else
    gh pr merge "$pr_num" --squash --delete-branch
    is_open(<task-issue-num>) && close_issue(<task-issue-num>, "Merged via PR #$pr_num")
  fi
  ```
```

- [ ] **Step 6: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest tests/test_orca_skills.py::test_orca_workflow_no_hardcoded_gh_issue_calls tests/test_orca_skills.py::test_orca_workflow_references_issue_tracker_selection tests/test_orca_skills.py::test_orca_workflow_has_onboarding_subflow tests/test_orca_skills.py::test_orca_workflow_uses_abstract_tracker_operations "tests/test_orca_skills.py::test_no_hardcoded_acceptance_criteria_heading[orca-workflow]" "tests/test_orca_skills.py::test_no_stale_terms_in_body[orca-workflow]" tests/test_orca_skills.py::test_orca_workflow_never_generates_or_evaluates_itself tests/test_orca_skills.py::test_delegation_references -v`

Expected: all PASS. (`test_no_stale_terms_in_body`/`test_orca_workflow_never_generates_or_evaluates_itself`/`test_delegation_references` are pre-existing tests — running them here confirms this rewrite didn't regress them.)

- [ ] **Step 7: Commit**

```bash
git add skills/orca-workflow/SKILL.md
git commit -m "feat(orca-workflow): route issue tracking through the tracker adapter instead of hardcoded gh issue calls"
```

---

### Task 6: Update `skills/orca-task-runner/SKILL.md`

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md`

**Interfaces:**
- Consumes: the acceptance-criteria section name `orca-workflow` now forwards in its dispatch spec (Task 5, §2a)
- Produces: an `orca-task-runner` that no longer assumes the GitHub `## Acceptance criteria` heading literally

- [ ] **Step 1: Replace the hardcoded heading reference**

Find:
```
- 검증 방법(구체적인 파일/함수/테스트로 — issue의 `## Acceptance criteria`를 어떻게 커버할지)
```

Replace:
```
- 검증 방법(구체적인 파일/함수/테스트로 — issue의 acceptance-criteria 섹션[`orca-workflow`가 dispatch spec으로 넘겨준 섹션명 — 백엔드에 따라 `## Acceptance criteria`, "완료 조건" 등 다르다]을 어떻게 커버할지)
```

- [ ] **Step 2: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest "tests/test_orca_skills.py::test_no_hardcoded_acceptance_criteria_heading[orca-task-runner]" "tests/test_orca_skills.py::test_no_stale_terms_in_body[orca-task-runner]" tests/test_orca_skills.py::test_orca_task_runner_declares_destructive_ops_field -v`

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "feat(orca-task-runner): stop hardcoding the GitHub acceptance-criteria heading"
```

---

### Task 7: Update `skills/orca-evaluate/SKILL.md`

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md`

**Interfaces:**
- Consumes: the acceptance-criteria section name `orca-workflow` now forwards in its dispatch spec (Task 5, §2a)
- Produces: an `orca-evaluate` that no longer assumes the GitHub `## Acceptance criteria` heading literally, in both places it's referenced

- [ ] **Step 1: Replace the first hardcoded heading reference (§1)**

Find:
```
`orca-task-runner`가 구현 전 제안서(범위 + 검증 방법)를 보내오면, 이 세션(evaluator)이 직접 판단하지 않고 **coding agent 터미널을 스폰**해서 issue의 원본 `## Acceptance criteria`에 대조 검토를 맡긴다 — 제안된 파일 범위·검증 방법이 실제 코드베이스에서 기술적으로 타당한지 보는 일이라 §3 code-reviewer와 같은 이유로 강한 reasoning 모델이 낫다.
```

Replace:
```
`orca-task-runner`가 구현 전 제안서(범위 + 검증 방법)를 보내오면, 이 세션(evaluator)이 직접 판단하지 않고 **coding agent 터미널을 스폰**해서 issue의 원본 acceptance-criteria 섹션(`orca-workflow`가 dispatch spec으로 넘겨준 섹션명)에 대조 검토를 맡긴다 — 제안된 파일 범위·검증 방법이 실제 코드베이스에서 기술적으로 타당한지 보는 일이라 §3 code-reviewer와 같은 이유로 강한 reasoning 모델이 낫다.
```

- [ ] **Step 2: Replace the second hardcoded heading reference (§1, the "no acceptance criteria" fallback)**

Find:
```
`## Acceptance criteria`가 issue body에 없으면 평가를 진행하지 않고 `orca-workflow`에 보고한다. (issue 생성 시 이 섹션을 보장하는 절차는 아직 없다 — 별도 후속 이슈. 임시로는 `/triage` 리다이렉트 대상으로 취급한다.)
```

Replace:
```
`orca-workflow`가 넘겨준 acceptance-criteria 섹션이 issue body에 없으면 평가를 진행하지 않고 `orca-workflow`에 보고한다. (issue 생성 시 이 섹션을 보장하는 절차는 아직 없다 — 별도 후속 이슈. 임시로는 `/triage` 리다이렉트 대상으로 취급한다.)
```

- [ ] **Step 3: Run the relevant test subset**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest "tests/test_orca_skills.py::test_no_hardcoded_acceptance_criteria_heading[orca-evaluate]" "tests/test_orca_skills.py::test_no_stale_terms_in_body[orca-evaluate]" tests/test_orca_skills.py::test_orca_evaluate_has_verdict_vocabulary tests/test_orca_skills.py::test_orca_evaluate_has_migration_escalate_condition -v`

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/orca-evaluate/SKILL.md
git commit -m "feat(orca-evaluate): stop hardcoding the GitHub acceptance-criteria heading"
```

---

### Task 8: Full validator run (green)

**Files:**
- Test: `tests/test_orca_skills.py` (full suite)

**Interfaces:**
- Consumes: everything from Tasks 1–7
- Produces: a fully green suite — the gate for moving on to deployment

- [ ] **Step 1: Run the full suite**

Run: `cd /Users/minchul/Projects/skills && python3 -m pytest tests/test_orca_skills.py -v`

Expected: all tests PASS (0 failed).

- [ ] **Step 2: If anything fails, fix inline and re-run**

Do not proceed to Task 9 until this is fully green.

---

### Task 9: Deploy the updated skills

**Files:**
- Modify (filesystem, outside the repo): `~/.agents/skills/{orca-workflow,orca-task-runner,orca-evaluate}/` and `~/.codex/skills/{orca-workflow,orca-task-runner,orca-evaluate}/` (real copies via `rsync`), `~/.claude/skills/{orca-workflow,orca-task-runner,orca-evaluate}` (symlinks into `~/.agents/skills/`, created only if not already present — per `scripts/deploy-skills.sh`)

**Interfaces:**
- Consumes: `skills/orca-workflow`, `skills/orca-task-runner`, `skills/orca-evaluate` from this repo (must be committed — `scripts/deploy-skills.sh` refuses dirty skills)
- Produces: updated global skill copies. `orca-workflows/issue-trackers/*.md` needs **no** deploy step — `~/.agents/orca-workflows` is a plain symlink to this repo's checkout (`AGENTS.md` #22 decision), so Tasks 2–4's new files are already live.

- [ ] **Step 1: Confirm the three skills are clean (deploy-skills.sh will refuse otherwise)**

```bash
cd /Users/minchul/Projects/skills && git status --short -- skills/orca-workflow skills/orca-task-runner skills/orca-evaluate
```

Expected: empty output (everything committed in Tasks 5–7).

- [ ] **Step 2: Run the deploy script**

```bash
cd /Users/minchul/Projects/skills && scripts/deploy-skills.sh orca-workflow orca-task-runner orca-evaluate
```

Expected: exits 0, prints success for all three skills, no `ABORT`/`SKIP` lines.

- [ ] **Step 3: Verify the deployed copies match the source**

```bash
for name in orca-workflow orca-task-runner orca-evaluate; do
  diff "/Users/minchul/Projects/skills/skills/$name/SKILL.md" "$HOME/.agents/skills/$name/SKILL.md" \
    && echo "$name: matches SSoT"
done
```

Expected: `$name: matches SSoT` for all three, no diff output above any line.

- [ ] **Step 4: Confirm `orca-workflows` symlink still resolves into this repo**

```bash
readlink -f ~/.agents/orca-workflows/issue-trackers/jira.md
```

Expected: resolves to `/Users/minchul/Projects/skills/orca-workflows/issue-trackers/jira.md`.

_(No commit in this task — it only touches files outside the repo.)_

---

### Task 10: Manual dry-run review against the real vprop convention

**Files:**
- None modified — this is a read-through checklist, not a code change.

**Interfaces:**
- Consumes: `skills/orca-workflow/SKILL.md`, `orca-workflows/issue-trackers/jira.md`, and the already-confirmed facts about `~/Projects/vprop` recorded in `docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`'s "세션 중 실측" section (Epic count, `parent` field linkage, empty `issuelinks`, the 3 done-category transitions) — no new live Jira calls needed, since those facts were already gathered read-only during design.
- Produces: confirmation that a fresh reader of the rewritten files would reach the same conclusions on vprop that the design session did. This is the closest thing to an integration test these prose files can get, and it substitutes for re-running live MCP calls.

- [ ] **Step 1: Confirm the design spec's real-world facts are still reflected correctly**

```bash
cd /Users/minchul/Projects/skills && grep -n "hierarchyLevel\|parent =\|getTransitionsForJiraIssue\|statusCategory" orca-workflows/issue-trackers/jira.md
```

Expected: all four terms appear, each tied to the correct operation (`hierarchyLevel` under `get_issue_type`, `parent =` under `list_children`, `statusCategory` under `is_open`, `getTransitionsForJiraIssue` under `close_issue`).

- [ ] **Step 2: Confirm no vprop-specific values leaked into the adapter**

```bash
cd /Users/minchul/Projects/skills && grep -n "VP-\|voyagerx\|fb59360c\|41.*완료" orca-workflows/issue-trackers/jira.md
```

Expected: no output. If anything matches, it means a vprop-specific value was hardcoded where a structural field should be — fix before proceeding.

- [ ] **Step 3: Trace through the resolution algorithm by hand against vprop's actual doc**

Read `~/Projects/vprop/AGENTS.md`'s "Issue tracker" section and `~/Projects/vprop/docs/agents/issue-tracker.md`, then confirm each of these by hand (referencing `skills/orca-workflow/SKILL.md` §0 and `orca-workflows/issue-trackers/selection.md`):

1. §0's tier-1 lookup would find vprop's `### Issue tracker` → `docs/agents/issue-tracker.md` pointer, and thus never trigger onboarding for this repo.
2. `close_issue` would target the "완료" (id 41) transition — the one named in vprop's documented workflow table — and never Duplicate/Won't Do (undocumented there, per the design spec's `getTransitionsForJiraIssue` finding).
3. `get_issue_type` on a known epic (e.g. VP-1145) would read `hierarchyLevel == 1` and classify it as epic, matching the confirmed `totalCount: 39` epics in the VP project.
4. `list_children(VP-1145)` maps to `parent = VP-1145`, matching the confirmed 4-child result (VP-1144/1146/1147/1148).
5. `get_child_order` would fall back to epic-description order for vprop, since `issuelinks` was confirmed empty on VP-1148.

- [ ] **Step 4: Confirm the GitHub path is unchanged for repos without a tracker doc**

This repo (`skills`) itself has no "Issue tracker" section in its AGENTS.md and uses plain numeric GitHub issue
numbers (see recent commits referencing `#32`, `#31`, `#30`). Trace `orca-workflow` §0 and
`orca-workflows/issue-trackers/selection.md` by hand against that fact:

1. Tier-1 lookup finds no "Issue tracker" section in this repo's AGENTS.md.
2. The issue identifier shape (plain number) matches GitHub's convention → selection.md's step 2 routes to
   `github.md` directly, without ever reaching the onboarding sub-flow.
3. `github.md`'s operations are the same `gh` CLI calls `orca-workflow` used to run inline before this
   plan — confirm by diffing intent, not text: `get_issue` → `gh issue view --json ...` (was: same call
   inline), `list_children` → `gh issue list --search "epic:<id> in:body"` (same), `close_issue` → `gh issue
   close --comment` (same), `link_pr_for_close` → the same "Closes #id" keyword check (same). No behavior
   change for this repo or any other undocumented GitHub repo.

- [ ] **Step 5: Note the known gap out loud (no action needed — just don't let it go unmentioned)**

Confirm the design spec's testing section still applies: **write-path operations (`close_issue`, PR merge) are not exercised by this plan** — they get their first real test during a supervised live `orca-workflow` run against vprop, per this repo's convention against running write/deploy commands merely to check output.

---

## Summary of what's deliberately NOT in this plan

- `orca-workflows/issue-trackers/linear.md` — add only when a Linear-tracked repo actually exists.
- Any change to `~/Projects/vprop` (its `docs/agents/issue-tracker.md`, its stale "Jira Epics" AGENTS.md language, or its `create-ticket`/`plan-ticket`/`implement-ticket`/`ship-pr` skills).
- Whether the generator/evaluator sub-sessions `orca-task-runner`/`orca-evaluate` spawn have Jira MCP access — flagged as an open follow-up in the design spec, tied to `model-selection.md`, not resolved here.
