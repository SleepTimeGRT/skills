# Pre-push nvm PATH Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/token-gate.sh` resolve `pnpm`/`node` via nvm when the invoking
process doesn't inherit an interactive shell's PATH (the root cause of `pnpm: command
not found` failures when pushing/committing through a non-interactive GUI git client),
without adding any new bypass/skip mechanism to the git hooks themselves.

**Architecture:** A guarded PATH-fallback block is added once, at the top of the
already-shared `scripts/token-gate.sh` (sourced by `pre-push` today); `pre-commit` is
changed to source the same file so it benefits too. The block is a no-op whenever
`pnpm` is already resolvable, and only touches nvm (the only version manager with
evidence of being installed) — no fnm/volta/asdf/mise support is added speculatively.

**Tech Stack:** Bash (hook templates), Python `unittest` + `subprocess` (existing test
harness in `tests/test_lifecycle_gate_policy.py`).

## Global Constraints

- nvm only — do not add fnm/volta/asdf/mise handling (no installed-machine evidence for them; see design spec's rejected-scope note).
- No repo-committed skip/bypass flag and no new marker-file mechanism — the GUI-client bypass is solved entirely outside this repo (Fork's own Custom Commands feature), per the approved design.
- Do not name the specific GUI client ("Fork") inside any shipped skill asset (`token-gate.sh`, `pre-commit`, `SKILL.md`, `agents-policy.md`) — keep wording generic ("a non-interactive GUI git client"), per the "no history/client references in skills" convention.
- Only the canonical templates in `skills/lifecycle-gate-policy/assets/` change. No target repository (medicount, etc.) is touched as part of this plan.
- Existing `token-gate.sh` behavior (PASS/WARN/FAIL/SKIP semantics, log capture) must not change — the fallback is additive, top-level code that runs once when the file is sourced.

---

## File Structure

- Modify: `skills/lifecycle-gate-policy/assets/scripts/token-gate.sh` — add the PATH-fallback block after the header comment, before `token_gate_begin()`.
- Modify: `skills/lifecycle-gate-policy/assets/githooks/pre-commit` — source `token-gate.sh` (for its PATH-fallback side effect) right after `set -euo pipefail`.
- Modify: `tests/test_lifecycle_gate_policy.py` — add `import shutil`, a `PRE_COMMIT` path constant, a `PathFallbackTests` class, and a `PreCommitHookTests` class.

No new files are created.

---

### Task 1: nvm PATH fallback in `token-gate.sh`

**Files:**
- Modify: `skills/lifecycle-gate-policy/assets/scripts/token-gate.sh:1-5`
- Test: `tests/test_lifecycle_gate_policy.py` (new `PathFallbackTests` class)

**Interfaces:**
- Consumes: `GitFixture` (base class with `self.repo`, `self.write()`), `RUNNER` constant, `run()` helper — all already defined earlier in `tests/test_lifecycle_gate_policy.py`.
- Produces: nothing later tasks depend on directly (Task 2 is independent; both just live in the same test file).

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_lifecycle_gate_policy.py`, after the existing `RunnerTests` class (before the `if __name__ == "__main__":` block):

```python
class PathFallbackTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        self.fixture_home = Path(self.tempdir.name) / "fixture home"
        self.fixture_home.mkdir()
        self.fake_bin = Path(self.tempdir.name) / "fake bin"
        self.fake_bin.mkdir()
        pnpm_stub = self.fake_bin / "pnpm"
        pnpm_stub.write_text("#!/usr/bin/env bash\necho fake-pnpm \"$@\"\n", encoding="utf-8")
        pnpm_stub.chmod(0o755)

    def write_fake_nvm(self) -> None:
        nvm_dir = self.fixture_home / ".nvm"
        nvm_dir.mkdir()
        (nvm_dir / "nvm.sh").write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                nvm() {{
                  case "${{1:-}}" in
                    use)
                      if [ "${{2:-}}" = "default" ]; then
                        export PATH={json.dumps(str(self.fake_bin))}:"$PATH"
                        return 0
                      fi
                      if [ -f "$(pwd)/.nvmrc" ]; then
                        export PATH={json.dumps(str(self.fake_bin))}:"$PATH"
                        return 0
                      fi
                      echo "No .nvmrc file found" >&2
                      return 1
                      ;;
                  esac
                }}
                """
            ).lstrip(),
            encoding="utf-8",
        )

    def run_source_probe(self, *, home: Path, path: str) -> subprocess.CompletedProcess[str]:
        script = self.write(
            "probe.sh",
            f"""
            #!/usr/bin/env bash
            set -u
            source {json.dumps(str(RUNNER))}
            command -v pnpm
            """,
            True,
        )
        return run("bash", str(script), cwd=self.repo, check=False, env={"HOME": str(home), "PATH": path})

    def test_falls_back_to_nvm_default_alias_when_no_nvmrc(self) -> None:
        self.write_fake_nvm()
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_uses_nvmrc_version_when_present(self) -> None:
        self.write_fake_nvm()
        self.write(".nvmrc", "v22.18.0\n")
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_does_not_invoke_nvm_when_pnpm_already_on_path(self) -> None:
        result = self.run_source_probe(home=self.fixture_home, path=f"{self.fake_bin}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.fake_bin / "pnpm"))

    def test_leaves_pnpm_unresolved_when_nvm_is_unavailable(self) -> None:
        result = self.run_source_probe(home=self.fixture_home, path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
```

Also add `import shutil` is **not** needed for this step (only Task 2 needs it) — skip it here.

- [ ] **Step 2: Run the new tests to verify the feature tests fail**

Run: `python3 -m unittest tests.test_lifecycle_gate_policy.PathFallbackTests -v`

Expected: `test_falls_back_to_nvm_default_alias_when_no_nvmrc` and
`test_uses_nvmrc_version_when_present` FAIL (stdout is empty / returncode 1, because
`token-gate.sh` has no fallback yet). `test_does_not_invoke_nvm_when_pnpm_already_on_path`
and `test_leaves_pnpm_unresolved_when_nvm_is_unavailable` PASS already (they describe
behavior that holds with or without the fix) — that's expected, not a problem.

- [ ] **Step 3: Implement the fallback**

Edit `skills/lifecycle-gate-policy/assets/scripts/token-gate.sh`. Current lines 1-6:

```sh
#!/usr/bin/env bash
# lifecycle-gate-policy: canonical scripts/token-gate.sh v1 — do not hand-edit in the
# target repository; change the copy in sleeptimegrt-skills and re-apply.
# Source this file from a non-interactive repository gate.

token_gate_begin() {
```

Replace with:

```sh
#!/usr/bin/env bash
# lifecycle-gate-policy: canonical scripts/token-gate.sh v1 — do not hand-edit in the
# target repository; change the copy in sleeptimegrt-skills and re-apply.
# Source this file from a non-interactive repository gate.

# A non-interactive GUI git client can spawn hooks without an interactive
# shell's PATH, so an nvm-managed pnpm/node can be invisible even though a
# normal terminal push works fine. Resolve it directly here instead of
# depending on the invoking process having sourced the user's shell profile.
# nvm only — no fnm/volta/asdf/mise support without evidence they're in use.
if ! command -v pnpm >/dev/null 2>&1 && [ -s "${HOME}/.nvm/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "${HOME}/.nvm/nvm.sh" --no-use
  nvm use >/dev/null 2>&1 || nvm use default >/dev/null 2>&1 || true
fi

token_gate_begin() {
```

- [ ] **Step 4: Run the tests to verify they all pass**

Run: `python3 -m unittest tests.test_lifecycle_gate_policy.PathFallbackTests -v`
Expected: all 4 tests PASS.

Then run the full file to confirm no regression on the existing 11 tests:

Run: `python3 -m unittest tests.test_lifecycle_gate_policy -v`
Expected: 15 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/lifecycle-gate-policy/assets/scripts/token-gate.sh tests/test_lifecycle_gate_policy.py
git commit -m "$(cat <<'EOF'
fix(lifecycle-gate-policy): resolve pnpm via nvm when PATH lacks it

Non-interactive GUI git clients can spawn hooks without an interactive
shell's PATH, so an nvm-managed pnpm/node was invisible to token-gate.sh
even when a normal terminal push worked fine. Source nvm.sh and select
the repo's .nvmrc version (or the default alias) only when pnpm isn't
already resolvable; no-op otherwise. nvm only — no other version manager
has evidence of being in use.
EOF
)"
```

---

### Task 2: source `token-gate.sh` from `pre-commit`

**Files:**
- Modify: `skills/lifecycle-gate-policy/assets/githooks/pre-commit:8-9`
- Test: `tests/test_lifecycle_gate_policy.py` (new `PRE_COMMIT` constant, `import shutil`, new `PreCommitHookTests` class)

**Interfaces:**
- Consumes: `GitFixture`, `RUNNER`, `run()` (existing); adds its own `PRE_COMMIT` constant next to `RUNNER`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Add `import shutil` to the import block near the top of `tests/test_lifecycle_gate_policy.py` (alphabetically between `import shlex` and `import stat`):

```python
import shlex
import shutil
import stat
```

Add a `PRE_COMMIT` constant right after the existing `RUNNER` line:

```python
RUNNER = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "scripts" / "token-gate.sh"
PRE_COMMIT = ROOT / "skills" / "lifecycle-gate-policy" / "assets" / "githooks" / "pre-commit"
```

Add this class after `PathFallbackTests` (before `if __name__ == "__main__":`):

```python
class PreCommitHookTests(GitFixture):
    def setUp(self) -> None:
        super().setUp()
        hooks_dir = self.repo / ".githooks"
        hooks_dir.mkdir()
        scripts_dir = self.repo / "scripts"
        scripts_dir.mkdir()
        shutil.copy(PRE_COMMIT, hooks_dir / "pre-commit")
        (hooks_dir / "pre-commit").chmod(0o755)
        shutil.copy(RUNNER, scripts_dir / "token-gate.sh")

        self.stub_bin = Path(self.tempdir.name) / "stub bin"
        self.stub_bin.mkdir()
        self.biome_marker = Path(self.tempdir.name) / "biome-invoked.marker"
        (self.stub_bin / "gitleaks").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (self.stub_bin / "gitleaks").chmod(0o755)
        (self.stub_bin / "pnpm").write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                if [ "$1" = "exec" ] && [ "$2" = "biome" ]; then
                  touch {json.dumps(str(self.biome_marker))}
                fi
                exit 0
                """
            ).lstrip(),
            encoding="utf-8",
        )
        (self.stub_bin / "pnpm").chmod(0o755)

    def run_pre_commit(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.stub_bin}:{env['PATH']}"
        return run("bash", str(self.repo / ".githooks" / "pre-commit"), cwd=self.repo, check=False, env=env)

    def test_still_runs_gitleaks_then_biome_after_sourcing_token_gate(self) -> None:
        self.write("src/app.ts", "export const x = 1;\n")
        result = self.run_pre_commit()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.biome_marker.exists())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_lifecycle_gate_policy.PreCommitHookTests -v`
Expected: FAIL — `pre-commit` currently calls `pnpm exec biome ...` directly, which
the stub handles fine, so this specific test may actually already pass. Confirm by
running it; if it already passes, that's fine (it's primarily a regression guard for
Step 3's change) — the important check is Step 4, after the change, still passes.

- [ ] **Step 3: Implement the change**

Edit `skills/lifecycle-gate-policy/assets/githooks/pre-commit`. Current lines 7-10:

```sh
# runtime verification belongs to premerge, static verification to pre-push.
set -euo pipefail

# 1. gitleaks — staged diff secret scan (unconditional: secrets must never land)
```

Replace with:

```sh
# runtime verification belongs to premerge, static verification to pre-push.
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
. "$REPO_ROOT/scripts/token-gate.sh"

# 1. gitleaks — staged diff secret scan (unconditional: secrets must never land)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_lifecycle_gate_policy.PreCommitHookTests -v`
Expected: PASS.

Then run the full file to confirm no regression:

Run: `python3 -m unittest tests.test_lifecycle_gate_policy -v`
Expected: 16 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/lifecycle-gate-policy/assets/githooks/pre-commit tests/test_lifecycle_gate_policy.py
git commit -m "$(cat <<'EOF'
fix(lifecycle-gate-policy): source token-gate.sh from pre-commit

pre-commit calls `pnpm exec biome` directly, which hits the same PATH
problem pre-push had under a non-interactive GUI git client. Source
token-gate.sh (already applied by pre-push) so its nvm PATH fallback
runs here too; pre-commit doesn't call any token_gate_* function itself.
EOF
)"
```

---

### Task 3: full regression run and global skill deploy

**Files:**
- None modified — validation and deployment only.

**Interfaces:**
- Consumes: everything from Task 1 and Task 2 (both already committed).
- Produces: nothing further.

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m unittest tests.test_lifecycle_gate_policy -v`
Expected: 16 tests, all PASS.

- [ ] **Step 2: Confirm the working tree is clean**

Run: `git status --short skills/lifecycle-gate-policy`
Expected: empty output (everything from Task 1/2 already committed).

- [ ] **Step 3: Deploy the updated skill globally**

Run: `scripts/deploy-skills.sh lifecycle-gate-policy`
Expected: exits 0; prints the deployed hash/commit for both `~/.agents/skills/lifecycle-gate-policy` and `~/.codex/skills/lifecycle-gate-policy`, with no `FAIL`/`ABORT` lines.

- [ ] **Step 4: Spot-check the deployed copy**

Run: `diff skills/lifecycle-gate-policy/assets/scripts/token-gate.sh ~/.agents/skills/lifecycle-gate-policy/assets/scripts/token-gate.sh`
Expected: no output (files identical).

No commit in this task — it only runs already-committed code and a deploy step that writes outside the repo.

**Note on `audit.py`:** the design spec's testing section mentions running
`skills/lifecycle-gate-policy/scripts/audit.py` against a fixture repo. It's
intentionally not a step here: `audit.py` hashes the *live* `assets/` directory
at run time (see `skills/lifecycle-gate-policy/scripts/audit.py:29-32`), so any
repo copy of the newly-fixed files matches automatically — there's no separate
hash registry to refresh. Running it would require assembling a fully-equipped
fixture (`.githooks/pre-push`, `post-checkout`, `scripts/premerge.sh`, a
`package.json` with the full script contract) that exercises none of this
plan's actual change; that belongs with a future "re-apply to a target repo"
task, not this one.
