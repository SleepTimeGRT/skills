---
source: docs/references/anthropic-building-skills-for-claude.pdf
title: The Complete Guide to Building Skills for Claude
publisher: Anthropic
summarized: 2026-08-12
---

# The Complete Guide to Building Skills for Claude — working summary

Distilled from the 33-page PDF in this directory so agents don't have to re-read it every
session. **Every section carries a page anchor** (`p. 10`, `pp. 15–17`) — when the exact wording
matters, read those pages of the PDF with `Read(pages: "...")` instead of trusting this summary.
The PDF is canonical; this file is an index plus the mechanical rules reproduced closely enough to
act on.

**Read this before authoring or substantially changing a skill.** The guide is this repo's north
star for skill design, testing, and iteration.

## Scope caveats for this repo (not from the guide)

- **Chapter 4 "Distribution and sharing" (pp. 18–20) is Claude.ai/API-surface-specific.** Zip →
  Settings > Capabilities > Skills, `container.skills`, `/v1/skills`, workspace-wide admin deploy —
  none of that is this repo's path. Here, skills ship via `scripts/deploy-skills.sh` into
  `~/.agents/skills/` (see AGENTS.md "Skill deployment"). Read Chapter 4 for the standard's shape,
  not for our deploy procedure.
- **Dated snapshots stay dated.** "Current distribution model (January 2026)" (p. 19), "org-level
  skills shipped December 18, 2025" (p. 19). Don't restate these as present-tense fact.
- **`allowed-tools` (Ref B, p. 31) is listed as a standard optional field, but AGENTS.md treats its
  behavior details as Claude-Code-only.** For portable skills in this repo, don't depend on it.
- The guide's own hedge on metrics (p. 9): the quantitative targets are "aspirational … rough
  benchmarks rather than precise thresholds," with an acknowledged element of vibes-based
  assessment.

## Ch. 1 Fundamentals (pp. 4–6)

A skill is a folder: `SKILL.md` (required), `scripts/`, `references/`, `assets/` (all optional).

**Progressive disclosure — three levels** (p. 5):

1. **YAML frontmatter** — always in the system prompt. Just enough for Claude to know *when* to
   load the skill.
2. **SKILL.md body** — loaded when Claude judges the skill relevant. Full instructions.
3. **Linked files** — bundled files Claude navigates to only as needed.

Other principles (p. 5): **composability** (multiple skills load at once — don't assume yours is
the only capability), **portability** (same skill across Claude.ai / Claude Code / API, given the
environment supports its dependencies).

MCP vs skills (pp. 5–6): MCP = connectivity, "what Claude *can* do"; skills = knowledge, "how
Claude *should* do it." Kitchen analogy: MCP is the kitchen, skills are the recipes.

## Ch. 2 Planning and design (pp. 7–13)

### Start with use cases (p. 8)

Identify 2–3 concrete use cases *before* writing anything. A good definition names Use Case /
Trigger / Steps / Result. Ask: what does the user want to accomplish; what multi-step workflow does
it require; which tools (built-in or MCP); what domain knowledge should be embedded.

Three observed categories (pp. 8–9): **1. Document & asset creation** (embedded style guides,
templates, quality checklists), **2. Workflow automation** (step-by-step with validation gates,
iterative refinement loops), **3. MCP enhancement** (sequenced MCP calls, error handling for common
MCP issues).

### Success criteria (p. 9)

Quantitative: triggers on ~90% of relevant queries (run 10–20 test queries, count auto-load vs
explicit invocation); completes the workflow in X tool calls (compare with/without the skill —
tool calls and total tokens); 0 failed API calls per workflow.
Qualitative: users don't need to prompt for next steps; workflows complete without user correction
(run the same request 3–5 times, compare structure/quality); consistent results across sessions.

### Technical requirements (p. 10) — the hard rules

- `SKILL.md` **exactly** that, case-sensitive. `SKILL.MD` / `skill.md` are rejected.
- Folder name kebab-case: `notion-project-setup` ✅ — no spaces, no underscores, no capitals.
- **No `README.md` inside the skill folder.** All docs go in `SKILL.md` or `references/`. (A
  repo-level README for human visitors is separate and still wanted.)
- `name` (required): kebab-case, no spaces/capitals, should match the folder name.
- `description` (required): **MUST include both what the skill does AND when to use it (trigger
  conditions)**; under 1024 chars; no XML angle brackets (`<` `>`); include specific tasks users
  might say; mention file types if relevant.
- Optional: `license`, `compatibility` (1–500 chars, environment requirements), `metadata` (free
  key-value; suggested author, version, mcp-server).
- **Security restrictions** (p. 11, Ref B p. 31): forbidden in frontmatter — XML angle brackets;
  code execution in YAML (safe YAML parsing); skill names using the reserved "claude" or
  "anthropic" prefix. Why: frontmatter lands in Claude's system prompt, so malicious content could
  inject instructions.

### The description field (pp. 11–12) — highest-value pages in the guide

Structure: `[What it does] + [When to use it] + [Key capabilities]`.

Good — specific, actionable, with real trigger phrases:

```
description: Analyzes Figma design files and generates developer handoff documentation.
Use when user uploads .fig files, asks for "design specs", "component documentation", or
"design-to-code handoff".

description: Manages Linear project workflows including sprint planning, task creation, and
status tracking. Use when user mentions "sprint", Linear tasks, "project planning", or asks
to "create tickets".
```

Bad:

```
description: Helps with projects.                       # too vague
description: Creates sophisticated multi-page ...       # missing triggers
description: Implements the Project entity model ...    # too technical, no user triggers
```

### Writing instructions (pp. 12–13)

Recommended body structure (p. 12): `# Skill Name` → `## Instructions` → `### Step N: [...]` with a
clear explanation, example command, and expected output per step → `## Examples` (user says X →
actions → result) → `## Troubleshooting` (error → cause → solution).

Best practices (p. 13):

- **Be specific and actionable.** ✅ "Run `python scripts/validate.py --input {filename}` to check
  data format. If validation fails, common issues include: …" ❌ "Validate the data before
  proceeding."
- **Include error handling** — a `## Common Issues` section with concrete symptoms and numbered
  fixes.
- **Reference bundled resources explicitly**: "Before writing queries, consult
  `references/api-patterns.md` for: rate limiting guidance, pagination patterns, error codes."
- **Use progressive disclosure**: keep `SKILL.md` on core instructions; move detail to
  `references/` and link to it.

## Ch. 3 Testing and iteration (pp. 14–17)

Rigor levels (p. 15): manual testing in Claude.ai (fast, no setup) → scripted testing in Claude
Code (repeatable across changes) → programmatic testing via the skills API (evaluation suites).
Match the level to who uses the skill.

**Pro tip (p. 15): iterate on a single task before expanding.** The most effective skill creators
iterate on one challenging task until Claude succeeds, then extract the winning approach into a
skill — this leverages in-context learning and gives faster signal than broad testing.

### The three test categories

**1. Triggering tests (p. 15)** — does the skill load at the right times? Cases: triggers on
obvious tasks ✅, triggers on paraphrased requests ✅, does NOT trigger on unrelated topics ❌.
Written as explicit `Should trigger:` / `Should NOT trigger:` phrase lists.

**2. Functional tests (p. 16)** — does the skill produce correct outputs? Cases: valid outputs
generated, API calls succeed, error handling works, edge cases covered. Written Given/When/Then:

```
Test: Create project with 5 tasks
Given: Project name "Q4 Planning", 5 task descriptions
When: Skill executes workflow
Then:
  - Project created in ProjectHub
  - 5 tasks created with correct properties
  - All tasks linked to project
  - No API errors
```

**3. Performance comparison (p. 16)** — does the skill beat the no-skill baseline? Compare
without-skill (e.g. 15 back-and-forth messages, 3 failed API calls requiring retry, 12,000 tokens)
against with-skill (automatic workflow execution, 2 clarifying questions, 0 failed calls, 6,000
tokens).

### Iteration on feedback (p. 17)

| Signal | Symptoms | Fix |
| --- | --- | --- |
| Undertriggering | Skill doesn't load when it should; users enable it manually; support questions about when to use it | Add detail and nuance to the description, including keywords for technical terms |
| Overtriggering | Loads for irrelevant queries; users disable it; confusion about purpose | Add negative triggers, be more specific |
| Execution issues | Inconsistent results; API call failures; user corrections needed | Improve instructions, add error handling |

`skill-creator` (pp. 16–17) can generate a first draft, review for vague descriptions / missing
triggers / structural problems, flag over- and under-triggering risk, and suggest test cases. Note
the guide's own caveat: **skill-creator designs and refines skills but does not execute automated
test suites or produce quantitative evaluation results.**

## Ch. 5 Patterns and troubleshooting (pp. 21–27)

**Framing (p. 22):** problem-first ("I need to set up a project workspace" → the skill orchestrates
the right calls in the right sequence) vs tool-first ("I have Notion MCP connected" → the skill
teaches optimal workflows). Most skills lean one way; knowing which helps pick the pattern.

Five patterns (pp. 22–24), each with an example skeleton in the PDF:

1. **Sequential workflow orchestration** — multi-step processes in a fixed order. Explicit step
   ordering, dependencies between steps, validation at each stage, rollback instructions.
2. **Multi-MCP coordination** — workflows spanning services. Clear phase separation, data passing
   between MCPs, validation before the next phase, centralized error handling.
3. **Iterative refinement** — quality improves with iteration. Explicit quality criteria,
   validation scripts, and *knowing when to stop iterating*.
4. **Context-aware tool selection** — same outcome, different tools by context. Decision tree,
   fallback options, transparency about the choice made.
5. **Domain-specific intelligence** — the skill adds expertise beyond tool access. Domain rules
   embedded in logic, compliance before action, audit trail.

### Troubleshooting (pp. 25–27)

- **Won't upload**: `SKILL.md` misnamed (case-sensitive); invalid frontmatter (missing `---`
  delimiters, unclosed quotes); invalid skill name (spaces or capitals).
- **Doesn't trigger**: revise the description. Checklist: too generic? does it include phrases
  users actually say? does it mention relevant file types? **Debugging technique: ask Claude "When
  would you use the [skill name] skill?" — it will quote the description back; adjust from what's
  missing.**
- **Triggers too often**: add negative triggers ("Do NOT use for simple data exploration (use
  data-viz skill instead)"), be more specific, clarify scope.
- **MCP connection issues**: verify the server is connected; check auth; test the MCP directly
  without the skill (if that fails, it's not a skill problem); verify tool names (case-sensitive).
- **Instructions not followed**: (a) instructions too verbose → concise bullets/numbered lists,
  detail to separate files; (b) instructions buried → critical items at the top, `## Important` /
  `## Critical` headers, repeat key points; (c) ambiguous language → ❌ "Make sure to validate
  things properly" vs ✅ "CRITICAL: Before calling create_project, verify: project name is
  non-empty; at least one team member assigned; start date is not in the past". **Advanced: for
  critical validations, bundle a script that performs the checks programmatically — code is
  deterministic, language interpretation isn't.** (d) model "laziness" → explicit encouragement
  ("take your time", "quality over speed", "do not skip validation steps"); the guide notes this
  works better in user prompts than in SKILL.md.
- **Large context issues (p. 27)**: symptoms are slowness / degraded responses. Causes: skill
  content too large, too many skills enabled, everything loaded instead of progressively disclosed.
  Fixes: move detail to `references/` and link; **keep `SKILL.md` under 5,000 words**; reconsider
  if more than 20–50 skills are enabled simultaneously; group related capabilities into skill
  "packs".

## Reference A: Quick checklist (p. 30)

Reproduced whole — directly usable as a pre-merge checklist.

**Before you start**
- [ ] Identified 2–3 concrete use cases
- [ ] Tools identified (built-in or MCP)
- [ ] Reviewed this guide and example skills
- [ ] Planned folder structure

**During development**
- [ ] Folder named in kebab-case
- [ ] `SKILL.md` file exists (exact spelling)
- [ ] YAML frontmatter has `---` delimiters
- [ ] `name` field: kebab-case, no spaces, no capitals
- [ ] `description` includes WHAT and WHEN
- [ ] No XML tags (`<` `>`) anywhere
- [ ] Instructions are clear and actionable
- [ ] Error handling included
- [ ] Examples provided
- [ ] References clearly linked

**Before upload**
- [ ] Tested triggering on obvious tasks
- [ ] Tested triggering on paraphrased requests
- [ ] Verified doesn't trigger on unrelated topics
- [ ] Functional tests pass
- [ ] Tool integration works (if applicable)
- [ ] Compressed as .zip file *(Claude.ai upload path — not this repo's deploy path)*

**After upload**
- [ ] Test in real conversations
- [ ] Monitor for under/over-triggering
- [ ] Collect user feedback
- [ ] Iterate on description and instructions
- [ ] Update version in metadata

## Ch. 6 Resources (p. 29) and Reference C (p. 32)

Official: Best Practices Guide, Skills Documentation, API Reference, MCP Documentation. Blog posts:
Introducing Agent Skills; Equipping Agents for the Real World; Skills Explained; How to Create
Skills for Claude; Building Skills for Claude Code; Improving Frontend Design through Skills.
Examples: `anthropics/skills` (public repo), document skills (PDF/DOCX/PPTX/XLSX), the Partner
Skills Directory. Bug reports go to `anthropics/skills/issues`.
