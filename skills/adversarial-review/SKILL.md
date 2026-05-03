---
name: adversarial-review
description: "Run an adversarial review loop on a scope (one file, many files, or a YAML manifest declaring both intent and locations). Dispatches reviewer agents to find issues, a triage agent to synthesize and route, a fixer to apply changes, and a scribe at the end to author the summary. Loops until clean, then promotes to opus for final verification. Use this skill whenever you need rigorous validation of a written artifact, when reviewing designs before implementation, when checking specs that AI agents will consume, or when the user asks to review, validate, stress-test, or audit something. Even if the user just says 'review this' or 'check this for issues', this skill applies."
user-invocable: true
argument-hint: "[subcommand] [args] — run <ref> [path], create-default (author mode), or just [path] for the full loop"
---

# Adversarial Review

An adversarial review loop that validates a review scope through multiple independent reviewer agents, synthesized by a triage agent, with fixes applied by a dedicated fixer agent and the final summary written by a scribe.

The skill ships with three default reviewers (coherence, design, detail) and supports user-supplied reviewers via configuration or ad-hoc invocation. Reviewer agents declare what they check and how they report; the loop's contract is enforced on the consumer side through a semantic audit step before pool composition.

## Glossary

- **Scope**: the conceptual whole under review — defined by a manifest (intent + locations + flags) and resolved into a set of files. May be one file or many.
- **Manifest**: a YAML document at `sessions/<id>/manifest.yml` declaring `intent` (the WHY of the review), `locations` (globs), `flags` (session concerns), and optionally `scope_mode` (`live` default; or `pinned`).
- **`<skill-directory>`**: the directory containing this `SKILL.md`. In the claude-materia source checkout this is `<repo-root>/skills/adversarial-review/`; at runtime under a plugin install, it resolves to the plugin's installed skill path. **Skill content only** — defaults, system agents, SKILL.md itself. Read-only at runtime.
- **`<plugin-data-dir>`**: the user-state directory for this plugin, resolves to `~/.claude/plugins/data/claude-materia-claude-materia/`. Where the runtime writes — audit cache, sessions, all per-user accumulating state. Survives plugin updates.

The split matters: skill content (`<skill-directory>`) is read-only at runtime under a plugin install; user state (`<plugin-data-dir>`) is the only writable location the skill should target.

## Architectural rules (Phase 2)

The review loop is built around a **blind orchestrator**: the conversational session running this skill never reads finding substance. It reads only `route.json` — a small instruction file authored by triage each iteration — and dispatches the next subagents based on that file. Two contract rules govern the loop:

### Read-discipline rule

During Phase 2, the orchestrator MUST NOT Read the following files:

- `iterations/<tier>-<N>/triage-output.json` (full findings — fixer's input)
- `iterations/<tier>-<N>/<reviewer>-output.md` (raw reviewer output)
- `iterations/<tier>-<N>/fixer-changelog.md` (fixer's audit trail)
- `iterations/<tier>-<N>/user-surface.md` (triage-authored; orchestrator echoes the path, never reads it)

The orchestrator's only authorized Phase 2 reads are:

- `iterations/<tier>-<N>/route.json` (small routing instruction)

Substance never lands in orchestrator context. The temptation to verify, summarize, or "just check" is the failure mode this rule prevents — every read of a substance file recreates the bug.

`accepted-risks.json` and `deferred-lows.json` are **triage-owned**: orchestrator never reads them, never writes them. Same for `triage-output.json`.

### Surfacing exclusivity rule

Inside Phase 2, **triage owns all surfacing of substance**. The orchestrator surfaces directly only:

1. In Phase 1 setup (manifest confirmation, pool confirmation)
2. On tier-transition announcements (cheap → opus promotion)
3. On triage-itself-failed exceptions (malformed `route.json`, missing JSON, schema mismatch)

All three are procedural, not substantive — bounded one-liners.

### Iteration validity invariant

An iteration is only valid if (a) each reviewer ran as an independent subagent — one Agent tool call per reviewer, never combined, (b) triage ran as its own subagent and produced a `route.json` file, and (c) the orchestrator's branching decisions reference only fields in `route.json`, never substance from any other file.

## Subcommands

- `/adversarial-review [path]` — Run the full review loop. `path` may be (a) a YAML manifest, (b) a single file, or (c) omitted (infer the artifact from conversation context — if context insufficient, ask). For (b) and (c), Phase 1 builds a manifest interactively.
- `/adversarial-review run <ref> <path>` — Single-pass: dispatch one reviewer agent against the scope. No loop, no triage, no fixer, no scribe. Useful for rapid iteration during artifact development.
- `/adversarial-review create-default` — Author-mode subcommand for skill authors only. Walks the author through guided creation of a new default reviewer. Available only when cwd is a claude-materia source checkout.

## Pool sources and namespacing

Reviewer agents are discovered from three categories of source. All sources are additive — each contributes candidates that go through the audit pipeline.

| Source | Namespace | Trust | When |
|---|---|---|---|
| Bundled defaults at `<skill-directory>/defaults/reviewers/` | `default` | Trusted (skip semantic audit) | Always |
| Environment-configured paths | `env` | Audited | Always (if env declares any) |
| Invocation-flag paths via `--reviewers <ref>` | `override` | Audited | Per invocation |
| Confirmation-time additions | `manual` | Audited | Per session, during confirmation |

`~/.claude/agents/` is **not** auto-scanned. It serves only as a search path for name resolution when the user explicitly references an agent by bare name.

### Reference resolution rules (`<ref>`)

| Pattern | Resolution |
|---|---|
| Starts with `/` | Absolute path |
| Starts with `./` or `../` | Cwd-relative path |
| Starts with `~/` | Home-relative path |
| Contains `/` (anywhere else) | Treated as path |
| Starts with `<known-namespace>:` (default, env, override, manual) | Namespace-prefixed reference; name resolves within that source's discovered candidates. **If a colon is present but the prefix is not a known namespace, it is a hard error** — do not fall through. |
| Otherwise (bare name) | Resolved via traversal of `~/.claude/agents/` for a matching `*.md` file |

A path can resolve to a file (single-agent source) or directory (multi-agent source, non-recursive walk).

### Environment configuration

If `~/.claude/env/index.md` exists and declares `adversarial-review.reviewers_dir`, the value (a path or list of paths) becomes the env-configured pool source. Each path is walked non-recursively. If unset, no env pool exists.

Edge cases:
- Path doesn't exist → warn at discovery, exclude, continue
- Path is a file (not directory) → treat as single-file source
- Path is empty directory → warn ("env declares X but found no `*.md` files"), continue
- Malformed YAML value → warn and skip that entry

### Namespace display

Internal references (orchestrator bookkeeping, output filenames `<namespace>__<name>-output.md`, audit log keys) use the full namespaced form. User-facing display uses shortest-unambiguous form: short name when unique across the discovered pool, full namespaced form when collision exists.

Within `manual`, duplicate references in one confirmation are deduplicated. Cross-source collisions still coexist as distinct agents.

---

## Single-Pass Review (`run`)

`/adversarial-review run <ref> <path>`

Scaffolded single-reviewer dispatch for rapid iteration during artifact development. Calling convention:

1. Resolve `<ref>` per the resolution rules above.
2. Read or build the manifest:
   - If `<path>` is a YAML manifest, parse it.
   - Otherwise, build an ephemeral manifest with `locations: [<path>]` and `intent: "(single-pass review)"`.
3. Resolve scope from manifest's `locations` (and `exclude` if present). Build `SCOPE.md` (see Phase 1 step 1).
4. Run the audit pipeline against the resolved candidate (Step 1 + Step 2 of the audit pipeline; cache-hits avoid re-dispatch).
5. Construct a minimal dispatch prompt for the reviewer with: scope file list, the manifest, `SCOPE.md`. No prior-iteration context.
6. Dispatch the reviewer as a subagent. Present its raw output to the user. No triage, no fixer, no scribe.

Distinct from raw `Task` dispatch in that `run` performs the same scope resolution and `SCOPE.md` composition the full loop does.

---

## Full Review Loop

### Phase 1: Session Setup

1. **Build or load the manifest, then compose `SCOPE.md`.**

   - **If `<path>` is a YAML file**: parse as manifest. Validate fields (`intent`, `locations` required; `exclude`, `flags`, `scope_mode` optional).
   - **If `<path>` is a non-YAML file or directory, or omitted**: build the manifest interactively.
     - Ask the user for `intent` if not derivable from conversation.
     - Set `locations: [<path>]` (or ask for additional patterns if the user wants).
     - Ask for any `flags` (concerns to focus on this session).
     - Default `scope_mode: live`.
   - Write the manifest to `<plugin-data-dir>/sessions/<timestamp>-<intent-slug>/manifest.yml`.
   - Resolve `locations` (with `exclude` filtering) using Bash globbing. The resulting absolute path list is the **resolved scope**.
     - Empty resolution → hard error. Surface to user, abort.
     - For `scope_mode: pinned`, also write the resolved list to `sessions/<id>/scope-pinned.json` for later iterations.
   - Run the environment discovery protocol (see `## Environment`).
   - Compose `SCOPE.md` — a profile of the review scope that every agent receives. Written to `review/SCOPE.md` when the session directory is created in step 4.

     ```markdown
     # Scope Profile

     **Manifest:** [path to manifest.yml]
     **Intent:** [from manifest]
     **Resolved files:** N files
     **Scope mode:** live | pinned

     ## Files in scope
     [Bulleted list of resolved file paths with brief role/format per file. For single-file scope, this is one entry; for multi-file scope, group by directory or component.]

     ## Environment source
     [One of:]
     - "Environment discovered at ~/.claude/env/index.md. Relevant entries: [list]. See below."
     - "Environment exists but no entries were relevant to this review. Reason: [why]."
     - "No environment found at ~/.claude/env/. Review proceeds on the scope's own merits."
     - "Environment at ~/.claude/env/ appears misconfigured (index.md absent/unreadable). Warned user. Proceeding without."

     ## Structural constraints
     [If env provided spec checklists, read/write contracts, naming conventions, routing rules, or other structural requirements applying to any file in scope, list them here.]

     ## Observations from inspection
     [Anything notable about the scope that reviewers should be aware of — cross-file relationships, conventions, format mixes.]
     ```

2. **Check version control.**
   - Detect VCS: jj first (`jj status`), then git (`git status`).
   - **jj available**: Create an initial change (`jj new -m "adversarial-review: checkpoint before review"`).
   - **git available**: Create an initial commit covering all files in scope (`git add <each scope file> && git commit -m "adversarial-review: checkpoint before review"`).
   - **No VCS**: Warn: "No version control detected. Changes cannot be easily reverted. Continue?" Wait for confirmation.
   - Capture the resulting commit/change hash as `pre-review-vcs-ref` for scribe to use later.

3. **Discover, audit, and recommend the pool.**

   The pool is built in three stages: discovery + audit (Stage A), recommendation (Stage B), and user confirmation (Stage C — see step 4).

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
         pattern (e.g., `after:<name>`, `requires:<name>`)
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
            HIT  → use cached verdict
            MISS → dispatch auditor agent, write result to cache
       d. Apply verdict (accept or reject)

   Step 3: Soft warning attachment (warnings flagged for confirmation display)

   Step 4: Compile audit report
     - Write `review/agent-audit.md` with per-candidate verdicts and reasoning
     - Compute pre-audit summary: per-source candidate count and cache-miss count
   ```

   Cache file lives at `<plugin-data-dir>/audit-cache.json`. Top-level structure:

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

   On session start, the orchestrator compares the current auditor.md hash to `last_auditor_hash`. If different, the audit report includes "auditor changed; full audit re-run" notice.

   **Stage B: Recommendation.** For each audit-cleared candidate:
   - Required agents (`required: true`) → recommend (subject to precondition check at iteration 1, performed by triage in tier-init mode — Phase 2)
   - Optional agents (`required: false`) → recommend if `trigger` matches the scope context
   - The orchestrator does NOT evaluate preconditions during pool composition — that's triage's job in tier-init. Pool composition only filters by `required` / `trigger`.

   Result: a proposed pool with per-agent reasoning ("Recommended because...", "Not recommended: trigger doesn't match").

4. **User confirmation (Stage C).**
   - Show the manifest summary, the pre-audit summary, the proposed pool, and audit-cleared-but-not-recommended candidates.
   - User can:
     - Edit `intent`, `flags`, or `locations` (re-resolve scope if locations change).
     - Add a reviewer reference (path or bare name) — runs through Step 1 + Step 2 of the audit pipeline (with caching).
     - Remove (prune) any audit-cleared candidate from the pool — per-session decision.
     - Accept the proposed pool.
   - Final pool is what the user confirms. After confirmation, the **pool source set is locked** for the rest of the session — no new agents discovered, audited, or added. Within the locked set, triage's per-iteration roster control may activate dormant candidates as preconditions become met.

5. **Create the session directory.**
   - Path: `<plugin-data-dir>/sessions/<timestamp>-<intent-slug>/`. Already created in step 1 for `manifest.yml`; now populate the rest.
   - Create subdirectories: `agents/`, `review/`, `review/iterations/`
   - Snapshot the resolved-and-confirmed pool into `sessions/<id>/agents/` using namespace-prefixed filenames (`default__coherence.md`, `manual__custom-thing.md`, etc.). The snapshot reflects the locked pool.
   - Copy system agent files (triage, fixer, auditor, scribe) into `sessions/<id>/agents/` with their bare names (no namespace prefix; system agents have no source-namespace).
   - Create `review/accepted-risks.json` with initial content `[]`
   - Create `review/deferred-lows.json` with initial content `[]`. Schema: array of objects with fields `id` (string), `tier` (string: `"c"` or `"o"`), `iteration` (integer), `files` (array of strings), `description` (string), `reason` (string).
   - Write the `SCOPE.md` composed in step 1 to `review/SCOPE.md`.
   - Write the audit report from Stage A to `review/agent-audit.md`.
   - Write `review/session-meta.json` with `pre_review_vcs_ref`, `vcs: git | jj | none`, and the resolved scope's pre-review file list (for scribe).

### Phase 2: The Review Loop

**Configuration:**
- `sonnet_max`: Maximum iterations for the cheap tier (default: 5, overridable via `--sonnet-max`)
- `opus_max`: Maximum iterations for the opus tier (default: 5, overridable via `--opus-max`)
- Current tier starts at `cheap` (sonnet for reviewers and fixer, opus for triage/auditor/scribe always)

**Iteration directory layout** under `review/iterations/`:

```
c-init/                     # cheap-tier-init triage output
├── route.json
└── (no triage-output.json — tier-init has no findings yet)

c-1/
├── default__coherence-output.md           reviewer (path-passed input/output)
├── default__design-output.md
├── triage-output.json                     full findings (fixer reads; orchestrator never)
├── route.json                             tiny routing instruction (orchestrator reads)
├── user-surface.md                        triage-authored; orchestrator echoes path
├── user-response.md                       iff requires_response: true and user responded
├── fixer-changelog.md                     iff gate was blocked
└── dispatches/                            written by THIS iter's triage for the NEXT iter
    ├── default__coherence.md              per-agent dispatch prompt
    └── fixer.md                           fixer brief (iff blocked this iter)

c-2/, c-3/ ...                             same shape

o-init/, o-1/, o-2/ ...                    same shape, opus tier
```

Convention: **dispatches live in the iteration where they're consumed**. Triage at `c-N` writes dispatches into `c-(N+1)/dispatches/` (creating that directory). Orchestrator's loop entry at `c-(N+1)` finds prompts already in place.

**Tier-init iteration.** Every tier starts with a tier-init triage call. The orchestrator dispatches triage with: scope, manifest, SCOPE.md, no reviewer outputs, prior triage history (empty for cheap-init; full cheap-tier history for opus-init), tier label, iteration=0. Triage cold-start-evaluates preconditions and emits `c-init/route.json` (or `o-init/route.json`) with `next_dispatches` for iteration 1. No `triage-output.json` is produced.

**Each numbered iteration:**

0. **Read the current iteration's `route.json`.** It exists from the previous iteration's triage (or from tier-init for iteration 1). It tells you exactly what to do next.

1. **If `surface.requires_response: true`:** echo `surface.breadcrumb` and `surface.path` to the user. Capture the user's typed response verbatim and write to `iterations/<tier>-<N>/user-response.md`. Re-dispatch triage with the updated history. Re-read the new `route.json`. (Triage will have updated `accepted-risks.json` or set `tier_max_increment` as appropriate, and emitted a new control decision.)

2. **If `tier_max_increment` is non-null:** add it to the current `tier_max`. Continue.

3. **Branch on `control`:**

   - **`continue`**:
     a. If `fixer_brief_path` is present: dispatch the fixer as a subagent with `Adopt the role defined in <session-dir>/agents/fixer.md. Execute the task described in <fixer_brief_path>.` Wait for one-line acknowledgment. VCS commit:
        - jj: `jj new -m "adversarial-review: iteration <tier>-<N> fixes"`
        - git: `git add <scope files> && git commit -m "adversarial-review: iteration <tier>-<N> fixes"`
     b. Increment iteration counter (or transition to next iteration's directory).
     c. For each entry in `next_dispatches`, dispatch the reviewer subagent in parallel with `Adopt the role defined in <session-dir>/agents/<agent_filename>. Execute the task described in <prompt_path>.` Wait for one-line acknowledgments.
     d. Dispatch triage as a subagent with paths to: this iteration's reviewer outputs, prior triage outputs, fixer changelogs, accepted-risks.json, deferred-lows.json, manifest.yml, SCOPE.md, all agent spec files. Triage authors `triage-output.json`, the next `route.json`, and (if blocked) the next iteration's dispatch prompts. Wait for one-line acknowledgment.
     e. Echo new `route.json`'s `surface.breadcrumb` and `surface.path`. Loop to step 0 of the new iteration.

   - **`exit_clean`**:
     - If `tier == "c"`: announce "Cheap tier complete. Promoting all agents to opus for final verification." Set `tier = "o"`, iteration=0. Dispatch tier-init triage. Loop continues at o-1.
     - If `tier == "o"`: dispatch the scribe (see Phase 4).

   - **`exit_aborted`**: dispatch the scribe with `termination_kind: aborted`.

   - **`escalate`**: re-route to step 1 above (surface required, capture response, re-dispatch triage). Note: `escalate` also has `requires_response: true`, so step 1 already handles it.

4. **Iteration limit fail-safe** (triage contract enforcement; this surface falls under case 3 of the Surfacing exclusivity rule — triage-itself-failed exception).
   - Triage owns iteration-limit handling per its spec §12 — at `iteration >= tier_max - 1` with the gate still blocked, triage should emit `control: escalate` with structured options.
   - If the orchestrator detects `iteration > tier_max` with `control: continue`, that is a **triage contract violation**: triage was supposed to escalate one iteration earlier and didn't. Surface as a triage-failed exception: "Triage exceeded tier_max without escalating (contract violation). Options: bump <N>, accept-risk <ids>, or abort." Capture response, write to `user-response.md`, re-dispatch triage. Triage parses the response and emits a new route.json with appropriate control.

### Phase 3: Tier Promotion

Tier promotion is handled inline in the `exit_clean` branch of Phase 2 (see above). The orchestrator's promotion logic is exactly:

1. Announce procedurally (one of the three direct-surface cases).
2. Reset iteration counter; set `tier = "o"`.
3. Dispatch tier-init triage; iteration 1 of opus tier follows from its `next_dispatches`.

No model-selection logic lives anywhere except the orchestrator's dispatch calls. Triage doesn't know about models.

### Phase 4: Completion

When opus exits clean (or any tier exits aborted/limit-reached):

1. **Dispatch the scribe** as a subagent. The dispatch prompt (orchestrator-authored, fixed template — no synthesis required) contains:
   - Path to the manifest
   - Path to SCOPE.md
   - Path to session-meta.json (for `pre_review_vcs_ref` and `vcs` flag)
   - Paths to all `iterations/*/triage-output.json`
   - Paths to all `iterations/*/fixer-changelog.md`
   - Paths to all `iterations/*/user-response.md` (if any)
   - Path to accepted-risks.json
   - Path to deferred-lows.json
   - `termination_kind`: `clean | aborted | limit_reached`
2. Wait for scribe's one-line acknowledgment.
3. Echo: "Review complete. Summary at `<session-path>/review/summary.md`."
4. Terminate.

The orchestrator never reads any session-state file at terminate time. The scribe's acknowledgment is the only signal.

---

## create-default (author mode)

`/adversarial-review create-default`

Author-mode subcommand for skill authors creating new default reviewers. **Available only when cwd is a claude-materia source checkout** — detected by walking up for `.claude-plugin/plugin.json` with `name: claude-materia`. End-users invoking this elsewhere get an immediate "this is author tooling, only available in claude-materia source."

The flow walks the author through guided creation:

1. **Purpose statement.** What the agent checks for and why.
2. **Naming.** Suggests a kebab-case name from the purpose.
3. **Required vs optional + trigger.** Reasons about whether this should run on every scope or a subset.
4. **Precondition.** Suggests one based on what the agent depends on.
5. **Severity guidance.** Proposes finding types and typical severities.
6. **Body sections.** Walks through "What you check," "What you do NOT check," "How to report findings," "Tone." Reviewer's report instructions should mention `files` field for multi-file findings.
7. **Self-audit.** Runs the full 2.6 rubric inline against the generated file. Point-in-time check against current auditor heuristics.
8. **On accept verdict:** writes file to `<skill-directory>/defaults/reviewers/<name>.md`, bumps `.claude-plugin/plugin.json` patch version, prints diff summary, reminds to commit.
9. **On reject verdict:** explains failed signals, offers to revise.

The subcommand does not auto-commit. Author reviews the diff and commits.

### Trust-by-source caveat

The self-audit in step 7 is a point-in-time check against the auditor heuristics current at authoring time. If `agents/auditor.md` evolves later, previously-authored defaults are not re-audited automatically — they remain trusted by repo convention.

---

## Environment

This skill extends with environment context. Before executing:

1. Check if `~/.claude/env/` exists.
   - If not: bare environment. Note this in `SCOPE.md` and proceed.
   - If exists but `index.md` is absent or unreadable: warn that environment appears misconfigured. Note in `SCOPE.md` and proceed.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: for each entry in the index, state whether it applies to this review and a brief rationale. No silent dropping — every entry gets an explicit disposition.
4. For relevant entries, read those files and extract any structural constraints, spec checklists, naming conventions, routing rules, or other heuristics that apply to any file in the resolved scope.
5. Include all discovered information in `SCOPE.md` under "Environment source" and "Structural constraints."

### Pool source configuration

If `~/.claude/env/index.md` (or a referenced env file) declares `adversarial-review.reviewers_dir`, the value (a path or list of paths) becomes the env-configured pool source. Each path is walked non-recursively. If unset, no env pool exists — the skill runs with bundled defaults only unless the user supplies `--reviewers <ref>` or adds references at confirmation.
