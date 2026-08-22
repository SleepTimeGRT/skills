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
