#!/usr/bin/env bash
# Portably converts a worker_done payload's filesModified value (the worker preamble's
# `--files-modified "a,b,c"` comma-separated string) into a newline-delimited pathspec file for
# `git ... --pathspec-from-file=<file>` (issue #70, orca-task-runner §5 codex commit-helper).
#
# PORTABILITY (contract round 3 rejected an earlier draft here, issue #70): the previous draft
# split the comma string into a bash array via `IFS=',' read -r -a files_modified <<< "$csv"`,
# then guarded the commit step on `${#files_modified[@]} -gt 0`. `read -a` is bash-only — in zsh
# (ZSH_VERSION=5.9, this machine's actual runtime shell for these dispatch blocks) it fails with
# `read:1: bad option: -a` but still returns exit code 0 (measured: bash produces an array of 2
# elements for a 2-path CSV, zsh produces 0 with no visible error), so the length guard silently
# treated every codex subtask's changes as "nothing to commit" — a fail-open that left codex
# workers' changes uncommitted forever with no error and no escalation, strictly worse than issue
# #70's original defect (a visible failure requiring manual recovery). This rewrite avoids arrays
# and indirect expansion entirely — same portability contract already established by
# orca_call_with_retry.sh and log_dispatch.sh in this directory: no `read -a`, no `${!name}`
# indirect expansion, no `[[ ]]`, no arrays. The "is there anything to commit" question is
# answered by testing the CSV string itself (`[ -z "$csv" ]`), never by measuring an array that a
# shell-dependent step may or may not have actually populated.
#
#   source ~/.agents/orca-workflows/scripts/write_pathspec_from_csv.sh
#   write_pathspec_from_csv "$files_modified_csv" "$pathspec_file"
#
# Return codes:
#   0  wrote >=1 path to $pathspec_file (one per line, from splitting the CSV on commas)
#   3  csv was empty — nothing written, $pathspec_file untouched. Caller should skip the whole
#      commit step as a normal no-op (worker had nothing to change), not treat this as a failure
#      or route it to escalation.
#   *  any other nonzero code is a real write failure (e.g. $pathspec_file's directory doesn't
#      exist or isn't writable) — propagated from the failing command, not swallowed.
#
# Known limitation (documented, not fixed): a literal comma inside a path breaks this split — the
# worker preamble's own --files-modified flag has the same limitation upstream (it is itself a
# naive comma-join), so this function does not attempt to work around it. If a comma-containing
# path is ever observed in practice, the fix belongs in the preamble's flag encoding first.

write_pathspec_from_csv() {
  local csv="$1" out="$2"
  if [ -z "$csv" ]; then
    return 3
  fi
  printf '%s\n' "$csv" | tr ',' '\n' > "$out"
}
