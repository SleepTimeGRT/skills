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
    if cmd == "next" and len(argv) == 4:
        rows = json.load(open(argv[2], encoding="utf-8"))
        state = json.load(open(argv[3], encoding="utf-8"))
        print(json.dumps(runnable(rows, state), ensure_ascii=False, indent=2))
        return 0
    print(f"usage error: {argv[1:]}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
