# Project-Setup Skill + E2E Tooling Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `orca-evaluate`'s hardcoded "Playwright MCP" agent-e2e tooling with a
project-declared tool read from `docs/agents/e2e-tooling.md`, and move all first-run project
onboarding (issue tracker + e2e tooling) out of `orca-workflow` §0 into a new, manually-invoked
`project-setup` skill.

**Architecture:** A new prose config file (`docs/agents/e2e-tooling.md`, same style as the
existing `docs/agents/issue-tracker.md`) declares Platform/Tool/Usage guidance/Precondition for
the target repo's agent-e2e testing. `orca-evaluate` §2 reads it at spawn time and splices its
fields into the `agy -p` launch string instead of the literal "Playwright MCP" text. A new
`project-setup` skill (invoked via `/project-setup`) owns writing both this file and
`docs/agents/issue-tracker.md` (moved out of `orca-workflow` §0's old inline onboarding).
`orca-workflow` §0 and `~/.agents/orca-workflows/issue-trackers/selection.md` §2 both redirect to
`/project-setup` instead of onboarding inline.

**Tech Stack:** Markdown skill/reference docs (prose, no schema files — this repo's established
convention per `docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`), Python
`pytest` for doc-schema regression tests (existing convention, see `tests/test_question_type_wait.py`
and `tests/test_ack_not_peek.py`), bash for `orca-set.version`/`deploy-skills.sh` interaction.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-11-project-setup-e2e-tooling-design.md` — every
  task below implements one numbered section of it; re-read the relevant section before starting
  a task if anything here is ambiguous.
- `docs/agents/e2e-tooling.md` and `docs/agents/issue-tracker.md` are **prose documents**, not
  JSON/YAML — this repo explicitly rejected structured config files for this purpose (design spec
  §"검토했으나 기각한 대안" #2, referencing the prior issue-tracker design's rejected alternative
  #3).
- Skill prose must stay cross-tool portable (Claude Code, Codex, Antigravity) — never name a
  Claude-Code-specific tool (e.g. `AskUserQuestion`) inside `SKILL.md` bodies; use generic phrasing
  like "ask the user directly" (AGENTS.md root principle, reaffirmed by the design spec §2).
- Do not touch `skills/orca-workflow-epic/SKILL.md` or `skills/orca-workflow-task/SKILL.md` — both
  already delegate tracker-onboarding decisions to `selection.md`, so fixing `selection.md` once
  fixes all three callers (design spec, "검토했으나 기각한 대안" #4).
- Do not change the numeric-issue-ID → GitHub-default path in `selection.md` §2 — it must keep
  working with no tracker doc present (regression guard called out explicitly in the design spec,
  §3 and §"검토했으나 기각한 대안").
- `docs/agents/e2e-tooling.md` supports exactly one platform/tool per repo (no multi-platform
  support) — YAGNI per design spec §1.
- `project-setup` joins `skills/orca-set.version` as a 7th member at the same version label as the
  other six (currently `v1.1.8`) — bump the version string when adding it (AGENTS.md: "이 여섯은
  항상 같은 버전 라벨을 공유", extended here to seven).
- New pytest test files go in `tests/`, follow the doc-schema-assertion style already used by
  `tests/test_question_type_wait.py`/`tests/test_ack_not_peek.py` (read the target `.md` file,
  assert exact substrings/structure — no mocking, no network).

---

### Task 1: `docs/agents/e2e-tooling.md` schema — write the reference doc and its test

This task defines the *shape* other tasks will read/write. No skill yet reads or writes a real
instance of this file — this task creates the reference/example doc that documents the schema, and
a test that pins its section headings so later tasks (and downstream repos) have a stable contract.

**Files:**
- Create: `docs/agents/e2e-tooling.md` (this repo's own instance — this repo is web-tooling-only
  today, i.e. Playwright-appropriate, since its skills operate on git worktrees/CLI, not a running
  app with a UI to click through — see Step 1 below for the exact content decision)
- Test: `tests/test_e2e_tooling_schema.py`

**Interfaces:**
- Produces: the four section headings `## Platform`, `## Tool`, `## Usage guidance`,
  `## Precondition` — every later task that reads or writes this file (Tasks 3, 5) must use these
  exact heading strings.

- [ ] **Step 1: Decide this repo's own `docs/agents/e2e-tooling.md` content**

  This repo (`sleeptimegrt-skills`) has no running web/native app of its own — its "agent e2e" is
  the Orca pipeline's own agent-e2e gate description, which already defaults to Playwright for web
  projects (design spec §2, "Tool 기본 제안"). Since this repo itself doesn't drive a UI, write
  the file as the reference example other repos copy, using the web/Playwright default explicitly
  so the schema is self-demonstrating:

  ```markdown
  # E2E Tooling

  ## Platform
  web

  ## Tool
  Playwright MCP

  ## Usage guidance
  Accessibility-tree 기반 — 스크린샷·좌표 클릭보다 UI 변경에 덜 깨진다. `orca-evaluate`가 이
  텍스트를 그대로 `agy -p` 프롬프트에 splice한다.

  ## Precondition
  없음 (웹 앱은 배포된 URL 또는 로컬 dev 서버만 있으면 된다).
  ```

  This is a legitimate own-repo default, not a placeholder — this repo's skills describe a web-first
  default tool (design spec §2, `project-setup` §2's proposed default), so documenting it here is
  the correct instance, not a stand-in for a real answer.

- [ ] **Step 2: Write the failing test**

  ```python
  """Doc-schema pin for docs/agents/e2e-tooling.md (issue #140 design spec §1) -- the four
  section headings this file must carry so orca-evaluate/§2 and project-setup/§2 can rely on a
  stable shape when reading or writing an instance of this file in any repo.
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  E2E_TOOLING_MD = REPO_ROOT / "docs" / "agents" / "e2e-tooling.md"


  def test_e2e_tooling_doc_exists():
      assert E2E_TOOLING_MD.is_file()


  def test_e2e_tooling_doc_has_all_four_sections_in_order():
      text = E2E_TOOLING_MD.read_text()
      headings = ["## Platform", "## Tool", "## Usage guidance", "## Precondition"]
      positions = [text.index(h) for h in headings]
      assert positions == sorted(positions), (
          "sections must appear in the order Platform, Tool, Usage guidance, Precondition"
      )


  def test_e2e_tooling_doc_declares_playwright_for_this_repo():
      text = E2E_TOOLING_MD.read_text()
      platform_start = text.index("## Platform")
      tool_start = text.index("## Tool")
      platform_section = text[platform_start:tool_start]
      assert "web" in platform_section
      usage_start = text.index("## Usage guidance")
      tool_section = text[tool_start:usage_start]
      assert "Playwright MCP" in tool_section
  ```

  Save this to `tests/test_e2e_tooling_schema.py`.

- [ ] **Step 3: Run test to verify it fails**

  Run: `cd /Users/minchul/worktrees/skills/orca-evaluate-2-agent-e2e-mcp-playwright && python3 -m pytest tests/test_e2e_tooling_schema.py -v`
  Expected: FAIL — `docs/agents/e2e-tooling.md` does not exist yet (`test_e2e_tooling_doc_exists`
  fails first; the other two error out on `FileNotFoundError` when `.read_text()` is called).

- [ ] **Step 4: Create the file from Step 1's content**

  Create `docs/agents/e2e-tooling.md` with exactly the content written in Step 1.

- [ ] **Step 5: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_e2e_tooling_schema.py -v`
  Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

  ```bash
  git add docs/agents/e2e-tooling.md tests/test_e2e_tooling_schema.py
  git commit -m "docs: add docs/agents/e2e-tooling.md schema + this repo's own instance (issue #140)"
  ```

---

### Task 2: `project-setup` skill — issue-tracker onboarding section (§1)

Create the new skill's `SKILL.md` with only the issue-tracker section for now (moved verbatim from
`orca-workflow` §0, unchanged behavior) — Task 3 adds the e2e-tooling section to the same file.
Splitting this way keeps each task's diff reviewable against one design-spec subsection at a time.

**Files:**
- Create: `skills/project-setup/SKILL.md`
- Test: `tests/test_project_setup_schema.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the skill file `skills/project-setup/SKILL.md` with a `## 1. Issue tracker` heading —
  Task 3 appends `## 2. E2E tooling` to this same file, and Task 6 references this skill's name
  (`project-setup`) from `orca-workflow` §0 and `selection.md` §2.

- [ ] **Step 1: Write the failing test**

  ```python
  """Doc-schema pin for the new skills/project-setup/SKILL.md (issue #140 design spec §2) -- a
  general-purpose, manually-invoked (`/project-setup`) onboarding skill that owns writing both
  docs/agents/issue-tracker.md and docs/agents/e2e-tooling.md. This test file is built up across
  two tasks: this task adds the §1 (issue tracker) assertions, Task 3 adds §2 (e2e tooling).
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  PROJECT_SETUP_MD = REPO_ROOT / "skills" / "project-setup" / "SKILL.md"


  def test_project_setup_skill_exists():
      assert PROJECT_SETUP_MD.is_file()


  def test_project_setup_has_yaml_frontmatter_with_name_and_description():
      text = PROJECT_SETUP_MD.read_text()
      assert text.startswith("---\n")
      end = text.index("\n---\n", 4)
      frontmatter = text[4:end]
      assert "name: project-setup" in frontmatter
      assert "description:" in frontmatter


  def test_project_setup_has_issue_tracker_section():
      text = PROJECT_SETUP_MD.read_text()
      assert "## 1. Issue tracker" in text


  def test_issue_tracker_section_skips_when_doc_already_exists():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 1. Issue tracker")
      end = text.index("## 2.") if "## 2." in text else len(text)
      window = text[start:end]
      assert "docs/agents/issue-tracker.md" in window
      assert "있으면" in window and ("스킵" in window or "건너" in window)


  def test_issue_tracker_section_github_default_writes_no_file():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 1. Issue tracker")
      end = text.index("## 2.") if "## 2." in text else len(text)
      window = text[start:end]
      assert "GitHub" in window
      # The GitHub-default path must not create a doc -- selection.md's numeric-ID fallback
      # depends on the doc's absence.
      assert "문서를 만들지 않" in window or "문서 생성 없이" in window


  def test_project_setup_avoids_claude_code_specific_tool_names():
      text = PROJECT_SETUP_MD.read_text()
      assert "AskUserQuestion" not in text
  ```

  Save this to `tests/test_project_setup_schema.py`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_project_setup_schema.py -v`
  Expected: FAIL — `skills/project-setup/SKILL.md` does not exist.

- [ ] **Step 3: Write `skills/project-setup/SKILL.md` (issue-tracker section only)**

  ```markdown
  ---
  name: project-setup
  description: Invoke explicitly via `/project-setup` — do not phrase-match. One-time-per-repo onboarding for project-level agent config docs under `docs/agents/`: issue tracker (`issue-tracker.md`) and agent-e2e tooling (`e2e-tooling.md`). Idempotent — sections whose doc already exists are skipped and reported as already-configured. `orca-workflow` §0 and `~/.agents/orca-workflows/issue-trackers/selection.md` §2 both redirect here instead of onboarding inline. Self-relative.
  ---

  # Project Setup

  대상 repo에 아직 없는 `docs/agents/*.md` 온보딩 문서를 만든다. 인자 없이 아래 섹션을 순서대로
  확인한다 — 이미 있는 문서는 스킵하고 "이미 설정됨"만 보고한다.

  **크로스툴 이식성**: "사용자에게 직접 묻는다"는 표현을 일반적으로만 쓴다 — 특정 도구(예: Claude
  Code의 질문 UI)의 이름을 이 문서 본문에 넣지 않는다. 플랫폼마다 자기 방식으로 묻는다.

  ## 1. Issue tracker

  `docs/agents/issue-tracker.md`가 있으면 스킵.

  없으면 사용자에게 직접 묻는다: ①이 repo가 GitHub Issues를 쓰는지, 다른 트래커(Jira/Linear 등)를
  쓰는지 ②(GitHub가 아니면) 그 tracker의 API를 부르는 데 필요한 최소 정보(Jira라면 site·cloudId·
  project key) ③"완료" transition/상태 이름. (acceptance-criteria가 적히는 섹션 이름은 여기서 묻지
  않는다 — AC는 저장소 설정 시점의 고정값이 아니라 이슈마다 매번 새로 협상되는 값이고,
  `orca-evaluate` §1의 contract negotiation이 이미 소유한다.)

  **GitHub면 문서를 만들지 않고 이 섹션을 종료한다** — 숫자 ID 폴백(`~/.agents/orca-workflows/
  issue-trackers/selection.md` §2)이 문서 부재를 전제로 동작하므로, 여기서 GitHub 전용 문서를 만들면
  그 폴백 경로가 깨진다.

  다른 트래커면 받은 답으로 `docs/agents/issue-tracker.md` 형식의 초안을 작성해 사용자에게 보여주고,
  승인되면 별도의 작은 커밋으로 대상 repo에 반영한다. 이후 실행부터는 문서가 있으므로 이 섹션이 다시
  트리거되지 않는다.
  ```

- [ ] **Step 4: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_project_setup_schema.py -v`
  Expected: PASS (all issue-tracker-related tests pass; e2e-tooling tests don't exist yet in this
  file — they're added in Task 3)

- [ ] **Step 5: Commit**

  ```bash
  git add skills/project-setup/SKILL.md tests/test_project_setup_schema.py
  git commit -m "feat: add project-setup skill with issue-tracker onboarding section (issue #140)"
  ```

---

### Task 3: `project-setup` skill — e2e-tooling onboarding section (§2)

Append the e2e-tooling section to the same `SKILL.md` created in Task 2, and extend the same test
file with the corresponding assertions.

**Files:**
- Modify: `skills/project-setup/SKILL.md` (append `## 2. E2E tooling`)
- Modify: `tests/test_project_setup_schema.py` (append e2e-tooling assertions)

**Interfaces:**
- Consumes: `skills/project-setup/SKILL.md`'s existing `## 1. Issue tracker` section (Task 2) —
  this task's new section must come immediately after it, numbered `## 2.`.
- Produces: `## 2. E2E tooling` heading — Task 6 references "both sections of `project-setup`"
  when redirecting `orca-workflow` §0.

- [ ] **Step 1: Write the failing test additions**

  Append to `tests/test_project_setup_schema.py`:

  ```python
  def test_project_setup_has_e2e_tooling_section():
      text = PROJECT_SETUP_MD.read_text()
      assert "## 2. E2E tooling" in text


  def test_e2e_tooling_section_skips_when_doc_already_exists():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 2. E2E tooling")
      window = text[start:]
      assert "docs/agents/e2e-tooling.md" in window
      assert "있으면" in window and ("스킵" in window or "건너" in window)


  def test_e2e_tooling_section_has_no_unconditional_default():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 2. E2E tooling")
      window = text[start:]
      # Unlike issue-tracker's GitHub default, e2e-tooling must always ask -- no silent default.
      assert "무조건" in window


  def test_e2e_tooling_section_covers_all_four_fields():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 2. E2E tooling")
      window = text[start:]
      for field in ["Platform", "Tool", "Usage guidance", "Precondition"]:
          assert field in window


  def test_e2e_tooling_section_proposes_playwright_default_for_web():
      text = PROJECT_SETUP_MD.read_text()
      start = text.index("## 2. E2E tooling")
      window = text[start:]
      assert "Playwright" in window
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_project_setup_schema.py -v`
  Expected: FAIL — the 5 new e2e-tooling tests fail (`## 2. E2E tooling` heading not found yet).

- [ ] **Step 3: Append the e2e-tooling section to `skills/project-setup/SKILL.md`**

  Append after the `## 1. Issue tracker` section:

  ```markdown

  ## 2. E2E tooling

  `docs/agents/e2e-tooling.md`가 있으면 스킵.

  없으면 **무조건** 사용자에게 직접 묻는다(GitHub 같은 무조건-기본값이 없다) — ①Platform(자유
  텍스트, 예시: `web`/`native-android`/`native-ios`/`desktop`) ②Tool(MCP/도구 이름 — Platform이
  `web`류면 기본 제안으로 "Playwright MCP"를 보여주되, 사람이 최종 승인한다) ③Usage guidance(그
  도구를 쓸 때 알아야 할 사항 — accessibility-tree 기반인지, YAML 시나리오인지 등) ④Precondition(연결
  전 충족해야 하는 인프라 조건 — 에뮬레이터 부팅, 앱 사전 설치 등).

  받은 답으로 아래 형식의 초안을 작성해 사용자에게 보여주고, 승인되면 별도의 작은 커밋으로 대상
  repo에 반영한다:

  ```markdown
  # E2E Tooling

  ## Platform
  <답변>

  ## Tool
  <답변>

  ## Usage guidance
  <답변>

  ## Precondition
  <답변, 없으면 "없음">
  ```

  이후 실행부터는 문서가 있으므로 이 섹션이 다시 트리거되지 않는다. `orca-evaluate` §2가 이 문서를
  agent-e2e 스폰 시 읽는다.
  ```

- [ ] **Step 4: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_project_setup_schema.py -v`
  Expected: PASS (all tests in the file pass, issue-tracker + e2e-tooling combined)

- [ ] **Step 5: Commit**

  ```bash
  git add skills/project-setup/SKILL.md tests/test_project_setup_schema.py
  git commit -m "feat: add e2e-tooling onboarding section to project-setup (issue #140)"
  ```

---

### Task 4: `~/.agents/orca-workflows/issue-trackers/selection.md` §2 — self-contained onboarding redirect

Change the onboarding-trigger paragraph so it points at `/project-setup` instead of at
`orca-workflow` §0's (now-removed, see Task 6) inline logic. This is the file all three callers
(`orca-workflow`, `orca-workflow-epic`, `orca-workflow-task`) already delegate to, so fixing it here
fixes all three without touching their `SKILL.md` files (design spec, rejected-alternative #4).

**Files:**
- Modify: `/Users/minchul/Projects/skills/orca-workflows/issue-trackers/selection.md` (this repo's
  worktree exposes it at `orca-workflows/issue-trackers/selection.md` — see Step 0)
- Test: `tests/test_selection_md_project_setup_redirect.py`

**Interfaces:**
- Consumes: the skill name `project-setup` (Task 2/3) — this file must reference it by that exact
  name so the redirect instruction is unambiguous.
- Produces: nothing consumed by later tasks — `orca-workflow-epic`/`orca-workflow-task` need no
  changes because they already delegate here.

- [ ] **Step 0: Confirm the on-disk path this worktree edits**

  `~/.agents/orca-workflows` is a symlink to `/Users/minchul/Projects/skills/orca-workflows` (the
  main-branch checkout), **not** to this worktree (per AGENTS.md's `orca-workflows/` deploy-path
  decision, #22: "edits made in a feature worktree are invisible at `~/.agents/orca-workflows/`
  until merged to main"). This worktree has its own `orca-workflows/` directory tracked in git —
  edit `orca-workflows/issue-trackers/selection.md` **inside this worktree/repo checkout**, not the
  symlink target. The change takes effect at `~/.agents/orca-workflows/` only after this branch
  merges to main. Run:

  ```bash
  cd /Users/minchul/worktrees/skills/orca-evaluate-2-agent-e2e-mcp-playwright
  ls orca-workflows/issue-trackers/selection.md
  ```

  Expected: file exists at that repo-relative path — this is the file every later step in this task
  edits.

- [ ] **Step 1: Write the failing test**

  ```python
  """Doc-schema pin for orca-workflows/issue-trackers/selection.md's onboarding redirect
  (issue #140 design spec §2/§3). Before this change, the onboarding trigger pointed at
  `skills/orca-workflow/SKILL.md` §0's inline onboarding subflow, which this issue moves into
  the new project-setup skill. selection.md must now be self-contained: it names
  `/project-setup` directly instead of pointing at orca-workflow's (now-removed) inline logic.
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  SELECTION_MD = REPO_ROOT / "orca-workflows" / "issue-trackers" / "selection.md"


  def test_onboarding_trigger_redirects_to_project_setup():
      text = SELECTION_MD.read_text()
      start = text.index("PROJECT-숫자")
      end = text.index("cloudId 같은 값은 추측으로 채울 수 없다")
      window = text[start:end]
      assert "/project-setup" in window


  def test_onboarding_trigger_no_longer_points_at_orca_workflow_inline_subflow():
      text = SELECTION_MD.read_text()
      start = text.index("PROJECT-숫자")
      end = text.index("cloudId 같은 값은 추측으로 채울 수 없다")
      window = text[start:end]
      assert "orca-workflow/SKILL.md` §0의 온보딩 서브플로우" not in window


  def test_numeric_id_github_default_path_unchanged():
      # Regression guard (design spec explicit call-out): the numeric-ID -> GitHub-default path
      # must still work with no tracker doc present -- this task must not touch it.
      text = SELECTION_MD.read_text()
      assert "순수 숫자(`123`) → GitHub Issues 기본값(현재 동작과 동일). 아래 3의 `github.md`로." in text
  ```

  Save this to `tests/test_selection_md_project_setup_redirect.py`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_selection_md_project_setup_redirect.py -v`
  Expected: FAIL on `test_onboarding_trigger_redirects_to_project_setup` (no `/project-setup`
  string present yet) and `test_onboarding_trigger_no_longer_points_at_orca_workflow_inline_subflow`
  (the old string is still there). The regression-guard test passes already (nothing changed yet).

- [ ] **Step 3: Edit `orca-workflows/issue-trackers/selection.md`**

  Find (current lines 18-20):

  ```markdown
  - `PROJECT-숫자` 형태(`VP-456`, `ENG-789`)인데 tracker 문서가 없음 → **온보딩**으로 넘어간다
    (`skills/orca-workflow/SKILL.md` §0의 온보딩 서브플로우). cloudId 같은 값은 추측으로 채울 수 없다 —
    여기서 GitHub로 조용히 넘어가면 안 된다. 온보딩이 끝나면(문서가 생기면) 다시 1로 돌아가 해석한다.
  ```

  Replace with:

  ```markdown
  - `PROJECT-숫자` 형태(`VP-456`, `ENG-789`)인데 tracker 문서가 없음 → 호출자(`orca-workflow`/
    `orca-workflow-epic`/`orca-workflow-task` 중 무엇이든)가 사용자에게 `/project-setup` 실행을
    안내하며 이번 실행을 중단한다. cloudId 같은 값은 추측으로 채울 수 없다 — 여기서 GitHub로
    조용히 넘어가면 안 된다. `/project-setup`이 문서를 만든 뒤 재실행하면 다시 1로 돌아가 해석한다.
  ```

  Also update line 44 ("tracker 문서가 없으면 기존처럼 온보딩으로 보내고, 온보딩 문서가 backend를
  명시하게 한다.") to reference `/project-setup` instead of "온보딩":

  Find:

  ```markdown
  tracker 문서가 없으면 기존처럼 온보딩으로 보내고, 온보딩 문서가 backend를 명시하게 한다.
  ```

  Replace with:

  ```markdown
  tracker 문서가 없으면 위와 동일하게 `/project-setup`으로 안내하고, 그 결과 만들어질 문서가
  backend를 명시하게 한다.
  ```

- [ ] **Step 4: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_selection_md_project_setup_redirect.py -v`
  Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

  ```bash
  git add orca-workflows/issue-trackers/selection.md tests/test_selection_md_project_setup_redirect.py
  git commit -m "docs: selection.md onboarding redirect points at /project-setup (issue #140)"
  ```

---

### Task 5: `orca-evaluate` §2 + fallback (L194) — read `e2e-tooling.md`, drop the Playwright hardcode

This is the core fix the issue asked for. Rewrite the agent-e2e spawn procedure to read
`docs/agents/e2e-tooling.md` and splice its fields into the `agy -p` string, replace the fallback's
hardcoded Playwright reference, and strengthen the self-recheck paragraph to catch silent tool
substitution (the exact selah-android failure mode from the issue).

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md` (§2 body, spawn command block, self-recheck paragraph,
  §4 ESCALATE bullet, fallback section)
- Test: `tests/test_orca_evaluate_e2e_tooling.py`

**Interfaces:**
- Consumes: `docs/agents/e2e-tooling.md`'s four field names (Task 1) — the spec text this task
  writes must reference `Platform`/`Tool`/`Usage guidance`/`Precondition` by those exact names.
- Produces: nothing consumed by later tasks in this plan.

- [ ] **Step 1: Write the failing test**

  ```python
  """Doc-schema pin for skills/orca-evaluate/SKILL.md's agent-e2e tooling generalization
  (issue #140). Before this change, §2's spawn command hardcoded the literal string
  "Playwright MCP 지침" into the agy -p launch string, and the fallback (old L194) hardcoded
  "Playwright MCP를 붙인 headless agy". This made agent-e2e unusable for native-mobile projects
  (studio-hevv/selah-android in the issue's real-world evidence). The fix reads
  docs/agents/e2e-tooling.md at spawn time and splices its declared tool into the launch string,
  with an ESCALATE-and-redirect-to-/project-setup path when the doc is missing, and a
  strengthened self-recheck that catches silent tool substitution (the issue's exact observed
  failure: Playwright declared, raw adb used instead).
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  EVALUATE_SKILL = REPO_ROOT / "skills" / "orca-evaluate" / "SKILL.md"


  def _section(text: str, start_marker: str, end_marker: str) -> str:
      start = text.index(start_marker)
      end = text.index(end_marker, start)
      return text[start:end]


  def test_section_2_no_longer_hardcodes_playwright_literal_in_spawn_command():
      text = EVALUATE_SKILL.read_text()
      section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
      assert "Playwright MCP 지침" not in section2


  def test_section_2_reads_e2e_tooling_doc_before_spawn():
      text = EVALUATE_SKILL.read_text()
      section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
      assert "docs/agents/e2e-tooling.md" in section2


  def test_section_2_splices_tool_and_usage_guidance_into_launch_string():
      text = EVALUATE_SKILL.read_text()
      section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
      assert "Tool" in section2 and "Usage guidance" in section2


  def test_section_2_missing_doc_redirects_to_project_setup():
      text = EVALUATE_SKILL.read_text()
      section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
      assert "/project-setup" in section2


  def test_self_recheck_paragraph_checks_declared_tool_actually_used():
      text = EVALUATE_SKILL.read_text()
      section2 = _section(text, "## 2. Test Gate", "## 3. Diff")
      assert "Tool" in section2
      assert "우회" in section2 or "대체" in section2


  def test_escalate_bucket_covers_missing_e2e_tooling_doc():
      text = EVALUATE_SKILL.read_text()
      section4 = text[text.index("## 4."):]
      assert "e2e-tooling" in section4 or "e2e-tooling.md" in section4


  def test_fallback_no_longer_hardcodes_playwright():
      text = EVALUATE_SKILL.read_text()
      fallback = text[text.index("## 폴백"):]
      assert "Playwright MCP를 붙인 headless agy" not in fallback
      assert "docs/agents/e2e-tooling.md" in fallback
  ```

  Save this to `tests/test_orca_evaluate_e2e_tooling.py`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_orca_evaluate_e2e_tooling.py -v`
  Expected: FAIL — the current file still has the literal `"Playwright MCP 지침"` string in §2 and
  `"Playwright MCP를 붙인 headless agy"` in the fallback; none of the new redirect/splice text
  exists yet.

- [ ] **Step 3: Edit §2's opening paragraph**

  Find (current §2 opening sentence):

  ```markdown
  앱을 직접 조작하는 e2e. Playwright MCP(accessibility-tree 기반 — 스크린샷·좌표 클릭보다 UI 변경에 덜 깨진다)를 붙인 agy(Gemini) 세션을 **headless(`-p`, one-shot)로** 스폰한다, REPL 아님(agy는 이 스킬 전체에서 REPL 금지 — 이유는 §0). 시나리오·경로·요청 형식을 launch 시점의 `-p` 인자 하나에 다 담아 한 번에 실행하고, 이후 orchestration 왕복 없이 완료를 회수한다. (e2e·pgTAP은 여기서 안 돈다 — §0 참고.)
  ```

  Replace with:

  ```markdown
  앱을 직접 조작하는 e2e. 스폰 전에 evaluator가 대상 repo의 `docs/agents/e2e-tooling.md`를 직접
  읽는다(script 없이, evaluator 자신의 판단으로). **문서가 없으면**: 이 시점에는 이미
  `orca-workflow` §0이 막았어야 하므로 도달은 예외적 경로(폴백 직행 등)다 — 조용히 Playwright로
  되돌아가지 않고, §4의 ESCALATE("인프라 문제로 판단 불가" 버킷)로 처리하며 `/project-setup` 실행을
  안내한다. **문서가 있으면**: `Platform`/`Tool`/`Usage guidance`/`Precondition` 네 필드를 읽어,
  그 `Tool`이 붙은 agy(Gemini) 세션을 **headless(`-p`, one-shot)로** 스폰한다, REPL 아님(agy는 이
  스킬 전체에서 REPL 금지 — 이유는 §0). `Usage guidance` 텍스트 + 시나리오·경로·요청 형식 + `
  Precondition` 확인 지침을 launch 시점의 `-p` 인자 하나에 다 담아 한 번에 실행하고, 이후
  orchestration 왕복 없이 완료를 회수한다. (e2e·pgTAP은 여기서 안 돈다 — §0 참고.)
  ```

- [ ] **Step 4: Edit the spawn command block**

  Find (current spawn command, the `--command` line inside the code block):

  ```bash
  orca_call_with_retry "orca-evaluate" "agent-e2e" -- \
    orca terminal create --worktree active --title eval-agent-e2e \
    --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오 + 앱 URL/worktree 경로 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
  ```

  Replace with:

  ```bash
  orca_call_with_retry "orca-evaluate" "agent-e2e" -- \
    orca terminal create --worktree active --title eval-agent-e2e \
    --command "agy -p '<e2e-tooling.md의 Tool + Usage guidance + 테스트 시나리오 + 앱 URL/worktree 경로 + e2e-tooling.md의 Precondition 확인 지침 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
  ```

- [ ] **Step 5: Edit the self-recheck paragraph (after the spawn code block)**

  Find:

  ```markdown
  이 세션(evaluator)은 agy의 자기 요약을 **그대로 믿지 않는다** — 이미 이 세션 자체가 롱컨텍스트 REPL 세션이므로, `$report_path`와 원본 트레이스를 직접(별도 터미널 스폰 없이) 읽어서 "성공했다"는 보고가 실제로 맞는지, 조용히 막히거나 우회한 흔적은 없는지 확인한다.
  ```

  Replace with:

  ```markdown
  이 세션(evaluator)은 agy의 자기 요약을 **그대로 믿지 않는다** — 이미 이 세션 자체가 롱컨텍스트 REPL 세션이므로, `$report_path`와 원본 트레이스를 직접(별도 터미널 스폰 없이) 읽어서 "성공했다"는 보고가 실제로 맞는지, 조용히 막히거나 우회한 흔적은 없는지 확인한다. **구체 기준**: 트레이스에서 `e2e-tooling.md`의 `Tool` 필드가 실제로 쓰였는지 확인한다. 다른 방식(예: 선언은 Maestro인데 raw adb로 우회)으로 조용히 대체된 흔적이 있으면 agy의 성공 자기요약을 그대로 신뢰하지 않는다(실측: studio-hevv/selah-android — 선언된 Playwright MCP 대신 즉석 raw `adb shell` 명령으로 조용히 대체된 사례).
  ```

- [ ] **Step 6: Edit §4's ESCALATE bullet**

  Find:

  ```markdown
  - **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.
  ```

  Replace with:

  ```markdown
  - **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경, **또는 `docs/agents/e2e-tooling.md` 부재·precondition 미충족** — 후자는 `/project-setup` 실행 안내와 함께)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.
  ```

- [ ] **Step 7: Edit the fallback (§ 폴백) agent-e2e bullet**

  Find:

  ```markdown
  agent e2e(§2)는 로컬에서 Playwright MCP를 붙인 headless agy 세션으로 직접 실행하고 report 경로만 기록.
  ```

  Replace with:

  ```markdown
  agent e2e(§2)는 로컬에서 `docs/agents/e2e-tooling.md`가 선언한 도구를 붙인 headless agy 세션으로 직접 실행하고 report 경로만 기록(§2와 동일 도구 선택 절차 — 문서가 없으면 §2와 동일하게 ESCALATE).
  ```

- [ ] **Step 8: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_orca_evaluate_e2e_tooling.py -v`
  Expected: PASS (7 passed)

- [ ] **Step 9: Run the full existing orca-evaluate test suite to check for regressions**

  Run: `python3 -m pytest tests/test_contract_schema_fails_before_fix.py tests/test_select_reviewer.py -v`
  Expected: PASS (unchanged — these tests target §1/§3, which this task did not touch)

- [ ] **Step 10: Commit**

  ```bash
  git add skills/orca-evaluate/SKILL.md tests/test_orca_evaluate_e2e_tooling.py
  git commit -m "fix: orca-evaluate §2 reads docs/agents/e2e-tooling.md instead of hardcoding Playwright (issue #140)"
  ```

---

### Task 6: `orca-workflow` §0 — remove inline onboarding, add e2e-tooling gate before routing

Remove the now-duplicated inline tracker-onboarding paragraph (moved to `project-setup` in Tasks
2-3, and `selection.md` now redirects there per Task 4), and add an e2e-tooling existence check
before §1's routing so a missing doc is caught before any generation work starts.

**Files:**
- Modify: `skills/orca-workflow/SKILL.md` (§0)
- Test: `tests/test_orca_workflow_project_setup_gate.py`

**Interfaces:**
- Consumes: `/project-setup` (Tasks 2-3) and `selection.md`'s redirect (Task 4) — this task's new
  prose must be consistent with both (same skill name, same "run `/project-setup`" phrasing).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

  ```python
  """Doc-schema pin for skills/orca-workflow/SKILL.md §0's onboarding removal + e2e-tooling gate
  (issue #140). Before this change, §0 carried its own inline tracker-onboarding paragraph
  (now redundant with orca-workflows/issue-trackers/selection.md's redirect, see
  tests/test_selection_md_project_setup_redirect.py, and with the new project-setup skill, see
  tests/test_project_setup_schema.py) and had no e2e-tooling existence check at all -- §1 routing
  ran unconditionally even when docs/agents/e2e-tooling.md was absent, which is the root cause
  of issue #140 (agent-e2e always hardcoded to Playwright with no per-project override).
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  ORCA_WORKFLOW_SKILL = REPO_ROOT / "skills" / "orca-workflow" / "SKILL.md"


  def test_section_0_no_longer_has_inline_onboarding_paragraph():
      text = ORCA_WORKFLOW_SKILL.read_text()
      section0 = text[text.index("## 0."):text.index("## 1.")]
      assert "①어떤 tracker를 쓰는지" not in section0


  def test_section_0_has_e2e_tooling_gate_before_routing():
      text = ORCA_WORKFLOW_SKILL.read_text()
      section0 = text[text.index("## 0."):text.index("## 1.")]
      assert "docs/agents/e2e-tooling.md" in section0
      assert "/project-setup" in section0


  def test_e2e_tooling_gate_precedes_section_1_in_document_order():
      text = ORCA_WORKFLOW_SKILL.read_text()
      gate_pos = text.index("docs/agents/e2e-tooling.md")
      section1_pos = text.index("## 1.")
      assert gate_pos < section1_pos


  def test_stuck_dispatched_sweep_bullet_still_present():
      # Regression guard -- this task only removes the onboarding bullet and adds the
      # e2e-tooling gate; the unrelated stale-dispatched-sweep bullet must survive untouched.
      text = ORCA_WORKFLOW_SKILL.read_text()
      section0 = text[text.index("## 0."):text.index("## 1.")]
      assert "고착 dispatched 스윕" in section0
  ```

  Save this to `tests/test_orca_workflow_project_setup_gate.py`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_orca_workflow_project_setup_gate.py -v`
  Expected: FAIL on the first three tests (inline onboarding paragraph still present, no
  e2e-tooling gate exists yet). The fourth (regression guard) passes already.

- [ ] **Step 3: Remove the inline onboarding bullet**

  Find (current §0 bullet):

  ```markdown
  - **온보딩**: selection.md가 "문서 없음 + GitHub 형식이 아닌 이슈 ID"로 판정하면, 곧바로 GitHub로 넘어가지
    않고 사용자에게 직접 묻는다: ①어떤 tracker를 쓰는지 + 그 API를 부르는 데 필요한 최소 정보(Jira라면
    site·cloudId·project key) ②"완료" transition/상태 이름. 받은 답으로 `docs/agents/issue-tracker.md` 형식의
    초안을 작성해 보여주고, 승인되면 별도의 작은 커밋으로 대상 repo에 반영한 뒤 이번 실행을 이어간다. 이후
    실행부터는 문서가 있으므로 다시 트리거되지 않는다.
  ```

  Delete this bullet entirely (its content now lives in `skills/project-setup/SKILL.md` §1, Task 2,
  and `selection.md` §2 now redirects there directly, Task 4 — so `orca-workflow` no longer needs
  to describe the onboarding flow itself, only to gate on it).

- [ ] **Step 4: Add the e2e-tooling gate immediately before §1 (still inside §0)**

  Add this bullet right after the "이슈 트래커 해석" bullet (replacing the position the deleted
  onboarding bullet occupied):

  ```markdown
  - **E2E tooling 확인**(실행 시작 시 1회, §1 라우팅 이전): 대상 repo의 `docs/agents/e2e-tooling.md`가
    없으면 §1로 넘어가지 않고 사용자에게 `/project-setup` 실행을 안내하며 이번 실행을 중단한다 —
    generation이 끝난 뒤 evaluate 단계(`orca-evaluate` §2)에서야 막히는 낭비를 피한다. 이슈 ID 모양에
    따른 예외는 없다(GitHub 숫자 ID든 Jira형이든 agent-e2e는 모든 task 평가에 항상 필요하다는 기존
    전제 — `orca-evaluate` §2가 이미 무조건 게이트로 문서화). 문서가 있으면 그대로 §1로 진행한다.
  ```

- [ ] **Step 5: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_orca_workflow_project_setup_gate.py -v`
  Expected: PASS (4 passed)

- [ ] **Step 6: Run the full test suite to check for cross-file regressions**

  Run: `python3 -m pytest tests/ -v`
  Expected: PASS across all files (this confirms Tasks 1-6 compose without breaking any
  pre-existing test, e.g. `test_log_enum_schema.py`'s unrelated assertions).

- [ ] **Step 7: Commit**

  ```bash
  git add skills/orca-workflow/SKILL.md tests/test_orca_workflow_project_setup_gate.py
  git commit -m "refactor: orca-workflow §0 drops inline onboarding, gates on e2e-tooling.md before routing (issue #140)"
  ```

---

### Task 7: `~/.agents/orca-workflows/models/agy.md` L75 — generalize the Playwright mapping note

Update the one remaining hardcoded Playwright reference outside `orca-evaluate` itself: the agy
model-mapping doc's agent-e2e configuration note.

**Files:**
- Modify: `orca-workflows/models/agy.md` (same worktree-vs-symlink caveat as Task 4 — edit the
  repo-tracked copy, not `~/.agents/orca-workflows/`)
- Test: `tests/test_agy_md_generalized_e2e_tool.py`

**Interfaces:**
- Consumes: nothing from other tasks (this file only needed a wording generalization, no schema
  dependency).
- Produces: nothing consumed by later tasks — this is the last task in the plan.

- [ ] **Step 1: Write the failing test**

  ```python
  """Doc-schema pin for orca-workflows/models/agy.md's agent-e2e configuration note
  (issue #140). Before this change, the note hardcoded "an accessibility-tree Playwright MCP"
  as the only tool agy configures for agent-e2e. Generalized to reference the project-declared
  tool orca-evaluate/§2 resolves from docs/agents/e2e-tooling.md, which is not necessarily an
  MCP server at all (e.g. a raw CLI like Maestro or adb).
  """
  from __future__ import annotations

  from pathlib import Path

  REPO_ROOT = Path(__file__).resolve().parent.parent
  AGY_MD = REPO_ROOT / "orca-workflows" / "models" / "agy.md"


  def test_agent_e2e_note_no_longer_hardcodes_playwright():
      text = AGY_MD.read_text()
      assert "an accessibility-tree Playwright MCP" not in text


  def test_agent_e2e_note_references_project_declared_tool():
      text = AGY_MD.read_text()
      assert "project-declared" in text


  def test_agent_e2e_note_still_requires_smoke_test_before_relying_on_it():
      # Regression guard -- the smoke-test-before-relying-on-it requirement predates this issue
      # and must survive the wording generalization.
      text = AGY_MD.read_text()
      assert "smoke-test" in text
  ```

  Save this to `tests/test_agy_md_generalized_e2e_tool.py`.

- [ ] **Step 2: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_agy_md_generalized_e2e_tool.py -v`
  Expected: FAIL — the current text still has the literal `"an accessibility-tree Playwright MCP"`
  string and no `"project-declared"` string.

- [ ] **Step 3: Edit `orca-workflows/models/agy.md`**

  Find:

  ```markdown
  For agent e2e, configure an accessibility-tree Playwright MCP and smoke-test the connection before relying
  on it. On quota or provider errors, use the fallback procedure owned by `orca-evaluate` or
  `orca-task-runner`.
  ```

  Replace with:

  ```markdown
  For agent e2e, configure the project-declared e2e tool (resolved by the consuming skill's
  `docs/agents/e2e-tooling.md`, not necessarily an MCP — e.g. a raw CLI) and smoke-test the
  connection/interface before relying on it. On quota or provider errors, use the fallback
  procedure owned by `orca-evaluate` or `orca-task-runner`.
  ```

- [ ] **Step 4: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_agy_md_generalized_e2e_tool.py -v`
  Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

  ```bash
  git add orca-workflows/models/agy.md tests/test_agy_md_generalized_e2e_tool.py
  git commit -m "docs: generalize agy.md agent-e2e note beyond Playwright (issue #140)"
  ```

---

### Task 8: `skills/orca-set.version` — add `project-setup` as the 7th member

Bump the version-set file and its pinning test to include the new skill, per the design spec's
version-set requirement (§7) and this repo's existing convention (`tests/test_log_enum_schema.py::
test_orca_set_version_bumped`, `tests/test_deploy_skills.py`).

**Files:**
- Modify: `skills/orca-set.version`
- Modify: `tests/test_log_enum_schema.py` (`test_orca_set_version_bumped`)

**Interfaces:**
- Consumes: the skill directory `skills/project-setup/` (Tasks 2-3) — `deploy-skills.sh` requires
  the skill directory to exist and be committed/clean before it will deploy the set (per AGENTS.md:
  "이 skill을 refuses dirty skills so the recorded commit never lies about the deployed content").
- Produces: nothing consumed by later tasks — this is the last task in the plan.

- [ ] **Step 1: Read the current version and members**

  Run: `cat skills/orca-set.version`
  Expected output:
  ```
  v1.1.8
  orca-evaluate
  orca-retro
  orca-task-runner
  orca-workflow
  orca-workflow-epic
  orca-workflow-task
  ```

- [ ] **Step 2: Write the failing test (update the existing pinning test)**

  In `tests/test_log_enum_schema.py`, find the `test_orca_set_version_bumped` function body and
  replace its assertions:

  Find:

  ```python
      # then again per issue #113 (v1.1.7 -> v1.1.8, set member orca-workflow-task touched by that
      # issue's proposal-r2.json scope).
      # Invariant unchanged: exact version string + 6-member list are still both enforced.
      lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
      assert lines[0] == "v1.1.8"
      assert sorted(lines[1:]) == sorted(
          [
              "orca-evaluate",
              "orca-retro",
              "orca-task-runner",
              "orca-workflow",
              "orca-workflow-epic",
              "orca-workflow-task",
          ]
      )
  ```

  Replace with:

  ```python
      # then again per issue #113 (v1.1.7 -> v1.1.8, set member orca-workflow-task touched by that
      # issue's proposal-r2.json scope).
      # then again per issue #140 (v1.1.8 -> v1.1.9, new 7th set member project-setup added --
      # orca-workflow/orca-evaluate both reference it by name in their fail-fast redirects, so a
      # version mismatch could point at a nonexistent or stale copy of the skill).
      # Invariant unchanged: exact version string + now-7-member list are still both enforced.
      lines = [l for l in SET_VERSION.read_text().splitlines() if l.strip()]
      assert lines[0] == "v1.1.9"
      assert sorted(lines[1:]) == sorted(
          [
              "orca-evaluate",
              "orca-retro",
              "orca-task-runner",
              "orca-workflow",
              "orca-workflow-epic",
              "orca-workflow-task",
              "project-setup",
          ]
      )
  ```

- [ ] **Step 3: Run test to verify it fails**

  Run: `python3 -m pytest tests/test_log_enum_schema.py::test_orca_set_version_bumped -v`
  Expected: FAIL — `skills/orca-set.version` still says `v1.1.8` with 6 members.

- [ ] **Step 4: Update `skills/orca-set.version`**

  Write the file with:

  ```
  v1.1.9
  orca-evaluate
  orca-retro
  orca-task-runner
  orca-workflow
  orca-workflow-epic
  orca-workflow-task
  project-setup
  ```

- [ ] **Step 5: Run test to verify it passes**

  Run: `python3 -m pytest tests/test_log_enum_schema.py::test_orca_set_version_bumped -v`
  Expected: PASS

- [ ] **Step 6: Run `test_deploy_skills.py` to confirm the set-deploy mechanics accept the 7th member**

  Run: `python3 -m pytest tests/test_deploy_skills.py -v`
  Expected: PASS — `test_deploying_one_set_member_deploys_whole_set_at_set_version` reads
  `members` directly from `skills/orca-set.version` (via `_set_version_and_members()`), so it
  picks up `project-setup` automatically and deploys all 7 without any test-file change needed.

- [ ] **Step 7: Run the full test suite one last time**

  Run: `python3 -m pytest tests/ -v`
  Expected: PASS across every file in `tests/` — this is the final regression check across all
  eight tasks in this plan.

- [ ] **Step 8: Commit**

  ```bash
  git add skills/orca-set.version tests/test_log_enum_schema.py
  git commit -m "chore: add project-setup as 7th orca-set.version member (issue #140)"
  ```

---

## Manual verification (per design spec §"검증" step 5 — not part of the TDD task loop above)

After all eight tasks land, perform one pilot run before considering the issue closed:

1. Run `/project-setup` in a scratch fixture repo with no `docs/agents/*` files and a numeric-style
   issue ID. Confirm: issue-tracker section is skipped (GitHub, no file written), e2e-tooling
   section asks and, on answering with a non-Playwright tool (e.g. a made-up native scenario),
   writes `docs/agents/e2e-tooling.md` with all four fields, and commits it in its own commit.
2. In that same fixture repo, hand-trace `orca-workflow` §0 against the new e2e-tooling gate: with
   the file now present, confirm §0 proceeds to §1 without prompting again.
3. Hand-trace `orca-evaluate` §2 against the fixture's `e2e-tooling.md`: confirm the constructed
   `-p` string embeds the fixture's declared `Tool` and `Usage guidance` text, not the word
   "Playwright" (unless the fixture happened to declare it).
4. Delete the fixture repo's `docs/agents/e2e-tooling.md` again and re-run `orca-workflow` §0:
   confirm it stops before §1 and names `/project-setup` in its message.

This step is deliberately manual and not encoded as a pytest test — it exercises the actual
Orca CLI spawn machinery (`orca terminal create`, `orca orchestration dispatch`), which the design
spec's verification plan (step 5) explicitly scopes to a one-time pilot rather than a standing
automated test, to bound cost.
