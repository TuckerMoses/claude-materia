---
name: adversarial-review
description: "Run an adversarial review loop on an artifact (plan, spec, design, agent file, skill, CLAUDE.md). Dispatches reviewer agents to find issues, a triage agent to synthesize and route, and a fixer agent to apply changes. Loops until clean, then promotes to opus for final verification. Use this skill whenever you need rigorous validation of a written artifact, when reviewing designs before implementation, when checking specs that AI agents will consume, or when the user asks to review, validate, stress-test, or audit a document. Even if the user just says 'review this' or 'check this for issues', this skill applies."
user-invocable: true
argument-hint: [subcommand] [args] — run <agent-name> [path], add <agent-file>, remove <agent-name>, or just [artifact-path] for the full loop
---

# Adversarial Review

An adversarial review loop that validates artifacts through multiple independent reviewer agents, synthesized by a triage agent, with fixes applied by a dedicated fixer agent.

## Subcommands

- `/adversarial-review [artifact-path]` — Run the full review loop (default). Path is optional — if omitted, infer the artifact from conversation context (active file, most recently discussed artifact). If context is insufficient, ask.
- `/adversarial-review run <agent-name> [artifact-path]` — Single-pass: dispatch one reviewer agent, no loop, no triage, no fixer. Returns findings directly. Path optional, same inference rules.
- `/adversarial-review add <agent-file>` — Add a reviewer agent to the pool
- `/adversarial-review remove <agent-name>` — Remove an optional reviewer agent

---

## Single-Pass Review (`run`)

`/adversarial-review run <agent-name> <artifact-path>`

Dispatches a single reviewer agent against the artifact. No session, no loop, no triage, no fixer.

1. Read the named agent from the skill's `agents/` directory. Must be a `role: reviewer` agent.
2. Read the artifact. Build `ARTIFACT.md` (see Phase 1 Step 1 of the full loop — the same procedure applies).
3. Create a minimal flags file with: no user concerns, no session concerns. The user is not prompted for concerns in single-pass mode — to include specific concerns, use the full loop.
4. Dispatch the reviewer as a subagent with: the artifact, `ARTIFACT.md`, and the flags file.
5. Present findings to the user. No triage, no severity override, no fixer. The reviewer's raw output is the result.

This is useful for quick checks, verifying a specific concern, or running a reviewer after the full loop to confirm the final state.

---

## Full Review Loop

### Phase 1: Session Setup

1. **Read the artifact and build `ARTIFACT.md`.**
   - Read the artifact at the given path.
   - Run the environment discovery protocol (see `## Environment`).
   - Inspect the artifact itself: structure, format, frontmatter, stated purpose, apparent audience.
   - Compose `ARTIFACT.md` — a profile of the artifact that every agent receives. This file **always exists**, regardless of whether an environment was found. It is written to `review/ARTIFACT.md` when the session directory is created in step 4. It must contain:

     ```markdown
     # Artifact Profile

     **Path:** [artifact path]
     **Format:** [markdown, YAML frontmatter + markdown, JSON, etc.]
     **Apparent purpose:** [what this artifact appears to be — a plan, a spec, an agent definition, etc.]

     ## Environment source
     [One of:]
     - "Environment discovered at ~/.claude/env/index.md. Relevant entries: [list]. See below."
     - "Environment exists but no entries were relevant to this artifact. Reason: [why]."
     - "No environment found at ~/.claude/env/. Review proceeds on the artifact's own merits."
     - "Environment at ~/.claude/env/ appears misconfigured (index.md absent/unreadable). Warned user. Proceeding without."

     ## Structural constraints
     [If the environment provided spec checklists, read/write contracts, naming
     conventions, routing rules, or other structural requirements that apply to
     this artifact, list them here. These become review inputs — reviewers should
     check the artifact against them.]

     [If no environment or no relevant constraints: "None — universal review only.
     Reviewers assess the artifact against general quality principles."]

     ## Observations from inspection
     [Anything notable the orchestrator observed about the artifact that reviewers
     should be aware of: unusual structure, mixed concerns, stated invariants,
     cross-references to other files, etc.]
     ```

   - The goal: every agent gets a self-contained briefing about what this artifact is and what rules apply to it, without needing to re-derive that information or know where it came from.

2. **Check version control.**
   - Detect VCS: check for jj first (`jj status`), then git (`git status`).
   - **jj available**: Create an initial change (`jj new -m "adversarial-review: checkpoint before review"`). Per-cycle changes will be committed as separate jj changes.
   - **git available**: Create an initial commit (`git add <artifact> && git commit -m "adversarial-review: checkpoint before review"`).
   - **No VCS**: Warn: "No version control detected. Changes cannot be easily reverted. Continue?" Wait for confirmation.

3. **Build the agent pool.**
   - Read all `role: reviewer` agent files from the skill's `agents/` directory.
   - Required agents (`required: true`) are included automatically.
   - Optional agents (`required: false`): the orchestrator reasons over each agent's `trigger` field against the artifact content, `ARTIFACT.md`, and user-stated intent. If the trigger condition appears met, propose including it with stated reasoning. The user confirms or overrides.
   - Present the planned pool to the user for approval:
     ```
     Planned review agents:
     - coherence (required) — internal consistency checks
     - design (required) — design quality evaluation
     - detail (optional, triggered: artifact is an agent spec) — AI-consumption explicitness
     
     Proceed with this pool? You can add or remove agents.
     ```
   - Wait for user confirmation.

4. **Create the session directory.**
   - Path: `<skill-directory>/sessions/<timestamp>-<artifact-slug>/` (where `<skill-directory>` is the directory containing this SKILL.md)
   - Create subdirectories: `agents/`, `review/`, `review/iterations/`
   - Copy approved reviewer agent files into `sessions/<id>/agents/` (snapshot, not symlink)
   - Also copy system agent files (triage, fixer) into `sessions/<id>/agents/`
   - Create symlink: `sessions/<id>/artifact` → absolute path to the artifact
   - Create `review/accepted-risks.json` with initial content `[]`
   - Create `review/deferred-lows.json` with initial content `[]`. Schema: array of objects with fields `id` (string), `description` (string), `tier` (string: `"c"` or `"o"`), `iteration` (integer), `reason` (string).
   - Write the `ARTIFACT.md` composed in step 1 to `review/ARTIFACT.md`.

5. **Write flags.**
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
- Current tier starts at `cheap` (sonnet for reviewers and fixer, opus for triage always)

**Iteration validity invariant (full review loop only):** An iteration is only valid if (a) each reviewer ran as an independent subagent — one Agent tool call per reviewer, never combined, and (b) triage ran as its own subagent and produced a `triage-output.json` file. An iteration where multiple review roles were performed by a single agent, or where the orchestrator evaluated the gate without a triage JSON, is structurally invalid regardless of the findings. This invariant exists because the orchestrator's incentive to compress increases as findings diminish — the structure must hold tightest when the temptation to shortcut is strongest.

**Each iteration:**

0. **Create the iteration directory.** `review/iterations/<N>/` before dispatching any agents.

1. **Dispatch reviewers.**
   - Iteration 1 (cold start): evaluate each reviewer's precondition individually against the cold-start state. Preconditions like "may be inconsistent" (coherence) are trivially met. Preconditions requiring prior verification (e.g., "internally consistent" for design/detail) are NOT met on cold start — exclude those reviewers. On iteration 1, excluded agents will run in a subsequent iteration once their preconditions are met — the coverage check (step 3) ensures this.
   - Iteration 2+: dispatch only the agents listed in triage's `next_reviewers` from the previous iteration.
   - Each reviewer runs as a subagent (Agent tool) with: the artifact, `ARTIFACT.md`, the flags file, and previous triage output (if iteration 2+).
   - Reviewers are always independent and always dispatched in parallel. **Never combine multiple reviewer roles into a single agent call.**
   - Model: current tier model (sonnet during cheap tier, opus during opus tier). Exception: triage always runs opus.
   - Save each reviewer's output to `review/iterations/<N>/<reviewer-name>-output.md`.

2. **Dispatch triage.**
   - After all reviewers complete, dispatch the triage agent (read `agents/triage.md` for its full spec) with:
     - All reviewer outputs from this iteration
     - Full iteration history (all prior triage outputs + fixer changelogs + user interventions)
     - All reviewer agent spec files from the session pool (for precondition evaluation)
     - The flags file
     - The accepted-risks file
   - Triage always runs on the most capable model (opus).
   - Triage emits its JSON output to `review/iterations/<N>/triage-output.json`.

3. **Evaluate the gate (orchestrator responsibility).**
   - **Validity check**: verify that `review/iterations/<N>/triage-output.json` exists and contains valid JSON with a `gate_result` field. If this file is missing, the iteration is invalid — go back and run triage. The orchestrator must never evaluate the gate without a triage JSON.
   - **Severity check**: read triage's `gate_result`. If `blocked`, continue to step 4.
   - **Coverage check** (performed by the orchestrator, not triage): has every reviewer agent in the pool run against the current artifact state and produced no medium+ findings? Check triage's `precondition_evaluations` — if any pool agent's precondition is `met` but that agent did not run this iteration, coverage is incomplete.
   - If severity passes but coverage fails: continue the loop. Triage's `next_reviewers` should already include the agents that need to run (their preconditions are met).
   - If both pass: the orchestrator appends any remaining low-severity findings to `review/deferred-lows.json` with `reason` set to `"gate passed with lows only"`. Then exit the loop (go to Phase 3 or Phase 4 depending on tier).

4. **Surface triage diagnosis to the user (if needed).**
   - Show the user: findings summary, gate result, diagnosis note, roster for next iteration.
   - If iteration >= 2: check the previous iteration's fixer changelog for `unable_to_resolve` entries. Present these to the user for decision.
   - If the user wants to mark findings as accepted risk: update `review/accepted-risks.json`.
   - If the user says to continue: proceed.
   - **Abort protocol:** If the user aborts:
     1. Stop immediately.
     2. Do NOT revert VCS changes.
     3. Write partial `review/summary.md` with `**Status: Aborted**`.
     4. Report: "Review aborted at iteration N. Partial summary at [path]."

5. **Dispatch fixer.**
   - Run the fixer agent (read `agents/fixer.md` for its full spec) with: the artifact, `ARTIFACT.md`, current triage output, the flags file.
   - Fixer model: current tier model (sonnet during cheap tier, opus during opus tier).
   - Fixer emits changelog to `review/iterations/<N>/fixer-changelog.md`.
   - **VCS commit:**
     - jj: `jj new -m "adversarial-review: iteration <N> fixes"`
     - git: `git add <artifact> && git commit -m "adversarial-review: iteration <N> fixes"`

6. **Check iteration limit.**
   - If counter exceeds tier max: surface to user with diagnosis. Options: (a) bump limit, (b) accept remaining findings as risk, (c) abort.
   - If the user accepts remaining findings as risk: update `accepted-risks.json`, then re-dispatch triage with the updated accepted-risks file so a fresh `triage-output.json` is produced reflecting the new risk acceptances. After the re-triage completes, return to step 3 to evaluate the gate on the new triage output — the existing gate mechanism handles the loop exit.
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
   - Every reviewer in the pool either ran in the final iteration and produced no medium+ findings, or has a `precondition_evaluations` entry showing `not met` (meaning a prior clean pass still holds).
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

## Adding a Reviewer

`/adversarial-review add <path-to-agent-file>`

1. Read the agent file at the given path.
2. **Validate role.** Must be `role: reviewer`. Reject `role: system` with: "System agents cannot be added via this subcommand."
3. **Validate frontmatter schema.** Required fields:
   - `name` (string, unique across existing agents)
   - `description` (string)
   - `role` (must be `reviewer`)
   - `required` (boolean)
   - `trigger` (string if `required: false`, null if `required: true`)
   - `precondition` (string, mandatory — must describe a system state, not reference another agent by name)
   - `severity_guidance` (list of `{finding_type, typical_severity}` or null)
4. **Validate precondition phrasing.** Must describe a property of the artifact or system state. Reject if it references another agent by name. Note: semantic coupling via state description (e.g., "internally consistent" implying coherence has passed) is the correct pattern.
5. **Check for name collision.** Reject if an agent with the same name exists.
6. **If optional, validate trigger.** Must describe a condition about the artifact or context.
7. Copy to `<skill-directory>/agents/<name>.md` (where `<skill-directory>` is the directory containing this SKILL.md). If the environment has a version-control procedure for config files (see environment conventions), follow it.
8. Confirm: "Added [name] as [required/optional] reviewer."

## Removing a Reviewer

`/adversarial-review remove <agent-name>`

1. Find the agent file by name.
2. **Block removal of required agents.** Reject: "Cannot remove a required agent. Change it to optional first."
3. **Block removal of system agents.** Reject: "Cannot remove system agents (triage, fixer)."
4. Remove from `<skill-directory>/agents/<name>.md`. If the environment has a version-control procedure for config files (see environment conventions), follow it.
5. Confirm: "Removed [name] from the reviewer pool."

---

## Environment

This skill extends with environment context. Before executing:

1. Check if `~/.claude/env/` exists.
   - If `~/.claude/env/` does not exist: bare environment. Note this in `ARTIFACT.md`
     and proceed — the review works without environment context.
   - If `~/.claude/env/` exists but `index.md` is absent or unreadable: warn the
     user that the environment appears misconfigured. Note in `ARTIFACT.md` and proceed.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: for each entry in the index, state whether
   it applies to this review and a brief rationale. No silent dropping —
   every entry gets an explicit disposition.
4. For relevant entries, read those files and extract any structural
   constraints, spec checklists, naming conventions, routing rules, or
   other heuristics that apply to the artifact under review.
5. Include all discovered information in `ARTIFACT.md` under
   "Environment source" and "Structural constraints." This is how
   environment-derived context reaches the agents — through the
   artifact profile, not through a separate file.
