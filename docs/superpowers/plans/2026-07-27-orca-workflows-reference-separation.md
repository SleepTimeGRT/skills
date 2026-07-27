# Orca Workflows Reference Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Orca worker-selection instructions compact while preserving source-backed model decisions and correcting the documentation defects found during review.

**Architecture:** Existing `model-selection.md` and `models/*.md` files remain operational entry points. Cross-provider rationale moves to `references/model-selection.md`, provider evidence moves to mirrored `references/models/*.md`, and unrelated adapter/logging defects are corrected in their owning documents.

**Tech Stack:** Markdown, shell command examples, Codex CLI model catalog, GitHub CLI/API, Atlassian connector capabilities

## Global Constraints

- Operational documents contain only selection, launch, escalation, and required runtime checks.
- Evidence lives in exactly one reference document and is loaded only for audits, mapping changes, or re-validation.
- Provider effort labels are not calibrated against one another by name.
- Codex `ultra` is not used for Orca workers because Orca already owns delegation.
- Preserve `PASS`, `WARN`, `FAIL`, and `SKIP` distinctions and do not weaken command safety semantics.
- Do not run deployment, release, migration, seed, wipe, or external-write commands for validation.

---

### Task 1: Split Model Evidence from Operational Guidance

**Files:**
- Create: `orca-workflows/references/model-selection.md`
- Create: `orca-workflows/references/models/codex.md`
- Create: `orca-workflows/references/models/claude-code.md`
- Create: `orca-workflows/references/models/agy.md`
- Modify: `orca-workflows/model-selection.md`
- Modify: `orca-workflows/models/codex.md`
- Modify: `orca-workflows/models/claude-code.md`
- Modify: `orca-workflows/models/agy.md`

**Interfaces:**
- Consumes: the approved design at `docs/superpowers/specs/2026-07-27-orca-workflows-reference-separation-design.md`
- Produces: compact operational documents with direct links to evidence references

- [ ] **Step 1: Create the cross-provider reference**

Write `references/model-selection.md` with:

- evidence-loading rule;
- ownership boundaries;
- no cross-provider effort-name calibration;
- current tier decisions and their confidence;
- benchmark comparison rules;
- re-verification triggers covering provider releases, CLI catalogs, pricing, and capability changes;
- a dated decision log recording the 2026-07-27 separation and effort corrections.

- [ ] **Step 2: Create provider evidence references**

Move, without duplicating, the following:

- Codex pricing, benchmark scores, CodeRabbit interpretation, effort support/defaults, smoke history, and unresolved Luna smoke into `references/models/codex.md`;
- Claude release history, benchmark discussion, effort trade-offs, automatic fallback evidence, advisor limitations, and smoke/version facts into `references/models/claude-code.md`;
- agy pricing, benchmark discussion, quota caveats, BrowserMCP evidence, and smoke history into `references/models/agy.md`.

- [ ] **Step 3: Compact the operational model-selection document**

Keep:

- tier definitions;
- explicit pinning invariant;
- concise default mapping;
- escalation conditions;
- provider preference;
- the Computer Use skeptical-cross-check routing stripped of benchmark prose;
- direct reference links.

Set Codex High Risk to Sol `high`, raised to `xhigh` for security/final gates with asymmetric miss cost. Remove `high = cost floor`, the context-capacity/MRCR comparison, and long research paragraphs.

- [ ] **Step 4: Correct and compact provider launch documents**

For Codex:

- document model-specific current effort values;
- exclude `ultra` from Orca worker launch;
- describe `workspace-write` and `never` accurately;
- set Terra `medium`, Luna `low`, and Sol `high`/conditional `xhigh`;
- allow Terra for bounded triage but not final high-risk review;
- give a clear Routine review escalation path.

For Claude and agy:

- retain safety-critical launch flags and runtime checks;
- replace evidence paragraphs with direct reference links;
- keep unresolved pre-launch checks operationally visible.

- [ ] **Step 5: Verify Task 1**

Run:

```bash
rg -n "minimal|high = cost floor|캘리브레이션 기준점|1M 토큰 네이티브 컨텍스트로|웹 리서치|\\$[0-9]" \
  orca-workflows/model-selection.md orca-workflows/models
```

Expected: no stale effort value, cross-provider calibration, invalid context comparison, research narration, or pricing detail in operational documents.

Run:

```bash
rg -n "references/(model-selection|models/(codex|claude-code|agy))\\.md" \
  orca-workflows/model-selection.md orca-workflows/models
```

Expected: every operational model document has its direct reference link.

### Task 2: Correct Tracker and Spawn-Failure Documentation

**Files:**
- Modify: `orca-workflows/issue-trackers/selection.md`
- Modify: `orca-workflows/issue-trackers/github.md`
- Modify: `orca-workflows/issue-trackers/jira.md`
- Modify: `orca-workflows/spawn-failures.md`

**Interfaces:**
- Consumes: current adapter operation names from `issue-trackers/selection.md`
- Produces: portable adapter guidance and valid worktree-safe JSONL logging

- [ ] **Step 1: Make GitHub native hierarchy primary**

Update `github.md` so `get_issue_type` uses native issue type when available and falls back to documented labels/body conventions. Make `list_children` use native sub-issues via `gh api repos/{owner}/{repo}/issues/<id>/sub_issues`, with body search only as a legacy fallback.

- [ ] **Step 2: Correct dependency and closing-keyword semantics**

Treat only explicit dependency language such as `Blocked by` or `Depends on` as ordering edges; `Refs` is informational. Make closing-keyword matching require an exact issue number boundary so `#12` cannot match `#123`.

- [ ] **Step 3: Make tracker selection extensible**

State that adding Linear requires:

- a `linear.md` adapter;
- a backend entry in selection step 3;
- identifier/onboarding disambiguation because Jira and Linear may both use `PROJECT-123` keys.

- [ ] **Step 4: Remove the Claude-specific Jira namespace**

Describe required Atlassian capabilities by operation (`get issue`, `search with JQL`, `list transitions`, `transition`, `add comment`) and require the current runtime to map those capabilities to its installed connector tools.

- [ ] **Step 5: Encode spawn-failure JSON safely**

Replace interpolated `printf` JSON with `jq -cn --arg`/`--argjson` so quotes, backslashes, and newlines produce valid JSONL. Keep directory mode `700`, file mode `600`, append-only behavior, and the same fields.

- [ ] **Step 6: Verify Task 2**

Run:

```bash
rg -n "네이티브 epic/task 계층이 없다|Refs #N|mcp__claude_ai_Atlassian|linear\\.md.*변경은 필요 없다|printf '\\{\"ts\"" \
  orca-workflows
```

Expected: no matches.

Run:

```bash
rg -n "sub_issues|Depends on|jq -cn|Atlassian.*capabil|Linear" \
  orca-workflows/issue-trackers orca-workflows/spawn-failures.md
```

Expected: the corrected native hierarchy, dependency, connector, JSON encoding, and Linear rules are present.

### Task 3: Cross-Document Consistency and Markdown Validation

**Files:**
- Modify as needed: all files changed in Tasks 1 and 2

**Interfaces:**
- Consumes: all operational/reference documents from Tasks 1 and 2
- Produces: a consistent, link-complete documentation set

- [ ] **Step 1: Compare mapping rows**

Verify these exact assignments appear consistently:

- High Risk Codex: Sol `high`, conditional `xhigh`;
- Routine Codex: Terra `medium`;
- Simple Codex: Luna `low`;
- Codex `ultra`: supported where the catalog exposes it but excluded from Orca workers.

- [ ] **Step 2: Check relative links**

Resolve every local Markdown target under `orca-workflows/` and confirm it exists. Links from `models/*.md` to provider references use `../references/models/<provider>.md`; the root model-selection link uses `references/model-selection.md`.

- [ ] **Step 3: Check reference ownership**

Search operational documents for prices, benchmark names/scores, dated web-research narration, and long provider comparisons. Move any remaining evidence-only content to its owning reference.

- [ ] **Step 4: Run repository checks**

Run:

```bash
git diff --check
rg -n "TBD|TODO|PLACEHOLDER" orca-workflows
git status --short
```

Expected: no whitespace errors, no placeholders introduced, and only intended files changed.

- [ ] **Step 5: Review the final diff**

Run:

```bash
git diff --stat
git diff -- orca-workflows
```

Expected: operational model documents are materially shorter, references contain the displaced evidence, and adapter/logging corrections are scoped to their owning documents.
