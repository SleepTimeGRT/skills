# orca-retro Issue Label Generalization + Execution-Time Version Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `term-<handle>.jsonl` meta record captures the versions in play when the terminal was spawned, and every issue `orca-retro` files carries an "환경/버전" section built from that data (or an explicitly-labeled fallback) plus a generalized `retro` label description.

**Architecture:** `orca-workflows/logging.md` §2's meta jq recipe grows three best-effort fields (`skill_version`, `orca_workflows_commit`, `orca_app_version`). Because `orca-workflow`/`orca-task-runner`/`orca-evaluate` all reference `logging.md §2` by pointer rather than embedding the recipe (verified: `grep -n meta` on all three `SKILL.md` files returns only "logging.md §2 term 로그: ... meta 기록 후" reference lines, no literal jq block), this one file edit propagates to all three call sites with no further skill-file changes. `orca-retro/SKILL.md` §4 gains an "환경/버전" assembly step that reads those fields back out of the term log it already cited as evidence, and the `retro` GitHub label's description is generalized via `gh label edit` (name unchanged, so existing filtering by 20+ prior issues keeps working).

**Tech Stack:** Bash, `jq`, `git`, `gh` CLI, `orca` CLI, pytest (structural assertions on markdown/prose files — this repo's `tests/test_orca_skills.py` pattern).

## Global Constraints

- Every new field is best-effort: if `~/.agents/skills/<skill>/.installed-version.json` is missing, `git -C ~/.agents/orca-workflows rev-parse HEAD` fails, or `orca status --json` fails/is unavailable, the corresponding field is JSON `null` — the meta write itself is never blocked or skipped for this reason (per repo convention: environment problems don't block logging).
- `orca_app_version` is read from `.result.runtime.appVersion` in `orca status --json` output — verified live in this environment (`1.4.175` observed), not assumed.
- Do not touch `skills/orca-workflow/SKILL.md`, `skills/orca-task-runner/SKILL.md`, or `skills/orca-evaluate/SKILL.md` — they reference `logging.md §2` by pointer, confirmed by grep, so no code there needs to change.
- Do not touch `orca-workflows/issue-trackers/{selection,github,jira}.md` — out of scope (see spec).
- Do not rename the `retro` GitHub label — description only.
- Spec: `docs/superpowers/specs/2026-08-07-orca-retro-issue-version-label-design.md`.

---

## File Structure

- Modify: `orca-workflows/logging.md` — §2 meta jq recipe gains 3 fields.
- Modify: `skills/orca-retro/SKILL.md` — §4 gains "환경/버전" section assembly + label-generalization sentence.
- Modify: `tests/test_orca_skills.py` — structural assertions for both of the above.
- External (no file): GitHub `retro` label description, via `gh label edit`.

---

### Task 1: `logging.md` §2 meta recipe — add version fields

**Files:**
- Modify: `orca-workflows/logging.md` (the `meta` code block under "### `meta` — write once, first line...")
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Produces: the `meta` JSONL record now includes `skill_version` (object `{version, commit}` or `null`), `orca_workflows_commit` (string or `null`), `orca_app_version` (string or `null`) alongside the existing `type/issue/skill/role/terminal/created_at` fields. Task 2 reads these three new keys back from `term-<handle>.jsonl` line 1.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, in the "orca-retro: epic-end skill-defect feedback loop" section (near `test_logging_outcome_enum_includes_retro_values`, around line 988):

```python
def test_logging_meta_records_version_fields():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    meta_section = text[text.index('### `meta`') : text.index('### `sent`')]
    for key in ("skill_version", "orca_workflows_commit", "orca_app_version"):
        assert key in meta_section, (
            f"logging.md meta recipe missing version field: {key} — issues filed "
            "against a term log can't be pinned to the version that produced the bug"
        )
    assert ".installed-version.json" in meta_section, (
        "meta recipe must source skill_version from the deployed commit-pin file"
    )
    assert "orca status --json" in meta_section, (
        "meta recipe must source orca_app_version from a live orca status call"
    )
    assert "rev-parse HEAD" in meta_section, (
        "meta recipe must source orca_workflows_commit from the live orca-workflows checkout"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py::test_logging_meta_records_version_fields -v`
Expected: FAIL (`skill_version` not found / `IndexError` won't occur since `### \`meta\`` and `### \`sent\`` headings already exist — the field assertions fail).

- [ ] **Step 3: Edit `orca-workflows/logging.md`**

Replace the existing `meta` code block:

```bash
if [ ! -s "$term_log" ] || ! head -1 "$term_log" | jq -e '.type == "meta"' >/dev/null 2>&1; then
  jq -cn --arg issue "<issue-num>" --arg skill "<skill>" --arg role "<role>" --arg terminal "<handle>" \
    --arg created_at "$(date -u +%FT%TZ)" \
    '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at}' \
    >> "$term_log"
  chmod 600 "$term_log"
fi
```

with:

```bash
if [ ! -s "$term_log" ] || ! head -1 "$term_log" | jq -e '.type == "meta"' >/dev/null 2>&1; then
  version_file="$HOME/.agents/skills/<skill>/.installed-version.json"
  sv_json="null"
  [ -f "$version_file" ] && sv_json="$(jq -c '{version, commit}' "$version_file" 2>/dev/null)"
  [ -z "$sv_json" ] && sv_json="null"

  owc_raw="$(git -C "$HOME/.agents/orca-workflows" rev-parse HEAD 2>/dev/null)"
  owc_json="null"
  [ -n "$owc_raw" ] && owc_json="$(printf '%s' "$owc_raw" | jq -R .)"

  oav_raw="$(orca status --json 2>/dev/null | jq -r '.result.runtime.appVersion // empty' 2>/dev/null)"
  oav_json="null"
  [ -n "$oav_raw" ] && oav_json="$(printf '%s' "$oav_raw" | jq -R .)"

  jq -cn --arg issue "<issue-num>" --arg skill "<skill>" --arg role "<role>" --arg terminal "<handle>" \
    --arg created_at "$(date -u +%FT%TZ)" \
    --argjson skill_version "$sv_json" --argjson orca_workflows_commit "$owc_json" \
    --argjson orca_app_version "$oav_json" \
    '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at,
      skill_version:$skill_version, orca_workflows_commit:$orca_workflows_commit,
      orca_app_version:$orca_app_version}' \
    >> "$term_log"
  chmod 600 "$term_log"
fi
```

Directly below the code block, add one sentence (this is prose the spawning skill's author needs, not filler):

```markdown
`skill_version`은 그 순간 실제 **배포(commit-pin)**된 버전(`~/.agents/skills/<skill>/.installed-version.json`),
`orca_workflows_commit`은 orca-workflows가 symlink-tracks-main이라 항상 "그 순간의" 레포 HEAD, `orca_app_version`은
Orca 앱 자체 버전(#42류 앱-기인 버그 추적용)이다. 셋 다 best-effort — 조회 실패는 `null`로만 남기고 meta
기록 자체를 막지 않는다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py::test_logging_meta_records_version_fields -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python3 -m pytest tests/test_orca_skills.py -v`
Expected: all passing (same count as before + 1)

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/logging.md tests/test_orca_skills.py
git commit -m "feat(orca-workflows): capture skill/workflows/app version in term meta record

Best-effort skill_version/orca_workflows_commit/orca_app_version fields on
the once-per-terminal meta line, so a bug's evidence can be pinned to the
version that actually produced it instead of whatever's deployed later.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `orca-retro` — "환경/버전" issue-body section + label generalization

**Files:**
- Modify: `skills/orca-retro/SKILL.md` (§4)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `skill_version`/`orca_workflows_commit`/`orca_app_version` fields on `term-<handle>.jsonl` line 1, produced by Task 1's `meta` recipe.
- Produces: no new function — the `gh issue create --body` argument now includes an "## 환경/버전" section assembled per the two-priority rule below. Task 3 (label description) is independent of this task's file edit but is documented together since both implement design item C/B.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, directly after `test_orca_retro_dedup_against_open_issues` (around line 1023):

```python
def test_orca_retro_issue_body_has_version_section():
    text = _read_skill("orca-retro")
    assert "환경/버전" in text, "issue body must carry a 환경/버전 section"
    assert "skill_version" in text and "orca_workflows_commit" in text and "orca_app_version" in text, (
        "orca-retro must pull the same three fields Task 1 added to the meta record"
    )
    assert "실행 당시와 다를 수 있음" in text, (
        "the no-term-log fallback path must warn the version may not match when the bug occurred"
    )


def test_orca_retro_label_documented_as_general_convention():
    text = _read_skill("orca-retro")
    assert "orca-retro 전용이 아니라" in text, (
        "retro label must be documented as a general skill-discovered-issue convention, "
        "not orca-retro-exclusive, even though orca-retro is currently the only implementer"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py::test_orca_retro_issue_body_has_version_section tests/test_orca_skills.py::test_orca_retro_label_documented_as_general_convention -v`
Expected: both FAIL

- [ ] **Step 3: Edit `skills/orca-retro/SKILL.md` §4**

Find the existing block (§4, around what's currently lines 87-93):

```markdown
- 신규 결함이면:

\`\`\`bash
gh issue create --repo <skills-repo-slug> --label retro \
  --title "<대상 스킬>: <결함 한 줄>" \
  --body "<대상 스킬 파일 경로 / 증거 인용(로그 경로+레코드 라인) / epic 번호 / 참조한 로그 경로 / 수정 방향 1문단(diff 금지)>"
\`\`\`
```

Replace it with:

```markdown
- 신규 결함이면, 먼저 "## 환경/버전" 섹션을 조립한다 — 우선순위 2단계:

  1. 이 후보의 증거로 인용한 term 로그(`term-<handle>.jsonl`)가 있으면 그 파일 1행(`type=="meta"`)에서
     그대로 뽑는다 — 버그가 실제로 관측된 시점의 버전이라 가장 정확하다:

     \`\`\`bash
     head -1 "$term_log" | jq -c '{skill_version, orca_workflows_commit, orca_app_version}'
     \`\`\`

  2. term 로그를 인용하지 않은 후보(렌즈 1·4처럼 assignments/spawn-failures만으로 나온 경우)는 대상 스킬의
     **현재** 배포 버전을 폴백으로 쓰고, 이슈 본문에 "분석 시점 기준 — 실행 당시와 다를 수 있음"이라고
     명시한다:

     \`\`\`bash
     version_file="$HOME/.agents/skills/<대상 스킬>/.installed-version.json"
     [ -f "$version_file" ] && jq -c '{version, commit}' "$version_file"
     \`\`\`

  라벨은 `retro` 그대로 쓴다 — orca-retro 전용이 아니라 앞으로 다른 경로로 스킬 결함 이슈를 파일링할 때도
  재사용하는 일반 컨벤션이다(다만 현재 `gh issue create`를 실제로 호출하는 스킬은 orca-retro뿐이다):

  \`\`\`bash
  gh issue create --repo <skills-repo-slug> --label retro \
    --title "<대상 스킬>: <결함 한 줄>" \
    --body "<대상 스킬 파일 경로 / 증거 인용(로그 경로+레코드 라인) / epic 번호 / 참조한 로그 경로 / 수정 방향 1문단(diff 금지) / ## 환경/버전 섹션(위에서 조립)>"
  \`\`\`
```

(The `\`\`\`` above are literal triple-backtick fences in the actual file content — write them unescaped when editing the real file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py::test_orca_retro_issue_body_has_version_section tests/test_orca_skills.py::test_orca_retro_label_documented_as_general_convention -v`
Expected: both PASS

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python3 -m pytest tests/test_orca_skills.py -v`
Expected: all passing (same count as Task 1's post-suite count + 2)

- [ ] **Step 6: Commit**

```bash
git add skills/orca-retro/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-retro): attach 환경/버전 section to filed issues, generalize retro label

Pulls skill_version/orca_workflows_commit/orca_app_version from the term
log's meta line when evidence cites one; falls back to the target skill's
current deployed version (explicitly caveated) otherwise. Documents the
retro label as a general skill-discovered-issue convention, not
orca-retro-exclusive.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Generalize the `retro` GitHub label description

**Files:** none (external GitHub state only)

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: nothing consumed by other tasks — this is the design's item C, executed independently since it's a repo-visible (shared) change, not a local file edit.

- [ ] **Step 1: Confirm current description (read-only)**

Run: `gh label list --json name,description | jq -r '.[] | select(.name=="retro")'`
Expected: `{"name":"retro","description":"orca-retro가 파일한 스킬 결함"}`

- [ ] **Step 2: Edit the label description**

Run: `gh label edit retro --description "스킬 실행 중 발견된 결함/이슈"`

- [ ] **Step 3: Verify the change**

Run: `gh label list --json name,description | jq -r '.[] | select(.name=="retro")'`
Expected: `{"name":"retro","description":"스킬 실행 중 발견된 결함/이슈"}`

No commit for this task — it's not a file change, and there's nothing else to batch it with.

---

## Self-Review Notes

- **Spec coverage:** A (logging.md fields) → Task 1. B (issue body assembly) → Task 2. C (label) → Task 3. All three design sections covered.
- **Placeholder scan:** no TBD/TODO; every step has literal code or literal `gh`/`jq` commands.
- **Type consistency:** `skill_version`/`orca_workflows_commit`/`orca_app_version` field names are identical across Task 1's producer code, Task 1's test, Task 2's consumer prose, and Task 2's test — checked by re-reading all four side by side.
