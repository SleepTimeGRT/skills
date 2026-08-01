#!/usr/bin/env bash
# sweep_stale_dispatched.sh — report-only janitor for dispatched tasks stuck past a threshold
# (issue #41: worker_done sends lost to Orca app downtime leave tasks dispatched forever, and
# the coordinator has no signal — the message that would have told it never arrived).
#
#   sweep_stale_dispatched.sh [threshold_seconds]   # default 3600
#
# task-list is run-scoped (the CLI refuses it without a bound Run), so the sweep enumerates
# run-list first and queries each run explicitly via --run. Prints one line per stale task:
#
#   STALE <run_id> <task_id> age_h=<n> terminal=<handle|none> alive=<yes|no|gone> title=<...>
#
# then a summary line `STALE_DISPATCHED total=<n>`. Exit 0 = none stale, 3 = stale found,
# 1 = CLI failure. Never mutates task state — recovery stays the documented manual step
# (orca-task-runner §5 worker_done-loss recovery, with the worker-side
# .orca-orphaned-result-<task_id>.json file as evidence when the worker hit retry exhaustion).

set -u
threshold="${1:-3600}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=orca_call_with_retry.sh
. "$here/orca_call_with_retry.sh"
skill="${SWEEP_SKILL:-orca-workflow}"

# Ignore-list: one task_id per line ('#' comments allowed) for tasks verified moot but
# impossible to bookkeep via CLI — an orphaned adopted run (coordinator_handle null) refuses
# both plain run-use and --takeover-legacy from every terminal kind, so its tasks can never
# be marked completed. Listing here keeps the sweep usable without hiding future stales.
ignore_file="${SWEEP_IGNORE_FILE:-$HOME/.local/state/orca-workflows/logs/sweep-ignore.txt}"
ignored_ids=""
[ -r "$ignore_file" ] && ignored_ids="$(grep -v '^#' "$ignore_file" | grep -v '^[[:space:]]*$' || true)"

runs_json="$(orca_call_with_retry "$skill" "janitor" -- orca orchestration run-list --json)" || exit 1
terms_json="$(orca_call_with_retry "$skill" "janitor" -- orca terminal list --limit 100 --json)" || exit 1
terms_slim="$(printf '%s' "$terms_json" | jq '[.result.terminals[]? | {handle, connected, orphaned}]')" || exit 1
now="$(date -u +%s)"

total=0
ignored=0
for rid in $(printf '%s' "$runs_json" | jq -r '.result.runs[].id'); do
  tasks_json="$(orca_call_with_retry "$skill" "janitor" -- \
    orca orchestration task-list --run "$rid" --status dispatched --brief --json)" || continue
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    tid="$(printf '%s' "$line" | awk '{print $3}')"
    if [ -n "$ignored_ids" ] && printf '%s\n' "$ignored_ids" | grep -qx "$tid"; then
      ignored=$((ignored + 1))
      continue
    fi
    total=$((total + 1))
    printf '%s\n' "$line"
  done < <(printf '%s' "$tasks_json" | jq -r --argjson now "$now" --argjson thr "$threshold" \
    --argjson terms "$terms_slim" '
    .result.tasks[]?
    | (.created_at | strptime("%Y-%m-%d %H:%M:%S") | mktime) as $ts
    | select($now - $ts > $thr)
    | (.assignee_handle // "none") as $h
    | ($terms | map(select(.handle == $h)) | first) as $t
    | "STALE \(.run_id) \(.id) age_h=\((($now - $ts) / 3600) | floor) terminal=\($h) alive=\(
        if $t == null then "gone"
        elif $t.connected and ($t.orphaned | not) then "yes"
        else "no" end
      ) title=\(.task_title // "-" | gsub("\\s+"; " ") | .[0:60])"
  ')
done

printf 'STALE_DISPATCHED total=%d ignored=%d\n' "$total" "$ignored"
[ "$total" -eq 0 ] && exit 0 || exit 3
