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
| `[fixtures]` | table | no | absent = no fixtures run | Which conformance fixtures to exercise against this repository. |
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
| `entrypoint` | string | yes | An observable command/event for this stage — e.g. `git commit`, `git push`, a premerge script invocation. Mechanism-agnostic: the harness runs this and observes its outcome, never its implementation. |
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

[fixtures.path-fallback]
timeout_seconds = 60
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `fixtures.enabled` | array of strings | no | `[]` (no fixtures run) | Names of conformance fixtures to run against this repository. |
| `fixtures.<name>.*` | fixture-specific | no | `{}` | Data the fixture needs that is repository-specific (a real file path, a timeout), never a description of mechanism. |

`premerge` is not a fixture/probe target: the fixtures shipped with this
policy exercise `pre-commit` and `pre-push` only, per the issue that
introduced them. `premerge` receives structural category-declaration
checking only; a report must mark it `NOT-EXERCISED` rather than `PASS`, so
"we didn't test this" is never misread as "this passed."

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
categories = ["full-verify", "e2e", "protected-escalation"]

[fixtures]
enabled = ["biome-noop", "path-fallback", "delete-only-push"]

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
