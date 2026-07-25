# Policy rationale — decision record (2026-07-21)

Why each rule in this policy exists. Claims from external
sources carry provenance: **[fetched]** = page read directly during the research
session (2026-07-21); **[snippet]** = search-result summary only.

## Operating profile this policy assumes

Solo developer, single device, agent-driven development, private GitHub repos on
the free plan (no branch-protection required checks), remote CI deliberately
removed for cost (see `remote-ci-economics`). Verification is entirely local.
Under a different profile — a team relying on required checks — several rules
below would flip; do not transplant this policy without re-checking the profile.

## Three-layer gates: static at push, heavy at merge

- Industry consensus layers checks by speed: pre-commit in seconds
  ("Make the quality checks really fast. Like 10 seconds fast!" — Thoughtworks,
  2020-01-13 [fetched]; "milliseconds in pre-commit, slower in CI" — Witowski,
  2023-11-28 [fetched]). That consensus assumes CI as the heavy backstop; with CI
  removed, the heavy tier must move to local merge-time, not disappear.
  Trunk-based literature agrees the highest-throughput setups verify commits
  *before* they land on trunk (trunkbaseddevelopment.com [fetched]).
- Agent-harness vendors (Codex, Copilot coding agent, Cursor) share one shape:
  the agent runs tests/lints itself while working, and a separate gate sits
  before merge. This policy is that shape with local substitutes: local harness
  instead of a vendor sandbox, local premerge instead of remote CI.
- Hooks are deterministic where prompts are advisory (Claude Code best-practices
  docs [fetched]: CLAUDE.md compliance is partial; hooks "guarantee the action
  happens") — hence gitleaks/format live in hooks, not instructions.
- Caveat recorded honestly: no primary source prescribes the exact
  "static-only pre-push / tests at merge" split. It is a reasoned extension of
  the speed-layering consensus, chosen because push feedback must stay fast and
  the un-skippable gate belongs where code enters the default branch.

## Self-merge allowed, gate-protected

- Vendor landscape (research 2026-07-21): GitHub is the only vendor that *hard-blocks*
  an agent approving/merging its own PR (Copilot cloud agent docs [fetched]);
  Devin/Cursor/Anthropic recommend human review without enforcing it; OpenAI
  publicly pushes review toward agent-to-agent (harness-engineering post
  [snippet]). Empirically, agentic PRs already merge with minimal reviewer
  interaction in the wild (arXiv 2605.22534, 2026-05-21 [fetched]).
- "A second human must approve" is a team norm that does not transfer to a solo
  operator — it relocates the bottleneck onto the only human. What transfers is
  the *reason* behind GitHub's rule: the author must not control the gate that
  judges it.
- Observed failure modes that motivate the mechanical PROTECTED check: agents
  removing tests or skipping lint steps to pass CI (GitHub blog, 2026-05-07
  [fetched]); reward hacking of the measuring function (o3 example [snippet]);
  same-model review sharing correlated blind spots (Vaughan, 2026-05-24
  [fetched]) — mitigated here by fresh-context and a skeptical review prompt,
  not by cross-provider separation (this repo's `/advisor` shows same-provider
  review is effective too).
- "Each PR green ≠ the combination is coherent" (ctx.rs merge-queue-for-agents
  [snippet]): hence premerge requires the branch to contain latest origin/main,
  merges are serialized, and periodic architecture reviews watch cross-PR drift.
- User decision (2026-07-21): when a bad change ships, the response is to improve
  verify/e2e/review — never to revoke self-merge. A review pass is required
  for code changes only; docs-only PRs pass on verify(+e2e) to keep trivial-PR
  throughput and token cost sane.

## Why canonical copies instead of a shared runtime dependency

Three repos previously carried three drifting variants of the same token-gate
script and three different pre-push semantics. Copies with hash-audit keep each
repo self-contained (a generated repo must never depend on this skills repo at
runtime — repository rule) while making drift visible and reversible: improve
the template here, re-apply everywhere, or upstream a repo's local improvement.

## E2E skip for diff-provably-inert changes (2026-07-25)

- Motivating problem: a diff can be one file with no possible runtime effect (e.g. a
  `.gitignore`-only change) while `premerge.sh` still runs the full e2e suite
  unconditionally — no test-impact analysis or selective run exists in the e2e runners
  this policy targets (Playwright et al.), and `token_gate_capture` only compacts output,
  it never skips execution. That makes a trivial chore PR cost the same as a feature PR.
- `E2E_EXEMPT_REGEX` closes this the same way `REVIEW_EXEMPT_REGEX` already does:
  diff-based, opt-in (empty default = current behavior, no repo is affected until it
  sets a pattern), and skip only when *every* changed path matches — one non-matching
  path anywhere in the diff forces the normal run.
- Kept independent from `REVIEW_EXEMPT_REGEX` on purpose: e2e-skippable and
  review-skippable are different claims about a diff (an e2e suite may not exercise a
  path that a human reviewer still cares about, or vice versa). A repo that wants both
  skipped together points both regexes at the same pattern; the script does not merge
  them.
- Safety argument is mechanical, not a claim about agent good behavior:
  `scripts/premerge.conf.sh` — where `E2E_EXEMPT_REGEX` lives — is itself inside
  `PROTECTED_REGEX` (gate-integrity check, stage 2). An agent cannot widen the exemption
  and have that wider exemption apply within the same PR; widening it always routes to
  a human merge first.

## Superseded arrangements (for archaeology)

- medicount: husky + `verify:ci` stamp gate in pre-push (stamp made sense when
  pre-push demanded the *full* chain; obsolete once pre-push went static-only).
- samhaengsi: tests in pre-push + main-agent-only merges via `pre-merge-local.sh`
  (its "un-fakeable final backstop" role is replaced by premerge.sh + the
  PROTECTED mechanical check).
- goldrush: full `pnpm verify` on every push; subagent self-merge without a
  merge-time gate (PR #501 had moved CI verify into pre-push; this policy moves
  the heavy tier onward to merge-time and adds the review requirement).
