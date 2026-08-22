# epic-drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `skills/epic-drain/` skill that plans every child issue of a GitHub epic with the human (superpowers brainstorming/writing-plans), then drains the queue unattended — one fresh provider agent (claude/codex/agy) per child in an Orca terminal, each running SDD → PR → squash merge.

**Architecture:** State lives only in GitHub (epic body queue block, plan docs, issue/PR state, result comments) — no new log files. A small Python helper (`scripts/queue.py`) owns the only mechanical parts worth testing: parsing/writing the queue block, deriving per-child state from `gh`, and choosing the next runnable child. Everything else is prose in `SKILL.md` that reuses superpowers skills and Orca's own `orca-cli`/`orchestration` skill docs at runtime.

**Tech Stack:** Python 3 stdlib (no third-party deps), `gh` CLI, pytest (existing `tests/` suite), Markdown skill format (`SKILL.md` + YAML frontmatter).

**Spec:** `docs/superpowers/specs/2026-08-22-epic-drain-design.md`

## Global Constraints

- Skill folder kebab-case, `SKILL.md` exact spelling, frontmatter `name` = `epic-drain`, `description` ≤ 1024 chars, no XML/HTML tags in SKILL.md prose — angle-bracket markers such as the queue/result HTML comments appear only inside fenced code blocks or inline backtick code.
- No history/dates/pilot names inside `SKILL.md` (repo rule: skills carry current instructions only).
- Orca command syntax is never copied into the skill — the skill tells the agent to read `orca skills get orca-cli` / `orca skills get orchestration` at run time.
- Python scripts: stdlib only, `python3`, runnable from any cwd, exit non-zero with a message on bad input.
- Tests: pytest files under `tests/`, fixture-driven, never call the real `gh` (stub on `PATH`).
- Run `python3 -m pytest tests/ -q --ignore=tests/test_skill_description_length.py` (that file needs the `yaml` module which is absent in this env; check description length with the inline `python3 -c` in Task 4 instead).

---

### Task 1: Queue block parse / render / upsert

**Files:**
- Create: `skills/epic-drain/scripts/queue.py`
- Test: `tests/test_epic_drain_queue.py`

**Interfaces:**
- Produces:
  - `QUEUE_START = "<!-- epic-drain:queue -->"`, `QUEUE_END = "<!-- /epic-drain:queue -->"`
  - `COLUMNS = ["order", "issue", "kind", "depends_on", "provider", "plan"]`
  - `parse_queue(body: str) -> list[dict] | None` — `None` when no block; each row dict has the six keys, `order` as `int`, `issue` as digit string without `#`, `depends_on` as `list[str]` of digit strings, `provider` as `"claude"` when blank/`—`, `plan` as `""` when `—`/`(issue comment)` is NOT normalized (kept verbatim).
  - `render_queue(rows: list[dict]) -> str` — the block including both markers, rows sorted by `order`.
  - `upsert_queue(body: str, rows: list[dict]) -> str` — replaces an existing block in place, otherwise appends `"\n\n" + block + "\n"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_epic_drain_queue.py
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PY = ROOT / "skills" / "epic-drain" / "scripts" / "queue.py"


def _load():
    spec = importlib.util.spec_from_file_location("epic_drain_queue", QUEUE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BLOCK = """<!-- epic-drain:queue -->
| order | issue | kind | depends_on | provider | plan |
|---|---|---|---|---|---|
| 1 | #85 | architectural | — | claude | docs/superpowers/plans/2026-08-22-subscription-tests.md |
| 2 | #86 | bounded | #85 | codex | (issue comment) |
| 3 | #87 | spike | — | — | — |
<!-- /epic-drain:queue -->"""


def test_parse_returns_none_without_block():
    q = _load()
    assert q.parse_queue("## 배경\n아무 내용\n") is None


def test_parse_rows_and_normalization():
    q = _load()
    rows = q.parse_queue("intro\n\n" + BLOCK + "\n\ntrailer")
    assert [r["issue"] for r in rows] == ["85", "86", "87"]
    assert rows[0]["order"] == 1 and isinstance(rows[0]["order"], int)
    assert rows[0]["depends_on"] == []
    assert rows[1]["depends_on"] == ["85"]
    assert rows[1]["provider"] == "codex"
    assert rows[2]["provider"] == "claude"   # "—" → default
    assert rows[0]["plan"].endswith("subscription-tests.md")
    assert rows[1]["plan"] == "(issue comment)"
    assert rows[2]["kind"] == "spike"


def test_parse_depends_on_multiple_and_blank():
    q = _load()
    body = BLOCK.replace("| 2 | #86 | bounded | #85 |", "| 2 | #86 | bounded | #85, #90 |").replace(
        "| 3 | #87 | spike | — | — | — |", "| 3 | #87 | spike |  |  |  |")
    rows = q.parse_queue(body)
    assert rows[1]["depends_on"] == ["85", "90"]
    assert rows[2]["depends_on"] == [] and rows[2]["provider"] == "claude" and rows[2]["plan"] == ""


def test_render_roundtrip_sorted_by_order():
    q = _load()
    rows = q.parse_queue(BLOCK)
    rows_reversed = list(reversed(rows))
    out = q.render_queue(rows_reversed)
    assert out.startswith(q.QUEUE_START) and out.rstrip().endswith(q.QUEUE_END)
    again = q.parse_queue(out)
    assert [r["issue"] for r in again] == ["85", "86", "87"]
    assert again[1]["depends_on"] == ["85"]


def test_upsert_replaces_in_place_and_appends_when_missing():
    q = _load()
    rows = q.parse_queue(BLOCK)
    rows[0]["provider"] = "agy"
    body = "head\n\n" + BLOCK + "\n\ntail\n"
    new_body = q.upsert_queue(body, rows)
    assert new_body.startswith("head\n\n") and new_body.rstrip().endswith("tail")
    assert new_body.count(q.QUEUE_START) == 1
    assert q.parse_queue(new_body)[0]["provider"] == "agy"

    appended = q.upsert_queue("no block here\n", rows)
    assert appended.startswith("no block here\n")
    assert q.parse_queue(appended)[1]["issue"] == "86"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q`
Expected: errors — `queue.py` does not exist (`FileNotFoundError`/`AttributeError`).

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""epic-drain queue helper.

The epic issue body carries the execution queue as a markdown table between two HTML-comment
markers. This module parses/renders that block, derives per-child state from `gh`, and picks the
next runnable child. Stdlib only.

CLI (see `main`):
  queue.py read  <body.md>                      -> JSON rows
  queue.py write <body.md> <rows.json>          -> new body text on stdout
  queue.py state <owner/repo> <rows.json>       -> JSON {issue: state}
  queue.py next  <rows.json> <state.json>       -> JSON {"next": row|null, "skipped": [...], "done": [...]}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Iterable

QUEUE_START = "<!-- epic-drain:queue -->"
QUEUE_END = "<!-- /epic-drain:queue -->"
COLUMNS = ["order", "issue", "kind", "depends_on", "provider", "plan"]
RESULT_MARKER_RE = re.compile(r"<!--\s*epic-drain:result\s+(merged|pr-open|failed|spike)\s*-->")
_EMPTY = {"", "—", "-", "–"}


def _cell_issue(cell: str) -> str:
    return cell.strip().lstrip("#").strip()


def _cell_deps(cell: str) -> list[str]:
    cell = cell.strip()
    if cell in _EMPTY:
        return []
    return [_cell_issue(p) for p in cell.split(",") if _cell_issue(p)]


def parse_queue(body: str) -> list[dict] | None:
    start = body.find(QUEUE_START)
    end = body.find(QUEUE_END, start + len(QUEUE_START)) if start != -1 else -1
    if start == -1 or end == -1:
        return None
    block = body[start + len(QUEUE_START):end]
    rows: list[dict] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(COLUMNS):
            continue
        if cells[0].lower() == "order" or set(cells[0]) <= set("-: "):
            continue  # header / separator
        provider = cells[4]
        rows.append({
            "order": int(cells[0]),
            "issue": _cell_issue(cells[1]),
            "kind": cells[2],
            "depends_on": _cell_deps(cells[3]),
            "provider": "claude" if provider in _EMPTY else provider,
            "plan": "" if cells[5] in _EMPTY else cells[5],
        })
    rows.sort(key=lambda r: r["order"])
    return rows


def render_queue(rows: Iterable[dict]) -> str:
    lines = [QUEUE_START, "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in sorted(rows, key=lambda r: r["order"]):
        deps = ", ".join(f"#{d}" for d in r["depends_on"]) or "—"
        plan = r["plan"] or "—"
        lines.append(f"| {r['order']} | #{r['issue']} | {r['kind']} | {deps} | {r['provider']} | {plan} |")
    lines.append(QUEUE_END)
    return "\n".join(lines)


def upsert_queue(body: str, rows: Iterable[dict]) -> str:
    block = render_queue(rows)
    start = body.find(QUEUE_START)
    end = body.find(QUEUE_END, start + len(QUEUE_START)) if start != -1 else -1
    if start == -1 or end == -1:
        return body.rstrip("\n") + "\n\n" + block + "\n"
    return body[:start] + block + body[end + len(QUEUE_END):]


# --- state / next (Task 2 & 3) -----------------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "read" and len(argv) == 3:
        rows = parse_queue(open(argv[2], encoding="utf-8").read())
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if rows is not None else 1
    if cmd == "write" and len(argv) == 4:
        body = open(argv[2], encoding="utf-8").read()
        rows = json.load(open(argv[3], encoding="utf-8"))
        sys.stdout.write(upsert_queue(body, rows))
        return 0
    print(f"usage error: {argv[1:]}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
chmod +x skills/epic-drain/scripts/queue.py
git add skills/epic-drain/scripts/queue.py tests/test_epic_drain_queue.py
git commit -m "epic-drain: queue block parse/render/upsert helper"
```

---

### Task 2: Next-runnable selection from queue + state

**Files:**
- Modify: `skills/epic-drain/scripts/queue.py` (add `runnable` + `next` CLI subcommand under the `# --- state / next` marker)
- Test: `tests/test_epic_drain_queue.py` (append)

**Interfaces:**
- Consumes: `parse_queue` rows from Task 1.
- Produces: `runnable(rows: list[dict], state: dict[str, str]) -> dict` returning `{"next": row|None, "skipped": [{"issue", "reason"}...], "done": [issue...], "blocked": [{"issue", "reason"}...]}`.
  - `state` maps issue → one of `pending | merged | closed | pr-open | failed | spike`.
  - `done` = issues whose state is `merged`/`closed`/`spike`, or `kind == "spike"`.
  - A row is **skipped** when any dependency's state is `failed`/`pr-open`, or a dependency is itself skipped (transitive), or a dependency issue is missing from `state` (reason `"dep #N not in queue/state"`).
  - A row is **blocked (not yet)** — neither next nor skipped — when a dependency is still `pending` (it simply isn't chosen now).
  - `blocked`: pending rows waiting on a non-done dep.
  - `next` = lowest-`order` row with state `pending`, `kind != "spike"`, all deps in `_DONE_STATES` (merged/closed/spike). `None` when nothing is runnable.
  - Rows with state `pr-open`/`failed` are neither next nor done (they are reported by the caller from `state`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_epic_drain_queue.py

def _rows():
    return [
        {"order": 1, "issue": "85", "kind": "architectural", "depends_on": [], "provider": "claude", "plan": "p85.md"},
        {"order": 2, "issue": "86", "kind": "bounded", "depends_on": ["85"], "provider": "codex", "plan": ""},
        {"order": 3, "issue": "87", "kind": "spike", "depends_on": [], "provider": "claude", "plan": ""},
        {"order": 4, "issue": "88", "kind": "bounded", "depends_on": ["86"], "provider": "claude", "plan": ""},
        {"order": 5, "issue": "89", "kind": "bounded", "depends_on": [], "provider": "agy", "plan": ""},
    ]


def test_next_picks_lowest_order_pending_with_deps_merged():
    q = _load()
    state = {"85": "pending", "86": "pending", "87": "spike", "88": "pending", "89": "pending"}
    out = q.runnable(_rows(), state)
    assert out["next"]["issue"] == "85"
    assert out["skipped"] == []
    assert out["done"] == ["87"]


def test_next_skips_dependents_of_failed_transitively():
    q = _load()
    state = {"85": "failed", "86": "pending", "87": "spike", "88": "pending", "89": "pending"}
    out = q.runnable(_rows(), state)
    assert out["next"]["issue"] == "89"
    assert [s["issue"] for s in out["skipped"]] == ["86", "88"]
    assert "85" in out["skipped"][0]["reason"]


def test_pr_open_dependency_also_skips():
    q = _load()
    state = {"85": "pr-open", "86": "pending", "87": "spike", "88": "pending", "89": "merged"}
    out = q.runnable(_rows(), state)
    assert out["next"] is None
    assert [s["issue"] for s in out["skipped"]] == ["86", "88"]
    assert out["done"] == ["87", "89"]


def test_blocked_by_pending_dep_is_neither_next_nor_skipped():
    q = _load()
    state = {"85": "merged", "86": "pending", "87": "spike", "88": "pending", "89": "merged"}
    out = q.runnable(_rows(), state)
    assert out["next"]["issue"] == "86"       # 88 waits on 86 silently
    assert out["skipped"] == []


def test_missing_dep_in_state_is_skipped_with_reason():
    q = _load()
    rows = _rows()
    rows[1]["depends_on"] = ["999"]
    state = {"85": "merged", "86": "pending", "87": "spike", "88": "pending", "89": "merged"}
    out = q.runnable(rows, state)
    assert [s["issue"] for s in out["skipped"]] == ["86", "88"]
    assert "999" in out["skipped"][0]["reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q -k "next or pr_open or blocked or missing"`
Expected: FAIL — `AttributeError: module has no attribute 'runnable'`.

- [ ] **Step 3: Implement `runnable` and the `next` subcommand**

Insert under the `# --- state / next` marker in `queue.py`:

```python
_DONE_STATES = {"merged", "closed", "spike"}
_BROKEN_STATES = {"failed", "pr-open"}


def runnable(rows: list[dict], state: dict[str, str]) -> dict:
    rows = sorted(rows, key=lambda r: r["order"])
    done: list[str] = []
    skipped: list[dict] = []
    skipped_set: set[str] = set()
    for r in rows:
        st = state.get(r["issue"], "pending")
        if r["kind"] == "spike" or st in _DONE_STATES:
            done.append(r["issue"])
            continue
        for dep in r["depends_on"]:
            if dep not in state:
                skipped.append({"issue": r["issue"], "reason": f"dep #{dep} not in queue/state"})
                skipped_set.add(r["issue"])
                break
            if state[dep] in _BROKEN_STATES:
                skipped.append({"issue": r["issue"], "reason": f"dep #{dep} is {state[dep]}"})
                skipped_set.add(r["issue"])
                break
            if dep in skipped_set:
                skipped.append({"issue": r["issue"], "reason": f"dep #{dep} skipped"})
                skipped_set.add(r["issue"])
                break
    nxt = None
    for r in rows:
        if r["issue"] in skipped_set or r["issue"] in done:
            continue
        if state.get(r["issue"], "pending") != "pending":
            continue
        if all(state.get(d) in ("merged", "closed") for d in r["depends_on"]):
            nxt = r
            break
    return {"next": nxt, "skipped": skipped, "done": done}
```

And in `main`, before the final `usage error` lines:

```python
    if cmd == "next" and len(argv) == 4:
        rows = json.load(open(argv[2], encoding="utf-8"))
        state = json.load(open(argv[3], encoding="utf-8"))
        print(json.dumps(runnable(rows, state), ensure_ascii=False, indent=2))
        return 0
```

- [ ] **Step 4: Run all queue tests**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/epic-drain/scripts/queue.py tests/test_epic_drain_queue.py
git commit -m "epic-drain: runnable() next-child selection with dependency skip"
```

---

### Task 3: Per-child state derivation via stubbed `gh`

**Files:**
- Modify: `skills/epic-drain/scripts/queue.py` (add `child_state` + `state` subcommand)
- Test: `tests/test_epic_drain_queue.py` (append; uses a fake `gh` on `PATH`)

**Interfaces:**
- Consumes: rows from Task 1; `RESULT_MARKER_RE`.
- Produces: `child_state(repo: str, rows: list[dict], run=subprocess.run) -> dict[str, str]`.
  - For each row: `gh issue view <n> -R <repo> --json state,comments` → parse JSON.
  - Precedence: latest comment body containing `<!-- epic-drain:result X -->` → `X`; else `kind == "spike"` → `"spike"`; else issue `state == "CLOSED"` → `"closed"`; else `"pending"`.
  - `gh` failure (non-zero) for an issue → `"pending"` (don't block the drain on a transient error; the caller sees the reason on stderr).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_epic_drain_queue.py
import json
import os
import stat
import subprocess
import textwrap


def _fake_gh(tmp_path, payloads: dict[str, dict]) -> dict[str, str]:
    """Install a fake `gh` that answers `gh issue view <n> ... --json ...` from payloads[n]."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    data = tmp_path / "gh-data.json"
    data.write_text(json.dumps(payloads))
    script = bindir / "gh"
    script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import json, sys
        args = sys.argv[1:]
        if args[:2] != ["issue", "view"]:
            sys.exit(9)
        n = args[2]
        data = json.load(open({str(data)!r}))
        if n not in data:
            sys.stderr.write("not found\\n"); sys.exit(1)
        print(json.dumps(data[n]))
        """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}


def test_child_state_precedence_marker_then_spike_then_closed(tmp_path):
    q = _load()
    payloads = {
        "85": {"state": "OPEN", "comments": [{"body": "noise"}, {"body": "done <!-- epic-drain:result merged -->"}]},
        "86": {"state": "OPEN", "comments": [{"body": "<!-- epic-drain:result failed --> boom"},
                                               {"body": "<!-- epic-drain:result pr-open --> later"}]},
        "87": {"state": "OPEN", "comments": []},
        "88": {"state": "CLOSED", "comments": []},
        "89": {"state": "OPEN", "comments": []},
    }
    env = _fake_gh(tmp_path, payloads)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(_rows()))
    res = subprocess.run(["python3", str(QUEUE_PY), "state", "o/r", str(rows_path)],
                         env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    state = json.loads(res.stdout)
    assert state == {"85": "merged", "86": "pr-open", "87": "spike", "88": "closed", "89": "pending"}


def test_child_state_gh_failure_falls_back_to_pending(tmp_path):
    q = _load()
    env = _fake_gh(tmp_path, {"85": {"state": "OPEN", "comments": []}})
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(_rows()[:2]))   # 86 missing from fake gh → exit 1
    res = subprocess.run(["python3", str(QUEUE_PY), "state", "o/r", str(rows_path)],
                         env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert json.loads(res.stdout) == {"85": "pending", "86": "pending"}
    assert "86" in res.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q -k child_state`
Expected: FAIL — `state` subcommand hits `usage error` (returncode 2).

- [ ] **Step 3: Implement `child_state` and `state` subcommand**

Add to `queue.py` under the `# --- state / next` marker (above `runnable`):

```python
def child_state(repo: str, rows: list[dict], run=subprocess.run) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        n = r["issue"]
        proc = run(["gh", "issue", "view", n, "-R", repo, "--json", "state,comments"],
                   capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"epic-drain: gh issue view {n} failed ({proc.returncode}): {proc.stderr.strip()} — treating as pending",
                  file=sys.stderr)
            out[n] = "pending"
            continue
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(f"epic-drain: gh issue view {n} returned non-JSON — treating as pending", file=sys.stderr)
            out[n] = "pending"
            continue
        marker = None
        for c in data.get("comments") or []:
            m = RESULT_MARKER_RE.search(c.get("body") or "")
            if m:
                marker = m.group(1)  # keep the latest
        if marker:
            out[n] = marker
        elif r["kind"] == "spike":
            out[n] = "spike"
        elif (data.get("state") or "").upper() == "CLOSED":
            out[n] = "closed"
        else:
            out[n] = "pending"
    return out
```

And in `main`:

```python
    if cmd == "state" and len(argv) == 4:
        rows = json.load(open(argv[3], encoding="utf-8"))
        print(json.dumps(child_state(argv[2], rows), ensure_ascii=False, indent=2))
        return 0
```

- [ ] **Step 4: Run the whole queue test file**

Run: `python3 -m pytest tests/test_epic_drain_queue.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/epic-drain/scripts/queue.py tests/test_epic_drain_queue.py
git commit -m "epic-drain: child_state via gh (result marker > spike > closed > pending)"
```

---

### Task 4: `SKILL.md` — frontmatter, preconditions, Phase A

**Files:**
- Create: `skills/epic-drain/SKILL.md`

**Interfaces:**
- Consumes: `scripts/queue.py` CLI (`read`/`write`) from Task 1.
- Produces: section headings `## 0. 전제`, `## 1. 페이즈 A — 계획`, that Task 5 continues with `## 2. 페이즈 B — 실행`, `## 3. 재개`, `## 4. 에러 처리`.

- [ ] **Step 1: Write the file**

```markdown
---
name: epic-drain
description: Invoke explicitly via `/epic-drain <epic#>` or `/epic-drain <issue#> [<issue#> ...]` — do not phrase-match. Drives a GitHub epic's child issues end to end — plans every child with the human first (superpowers brainstorming → writing-plans, order and dependencies confirmed, queue recorded in the epic body), then drains the queue unattended — one fresh provider agent (claude/codex/agy, chosen per child) per child issue in an Orca worktree terminal, each running subagent-driven-development → PR → squash merge, with results reported as issue comments. Human input is needed only in the planning phase. Do NOT use for a single ad-hoc change (use superpowers directly), for ad-hoc multi-agent coordination (use `orchestration`), or for raw terminal/worktree control (use `orca-cli`).
compatibility: Claude Code session for the planning/driver phase (superpowers plugin + Agent tool). Child agents run inside Orca terminals — requires the `orca` CLI with orchestration enabled, `gh`, and superpowers installed for each provider used (claude/codex/agy).
---

# Epic Drain

이슈 여러 개를 epic으로 묶어 끝까지(merge까지) 가져가는 스킬. 두 페이즈로 나뉜다:

- **페이즈 A — 계획(사람과 함께)**: 자식 순서·의존을 정하고, 자식마다 superpowers brainstorming으로
  무엇을 만들지 합의하고(architectural이면 spec+plan 문서까지), 큐를 epic 본문에 기록한다.
- **페이즈 B — 실행(무인)**: 큐 순서대로 자식마다 Orca worktree + provider 터미널을 띄워 구현→PR→merge를
  맡기고 결과만 받는다. 이 세션(드라이버)은 코드를 읽지도 쓰지도 않는다.

상태 정본은 GitHub뿐이다 — epic 본문의 큐 블록, 자식 이슈/PR 상태, 자식 이슈의 결과 코멘트, plan 문서.
별도 로그 파일·상태 파일을 만들지 않는다.

## 0. 전제

- 대상 repo = 현재 cwd의 git repo. `gh auth status`가 통과해야 한다. `REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"`.
- 페이즈 B는 `orca status --json`이 ready여야 한다. 아니면 페이즈 A까지만 하고 보고한다.
- 이 스킬의 헬퍼: `QUEUE="$HOME/.agents/skills/epic-drain/scripts/queue.py"` (배포 경로. 이 repo 안에서
  개발 중이면 `skills/epic-drain/scripts/queue.py`). 서브커맨드 `read`/`write`/`state`/`next`.
- Orca 명령 문법은 여기 복제하지 않는다 — 필요한 시점에 `orca skills get orca-cli`(worktree·터미널),
  `orca skills get orchestration`(Run/task/worker-start/check)을 읽고 거기 적힌 현재 구성을 쓴다.
- 입력 해석:
  - `/epic-drain <epic#>` — 그 이슈가 epic. 자식 = 본문에서 참조된 `#N`(체크리스트 포함) ∪ `gh issue view <epic#> --json` 으로 읽히는 sub-issue 가운데 **열린 것**. 큐 블록이 이미 있으면 그 블록이 자식 목록의 정본이다(→ §3 재개).
  - `/epic-drain <issue#> [<issue#> ...]` — epic이 아직 없다. 제목·자식 체크리스트를 제안하고 사람이 승인하면 `gh issue create`로 epic을 만든 뒤 위 경로로 합류한다.

## 1. 페이즈 A — 계획

사람과 같은 세션에서 한다. 질문은 한 번에 하나, 선택지는 추천 먼저.

### 1.1 순서·의존 제안 → 확정

자식 이슈 본문을 모두 읽고 표를 제안한다 — 자식마다 한 줄 근거(파일 겹침, 선행 산출물 필요, 독립). 사람이
순서·의존·provider를 고친다. provider는 전부 `claude`로 시작하고 사람이 자식별로 `codex`/`agy`로 바꿀 수
있다(목적은 구독·레이트리밋 풀 분산 — 품질 비교가 아니다). 확정되면 큐 블록을 epic 본문에 쓴다:

```bash
gh issue view "$EPIC" -R "$REPO" --json body -q .body > /tmp/epic-body.md
# rows.json: [{"order":1,"issue":"85","kind":"","depends_on":[],"provider":"claude","plan":""}, ...]
python3 "$QUEUE" write /tmp/epic-body.md /tmp/rows.json > /tmp/epic-body.new.md
gh issue edit "$EPIC" -R "$REPO" --body-file /tmp/epic-body.new.md
```

`kind`는 이 단계에선 비워 둔다 — 1.2가 채운다. 블록 형식(큐 파서가 읽는 형식 그대로):

```
<!-- epic-drain:queue -->
| order | issue | kind | depends_on | provider | plan |
|---|---|---|---|---|---|
| 1 | #85 | architectural | — | claude | docs/superpowers/plans/2026-08-22-subscription-tests.md |
| 2 | #86 | bounded | #85 | codex | (issue comment) |
| 3 | #87 | spike | — | — | — |
<!-- /epic-drain:queue -->
```

### 1.2 자식마다 brainstorming

큐 순서대로 자식 하나씩 `superpowers:brainstorming`을 **실제로 호출**한다. 입력 = 이슈 원문 + 앞 자식들의
확정 plan 요약(의존 관계가 있으면 그 plan 전문). brainstorming 자신의 분류를 그대로 따른다:

- **spike** — 조사 결과를 이슈 코멘트로 남기고 `kind=spike`. 페이즈 B에서 제외. 이슈 닫기는 사람 몫.
- **bounded** — spec/plan 문서 없이 짧은 합의만. 합의 내용을 이슈 코멘트로 남기되 첫 줄을
  `<!-- epic-drain:agreement -->`로 시작한다(자식 에이전트가 이 코멘트를 찾는다). `kind=bounded`,
  `plan=(issue comment)`.
- **architectural** — brainstorming이 spec을 `docs/superpowers/specs/`에 쓰고 이어서
  `superpowers:writing-plans`로 plan을 `docs/superpowers/plans/`에 쓴다. 둘 다 **대상 repo의 default
  브랜치에 직접 커밋·푸시**한다(문서만이라 PR을 만들지 않는다). `kind=architectural`, `plan=<repo 상대경로>`.

자식 하나가 끝날 때마다 큐 블록을 갱신한다(`read` → 해당 row 수정 → `write` → `gh issue edit`).

뒤 자식의 plan은 앞 자식의 *계획*은 알지만 *구현 결과*는 모른다. 이 어긋남은 페이즈 B의 자식 에이전트가
SDD의 ruling으로 흡수한다 — 여기서 미리 맞추려 하지 않는다.

### 1.3 실행 승인

전 자식이 끝나면 큐 블록 최종본을 보여주고 **"이대로 페이즈 B를 시작할까?"** 한 번 묻는다. 승인 뒤
페이즈 B는 사람에게 묻지 않는다. 거절이면 여기서 끝 — 큐는 epic에 남아 있으므로 나중에
`/epic-drain <epic#>`로 이어간다(§3).
```

- [ ] **Step 2: Check frontmatter constraints**

Run:
```bash
python3 - <<'EOF'
import re
t=open("skills/epic-drain/SKILL.md").read()
fm=t.split("---",2)[1]
desc=re.search(r"^description:\s*(.*)$", fm, re.M).group(1)
print("desc len", len(desc)); assert len(desc)<=1024
body=t.split("---",2)[2]
# XML-ish tags outside fenced blocks / inline code are forbidden
outside=re.sub(r"```.*?```", "", body, flags=re.S)
outside=re.sub(r"`[^`\n]*`", "", outside)
assert "<!--" not in outside and not re.search(r"<[a-zA-Z/!]", outside), "angle-bracket tag outside code"
print("OK")
EOF
```
Expected: `desc len <N>` (≤ 1024) and `OK`.

- [ ] **Step 3: Commit**

```bash
git add skills/epic-drain/SKILL.md
git commit -m "epic-drain: SKILL.md frontmatter, preconditions, phase A"
```

---

### Task 5: `SKILL.md` — Phase B, resume, error table; child prompt reference

**Files:**
- Modify: `skills/epic-drain/SKILL.md` (append after §1)
- Create: `skills/epic-drain/references/child-prompt.md`

**Interfaces:**
- Consumes: `queue.py state|next` (Tasks 2–3); result marker format `<!-- epic-drain:result <merged|pr-open|failed|spike> -->` (Task 3's `RESULT_MARKER_RE`).
- Produces: the child prompt template that the driver fills and dispatches.

- [ ] **Step 1: Append Phase B / resume / errors to SKILL.md**

```markdown
## 2. 페이즈 B — 실행

드라이버 = 이 세션(페이즈 A를 끝낸 세션, 또는 §3로 들어온 세션). 루프 한 바퀴 = 자식 하나. 컨텍스트에는
자식당 결과 한 줄만 남긴다 — 자식의 diff·리뷰·plan 본문을 읽지 않는다.

### 2.1 다음 자식 고르기

```bash
gh issue view "$EPIC" -R "$REPO" --json body -q .body > /tmp/epic-body.md
python3 "$QUEUE" read /tmp/epic-body.md > /tmp/rows.json
python3 "$QUEUE" state "$REPO" /tmp/rows.json > /tmp/state.json
python3 "$QUEUE" next /tmp/rows.json /tmp/state.json > /tmp/next.json
```

`next`가 `null`이면 §2.5로. `skipped`에 새로 들어온 자식이 있으면 그 이슈에 코멘트
`<!-- epic-drain:result failed -->` + "skipped: <reason>"을 남겨 다음 바퀴에 다시 고르지 않게 한다.

### 2.2 격리 + 스폰

`orca skills get orca-cli`의 현재 문법으로: `orca worktree create --name task-<N>`(이미 있으면 그대로
쓴다 — `orca worktree show`로 확인) → 그 worktree에 provider REPL 터미널을 **대화형으로** 만든다.
provider별 launch는 permission-bypass 플래그를 인라인으로 넣는다: claude `--dangerously-skip-permissions`,
codex `--dangerously-bypass-approvals-and-sandbox`, agy `--dangerously-skip-permissions`. model/effort는
지정하지 않는다(하네스 기본값). REPL이 idle이 될 때까지 기다린 뒤 다음으로(orca-cli 문서의 wait 구성).

### 2.3 dispatch 1회

`orca skills get orchestration`의 현재 구성(Run 생성/바인딩 → `task-create` → `worker-start`)으로
`references/child-prompt.md`를 채운 프롬프트를 한 번 보낸다. 이 세션의 Run 하나를 페이즈 B 내내 재사용한다.

### 2.4 대기 → 기록

`worker_done` 또는 `escalation`을 orchestration 문서의 wait 구성으로 5~10분 단위 bounded stretch로 기다린다.
재시도·복구 루프는 없다:

| 관측 | 처리 |
|---|---|
| `worker_done` (payload 첫 줄이 `merged #<PR>` / `pr-open: <사유>` / `failed: <사유>`) | 그 줄을 자식 이슈 코멘트로(첫 줄 `<!-- epic-drain:result <status> -->`). merged면 터미널 종료 |
| `escalation` | `failed: escalation — <내용>` 코멘트, 터미널·worktree·PR 보존 |
| 누적 대기 3시간 초과 / 터미널 사망(`orca terminal` 조회 실패) | `failed: timeout|terminal dead` 코멘트, 보존 |

기록 후 §2.1로 돌아간다(의존 자식 skip은 `next`가 계산한다).

### 2.5 종료

큐에 고를 자식이 없으면 epic에 요약 코멘트 — 자식별 `merged/pr-open/failed/skipped/spike` + 사람이 볼 것
(열린 PR, failed 사유). 전 자식이 `merged`/`closed`/`spike`면 `gh issue close "$EPIC"`. 아니면 열어 둔다.

## 3. 재개

`/epic-drain <epic#>`를 다시 부르면:

- 큐 블록이 있으면 §1.1을 건너뛴다. `kind`가 비었거나, `architectural`인데 `plan` 파일이 repo에 없는
  자식만 §1.2를 다시 탄다. 그 외 자식은 §1.3 승인만 다시 받고 §2로.
- §2.1의 `state`가 `merged`/`closed`/`spike`인 자식은 자동으로 건너뛴다. `failed`/`pr-open`인 자식은 사람에게
  "재시도 / 그대로 둠" 한 번 묻는다 — 재시도면 그 이슈에 `<!-- epic-drain:result retry -->`가 아니라
  새 코멘트 없이 상태를 `pending`으로 취급하도록, 이전 결과 코멘트를 **편집**해 마커를 지운다(`gh api`
  PATCH). 그대로 두면 그 자식과 의존 자식은 이번 실행에서 빠진다.
- 이전 실행의 Orca 터미널·Run은 재사용하지 않는다. worktree(`task-<N>`)는 재사용한다.

## 4. 에러 처리

| 상황 | 처리 |
|---|---|
| `orca status` 불가 | 페이즈 A만 수행, 페이즈 B 진입 전에 멈추고 보고 |
| worktree 생성 실패 / 터미널 스폰 실패 | 그 자식 `failed: spawn — <메시지>` 코멘트, 다음 자식 |
| `gh` 호출 실패 | 그 자식은 `pending`으로 보고 다음 바퀴에 재시도(헬퍼가 stderr에 남김) |
| 드라이버 세션 크래시 | 상태는 GitHub에 있다 — §3 |
| 자식이 사람 질문을 올림(ask) | 답하지 않는다. SDD의 4가지 stop 조건은 `escalation`으로 오므로 그 경로로 처리 |
```

- [ ] **Step 2: Write the child prompt reference**

```markdown
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
   - 전체 테스트 통과 확인 → `git push -u origin task-{ISSUE}` → `gh pr create --fill --body "Closes #{ISSUE}"`
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
```

- [ ] **Step 3: Re-run the frontmatter/tag check from Task 4 Step 2 and the full suite**

Run: the Task 4 Step 2 python snippet, then `python3 -m pytest tests/ -q --ignore=tests/test_skill_description_length.py`
Expected: `OK`; all tests pass (existing 107 + 12 new).

- [ ] **Step 4: Reference A checklist pass (manual, record in commit message)**

Open `docs/references/anthropic-building-skills-for-claude.md` "Reference A" and confirm: kebab-case folder, `SKILL.md` spelling, frontmatter delimiters, `name` kebab-case, description has WHAT+WHEN, no XML tags outside fences, error handling section present, example (queue block) present, references linked (`references/child-prompt.md`, `scripts/queue.py`).

- [ ] **Step 5: Commit**

```bash
git add skills/epic-drain/SKILL.md skills/epic-drain/references/child-prompt.md
git commit -m "epic-drain: SKILL.md phase B/resume/errors + child prompt template (Reference A checked)"
```

---

### Task 6: Finish — PR, merge, deploy

**Files:**
- None new. Uses `scripts/deploy-skills.sh`.

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin HEAD
gh pr create --title "epic-drain 스킬: epic 자식 일괄 계획 + provider별 자식 에이전트 순차 실행" \
  --body "Spec: docs/superpowers/specs/2026-08-22-epic-drain-design.md
Plan: docs/superpowers/plans/2026-08-22-epic-drain.md

- skills/epic-drain/{SKILL.md,references/child-prompt.md,scripts/queue.py}
- tests/test_epic_drain_queue.py (12 tests, fake gh on PATH)

Tests: python3 -m pytest tests/ -q --ignore=tests/test_skill_description_length.py

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 2: Squash-merge and deploy**

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull
scripts/deploy-skills.sh epic-drain
ls -la ~/.claude/skills/epic-drain ~/.agents/skills/epic-drain/SKILL.md
```
Expected: `OK epic-drain (...)` line from the deploy script; symlink present.

- [ ] **Step 3: Report**

State what was built, the test count, and the pilot still to run (selah epic #91 children #87–#90; codex/agy children marked "supported" only after one successful pilot each — this is tracked outside the skill text).
