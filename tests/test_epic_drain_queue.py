from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import textwrap
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


def test_transitive_skip_is_order_independent():
    q = _load()
    rows = [
        {"order": 1, "issue": "88", "kind": "bounded", "depends_on": ["86"], "provider": "claude", "plan": ""},
        {"order": 2, "issue": "86", "kind": "bounded", "depends_on": ["85"], "provider": "claude", "plan": ""},
        {"order": 3, "issue": "85", "kind": "bounded", "depends_on": [], "provider": "claude", "plan": ""},
    ]
    state = {"85": "failed", "86": "pending", "88": "pending"}
    out = q.runnable(rows, state)
    assert out["next"] is None
    assert sorted(s["issue"] for s in out["skipped"]) == ["86", "88"]
    assert len(out["skipped"]) == 2


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


def test_dependency_on_spike_counts_as_done():
    q = _load()
    rows = [
        {"order": 1, "issue": "87", "kind": "spike", "depends_on": [], "provider": "claude", "plan": ""},
        {"order": 2, "issue": "88", "kind": "bounded", "depends_on": ["87"], "provider": "claude", "plan": ""},
    ]
    out = q.runnable(rows, {"87": "spike", "88": "pending"})
    assert out["next"]["issue"] == "88"
    assert out["done"] == ["87"] and out["skipped"] == [] and out["blocked"] == []


def test_blocked_lists_pending_rows_waiting_on_pending_deps():
    q = _load()
    state = {"85": "merged", "86": "pending", "87": "spike", "88": "pending", "89": "merged"}
    out = q.runnable(_rows(), state)
    assert out["next"]["issue"] == "86"
    assert out["blocked"] == [{"issue": "88", "reason": "dep #86 is pending"}]


def test_cycle_reports_blocked_not_silent():
    q = _load()
    rows = [
        {"order": 1, "issue": "10", "kind": "bounded", "depends_on": ["11"], "provider": "claude", "plan": ""},
        {"order": 2, "issue": "11", "kind": "bounded", "depends_on": ["10"], "provider": "claude", "plan": ""},
    ]
    out = q.runnable(rows, {"10": "pending", "11": "pending"})
    assert out["next"] is None and out["skipped"] == []
    assert [b["issue"] for b in out["blocked"]] == ["10", "11"]


def test_duplicate_issue_rows_raise():
    import pytest
    q = _load()
    rows = [
        {"order": 1, "issue": "10", "kind": "bounded", "depends_on": [], "provider": "claude", "plan": ""},
        {"order": 2, "issue": "10", "kind": "bounded", "depends_on": [], "provider": "claude", "plan": ""},
    ]
    with pytest.raises(ValueError):
        q.runnable(rows, {"10": "pending"})


def test_read_without_block_exits_1_with_message(tmp_path):
    body = tmp_path / "body.md"; body.write_text("no block\n")
    res = subprocess.run(["python3", str(QUEUE_PY), "read", str(body)], capture_output=True, text=True)
    assert res.returncode == 1 and res.stdout.strip() == "" and "no queue block" in res.stderr


def test_malformed_order_cell_raises():
    import pytest
    q = _load()
    bad = BLOCK.replace("| 2 | #86 |", "| 2x | #86 |")
    with pytest.raises(ValueError):
        q.parse_queue(bad)
    empty = BLOCK.replace("| 2 | #86 |", "|  | #86 |")
    with pytest.raises(ValueError):
        q.parse_queue(empty)
