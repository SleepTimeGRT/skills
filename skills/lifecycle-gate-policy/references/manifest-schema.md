# `lifecycle-gate.toml` schema

Each repository declares, in a `lifecycle-gate.toml` at its root, which
observable entrypoint fulfills each category required by
[policy-spec.md](policy-spec.md). The manifest states *what to run and
where to look*; it never states *how the entrypoint is implemented*.

A ready-to-copy template with inline comments lives at
[../assets/lifecycle-gate.toml.example](../assets/lifecycle-gate.toml.example).

## Why TOML, not YAML

The issue that introduced this manifest left the format name open
("`lifecycle-gate.yaml` (가칭)"). TOML was chosen because the auditing tool
must parse the manifest with zero install step: Python's `tomllib` is
standard library (3.11+), while YAML parsing requires an external
dependency (PyYAML) that is not guaranteed to be present. Parsing the
manifest must never itself require a package install.

## Top-level fields

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `policy_version` | string | yes | — | Schema version this manifest conforms to. Currently only `"2"` is valid. |
| `[bootstrap]` | table | yes | — | See [Bootstrap](#bootstrap-required) below. |
| `[stages.*]` | table | at least one | — | Per-stage entrypoint + declared categories. See [Stages](#stages). |
| `[fixtures]` | table | no, but required to reach `COMPLIANT` | absent = nothing is observed, so the audit reports `UNVERIFIED` (exit 3) and `COMPLIANT` is unreachable | Which conformance fixtures to exercise against this repository. See [Verdicts](#verdicts). |
| `[fixtures.<name>]` | table | no, per fixture | `{}` | Fixture-specific configuration data (never mechanism — see policy-spec's mechanism-agnostic section). |

## Bootstrap (required)

```toml
[bootstrap]
entrypoint = "pnpm run prepare"
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `entrypoint` | string | **yes** | A shell command that reproduces this repository's gate wiring in a fresh checkout. |

**Why this field is required, not optional:** the conformance harness runs
fixtures against an isolated copy of the repository made with
`git clone --local`, so that no fixture can ever push to the repository's
real remote or mutate its working tree. But `git clone` does not carry over
*local* git config — most importantly `core.hooksPath` — because that config
lives in `.git/config`, which a clone starts fresh, not in any file that
`git clone` copies. A repository that wires its hooks via
`git config core.hooksPath .githooks` (commonly from a `package.json`
`prepare` script) therefore ends up with **no hooks wired at all** in the
clone unless something re-runs that wiring step inside the clone. Without
`[bootstrap].entrypoint`, every fixture would run against a clone where the
gate never fires — probes would report the stage as blocked-successfully
for the wrong reason (no hook to run, not a passing hook), and every fixture
would pass *vacuously*. Requiring this field is what prevents that: a
manifest with no bootstrap entrypoint is reported `MISSING`, not silently
treated as compliant.

**Constraint: bootstrap is wiring-only, never a dependency install.** The
harness symlinks the source repository's `node_modules` into the scratch
clone (rather than reinstalling) so that fixtures stay cheap. A bootstrap
command that runs an install step (`pnpm install`, `npm ci`, etc.) risks
writing into that symlinked directory, which mutates the **original**
repository's `node_modules`, not just the scratch copy. `entrypoint` must
only reproduce gate wiring (setting `core.hooksPath`, running a hook
manager's own install-the-hooks step, etc.) — never a package-dependency
install.

## Stages

At least one `[stages.<name>]` table must be present. Each declares:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `entrypoint` | string | yes | An observable command/event for this stage — e.g. `git commit`, `git push`, a premerge script invocation. Mechanism-agnostic: what is observed is the entrypoint's outcome, never its implementation. The audit checks that the declaration is present and non-empty — it does not check that the named command exists or run it; see the coverage note below for which entrypoints the shipped fixtures actually drive. |
| `categories` | array of strings | yes | Category names (from the vocabulary in policy-spec.md) that this stage's entrypoint is asserted to enforce. |

Recognized stage names for this manifest version: `pre-commit`, `pre-push`,
`premerge`. See [policy-spec.md](policy-spec.md#required-categories-by-stage)
for which categories are required at each.

## Fixtures

```toml
[fixtures]
enabled = ["biome-noop", "path-fallback", "delete-only-push"]

[fixtures.biome-noop]
ignored_path = "src/lib/supabase/types.ts"

### `[fixtures.biome-noop].ignored_path` — two requirements

The path must satisfy both, or the fixture reports `SKIP` rather than a verdict:

1. **Inside the formatter's ignore-set.** That is the condition the fixture reproduces.
2. **A file extension the formatter would otherwise process** (`.ts`, `.tsx`, `.js`,
   `.jsx`, `.mjs`, `.cjs`, `.json`, `.jsonc`). A path the formatter never looks at —
   markdown, logs, docs — makes the commit succeed for an unrelated reason. That is a
   vacuous PASS, the failure mode this fixture set exists to prevent.

If the formatter cannot be resolved inside the scratch clone (for example a workspace
whose per-package dependencies are not installed there), the fixture reports
`SKIP (tooling-unavailable)`: a blocked commit caused by a missing tool says nothing
about the repository's policy.

[fixtures.path-fallback]
timeout_seconds = 60
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `fixtures.enabled` | array of strings | no | `[]` (no fixtures run) | Names of conformance fixtures to run against this repository. |
| `fixtures.<name>.*` | fixture-specific | no | `{}` | Data the fixture needs that is repository-specific (a real file path, a timeout), never a description of mechanism. |

`premerge` was originally not a fixture/probe target: the three fixtures shipped by the issue that
introduced this manifest format exercise `pre-commit` and `pre-push` only. One exception exists — the
`premerge-secret-scan` fixture (added for issue #26) reads `[stages.premerge].entrypoint` from the
manifest and runs it directly, specifically to observe the `secret-scan` category now required at
`premerge` (see policy-spec.md). When `premerge-secret-scan` is not declared in `[fixtures].enabled`,
`premerge` still receives structural category-declaration checking only and
`stages.premerge.behavioral` reports `NOT-EXERCISED` — "we didn't test this" must never be misread as
"this passed." When `premerge-secret-scan` *is* declared, its own `fixture:premerge-secret-scan`
result line carries the real status instead, and no separate `NOT-EXERCISED` line is added.

## Full example

```toml
policy_version = "2"

[bootstrap]
entrypoint = "pnpm run prepare"

[stages.pre-commit]
entrypoint = "git commit"
categories = ["secret-scan", "format-autofix"]

[stages.pre-push]
entrypoint = "git push"
categories = ["static-verify"]

[stages.premerge]
entrypoint = "bash scripts/premerge.sh"
categories = ["full-verify", "e2e", "protected-escalation", "secret-scan"]

[fixtures]
enabled = ["biome-noop", "path-fallback", "delete-only-push", "premerge-secret-scan"]

[fixtures.biome-noop]
ignored_path = "src/lib/supabase/types.ts"

[fixtures.path-fallback]
timeout_seconds = 60
```

## Validation rules

| Condition | Result |
|---|---|
| Manifest file absent | `MISSING` (never crash — the message must say what to add) |
| `policy_version` is not `"2"` | `FAIL` |
| `[bootstrap].entrypoint` absent or empty | `MISSING` |
| A declared stage's `categories` does not cover that stage's required set (policy-spec.md) | `FAIL` |
| A category name is outside the vocabulary | `FAIL` |
| `premerge` categories omit `e2e` | `WARN` |

### What the shipped fixtures actually drive

Four fixtures ship with this skill. Three drive `git commit` (pre-commit) and `git push` (pre-push)
directly, regardless of what a stage declares. The fourth, `premerge-secret-scan`, is the one
exception described above: it reads and runs whichever command `[stages.premerge].entrypoint` names,
so unlike the other three, its liveness check is only as good as that declared entrypoint actually
being the repo's real premerge command. A `pre-commit` or `pre-push` stage that names a different
entrypoint — `make gate`, a wrapper script — has the presence of its declaration checked and nothing
more: the audit never resolves or runs that command, because none of the `pre-commit`/`pre-push`
fixtures read the manifest's declared entrypoint at all (they always drive `git commit`/`git push`
directly). `premerge` does not share that limitation once `premerge-secret-scan` is enabled — that
fixture resolves and runs the declared `[stages.premerge].entrypoint` verbatim. Without
`premerge-secret-scan` enabled, `premerge` is in the same position as an undriven `pre-commit`/
`pre-push` entrypoint and is reported `NOT-EXERCISED`.

Two things follow, and the second one surprises people:

1. A named-but-undriven entrypoint is never verified. Nothing observed whether
   `make gate` blocks anything.
2. A fixture's `PASS` is attributed to the fixture, not to the declared
   entrypoint. So a `pre-push` stage declaring `make gate` can still show
   `fixture:delete-only-push PASS` — that result came from `git push`, and it
   says nothing about `make gate`.

Declaring an entrypoint no fixture drives is allowed; mistaking it for verified
coverage is the failure to avoid. Keep declared entrypoints aligned with what
the fixtures actually drive if you want the report to mean what it appears to
mean — see [Verdicts](#verdicts) for the scope the verdict does cover.

## Verdicts

The verdict describes the run as a whole. At that scope it is fail-closed: a run
in which nothing was observed is never reported as compliance.

| Verdict | Exit | Reached when |
|---|---|---|
| `COMPLIANT` | 0 | at least one fixture reported `PASS` and no behavioral check was `WARN`/`SKIP` |
| `STRUCTURE-ONLY` | 0 | `--skip-fixtures` was passed — the declaration was checked, nothing was observed |
| `UNVERIFIED` | 3 | no failures, but evidence is incomplete: a fixture skipped or warned, an enabled fixture name is unimplemented, or `[fixtures]` declares none |
| `NON-COMPLIANT` | 1 | any check is `FAIL` or `MISSING`, including a `[bootstrap].entrypoint` that does not succeed in a scratch clone |

Advisory structural warnings (for example "no `e2e` category declared —
recommended, not required") are advice about the declaration, not missing
evidence, and do not block `COMPLIANT`.

### The scope the verdict does not cover

`COMPLIANT` is not a per-stage certificate. It is reached when at least one
enabled fixture reported `PASS` and no behavioral check was inconclusive — the
declared stages that no enabled fixture drives are not counted against it. A
repository with no pre-commit hook at all reaches `COMPLIANT` if its single
enabled fixture is `delete-only-push`, and the report contains no line saying
pre-commit went unobserved (only `premerge` gets `NOT-EXERCISED`).

The practical trap: `pre-commit` is observed only inside `biome-noop`, which
needs `[fixtures.biome-noop].ignored_path` and otherwise reports `SKIP` — which
holds the run at `UNVERIFIED`. Deleting that fixture from `enabled` therefore
*raises* the verdict to `COMPLIANT`, provided another enabled fixture is still
passing, while removing the last observation of pre-commit. (If it was the only
enabled fixture, the run stays at `UNVERIFIED` — nothing is observed at all.) Do
not resolve an `UNVERIFIED` that way; resolve it by making the skipped fixture
able to run.

Capping the verdict per declared stage — every declared stage needing its own
observation — is a follow-up rather than a tweak: `premerge` is exercised only
when `premerge-secret-scan` is enabled, and even then only for the `secret-scan`
category — `full-verify` and `protected-escalation` at `premerge` still have no
fixture of their own, so `premerge` needs a category-scoped exemption rather than
an all-or-nothing one, and pre-commit observation has to be promoted out of
`biome-noop` into a standalone probe first, or repositories with no eligible
`ignored_path` could never reach `COMPLIANT`.
