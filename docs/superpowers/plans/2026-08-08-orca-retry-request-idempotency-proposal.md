# Proposal: call-site `--retry-request` idempotency keys for mutating orca orchestration calls (issue #73)

> Status: **proposal**, contract-negotiation round 2 — orca-task-runner → orca-evaluate. Round 1 was
> **REJECTED** (`.evaluate-contract-review-report.md`): the proposed insertion position broke
> `tests/test_orca_skills.py`'s `_DISPATCH_INJECT_RE`-based tests at 6 `dispatch --inject` sites
> (2 hard failures + a silent coverage collapse to 0 sites for `orca-evaluate`), and the proposal
> omitted `orca-workflows/self-recovery.md:81`'s `worker-start` call from its audit. Both are fixed
> below, with a real `pytest` run attached as evidence (not just prose claims). Not yet implemented.

## Problem recap

`orca_call_with_retry()` (`orca-workflows/scripts/orca_call_with_retry.sh`) retries a wrapped `orca`
CLI call verbatim when its combined stdout+stderr matches a broadened Orca-restart signature
(issue #42). For a genuinely read-only call (`orca status`) a spurious retry is harmless. For
**mutating** calls — `task-create`, `dispatch`, `worker-start`, and `terminal create` — a spurious
match (server succeeded, client saw a false-positive signature in otherwise-unrelated output) can
retry an already-applied call and duplicate a task/dispatch/terminal. Issue #42's broadening
(2 literals → 4 case-insensitive keywords) widened the match surface and therefore this risk,
without introducing it — it was already latent with the 2-literal regex. This proposal addresses
the three mutating calls that expose a server-side dedupe flag (`task-create`/`dispatch`/
`worker-start`); `terminal create` has no such flag and its duplication risk stays unmitigated
(noted, not solved, in the AC3 header-comment rewrite below).

Issue #73 was filed to close the gap. This session verified empirically (see issue body,
"스코핑 실측" section, reused here without re-verification):

- `orca orchestration task-create --help` / `dispatch --help` / `worker-start --help` all expose a
  `--retry-request <id>` flag (confirmed again below, same output).
- Calling `task-create` twice with the same `--retry-request <key>` value returns, on the second
  call, `mutation.replayed: true` and the **same** `task.id` as the first call — i.e. the server
  already implements client-request-id/dedupe for this flag; the client only has to supply a
  stable id.
- `orca terminal create --help` has **no** `--retry-request` flag — it is not covered by this
  mechanism and is out of scope for this proposal (AC2 explicitly excludes it).

## Scope

### AC1 — wrapper stays opaque

`orca_call_with_retry()` itself (`orca-workflows/scripts/orca_call_with_retry.sh`) is **not
modified** by this proposal. It already re-executes the identical `"$@"` on every retry cycle
(`orca_call_with_retry.sh:63`, `"$@" >"$out" 2>"$err"` inside the `while :; do` loop) — so whatever
argument vector the caller constructs, including a `--retry-request <id>` flag baked into it, is
byte-for-byte identical from the first attempt through the last retry. No wrapper change is needed
to get that guarantee; it falls out of the wrapper's existing pass-through-args design. This also
preserves the wrapper's current contract of working with commands it has no opinion about (`orca
status`, `terminal create`), which a command-parsing/injecting wrapper would break.

The id must therefore be generated **once, by the caller, before `orca_call_with_retry` is
invoked** — as a shell command-substitution evaluated at call-construction time, not inside the
retry loop. Concretely:

```bash
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
```

`$(uuidgen)` expands once, when this line is parsed/expanded by the calling shell, before
`orca_call_with_retry` ever sees `"$@"`. The resulting literal UUID is what's stored in
`"$@"` inside the function and is what gets re-executed on every retry cycle. This is a structural
property of bash argument expansion, not a promise `orca_call_with_retry` has to keep — which is
exactly why AC1 says the wrapper doesn't need to change. **This claim is now also verified by a real
subprocess test, not just this argument** — see AC4 §3 below; round 1's version of this section was
correct but untested end-to-end.

### Id generation method

`uuidgen` (confirmed on `PATH` on this machine — `/usr/bin/uuidgen`; standard on macOS/BSD and via
`uuid-runtime` on most Linux distros). `orca-workflows/` is already a single-machine, single-checkout
symlink target (AGENTS.md, "orca-workflows/ deploy path" decision, #22) with an existing
darwin/bash/jq assumption (`docs/superpowers/plans/2026-07-30-orca-retry-backoff.md`, Tech Stack:
"bash, jq (confirmed installed, 1.7.1)") — `uuidgen` fits the same assumption and needs no new
dependency. No fallback path is proposed; if `uuidgen` is ever missing this is a hard environment
error, consistent with how the existing `jq` dependency is treated (unconditional, no fallback).

The value only needs to be unique enough to not collide with a concurrent unrelated call in the
same Run — it is not a security token and is never persisted beyond the single call/retry cycle, so
no format constraint beyond "opaque string" applies.

### AC2 — call sites

Direct grep of the three SKILL.md files (2026-08-08) finds **16** `task-create`/`dispatch`/
`worker-start` invocations wrapped in `orca_call_with_retry`, not the "14" the issue's prose count
states — the issue's own itemized breakdown (8 + 2 + 6 = 16) already matches this; only its summary
sentence ("아래 14개") undercounts. This proposal treats **16 as authoritative** (itemized
breakdown + direct file inspection agree) and flags the "14" in the issue body as a probable
arithmetic slip to correct when AC2/AC4's wording is closed out — not a scope question to resolve
before implementing, since the itemized list is unambiguous. **This "16" claim is scoped to the
`skills/*/SKILL.md` family specifically** — see "Scope boundary: `orca-workflows/self-recovery.md`"
below for the one executable mutating call site that lives outside that family and is deliberately
not counted in the 16.

`orca terminal create` sites are excluded throughout (flag unsupported, confirmed above) — 3 in
`orca-workflow`, 4 in `orca-task-runner` (3 provider launches + 1 commit-helper), 4 in
`orca-evaluate`. `orca orchestration task-list` (round-2+ relay's `reportPath` lookup) is also
excluded — it's a read, not a mutation, and `--help` for it is not claimed to expose the flag (not
checked; out of AC2's named scope of task-create/dispatch/worker-start).

**`skills/orca-workflow/SKILL.md` (8 sites):**

| # | Line(s) | Role | Command | Insert point |
|---|---|---|---|---|
| 1 | 96-97 | retro | `task-create --spec "$spec_text" --json` | before `--json` |
| 2 | 98-99 | retro | `dispatch --task <task_id> --to <retro-handle> --inject --json` | **before `--inject`** |
| 3 | 133-134 | task-runner | `task-create --spec "$spec_text" --json` | before `--json` |
| 4 | 135-136 | task-runner | `dispatch --task <task_id> --to <run-handle> --inject --json` | **before `--inject`** |
| 5 | 163-164 | evaluator | `task-create --spec "$spec_text" --json` | before `--json` |
| 6 | 165-166 | evaluator | `dispatch --task <task_id> --to <evaluate-handle> --inject --json` | **before `--inject`** |
| 7 | 202-203 | contract-round (round 2+) | `task-create --spec "$spec_text" --json` | before `--json` |
| 8 | 204-206 | contract-round (round 2+) | `worker-start --task <task_id> --worktree current --terminal <handle> --run "$RUN_ID" --from <handle> --json` | before `--json` |

**`skills/orca-task-runner/SKILL.md` (2 sites):**

| # | Line(s) | Role | Command | Insert point |
|---|---|---|---|---|
| 9 | 84-85 | subtask-impl | `task-create --spec "$spec_text" --deps '["task_xxx"]' --json` | before `--json` |
| 10 | 167-168 | subtask-impl | `worker-start --task <task_id> --worktree active --terminal <impl_handle> --run "$RUN_ID" --from <handle> --json` | before `--json` |

**`skills/orca-evaluate/SKILL.md` (6 sites):**

| # | Line(s) | Section | Command | Insert point |
|---|---|---|---|---|
| 11 | 32-33 | §0 | `task-create --spec "..." --json` | before `--json` |
| 12 | 34-35 | §0 | `dispatch --task <task_id> --to <evaluate-handle> --inject --json` | **before `--inject`** |
| 13 | 55-56 | §1 (contract-review) | `task-create --spec "$spec_text" --json` | before `--json` |
| 14 | 57-58 | §1 (contract-review) | `dispatch --task <task_id> --to <contract-handle> --inject --json` | **before `--inject`** |
| 15 | 164-165 | §3 (code-review) | `task-create --spec "$spec_text" --json` | before `--json` |
| 16 | 166-167 | §3 (code-review) | `dispatch --task <task_id> --to <review-handle> --inject --json` | **before `--inject`** |

**Insertion rule, corrected from round 1**: the 10 `task-create`/`worker-start` sites insert
`--retry-request "$(uuidgen)"` immediately before the trailing `--json`, unchanged from round 1. The
**6 `dispatch --inject` sites insert it *before* `--inject` instead** — `--to <handle>
--retry-request "$(uuidgen)" --inject --json` — because `tests/test_orca_skills.py:543-545`'s
`_DISPATCH_INJECT_RE` requires `--inject` and `--json` to be **textually adjacent**
(`dispatch --task .*? --inject --json`); round 1 broke that adjacency by putting the new flag
between them. `task-create` and `worker-start` have no such adjacency requirement in any existing
test (confirmed by grep and by the verification run below), so their insertion point is unchanged.

Example diff for a `task-create` site (site 1, unchanged from round 1):

```diff
 orca_call_with_retry "orca-workflow" "retro" -- \
-  orca orchestration task-create --spec "$spec_text" --json
+  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
```

Example diff for a `dispatch --inject` site (site 2, **corrected insertion point**):

```diff
 orca_call_with_retry "orca-workflow" "retro" -- \
-  orca orchestration dispatch --task <task_id> --to <retro-handle> --inject --json
+  orca orchestration dispatch --task <task_id> --to <retro-handle> --retry-request "$(uuidgen)" --inject --json
```

Example diff for the multi-flag `worker-start` site (site 8, unchanged from round 1):

```diff
 orca_call_with_retry "orca-workflow" "contract-round" -- \
   orca orchestration worker-start --task <방금 만든 task_id> --worktree current \
-  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --json
+  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
```

The same two shapes apply uniformly across all 16 sites: `--inject` sites get the flag inserted
before `--inject`; all others get it inserted before the trailing `--json`.

### Scope boundary: `orca-workflows/self-recovery.md`

A repo-wide grep (`skills/` + `orca-workflows/`, not just the three SKILL.md files) finds one more
executable mutating call site: `orca-workflows/self-recovery.md:81-83`, inside the shared
wait/recovery loop's `dead` branch:

```bash
new_result="$(orca orchestration worker-start --task "$TASK_ID" --worktree active \
  --terminal "$NEW_OR_SAME_HANDLE" --retry-of "$DISPATCH_ID" --run "$RUN_ID" \
  --from "$MY_HANDLE" --json)"
```

**This proposal excludes it from the 16-site edit set, deliberately, for two reasons:**

1. **It is not wrapped by `orca_call_with_retry`.** Grepping `self-recovery.md` end to end finds no
   `source .../orca_call_with_retry.sh` or `orca_call_with_retry` invocation anywhere in the file —
   this call runs as a bare `orca orchestration worker-start ...`. Issue #73's threat model is
   specifically "the *wrapper* re-executes an identical mutating command after a false-positive
   transport-failure match" — that mechanism cannot fire here because the wrapper is never in this
   call's path.
2. **It already carries `--retry-of "$DISPATCH_ID"`**, a different and already-intentional
   retry-lineage flag: this call *is* the tracked-retry action for a worker judged `dead`
   (`worker-abandon` fences the old dispatch, then this `worker-start --retry-of` explicitly starts
   a new one). It's a deliberate, once-per-dead-detection state transition, not a candidate for
   accidental duplication by a blind client-side re-exec — the risk `--retry-request` is designed to
   prevent (the *same* call silently running twice) doesn't describe what this line does.

If `self-recovery.md`'s wait loop is ever itself wrapped in `orca_call_with_retry` in a future
change, this call would need `--retry-request` added at that time — noted here as a forward
pointer, not fixed now, since doing so would mean modifying `self-recovery.md`'s retry/wait
semantics, which is out of this issue's stated scope (AC1–AC4 name only `task-create`/`dispatch`/
`worker-start` *call-site wrapping in the three SKILL.md files*, not a redesign of the self-recovery
loop). The three other `orca orchestration`/`orca terminal` mentions elsewhere in `orca-workflows/`
(`logging.md:172,231`, `spawn-failures.md:102`, `references/models/agy.md:44`) are prose references
describing the convention, not executable call sites, and are not candidates either.

### AC3 — header comment fact update

`orca-workflows/scripts/orca_call_with_retry.sh:40-46`, the "Idempotency scope note" paragraph,
currently ends with:

> No idempotency safeguard (client-request-id, dedupe) was found for these calls in this repo.
> Auditing and fixing that is issue #73, deliberately not addressed here.

This is stale once #73 lands. Replace the last two sentences with a factual update — no new issue
narrative, no date list, per AGENTS.md's "skills엔 역사 남기지 말 것" spirit applied here to
scripts as well:

```diff
- Idempotency scope note (out of scope for #42, tracked separately): this function also wraps
- mutating calls (`task-create`/`dispatch`/`worker-start`/`terminal create`). If one of those
- succeeds server-side but the client observes a non-zero exit whose output happens to contain one
- of the broadened keywords, a retry can duplicate the task/dispatch — a pre-existing risk (it
- already existed for the two original literals) that this broadening widens the surface of,
- without introducing it. No idempotency safeguard (client-request-id, dedupe) was found for these
- calls in this repo. Auditing and fixing that is issue #73, deliberately not addressed here.
+ Idempotency scope note (out of scope for #42, tracked separately): this function also wraps
+ mutating calls (`task-create`/`dispatch`/`worker-start`/`terminal create`). If one of those
+ succeeds server-side but the client observes a non-zero exit whose output happens to contain one
+ of the broadened keywords, a retry can duplicate the task/dispatch — a pre-existing risk (it
+ already existed for the two original literals) that this broadening widens the surface of,
+ without introducing it. `task-create`/`dispatch`/`worker-start` support a `--retry-request <id>`
+ flag with confirmed server-side dedupe (same key replayed returns `mutation.replayed: true` and
+ the same resulting id) — callers that want this call idempotent supply a stable id in the wrapped
+ command's own argument vector (this function stays opaque to it; see the three SKILL.md families'
+ call sites, `skills/` scope only — `orca-workflows/self-recovery.md`'s unwrapped `worker-start
+ --retry-of` call is a separate, already-intentional retry-lineage mechanism and is out of this
+ note's scope). `terminal create` has no `--retry-request` flag and remains unprotected.
```

### AC4 — regression tests

Two layers, matching the repo's existing convention
(`tests/test_orca_skills.py` = structural/prose assertions on the markdown; a dedicated functional
test file = real subprocess execution of the bash helper — see
`tests/test_orca_call_with_retry.py`, `tests/test_log_dispatch.py`).

**1. Structural pin in `tests/test_orca_skills.py`** (new tests, appended near the existing
`EXPECTED_RETRY_WRAP_COUNTS` block at `tests/test_orca_skills.py:724-737`):

```python
EXPECTED_RETRY_REQUEST_COUNTS = {
    "orca-workflow": 8,
    "orca-task-runner": 2,
    "orca-evaluate": 6,
}

_RETRY_REQUEST_MUTATING_CALL_RE = re.compile(
    r"orca orchestration (?:task-create|dispatch|worker-start)\b[^\n]*"
    r"(?:\n[ \t]+--[^\n]*)*",  # command may continue on wrapped `\`-continuation lines
)


@pytest.mark.parametrize(("name", "expected"), EXPECTED_RETRY_REQUEST_COUNTS.items())
def test_mutating_call_sites_carry_retry_request(name, expected):
    """AC2: every task-create/dispatch/worker-start invocation must embed its own
    --retry-request "$(uuidgen)" so the server can dedupe a client-side spurious retry
    (issue #73). Scoped to the three flags that --help confirms support it -- terminal create
    does not and is asserted absent below, not required here."""
    text = _read_skill(name)
    calls = _RETRY_REQUEST_MUTATING_CALL_RE.findall(text)
    assert len(calls) == expected, (
        f"{name}: expected {expected} task-create/dispatch/worker-start call sites, found {len(calls)}"
    )
    missing = [c.splitlines()[0] for c in calls if "--retry-request" not in c]
    assert missing == [], f"{name}: call site(s) missing --retry-request: {missing}"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_terminal_create_never_carries_retry_request(name):
    """orca terminal create --help has no --retry-request flag (confirmed 2026-08-08) -- a
    site that adds it anyway would silently no-op or error depending on CLI strictness, and
    either way signals someone copy-pasted the mutating-call pattern onto the wrong command.
    Scoped to fenced ```bash blocks via the repo's existing _BASH_FENCE_RE (same convention as
    _bare_wrapped_call_line_numbers, tests/test_orca_skills.py:686-711) rather than a loose
    re.S span over the whole file -- round 1's version of this test used `.*?--json` with re.S,
    which over-matches into prose sentences that merely mention 'orca terminal create' (e.g.
    each skill's own §0 note) and would false-positive the moment an unrelated --retry-request
    site landed later in the same file."""
    text = _read_skill(name)
    for m in _BASH_FENCE_RE.finditer(text):
        block_lines = m.group(1).splitlines()
        for j, line in enumerate(block_lines):
            if "orca terminal create" in line:
                window = "\n".join(block_lines[j : j + 4])
                assert "--retry-request" not in window, (
                    f"{name}: 'orca terminal create' must not carry --retry-request (unsupported flag)"
                )


EXPECTED_DISPATCH_POSITIONS = {
    "orca-workflow": 4,
    "orca-task-runner": 1,
    "orca-evaluate": 3,
}


@pytest.mark.parametrize(("name", "expected"), EXPECTED_DISPATCH_POSITIONS.items())
def test_dispatch_inject_positions_not_vacuous(name, expected):
    """Vacuity guard (round-1 rejection root cause): test_dispatch_sites_are_followed_by_*_pointer
    iterate `_dispatch_positions(text)` and assert something about each element -- an empty list
    makes the loop body never execute and the test passes having verified nothing. This pins the
    per-skill count so a future edit that collapses positions to 0 (e.g. by breaking
    _DISPATCH_INJECT_RE's `--inject --json` adjacency requirement, exactly what round 1 of this
    proposal did before this fix) fails loudly here instead of the pointer tests going green
    for the wrong reason. Counts match today's pre-#73 baseline exactly -- this proposal's
    call-site edits are additive-only and must not change how many sites _DISPATCH_INJECT_RE
    matches."""
    text = _read_skill(name)
    positions = _dispatch_positions(text)
    assert len(positions) == expected, (
        f"{name}: expected {expected} _DISPATCH_INJECT_RE match(es), found {len(positions)} "
        f"-- a drop to 0 would make the logging/dispatch-verify pointer tests vacuously pass"
    )
```

Note: `NEW_SKILLS` (`tests/test_orca_skills.py:17`) **includes** `orca-retro` — round 1 of this
proposal incorrectly claimed it was excluded; corrected here. `orca-retro/SKILL.md` has no
`task-create`/`dispatch`/`worker-start`/`terminal create` call sites of its own (it's launched *by*
`orca-workflow`'s §1d, whose two calls are already counted as sites 1-2 above), so
`test_terminal_create_never_carries_retry_request[orca-retro]` passes vacuously-but-correctly (no
matching lines to check) — the same shape as several other per-skill parametrized tests already in
this file for skills that don't exercise every pattern.

**2. Header-comment fact assertion**, alongside the existing spawn-failures/header tests:

```python
def test_retry_wrapper_header_documents_retry_request_dedupe():
    text = SCRIPT.read_text()  # orca-workflows/scripts/orca_call_with_retry.sh
    assert "No idempotency safeguard" not in text, (
        "stale claim -- --retry-request dedupe now exists and must be documented instead (#73)"
    )
    assert "--retry-request" in text
    assert "mutation.replayed" in text
```

(This goes in `tests/test_orca_call_with_retry.py`, which already defines `SCRIPT` pointing at
`orca-workflows/scripts/orca_call_with_retry.sh`.)

**3. Subprocess-level behavioral test** — text matching alone cannot verify the load-bearing claim
in AC1 (id stays identical across the whole retry cycle because it's expanded once at call-site
construction, not regenerated per attempt). Precedent for going past text matching:
`tests/test_log_dispatch.py`'s bash+zsh parametrization was added specifically because "a bash-only
harness structurally cannot catch shell-dependent defects" (issue #68 round 1 finding, reused
verbatim in AC4's own wording). Extend `tests/test_orca_call_with_retry.py`'s `_run` helper
(`tests/test_orca_call_with_retry.py:25-49` — corrected line reference; round 1 misquoted this as
`74-99`) to accept a `shell` parameter (default `"bash"`, mirroring `test_log_dispatch.py:36-38`'s
`shutil.which(shell) is None: pytest.skip(...)` guard), then add:

```python
import shutil

SHELLS = ["bash", "zsh"]


@pytest.mark.parametrize("shell", SHELLS)
def test_retry_request_value_is_identical_across_retry_cycle(tmp_path, shell):
    """A caller embeds --retry-request "$(uuidgen)" in the command line handed to
    orca_call_with_retry, once, before the retry loop starts. This test proves that literal
    value -- not a fresh uuidgen call -- is what reaches the wrapped command on every retry
    attempt, which is exactly the property issue #73/AC1 relies on to make retries
    idempotent server-side. Reproduces the wrapper's real retry path (transient failure -> orca
    status ready -> identical re-exec) rather than asserting on the SKILL.md prose."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"state":"ready"}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            # record every --retry-request value this invocation was called with
            for a in "$@"; do
              if [ "$prev" = "--retry-request" ]; then echo "$a" >> "$SEEN_FILE"; fi
              prev="$a"
            done
            count=0
            [ -f "$COUNTER_FILE" ] && count="$(cat "$COUNTER_FILE")"
            count=$((count + 1))
            echo "$count" > "$COUNTER_FILE"
            if [ "$count" -eq 1 ]; then
              echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
              exit 1
            fi
            exit 0
        """,
    }
    counter_file = tmp_path / "counter"
    seen_file = tmp_path / "seen"
    # mimic a caller's real call-site: id expanded once via command substitution, at
    # construction time, exactly as skills/*/SKILL.md's proposed edits do
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- '
        'real-cmd --retry-request "$(uuidgen)" --json',
        extra_env={
            "COUNTER_FILE": str(counter_file),
            "SEEN_FILE": str(seen_file),
            "ORCA_RETRY_POLL_INTERVAL": "0",
            "ORCA_RETRY_POLL_MAX": "1",
        },
        shell=shell,
    )
    assert result.returncode == 0
    seen = seen_file.read_text().splitlines()
    assert len(seen) == 2, f"expected real-cmd invoked twice (initial + 1 retry), got {seen}"
    assert seen[0] == seen[1], (
        f"--retry-request value changed across the retry cycle: {seen[0]!r} != {seen[1]!r}"
    )
    assert seen[0] != "", "--retry-request value must not be empty"
```

This test needs `uuidgen` on the stub `PATH` (or the real `/usr/bin/uuidgen` — the stub `bin_dir` is
prepended to `PATH`, real system dirs remain reachable behind it per `_run`'s
`env["PATH"] = f"{bin_dir}:{env['PATH']}"`, so no stub is needed for `uuidgen` itself).

## Affected files

- `orca-workflows/scripts/orca_call_with_retry.sh` — comment-only edit (AC3), lines 40-46. No
  behavioral change, no version bump needed (it's the symlink-tracks-main path per AGENTS.md #22).
- `skills/orca-workflow/SKILL.md` — 8 call sites (lines 96-99, 133-136, 163-166, 202-206).
- `skills/orca-task-runner/SKILL.md` — 2 call sites (lines 84-85, 167-168).
- `skills/orca-evaluate/SKILL.md` — 6 call sites (lines 32-35, 55-58, 164-167).
- `tests/test_orca_skills.py` — new structural tests (§AC4.1 above).
- `tests/test_orca_call_with_retry.py` — new header-fact test (§AC4.2) + new behavioral test
  (§AC4.3), plus a small `_run` signature extension (`shell` parameter) to support it.

`skills/orca-retro/SKILL.md` and `orca-workflows/self-recovery.md` are untouched by this proposal —
see the "Scope boundary" section above for why `self-recovery.md`'s one `worker-start` site is
deliberately excluded, and the AC4 note above for `orca-retro` having no call sites of its own.

## Destructive operations

None. This is a documentation/prose edit to three SKILL.md files plus one comment block and two
test files. No schema, migration, or data-affecting code path is touched.

## Existing tests that go red or need updating

**Round 1 got this section wrong** — it claimed "none red" without actually applying the proposed
edits and running the suite. This round's version is backed by a real run: the exact 16-site edit
set from AC2 above (10 sites inserted before `--json`, 6 `dispatch --inject` sites inserted before
`--inject`) was applied to a working copy of the three SKILL.md files and verified with
`python3 -m pytest tests/test_orca_skills.py -q`:

```
165 passed in 0.07s
```

— identical to the pre-edit baseline (also 165 passed, same command, `main @ bc6ee7c`). No test
newly fails and no test's coverage silently collapses. Specifically:

- `_dispatch_positions()` counts per skill (`tests/test_orca_skills.py:543-549`,
  `_DISPATCH_INJECT_RE`) after the edit: `orca-workflow` 4, `orca-task-runner` 1, `orca-evaluate` 3
  — **unchanged from the pre-edit baseline**, confirmed by direct script execution against the
  edited files (not inferred from reading the regex). This is what round 1 got wrong: inserting
  before `--json` at the 6 `dispatch --inject` sites broke the `--inject --json` adjacency
  `_DISPATCH_INJECT_RE` requires, dropping these to `orca-workflow` 1 / `orca-task-runner` 1 /
  `orca-evaluate` 0 and silently emptying the loop bodies of
  `test_dispatch_sites_are_followed_by_logging_pointer` (`:597-610`) and
  `test_dispatch_sites_are_followed_by_dispatch_verify_pointer` (`:1068-`) — both still "passed"
  with zero iterations, i.e. vacuously. Inserting before `--inject` instead keeps `--inject --json`
  adjacent, so all three counts are preserved and both pointer tests actually exercise their
  assertions again. `test_dispatch_site_count_and_section0_exception_shape` (`:570-594`, asserting
  `total == 8` and `excluded == 1` across all `NEW_SKILLS`) also passed unchanged for the same
  reason.
- `tests/test_orca_skills.py::test_orca_call_with_retry_count_per_skill` (line 734-737,
  `EXPECTED_RETRY_WRAP_COUNTS`) — unaffected: adding `--retry-request "$(uuidgen)"` inside an
  existing `orca_call_with_retry "<skill>" "<role>" -- \` invocation doesn't change how many such
  invocation lines exist, and `_RETRY_INVOCATION_LINE_RE` only matches the invocation line itself,
  not the wrapped command's flags.
- `tests/test_orca_skills.py::test_no_bare_wrapped_call_sites` — unaffected for the same reason.
- `tests/test_orca_skills.py::test_orca_workflow_round2_relay_worker_start_uses_worktree_current`
  (lines 778-798) — unaffected: it slices from `"orca orchestration worker-start --task"` to the
  next `"--json"` and asserts `--worktree current`/`not --worktree active` inside that slice.
  Inserting `--retry-request "$(uuidgen)"` before the trailing `--json` (this site is a
  `worker-start`, not a `dispatch --inject`, so its insert point is unchanged from round 1) keeps
  both flags inside the same slice; the assertion strings are unaffected.
- `tests/test_orca_call_with_retry.py` is a separate file from `tests/test_orca_skills.py`, not
  collected by the 165-test run above — checked independently:
  `python3 -m pytest tests/test_orca_call_with_retry.py -q` → **13 passed**. None of its existing
  tests assert on the wrapped command's own argument content, only on `orca_call_with_retry`'s own
  stdout/stderr/exit-code/logging behavior with the trivially-named `real-cmd` stub, and this
  proposal doesn't edit `orca_call_with_retry.sh`'s behavior (AC1, AC3 is comment-only) — so all 13
  stay green, and this count becomes the "existing" baseline the new AC4 §2/§3 tests are added on
  top of.

No existing assertion needs to be deleted or rewritten; this proposal is purely additive at the
test level (new tests) and additive-plus-one-comment-rewrite at the doc/script level. The
`EXPECTED_DISPATCH_POSITIONS` vacuity guard added in AC4 §1 above is the mechanism that makes this
claim self-enforcing going forward, not just true today.

## Open question surfaced for the evaluator

The issue's own text says "14개 call site" in AC2's lead sentence but its itemized breakdown sums
to 16, and this proposal's independent grep of the three files also finds 16. This proposal
proceeds on 16 (all sites, matching the itemized list) rather than stopping short at 14 of them —
flagging this explicitly in case the evaluator has context this session doesn't for why 14 might be
the intended number (e.g. if two of the itemized sites were meant to be merged or one skill's count
was meant to be lower). Round 1's evaluator response confirmed the itemized 8+2+6=16 breakdown as
correct via independent re-grep and did not raise this as a blocker, so this round carries it
forward unchanged rather than re-litigating it.
