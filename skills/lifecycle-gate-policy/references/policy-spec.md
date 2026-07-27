# Policy spec — required categories by stage

This document is the **policy** half of lifecycle-gate-policy: it states what
must be blocked, when, in terms of *categories* — never in terms of a
specific script, hook manager, or file layout. A repository satisfies this
spec by declaring, in its own `lifecycle-gate.toml`
(see [manifest-schema.md](manifest-schema.md)), which observable entrypoint
in its stack fulfills each required category. How that entrypoint is wired —
husky, lefthook, `.githooks` + `core.hooksPath`, raw `.git/hooks`, or anything
else — is the repository's choice and is out of scope here.

## Category vocabulary

Seven categories exist. A category name outside this list is not valid in a
manifest.

| Category | Definition |
|---|---|
| `secret-scan` | Scans staged content for credentials/secrets before they enter a commit. Blocks the commit when a match is found. |
| `format-autofix` | Automatically rewrites staged files to a canonical format/lint style as part of committing, rather than only reporting violations. |
| `static-verify` | Fast checks that don't execute the runtime or test suite — typechecking, linting, static analysis. No emulators, no network, no test execution. |
| `full-verify` | The complete non-e2e verification chain — everything in `static-verify` plus unit/integration tests. Runs once, at merge time, not on every push. |
| `e2e` | End-to-end tests that exercise the running system as a whole. Expensive; not required for repositories that don't maintain an e2e suite. |
| `protected-escalation` | A mechanical check that routes changes to the gate's own integrity surface (hook config, gate scripts, gate config) to a human instead of the authoring agent, so the gate is never writable by the agent it judges. |
| `sync-check` | Verifies the change is being merged on top of the current default-branch HEAD, so a green result was not computed against a stale base. |

## Required categories by stage

| Stage | Required | Recommended (not required) |
|---|---|---|
| `pre-commit` | `secret-scan` | `format-autofix` |
| `pre-push` | `static-verify` | — |
| `premerge` | `full-verify`, `protected-escalation`, `secret-scan` | `e2e` (see below), `sync-check` |

`secret-scan` at `premerge` exists for a different reason than at `pre-commit`: `pre-commit` and
`pre-push` are both git hooks, so a shared dependency — whether `core.hooksPath` is actually wired in
a given worktree/git client — can silently disable both at once (observed, not hypothetical: see
issue #26). `premerge` is not a git hook; it is an explicitly-invoked script, so it does not share
that failure mode, and self-merge policy already names it the one mandatory checkpoint. Requiring
`secret-scan` there gives secret-scan coverage a second, independently-failing path — not a stronger
version of the same check.

- A stage missing a required category is a policy **FAIL** — not an
  implementation opinion, an unmet requirement.
- `e2e` is recommended at `premerge` only when the repository actually
  maintains an e2e suite. A repository with no e2e suite omitting it is a
  **WARN**, not a FAIL — there is nothing to run. A repository that has an
  e2e suite and omits the category from its manifest is also a WARN: the
  policy encourages running it before merge but does not force it, since
  suite cost/flake tradeoffs are a repository-level call.
- Categories beyond the required set (e.g. `format-autofix` at pre-commit,
  `sync-check` at premerge) may be declared at any stage where they make
  sense; declaring them is never penalized.

## What "mechanism-agnostic" means (and does not mean)

This is the load-bearing distinction in this policy, stated precisely
because it is easy to over-read:

**Mechanism-agnostic means: do not read or hash-compare the contents of a
repository's hooks or scripts.** A conformance check must never open
`.githooks/pre-commit`, diff it against a canonical copy, or otherwise judge
a repository by what its implementation *looks like*. Two repositories using
completely different hook managers, languages, or script structures can both
be compliant, and neither is more "correct" than the other for having chosen
a particular mechanism.

**Mechanism-agnostic does not mean: do not observe results.** Observing
whether an entrypoint actually blocks — its exit code, whether it stops the
operation (commit/push/merge), and what it prints — is not "reading the
script." It is the *only* way to know a stage is actually live rather than
declared-but-inert, and this policy requires it: a manifest declaration with
no corresponding observed behavior is not evidence that *that stage* complies.

That is the policy's requirement. The shipped audit implements it one run at a
time, not one stage at a time: it refuses to certify a run that observed
nothing, but a run that observed one stage can still report `COMPLIANT` while
another declared stage went unobserved. Closing that gap per stage is a known
follow-up — see the verdict scope section in `manifest-schema.md`. Until then,
read the per-stage lines rather than the headline verdict when you need to know
whether a specific stage was exercised.

Concretely, allowed and required observations include:

- the process exit code of the entrypoint command,
- whether the git operation it gates (commit/push/merge) was actually
  blocked or allowed through,
- literal strings the entrypoint writes to stdout/stderr, used only to rule
  out a category of failure (e.g. "command not found") — not to infer
  internal script logic.

None of this requires opening a file inside the repository under test. A
conformance check that only ever runs commands and reads their outcomes has
not violated mechanism-agnosticism no matter how much output it inspects.

## Hook manager choice is unconstrained

This policy does not prefer husky, lefthook, `.githooks` + `core.hooksPath`,
raw `.git/hooks`, or any other mechanism over another. A repository picks
whichever fits its stack. What the policy requires is that the repository's
manifest name an observable entrypoint for each required category, and that
conformance be judged by an entrypoint's observable outcome rather than by the
mechanism behind it.

What gets exercised is a separate question from what is declared. The fixtures
shipped here drive `git commit` and `git push`; a stage naming some other
command has that name recorded but not run, so its declaration stays unverified
(`manifest-schema.md` states this per stage).
