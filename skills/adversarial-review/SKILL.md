---
name: adversarial-review
description: "Run an adversarial review loop on an artifact (plan, spec, design, agent file, skill, CLAUDE.md). Dispatches reviewer agents to find issues, a triage agent to synthesize and route, and a fixer agent to apply changes. Loops until clean, then promotes to opus for final verification. Use this skill whenever you need rigorous validation of a written artifact, when reviewing designs before implementation, when checking specs that AI agents will consume, or when the user asks to review, validate, stress-test, or audit a document. Even if the user just says 'review this' or 'check this for issues', this skill applies."
user-invocable: true
argument-hint: "[subcommand] [args] — run <ref> [path], create-default (author mode), or just [artifact-path] for the full loop"
---

# Adversarial Review

An adversarial review loop that validates artifacts through multiple independent reviewer agents, synthesized by a triage agent, with fixes applied by a dedicated fixer agent.

The skill ships with three default reviewers (coherence, design, detail) and supports user-supplied reviewers via configuration or ad-hoc invocation. Reviewer agents declare what they check and how they report; the loop's contract is enforced on the consumer side through a semantic audit step before pool composition.

## Glossary

- **`<skill-directory>`**: the directory containing this `SKILL.md`. In the claude-materia source checkout this is `<repo-root>/skills/adversarial-review/`; at runtime under a plugin install, it resolves to the plugin's installed skill path (e.g., `~/.claude/plugins/cache/claude-materia/claude-materia/<version>/skills/adversarial-review/`). **Skill content only** — defaults, system agents, SKILL.md itself. The plugin author writes here; the runtime does not.
- **`<plugin-data-dir>`**: the user-state directory for this plugin, resolves to `~/.claude/plugins/data/claude-materia-claude-materia/`. This is where the runtime writes — audit cache, sessions, any other per-user accumulating state. Survives plugin updates (Claude Code preserves user-data across version bumps). The directory is created on first write if absent.

The split matters: skill content (`<skill-directory>`) is read-only at runtime under a plugin install, and user state (`<plugin-data-dir>`) is the only writable location the skill should target. Mixing the two breaks plugin-update semantics and pollutes the install.

## Subcommands

- `/adversarial-review [artifact-path]` — Run the full review loop (default). Path is optional — if omitted, infer the artifact from conversation context. If context is insufficient, ask.
- `/adversarial-review run <ref> [artifact-path]` — Single-pass: dispatch one reviewer agent against the artifact in scaffolded mode. No loop, no triage, no fixer. Useful for rapid iteration during artifact development. `<ref>` resolves per the rules in **Pool sources and namespacing**.
- `/adversarial-review create-default` — Author-mode subcommand for skill authors only. Walks the author through guided creation of a new default reviewer. Available only when cwd is a claude-materia source checkout. See **create-default (author mode)** below.

## Pool sources and namespacing

The skill discovers reviewer agents from three categories of source. All sources are additive — each contributes candidates that go through the audit pipeline.

| Source | Namespace | Trust | When |
|---|---|---|---|
| Bundled defaults at `<skill-directory>/defaults/reviewers/` | `default` | Trusted (skip semantic audit) | Always |
| Environment-configured paths | `env` | Audited | Always (if env declares any) |
| Invocation-flag paths via `--reviewers <ref>` | `override` | Audited | Per invocation |
| Confirmation-time additions | `manual` | Audited | Per session, during confirmation |

`~/.claude/agents/` is **not** auto-scanned. It serves only as a search path for name resolution when the user explicitly references an agent by bare name.

### Reference resolution rules (`<ref>`)

When a user supplies an agent reference (via `--reviewers <ref>`, confirmation-time addition, or `run <ref>`), the skill interprets it per these rules in order:

| Pattern | Resolution |
|---|---|
| Starts with `/` | Absolute path |
| Starts with `./` or `../` | Cwd-relative path |
| Starts with `~/` | Home-relative path |
| Contains `/` (anywhere else) | Treated as path |
| Starts with `<known-namespace>:` (default, env, override, manual) | Namespace-prefixed reference; name resolves within that source's discovered candidates. **If a colon is present but the prefix is not a known namespace, it is a hard error** — do not fall through. |
| Otherwise (bare name) | Resolved via traversal of `~/.claude/agents/` for a matching `*.md` file (filename match) |

A path can resolve to a file (single-agent source) or directory (multi-agent source, non-recursive walk).

### Environment configuration

If `~/.claude/env/index.md` exists and declares `adversarial-review.reviewers_dir` (a path or list of paths), those paths contribute candidates with namespace `env`. If not declared, no env-configured pool exists.

Env-declared paths get the same edge-case handling as runtime-resolved references:
- Path doesn't exist → warn at discovery, exclude, continue
- Path is a file (not directory) → treat as single-file source
- Path is empty directory → warn ("env declares X but found no `*.md` files"), continue
- Malformed YAML value → warn and skip that entry
- All warnings surfaced at confirmation, so silent zero-contribution is impossible

### Namespace display

Internal references (orchestrator bookkeeping, output filenames `<namespace>__<name>-output.md`, audit log keys) use the full namespaced form. User-facing display uses shortest-unambiguous form: short name when unique across the discovered pool, full namespaced form when collision exists. Same pattern as Git branch shorthand.

Within `manual`, duplicate references (same agent supplied twice in one confirmation) are deduplicated. Cross-source collisions still coexist as distinct agents — the user composes their final pool at confirmation.

---

## Single-Pass Review (`run`)

`/adversarial-review run <ref> <artifact-path>`

Scaffolded single-reviewer dispatch for rapid iteration during artifact development. Calling convention:

1. Resolve `<ref>` per the resolution rules above (path or namespace-prefixed or bare name).
2. Read the artifact. Build `ARTIFACT.md` (see Phase 1 Step 1 of the full loop — same procedure).
3. Run the audit pipeline against the resolved candidate (Step 1 + Step 2 of the audit pipeline; cache-hits avoid re-dispatch). If `<ref>` already corresponds to a discovered candidate from bundled defaults or env-configured pool, the existing audit verdict is reused; for bundled defaults the verdict is the auto-accept from trust-by-source.
4. Create a minimal flags file with: no user concerns, no session concerns. The user is not prompted for concerns in single-pass mode — to include specific concerns, use the full loop.
5. Dispatch the reviewer as a subagent with: the artifact, `ARTIFACT.md`, and the flags file.
6. Present findings to the user. No triage, no severity override, no fixer. The reviewer's raw output is the result.

Distinct from raw `Task` dispatch in that `run` performs the same Phase 1 setup the full loop does. Raw dispatch is always available for users who want no ceremony.

---

## Full Review Loop

### Phase 1: Session Setup

1. **Read the artifact and build `ARTIFACT.md`.**
   - Read the artifact at the given path.
   - Run the environment discovery protocol (see `## Environment`).
   - Inspect the artifact: structure, format, frontmatter, stated purpose, apparent audience.
   - Compose `ARTIFACT.md` — a profile of the artifact that every agent receives. Written to `review/ARTIFACT.md` when the session directory is created in step 4.

     ```markdown
     # Artifact Profile

     **Path:** [artifact path]
     **Format:** [markdown, YAML frontmatter + markdown, JSON, etc.]
     **Apparent purpose:** [what this artifact appears to be — a plan, spec, agent file, etc.]

     ## Environment source
     [One of:]
     - "Environment discovered at ~/.claude/env/index.md. Relevant entries: [list]. See below."
     - "Environment exists but no entries were relevant to this artifact. Reason: [why]."
     - "No environment found at ~/.claude/env/. Review proceeds on the artifact's own merits."
     - "Environment at ~/.claude/env/ appears misconfigured (index.md absent/unreadable). Warned user. Proceeding without."

     ## Structural constraints
     [If env provided spec checklists, read/write contracts, naming conventions, routing rules, or other structural requirements applying to this artifact, list them here.]

     ## Observations from inspection
     [Anything notable about the artifact that reviewers should be aware of.]
     ```

2. **Check version control.**
   - Detect VCS: jj first (`jj status`), then git (`git status`).
   - **jj available**: Create an initial change (`jj new -m "adversarial-review: checkpoint before review"`).
   - **git available**: Create an initial commit (`git add <artifact> && git commit -m "adversarial-review: checkpoint before review"`).
   - **No VCS**: Warn: "No version control detected. Changes cannot be easily reverted. Continue?" Wait for confirmation.

3. **Discover, audit, and recommend the pool.**

   The pool is built in three stages: discovery + audit (Stage A), recommendation (Stage B), and user confirmation (Stage C — see step 4). Stages A and B happen automatically; Stage C is interactive.

   **Stage A: Discovery + audit.** A four-step pipeline:

   ```
   Step 1: Pre-check (cheap, deterministic, runs on all candidates)
     - Walk all configured sources (bundled defaults, env paths, --reviewers paths).
     - For each *.md file: parse frontmatter, validate hard contract.
     - Hard rejects (excluded from pool):
       * Frontmatter doesn't parse as YAML
       * Missing or empty `name`
       * Empty prompt body
       * `precondition` references another agent by name in a runtime-dependency
         pattern (e.g., `after:<name>`, `requires:<name>` — innocuous prose
         mentions are not rejected)
       * `required: false` without a `trigger` (uninvokable)
     - Soft warnings (accepted with flag):
       * Missing `description`
       * Missing `precondition`
       * Unknown frontmatter fields (other than `role`, which is silently ignored)

   Step 2: Semantic audit (LLM-driven, with caching)
     - SKIP for candidates from <skill-directory>/defaults/reviewers/
       → verdict: accept (trusted: bundled default by repo convention)
     - RUN for all other candidates:
       a. Compute auditor_hash = SHA-256(<skill-directory>/agents/auditor.md)
       b. Compute agent_hash   = SHA-256(<candidate-file>)
       c. Cache lookup at audit-cache.json[auditor_hash][agent_hash]:
            HIT  → use cached verdict (counts as audit verdict per 2.3)
            MISS → dispatch auditor agent, write result to cache
       d. Apply verdict (accept or reject)

   Step 3: Soft warning attachment (warnings flagged for confirmation display)

   Step 4: Compile audit report
     - Write `review/agent-audit.md` with per-candidate verdicts and reasoning
     - Compute pre-audit summary: per-source candidate count and cache-miss count
   ```

   Cache file lives at `<plugin-data-dir>/audit-cache.json` (i.e., `~/.claude/plugins/data/claude-materia-claude-materia/audit-cache.json`). Top-level structure:

   ```json
   {
     "last_auditor_hash": "<auditor-content-hash>",
     "<auditor-content-hash>": {
       "<agent-content-hash>": {
         "verdict": "accept",
         "reasoning": "Evaluative purpose: strong — ...",
         "audited_at": "2026-04-26T14:32:11Z",
         "agent_name_at_audit": "coherence"
       }
     }
   }
   ```

   On session start, the orchestrator compares the current auditor.md hash to `last_auditor_hash`. If different, the audit report includes "auditor changed; full audit re-run" notice. The field is updated post-audit.

   **Stage B: Recommendation.** For each audit-cleared candidate, the skill applies judgment to produce a proposed pool:
   - Required agents (`required: true`) → recommend (subject to precondition check)
   - Optional agents (`required: false`) → recommend if `trigger` matches the artifact context
   - Cold-start preconditions: only recommend agents whose preconditions could be met on iteration 1

   Result: a proposed pool with per-agent reasoning ("Recommended because...", "Not recommended: trigger doesn't match").

4. **User confirmation (Stage C).**
   - Show the pre-audit summary, the proposed pool, and audit-cleared-but-not-recommended candidates.
   - User can:
     - Add a reference (path or bare name) — runs through Step 1 + Step 2 of the audit pipeline (with caching). Auditor's verdict shown inline; user can accept or override. For directory-form additions, a brief per-batch summary is shown before dispatch.
     - Remove (prune) any audit-cleared candidate from the pool — per-session decision, doesn't affect source files.
     - Accept the proposed pool.
   - Final pool is what the user confirms. After confirmation, the **pool source set is locked** for the rest of the session — no new agents discovered, audited, or added.

5. **Create the session directory.**
   - Path: `<plugin-data-dir>/sessions/<timestamp>-<artifact-slug>/` — sessions live in user state, not under the skill install. Create the parent `<plugin-data-dir>/sessions/` directory if absent.
   - Create subdirectories: `agents/`, `review/`, `review/iterations/`
   - Snapshot the resolved-and-confirmed pool into `sessions/<id>/agents/` using namespace-prefixed filenames (`default__coherence.md`, `manual__custom-thing.md`, etc.) — matches the output-file naming convention. The snapshot reflects the locked pool, not source directory contents.
   - Copy system agent files (triage, fixer, auditor) into `sessions/<id>/agents/` with their bare names (no namespace prefix; system agents have no source-namespace).
   - Create symlink: `sessions/<id>/artifact` → absolute path to the artifact
   - Create `review/accepted-risks.json` with initial content `[]`
   - Create `review/deferred-lows.json` with initial content `[]`. Schema: array of objects with fields `id` (string), `description` (string), `tier` (string: `"c"` or `"o"`), `iteration` (integer), `reason` (string).
   - Write the `ARTIFACT.md` composed in step 1 to `review/ARTIFACT.md`.
   - Write the audit report from Stage A to `review/agent-audit.md`.

6. **Write flags.**
   - Create `review/flags.md`:
     ```markdown
     # Review Flags

     > These are hints for reviewers. Review the entire artifact regardless of what is flagged here.

     ## User concerns
     [Transcribe any concerns the user raised in conversation]

     ## Session concerns
     [Note any concerns you (the orchestrator) have about the artifact]
     ```
   - Ask the user: "Any specific concerns you want reviewers to pay attention to?" Incorporate their response.

### Phase 2: The Review Loop

**Configuration:**
- `sonnet_max`: Maximum iterations for the cheap tier (default: 5, overridable via `--sonnet-max`)
- `opus_max`: Maximum iterations for the opus tier (default: 5, overridable via `--opus-max`)
- Current tier starts at `cheap` (sonnet for reviewers and fixer, opus for triage and auditor always)

**Iteration validity invariant:** An iteration is only valid if (a) each reviewer ran as an independent subagent — one Agent tool call per reviewer, never combined, and (b) triage ran as its own subagent and produced a `triage-output.json` file. An iteration where multiple review roles were performed by a single agent, or where the orchestrator evaluated the gate without a triage JSON, is structurally invalid regardless of the findings. This invariant exists because the orchestrator's incentive to compress increases as findings diminish — the structure must hold tightest when the temptation to shortcut is strongest.

**Pool source set is locked; pool membership may shift.** Once Phase 1 confirmation completes, no new agents are discovered, audited, or added. But within the locked source set, triage's `precondition_evaluations` may promote dormant candidates (those that didn't run in earlier iterations because their preconditions weren't met) into the active roster as the artifact evolves. This preserves the audit-cost invariant (no mid-loop LLM dispatches for new audits) without freezing the iteration-1 view of which agents apply.

**Each iteration:**

0. **Create the iteration directory.** `review/iterations/<N>/` before dispatching any agents.

1. **Dispatch reviewers.**
   - Iteration 1 (cold start): evaluate each reviewer's precondition individually against the cold-start state. Preconditions like "may be inconsistent" (coherence) are trivially met. Preconditions requiring prior verification (e.g., "internally consistent" for design/detail) are NOT met on cold start — exclude those reviewers. The coverage check (step 3) ensures excluded agents will run in a subsequent iteration once their preconditions are met.
   - Iteration 2+: dispatch only the agents listed in triage's `next_reviewers` from the previous iteration.
   - Each reviewer runs as a subagent (Agent tool) with: the artifact, `ARTIFACT.md`, the flags file, and previous triage output (if iteration 2+).
   - Reviewers are always independent and always dispatched in parallel. **Never combine multiple reviewer roles into a single agent call.**
   - Reviewers may emit free-form output — prose, structured lists, JSON, anything. Triage normalizes.
   - Model: current tier model (sonnet during cheap tier, opus during opus tier). Exception: triage always runs opus.
   - Save each reviewer's output to `review/iterations/<N>/<namespace>__<reviewer-name>-output.md`.

2. **Dispatch triage.**
   - After all reviewers complete, dispatch the triage agent (read `agents/triage.md` for its full spec) with:
     - All reviewer outputs from this iteration
     - Full iteration history (all prior triage outputs + fixer changelogs + user interventions)
     - All reviewer agent spec files from the session pool (for precondition evaluation and `severity_guidance` lookup)
     - The flags file
     - The accepted-risks file
   - Triage always runs on the most capable model (opus).
   - Triage emits its JSON output to `review/iterations/<N>/triage-output.json`. The schema is declared canonically in `agents/triage.md` — every finding has `source_trace` (one of `quote`/`region`/`synthesis`) and `interpretation_note`.

3. **Evaluate the gate (orchestrator responsibility).**
   - **Validity check**: verify that `review/iterations/<N>/triage-output.json` exists and contains valid JSON with a `gate_result` field. If missing, the iteration is invalid — go back and run triage. The orchestrator must never evaluate the gate without a triage JSON.
   - **Severity check**: read triage's `gate_result`. If `blocked`, continue to step 4.
   - **Coverage check** (orchestrator, not triage): has every reviewer agent in the pool run against the current artifact state and produced no medium+ findings? Check triage's `precondition_evaluations` — if any pool agent's precondition is `met` but that agent did not run this iteration, coverage is incomplete.
   - If severity passes but coverage fails: continue the loop. Triage's `next_reviewers` should already include the agents that need to run.
   - If both pass: the orchestrator appends any remaining low-severity findings to `review/deferred-lows.json` with `reason` set to `"gate passed with lows only"`. Then exit the loop (go to Phase 3 or Phase 4 depending on tier).

4. **Surface triage diagnosis to the user (if needed).**
   - Show: findings summary, gate result, diagnosis note, roster for next iteration.
   - If iteration >= 2: check the previous iteration's fixer changelog for `unable_to_resolve` entries. Present these to the user for decision.
   - If the user wants to mark findings as accepted risk: update `review/accepted-risks.json`.
   - **Abort protocol:** If the user aborts:
     1. Stop immediately.
     2. Do NOT revert VCS changes.
     3. Write partial `review/summary.md` with `**Status: Aborted**`.
     4. Report: "Review aborted at iteration N. Partial summary at [path]."

5. **Dispatch fixer.**
   - Run the fixer agent (read `agents/fixer.md` for its full spec) with: the artifact, `ARTIFACT.md`, current triage output, the flags file.
   - Fixer ignores triage-internal fields (`source_trace`, `interpretation_note`) and acts on `id`, `severity`, `location`, `description`, `suggestion`.
   - Fixer model: current tier model (sonnet during cheap tier, opus during opus tier).
   - Fixer emits changelog to `review/iterations/<N>/fixer-changelog.md`.
   - **VCS commit:**
     - jj: `jj new -m "adversarial-review: iteration <N> fixes"`
     - git: `git add <artifact> && git commit -m "adversarial-review: iteration <N> fixes"`

6. **Check iteration limit.**
   - If counter exceeds tier max: surface to user with diagnosis. Options: (a) bump limit, (b) accept remaining findings as risk, (c) abort.
   - If user accepts remaining findings as risk: update `accepted-risks.json`, then re-dispatch triage with the updated accepted-risks file. After re-triage completes, return to step 3 to evaluate the gate on the new triage output.
   - Otherwise: return to step 0.

### Phase 3: Tier Promotion

When the cheap tier loop exits clean:

1. Announce: "Cheap tier review complete. Promoting all agents to opus for final verification."
2. Switch tier to `opus`. Reset iteration counter to 1.
3. Re-enter Phase 2. All agents now run on opus. Triage was already on opus.
4. The opus loop runs identically — same gate (severity + coverage), same iteration limit (`opus_max`), same diagnosis.

### Phase 4: Completion

When the opus tier loop exits clean:

1. **Verify completion invariant.** Before writing the summary, confirm:
   - The final iteration of the opus tier has a `triage-output.json` with `gate_result` that is not `blocked`.
   - Every reviewer in the pool either ran in the final iteration and produced no medium+ findings, or has a `precondition_evaluations` entry showing `not met`.
   - If either check fails, the review is not complete — go back and run the formal iteration.

2. Write `review/summary.md`:
   ```markdown
   # Review Summary

   **Artifact:** [path]
   **Date:** [timestamp]
   **Final triage:** [path to final triage-output.json]

   ## Iterations
   - Cheap tier: N iterations
   - Opus tier: N iterations

   ## Findings resolved
   [List of all findings that were fixed, with iteration reference]

   ## Accepted risks
   [List of findings the user accepted, with rationale]

   ## Deferred low-severity findings
   [List from deferred-lows.json]

   ## Final state
   [Clean / accepted-risks-only / deferred-lows-only]
   ```

3. Report to user: "Review complete. [N] findings resolved across [M] iterations. [K] accepted risks. Session preserved at [session path]."

---

## create-default (author mode)

`/adversarial-review create-default`

Author-mode subcommand for skill authors creating new default reviewers. **Available only when cwd is a claude-materia source checkout** — detected by walking up for `.claude-plugin/plugin.json` with `name: claude-materia`. End-users invoking this elsewhere get an immediate "this is author tooling, only available in claude-materia source."

The flow walks the author through guided creation:

1. **Purpose statement.** Asks what the agent checks for and why. One source of truth for everything else.
2. **Naming.** Suggests a kebab-case name from the purpose. Author confirms or overrides.
3. **Required vs optional + trigger.** Reasons about whether this should run on every artifact or only on a subset. Proposes a trigger string if optional.
4. **Precondition.** Suggests one based on what the agent depends on (e.g., "internally consistent" for design-quality-style reviewers, or "may be inconsistent" for coherence-style). Author confirms.
5. **Severity guidance.** Proposes finding types and typical severities derived from the purpose. Author edits.
6. **Body sections.** Walks through "What you check," "What you do NOT check," "How to report findings," "Tone." Generates draft prose, iterates with author.
7. **Self-audit.** Runs the full 2.6 rubric (signal list + verdict logic + signal-by-signal output format) inline against the generated file (Claude evaluating against the rubric in the same context as authoring). This is a **point-in-time check** against the auditor heuristics current at authoring time — see the trust-by-source caveat below.
8. **On accept verdict:** writes file to `<skill-directory>/defaults/reviewers/<name>.md`, bumps `.claude-plugin/plugin.json` patch version, prints diff summary, reminds to commit.
9. **On reject verdict:** explains failed signals, offers to revise rather than ship a default that wouldn't pass its own audit.

The subcommand does not auto-commit. Author reviews the diff and commits.

### Trust-by-source caveat

The self-audit in step 7 is a point-in-time check against the auditor heuristics current at authoring time. If `agents/auditor.md` evolves later (new signals, changed verdict logic), previously-authored defaults are not re-audited automatically — they remain trusted by repo convention. The maintenance obligation is to re-run `create-default` (or a future `audit-defaults` subcommand) over existing defaults whenever auditor heuristics change. Repo convention enforces audit-passing at merge time, not at session time.

---

## Environment

This skill extends with environment context. Before executing:

1. Check if `~/.claude/env/` exists.
   - If not: bare environment. Note this in `ARTIFACT.md` and proceed.
   - If exists but `index.md` is absent or unreadable: warn that environment appears misconfigured. Note in `ARTIFACT.md` and proceed.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: for each entry in the index, state whether it applies to this review and a brief rationale. No silent dropping — every entry gets an explicit disposition.
4. For relevant entries, read those files and extract any structural constraints, spec checklists, naming conventions, routing rules, or other heuristics that apply to the artifact under review.
5. Include all discovered information in `ARTIFACT.md` under "Environment source" and "Structural constraints."

### Pool source configuration

If `~/.claude/env/index.md` (or a referenced env file) declares `adversarial-review.reviewers_dir`, the value (a path or list of paths) becomes the env-configured pool source. Each path is walked non-recursively. If the value is unset, no env pool exists — the skill runs with bundled defaults only unless the user supplies `--reviewers <ref>` at invocation or adds references at confirmation.
