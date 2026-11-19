---
name: adversarial-review
description: "Run an adversarial review loop on a scope (one file, many files, or a YAML manifest declaring both intent and locations). Dispatches reviewer agents to find issues, a triage agent to synthesize and route, a fixer to apply changes, and a scribe at the end to author the summary. Loops until clean, then promotes to opus for final verification. Use this skill whenever you need rigorous validation of a written artifact, when reviewing designs before implementation, when checking specs that AI agents will consume, or when the user asks to review, validate, stress-test, or audit something. Even if the user just says 'review this' or 'check this for issues', this skill applies."
user-invocable: true
argument-hint: "[subcommand] [args] — run <ref> [path], create-default (author mode), or just [path] for the full loop; add --autonomy to run hands off"
---

# Adversarial Review

An adversarial review loop that validates a review scope through multiple independent reviewer agents, synthesized by a triage agent, with fixes applied by a dedicated fixer agent and the final summary written by a scribe.

The skill ships with five default reviewers (coherence, design, detail, lost-items, bloat) and supports user-supplied reviewers via configuration or ad-hoc invocation. Reviewer agents declare what they check and how they report; the loop's contract is enforced on the consumer side through a semantic audit step before pool composition.

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
- `iterations/<tier>-<N>/scope.txt` (triage-authored, fixer-appended scope list; the baseline comparison script consumes it)
- `iterations/<tier>-<N>/baseline.diff` and `iterations/<tier>-<N>/baseline-sizes.tsv` (script output; reviewers and triage read them)
- anything under `review/baseline/` (the pre-review copies of the scope files)

The orchestrator's only authorized Phase 2 reads are:

- `iterations/<tier>-<N>/route.json` (small routing instruction)
- The `autonomy` field of `review/session-meta.json` and, in autonomy mode only, its `principal_bump_limit` field, the principal's final two lines (`RESPONSE:` / `REASON:`), the first line of each of this tier's `user-response.md` and `user-response.<k>.md` files, and the second line of those whose first line is `source: principal`

The baseline comparison script's inputs (`scope.txt`, `review/baseline/`) are consumed by the shell, not read into orchestrator context; running the script is not a read.

Substance never lands in orchestrator context. The temptation to verify, summarize, or "just check" is the failure mode this rule prevents — every read of a substance file recreates the bug.

`accepted-risks.json` and `deferred-lows.json` are **triage-owned**: orchestrator never reads them, never writes them. Same for `triage-output.json`.

### Surfacing exclusivity rule

Inside Phase 2, **triage owns all surfacing of substance**. The orchestrator surfaces directly only:

1. In Phase 1 setup (manifest confirmation, pool confirmation, baseline snapshot failure)
2. On tier-transition announcements (cheap → opus promotion)
3. On triage-itself-failed exceptions (malformed `route.json`, missing JSON, schema mismatch), when the orchestrator-run baseline comparison fails (non-zero exit; see Phase 2 step 3), and, in autonomy mode, the fixed pause line that precedes a surface the principal may not answer

All three are procedural, not substantive — bounded one-liners.

### Dispatch-discipline rule

When dispatching a subagent (reviewer, triage, fixer, scribe, auditor, principal — whose last line Autonomy mode replaces), the orchestrator MUST use this exact wrapper template — verbatim — and add no other content:

```
You are <agent-bare-name>. Adopt the role at <session-dir>/agents/<agent_filename>.
Execute the task at <prompt_path>.
End your turn with literal "ACK <output-path>" and nothing else.
```

Three substitutions only: `<agent-bare-name>`, `<agent_filename>` (with namespace prefix where applicable), `<prompt_path>` (and a corresponding `<output-path>` the subagent writes to). The wrapper MUST NOT contain:

- Iteration context, diagnosis priorities, focus reminders, or "be careful about X" prose
- Restatements of the manifest or scope
- Re-explanations of the agent's role beyond the role file path
- Anything the path-passed prompt file at `<prompt_path>` already contains

Triage's authored prompt file is the only authoritative input to the subagent. The orchestrator's wrapper is plumbing, not coordination — every line the orchestrator adds is substance bleeding into orchestrator context that should have stayed agent-local.

For the auditor in Phase 1 (no triage exists yet), the orchestrator authors the brief at `review/audit-briefs/<candidate>.md` and uses the same three-line wrapper. Same discipline.

### Acknowledgment-discipline rule

Subagents MUST end their turns with literal `ACK <output-path>` — no other text after that line, no preamble. The orchestrator MUST NOT read or summarize anything in the subagent's response beyond extracting the path token. Treat the response as an opaque parse for the path; ignore the rest.

Two agents end differently, and only as their sections specify: the principal replies with only a two-line `RESPONSE:` / `REASON:` decision in place of an ACK (see **Autonomy mode**), and the scribe may end with `WRITE-REFUSED` blocks when the harness refuses its writes (see Phase 4).

If a subagent's response does not match the literal ack format, treat it as an agent-failed exception (the orchestrator surfaces under case 3 of the Surfacing exclusivity rule). Do not "salvage" substance from a malformed ack — that re-creates the leak the discipline prevents.

### Known platform leak: file-modification reminders

When a subagent (typically the fixer) modifies a file in scope via Edit/Write, the platform's harness inserts a `<system-reminder>` into the orchestrator's context showing the modification — including substantial portions of the modified file. This is platform behavior, not skill behavior, and **cannot be suppressed from inside the skill**.

Practical impact: budget for ~3-10k tokens of orchestrator-context bleed per fixer dispatch on a moderate-sized scope, scaling roughly with the number and size of files the fixer touches. This is the dominant residual leak after the dispatch- and ack-discipline rules above. If it becomes the binding cost constraint, mitigation is engineering work outside this skill (e.g., having the fixer write a patch file the orchestrator applies via Bash, where Bash output may be terser than subagent file-edit reminders) — backlog item, not a 0.6.0/0.7.0 problem.

### Iteration validity invariant

An iteration is only valid if (a) each reviewer ran as an independent subagent — one Agent tool call per reviewer, never combined, (b) triage ran as its own subagent and produced a `route.json` file, and (c) the orchestrator's branching decisions reference only fields in `route.json`, never substance from any other file. Exceptions: the orchestrator also branches on the exit status of the baseline comparison script and on the user's `retry` / `abort` reply to its failure (Phase 2 step 3), and, in autonomy mode, on the reads the autonomy bullet of the Read-discipline rule authorizes (see Autonomy mode -> Answering an escalation).

## Subcommands

- `/adversarial-review [path]` — Run the full review loop. `path` may be (a) a YAML manifest, (b) a single file, or (c) omitted (infer the artifact from conversation context — if context insufficient, ask). For (b) and (c), Phase 1 builds a manifest interactively. Add `--autonomy` to run the loop hands off, with a principal agent answering escalations (see **Autonomy mode**).
- `/adversarial-review run <ref> <path>` — Single-pass: dispatch one reviewer agent against the scope. No loop, no triage, no fixer, no scribe. Useful for rapid iteration during artifact development.
- `/adversarial-review create-default` — Author-mode subcommand for skill authors only. Walks the author through guided creation of a new default reviewer. Available only when cwd is a claude-materia source checkout.

## Pool sources and namespacing

Reviewer agents are discovered from three categories of source. All sources are additive — each contributes candidates that go through the audit pipeline.

| Source | Namespace | Trust | When |
|---|---|---|---|
| Bundled defaults at `<skill-directory>/defaults/reviewers/` | `default` | Trusted (skip semantic audit) | Always |
| Per-install-configured paths (from `~/.claude/adversarial-review.local.md`) | `binding` | Audited | Always (if the `.local.md` declares any) |
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
| Starts with `<known-namespace>:` (default, binding, override, manual) | Namespace-prefixed reference; name resolves within that source's discovered candidates. **If a colon is present but the prefix is not a known namespace, it is a hard error** — do not fall through. |
| Otherwise (bare name) | Resolved via traversal of `~/.claude/agents/` for a matching `*.md` file |

A path can resolve to a file (single-agent source) or directory (multi-agent source, non-recursive walk).

### Per-install pool configuration

If `~/.claude/adversarial-review.local.md` declares `reviewers_dir` (directly, or via a pointer it forwards to), the value (a path or list of paths) becomes the per-install-configured pool source under the `binding` namespace. Each path is walked non-recursively. If the `.local.md` is absent or declares nothing, no `binding` pool exists.

Edge cases:
- Path doesn't exist → warn at discovery, exclude, continue
- Path is a file (not directory) → treat as single-file source
- Path is empty directory → warn ("the binding declares X but found no `*.md` files"), continue
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
5. Construct a minimal dispatch prompt for the reviewer with: scope file list, the manifest, `SCOPE.md`. No prior-iteration context and no `## Session inputs` section: a single pass has no baseline, so a baseline-dependent reviewer (lost-items, bloat) reports "no baseline provided" and emits no findings.
6. Dispatch the reviewer as a subagent. Present its raw output to the user. No triage, no fixer, no scribe.

Distinct from raw `Task` dispatch in that `run` performs the same scope resolution and `SCOPE.md` composition the full loop does.

---

## Full Review Loop

### Phase 1: Session Setup

In autonomy mode, steps 1, 4 and 5 change as described under **Autonomy mode → Setup**. Decide whether the mode is on before step 1.

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
   - Run the per-install-binding discovery protocol (see `## Per-install binding`).
   - Compose `SCOPE.md` — a profile of the review scope that every agent receives. Written to `review/SCOPE.md` when the session directory is created in step 4.

     ```markdown
     # Scope Profile

     **Manifest:** [path to manifest.yml]
     **Intent:** [from manifest]
     **Resolved files:** N files
     **Scope mode:** live | pinned

     ## Files in scope
     [Bulleted list of resolved file paths with brief role/format per file. For single-file scope, this is one entry; for multi-file scope, group by directory or component.]

     ## Binding source
     [One of:]
     - "Per-install binding found at ~/.claude/adversarial-review.local.md. Heuristics discovered via its pointer. Relevant entries: [list]. See below."
     - "Per-install binding found but no entries were relevant to this review. Reason: [why]."
     - "No per-install binding found (~/.claude/adversarial-review.local.md absent). Review proceeds on the scope's own merits."
     - "Per-install binding at ~/.claude/adversarial-review.local.md is unreadable or its pointer is broken. Warned user. Proceeding without."

     ## Structural constraints
     [If the binding's heuristics provided spec checklists, read/write contracts, naming conventions, routing rules, or other structural requirements applying to any file in scope, list them here.]

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
     - Walk all configured sources (bundled defaults, binding paths, --reviewers paths).
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
   - Create subdirectories: `agents/`, `review/`, `review/iterations/`, `review/baseline/`
   - **Snapshot the baseline.** Copy every file in the resolved scope into `review/baseline/`, mirroring each file's absolute path with the leading `/` removed (`/a/b/c.md` → `review/baseline/a/b/c.md`). Use Bash `cp` (creating parent directories), and if any copy exits non-zero, stop setup and surface one line under Surfacing exclusivity case 1, "Baseline snapshot failed for `<session-dir>/review/baseline/`. Reply `retry` or `abort`."; `retry` reruns the copy, `abort` ends the session without dispatching the scribe, and any other reply re-surfaces the same line; never Read the files. This runs after the step-2 checkpoint, so for checkpointed files the baseline equals the content at `pre_review_vcs_ref`; a file added to the scope at step 4 is baselined as it stands now. The baseline is written once and never updated, in both scope modes and across the tier promotion. It is the only record of the pre-review original that reviewers can see.
   - Snapshot the resolved-and-confirmed pool into `sessions/<id>/agents/` using namespace-prefixed filenames (`default__coherence.md`, `manual__custom-thing.md`, etc.). The snapshot reflects the locked pool.
   - Copy system agent files (triage, fixer, auditor, scribe) into `sessions/<id>/agents/` with their bare names (no namespace prefix; system agents have no source-namespace).
   - Create `review/accepted-risks.json` with initial content `[]`
   - Create `review/deferred-lows.json` with initial content `[]`. Schema: array of objects with fields `id` (string), `tier` (string: `"c"` or `"o"`), `iteration` (integer), `files` (array of strings), `description` (string), `reason` (string).
   - Write the `SCOPE.md` composed in step 1 to `review/SCOPE.md`.
   - Write the audit report from Stage A to `review/agent-audit.md`.
   - Write `review/session-meta.json` with `pre_review_vcs_ref`, `vcs: git | jj | none`, `baseline_dir` (the absolute path of `review/baseline/`), and the resolved scope's pre-review file list (for scribe).

### Phase 2: The Review Loop

In autonomy mode, step 1, the failure branch of step 3 (b2), and step 4 change as described under **Autonomy mode**.

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
├── scope.txt                              scope list — written by PREVIOUS iter's triage (or tier-init); fixer may append
├── baseline.diff                          baseline -> current diff — written by the orchestrator's script before reviewers run
├── baseline-sizes.tsv                     per-file line and word counts, baseline vs current — same script
├── default__coherence-output.md           reviewer (path-passed input/output)
├── default__design-output.md
├── triage-output.json                     full findings (fixer reads; orchestrator never)
├── route.json                             tiny routing instruction (orchestrator reads)
├── user-surface.md                        triage-authored; orchestrator echoes path
├── user-response.md                       iff requires_response: true and the user or principal responded
├── fixer-changelog.md                     iff gate was blocked
└── dispatches/                            consumed in THIS iter
    ├── default__coherence.md              reviewer prompt — written by PREVIOUS iter's triage (or tier-init)
    └── fixer.md                           fixer brief — written by THIS iter's triage (iff blocked this iter)

c-2/, c-3/ ...                             same shape

o-init/, o-1/, o-2/ ...                    same shape, opus tier
```

Convention: **dispatches live in the iteration where they're consumed**. Triage at `c-N` writes dispatches into `c-(N+1)/dispatches/` (creating that directory) and writes `c-(N+1)/scope.txt` beside them. Orchestrator's loop entry at `c-(N+1)` finds prompts and scope list already in place.

**Baseline paths.** Every triage dispatch (tier-init, numbered iteration, and re-dispatch after a user response) also passes absolute paths (five, or four at tier-init): `baseline_dir` (`<session-dir>/review/baseline/`, the value written to `session-meta.json` in Phase 1; derive it, do not Read that file for it), the current iteration's `baseline-sizes.tsv` (absent in tier-init), and for the next iteration `next_baseline_diff_path`, `next_baseline_sizes_path`, and `next_scope_list_path`. The current `baseline-sizes.tsv` is under `<session-dir>/review/iterations/<tier>-<N>/`, beside `route.json`; the three `next_*` paths are under `<tier>-<N+1>/` (`<tier>-1/` at tier-init). Triage writes the scope list; the orchestrator's script writes the other two before reviewers are dispatched.

**Tier-init iteration.** Every tier starts with a tier-init triage call. The orchestrator dispatches triage with: scope, manifest, SCOPE.md, no reviewer outputs, prior triage history (empty for cheap-init; full cheap-tier history for opus-init), tier label, iteration=0, and the baseline paths (see **Baseline paths**). Triage cold-start-evaluates preconditions, writes `c-1/scope.txt` (or `o-1/scope.txt`), and emits `c-init/route.json` (or `o-init/route.json`) with `next_dispatches` for iteration 1. No `triage-output.json` is produced.

**Each numbered iteration:**

0. **Read the current iteration's `route.json`.** It exists from the previous iteration's triage (or from tier-init for iteration 1). It tells you exactly what to do next.

1. **If `surface.requires_response: true`:** echo `surface.breadcrumb` and `surface.path` to the user. Capture the user's typed response verbatim and write to `iterations/<tier>-<N>/user-response.md`. Re-dispatch triage with the updated history (including every `user-response.md`, `user-response.<k>.md` and `user-response.principal.<k>.md` in the session, and the five baseline paths). Re-read the new `route.json`. (Triage will have updated `accepted-risks.json` or set `tier_max_increment` as appropriate, and emitted a new control decision.)

2. **If `tier_max_increment` is non-null:** add it to the current `tier_max`. Continue.

3. **Branch on `control`:**

   - **`continue`**:
     a. If `fixer_brief_path` is present: dispatch the fixer as a subagent using the dispatch-discipline wrapper (see Phase 2 architectural rules). Wait for the literal `ACK <output-path>` acknowledgment. VCS commit:
        - jj: `jj new -m "adversarial-review: iteration <tier>-<N> fixes"`
        - git: `git add <scope files> && git commit -m "adversarial-review: iteration <tier>-<N> fixes"`
     b. Increment iteration counter (or transition to next iteration's directory).
     b2. **Baseline comparison.** Run one Bash command: `bash "<skill-directory>/scripts/baseline-compare.sh" <session-dir> <iteration-dir> >/dev/null 2>&1`, both arguments absolute, `<iteration-dir>` being the new iteration's directory. It writes `baseline.diff` and `baseline-sizes.tsv` there from `review/baseline/` and the iteration's `scope.txt`. Run it every numbered iteration, unconditionally; do not reason about which reviewers need it. Branch only on the exit status, never on output:
        - Exit 0: continue to step c.
        - Non-zero: dispatch no reviewer. Surface one line under Surfacing exclusivity case 3: "Baseline comparison failed for `<iteration-dir>`. Reply `retry` or `abort`." On `retry`, rerun the script (no triage dispatch, no `user-response.md`). On `abort`, dispatch the scribe with `termination_kind: aborted`. Any other reply re-surfaces the same line.
     c. For each entry in `next_dispatches`, dispatch the reviewer subagent in parallel using the dispatch-discipline wrapper. Wait for literal `ACK <output-path>` acknowledgments.
     d. Dispatch triage as a subagent (using the dispatch-discipline wrapper) with paths to: this iteration's reviewer outputs, prior triage outputs, fixer changelogs, every `user-response.md`, `user-response.<k>.md` and `user-response.principal.<k>.md` in the session, accepted-risks.json, deferred-lows.json, manifest.yml, SCOPE.md, all agent spec files, and the five baseline paths (see **Baseline paths** above). Triage authors `triage-output.json`, the next `route.json`, the next iteration's `scope.txt`, and the next iteration's dispatch prompts. Wait for the literal `ACK <route.json path>` acknowledgment.
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
   - Paths to all `iterations/*/user-response.md`, `iterations/*/user-response.<k>.md` and `iterations/*/user-response.principal.<k>.md` (if any)
   - Path to accepted-risks.json
   - Path to deferred-lows.json
   - `termination_kind`: `clean | aborted | limit_reached`
   - In autonomy mode, also: `autonomy: true`, the path to `review/principal-brief.md`, and the path to the last numbered iteration's `baseline-sizes.tsv` (on an abort from a failed baseline comparison, that iteration's path all the same). The scribe then writes `review/autonomy-brief.md` as well.
2. Wait for the literal `ACK <summary.md path>` acknowledgment. **Write fallback:** some harnesses refuse a subagent's write of a report file. The scribe then ends its turn with one block per refused file: a line `WRITE-REFUSED <path>` followed by that file's full content. Save each block's content verbatim to its path and continue; the blocks stand in for the ACK. This is the one case where the orchestrator handles a subagent's content; the loop is already over.
3. Echo: "Review complete. Summary at `<session-path>/review/summary.md`."
4. Terminate.

The orchestrator never reads any session-state file at terminate time, with one exception: in autonomy mode it reads `review/autonomy-brief.md` (see **Autonomy mode → The end-of-run brief**). Otherwise the scribe's acknowledgment is the only signal.

## Autonomy mode

In autonomy mode the review runs without the user answering. A **principal** agent answers escalations in the user's place, from a brief the session writes at setup. The principal is a subagent, so finding substance stays out of orchestrator context; the brief is how the user's intent reaches it. Triage is unchanged in role: it still normalizes, routes, and authors every surface. The principal replaces only the person who answers.

### Trigger

Autonomy mode is on when either holds:

- the invocation carries `--autonomy`; or
- the user has said, in the conversation that invokes the skill, that they want to be hands off for this review (for example "run it without me", "I'll be away", "don't stop to ask me").

A preference stated in an earlier, unrelated task does not count. When you infer the mode from conversation, say so in one line at setup ("Running in autonomy mode because you said …") so the user can correct it. The mode is fixed at setup and recorded in `review/session-meta.json` as `autonomy: true | false`.

### Setup

- **Step 1 (manifest).** Build the manifest from the conversation without asking. If `intent`, or the artifact when no path was given, cannot be derived from the conversation, ask for it once, as outside autonomy mode; everything else proceeds unasked.
- **Step 2 (version control).** Unchanged. The no-VCS "Continue?" still waits for the user.
- **Step 4 (confirmation).** Show the manifest summary and the proposed pool, then proceed without waiting.
- **Step 5 (session directory).** Also copy `principal.md` into `agents/` with the other system agents, and write `review/principal-brief.md`.

**The principal brief.** Write it from the conversation before any reviewer runs. This is the only point where your knowledge of the user's intent enters the loop. State only what the conversation supports, and quote the user where you can.

```markdown
# Principal brief

## What the user wants from this review
[What they said the review is for, what they care about most, what they would rather not see.]

## What you may decide
[The default limits below, widened or narrowed only where the user said so, quoting what they said. State the bump limit as a number.]

## What you must send back
[The defaults below, plus anything the user said they want to decide themselves.]
```

Default limits, used unless the user said otherwise:

- `bump`: at most 3 extra iterations per tier in total, and only while the count of open high and medium findings is falling: lower than in the previous iteration of the same tier. With no previous iteration in the tier, the condition is met.
- `accept-risk`: medium and low findings only, and only for a reason the brief lists. Default reasons: the finding contradicts a decision the user already made; it concerns behaviour outside what this review is for; its fix would remove meaning the user wants kept.
- Send back: any high or critical finding that needs a decision; any `baseline_unavailable` or `incomplete_check` finding; any wish to abort; anything the brief does not cover.

Record the bump limit in `review/session-meta.json` as `principal_bump_limit`. Show the user the brief's path and its "What you may decide" and "What you must send back" sections. Do not wait.

### Answering an escalation

When `surface.requires_response` is true and `surface.human_only` is not true, do this in place of Phase 2 step 1's ask-the-user step:

1. Echo `surface.breadcrumb` and `surface.path`, so the transcript shows the escalation.
2. Write `iterations/<tier>-<N>/dispatches/principal.md` from this fixed template, paths only, `<tier>-<N>` being the iteration directory holding the route.json that carries this escalation:

   ```markdown
   # Principal dispatch — iteration <tier>-<N>
   - brief: <session-dir>/review/principal-brief.md
   - user-surface: <surface.path>
   - triage-output: <session-dir>/review/iterations/<tier>-<N>/triage-output.json
   - route.json: <session-dir>/review/iterations/<tier>-<N>/route.json
   - earlier user responses: [paths to every user-response.md, user-response.<k>.md and user-response.principal.<k>.md in the session, by iteration; within one, user-response.md is the latest in effect; "none"]
   - previous triage-output (same tier): <session-dir>/review/iterations/<tier>-<N-1>/triage-output.json, or "none" at iteration 1 of a tier
   ```

3. Dispatch the principal on the most capable model with the dispatch-discipline wrapper, its last line replaced by: `End your turn with the two-line RESPONSE / REASON decision your role file specifies and nothing else.`
4. Read the last two lines of its reply, and nothing else in it:

   ```
   RESPONSE: <bump N | accept-risk <ids> | continue | defer-to-user>
   REASON: <one sentence; findings named by id and severity only>
   ```

5. Apply the hard limits. Treat the reply as `defer-to-user` when any of these holds:
   - `malformed`: it does not end with a well-formed `RESPONSE:` / `REASON:` pair;
   - `abort`: `RESPONSE` is `abort`, or anything other than the four forms above;
   - `over-budget`: `RESPONSE` is `bump <N>` and N is not a positive integer, or N plus the principal's earlier bumps in this tier exceeds `principal_bump_limit` (from `session-meta.json`). Count earlier bumps from this tier's `user-response.md` and `user-response.<k>.md` files whose first line is `source: principal` (never `user-response.principal.<k>.md`), reading only what the Read-discipline rule authorizes.
6. Otherwise write `iterations/<tier>-<N>/user-response.md` (if this iteration already holds one, first rename it to `user-response.<k>.md`, k the next free integer from 1) as exactly:

   ```
   source: principal
   <the RESPONSE value>
   reason: <the REASON value>
   ```

   Then re-dispatch triage and continue exactly as after a human reply.

**Pausing for the user.** On `defer-to-user` (from the principal or a hard limit), or when `surface.human_only` is true, surface to the user as Phase 2 step 1 does outside autonomy mode, preceded by one line: "Autonomy mode paused: this decision is outside what the principal may decide." First record the principal response not put into effect as `user-response.principal.<k>.md`, k the next free integer from 1: in the `human_only` case, rename the principal-written `user-response.md` that triage refused; on `defer-to-user`, write the step-6 format with the RESPONSE value (or `malformed`) and, in `reason:`, the REASON value (or `none`) followed by the name of the hard limit that fired, if any. Wait. Write the user's typed reply to `user-response.md` with no `source:` line (renaming any existing one as in step 6), re-dispatch triage, and resume in autonomy mode.

**Triage's guard.** Only triage sees severities. If a principal response accepts a finding it may not (high or critical severity, or type `baseline_unavailable` or `incomplete_check`), triage refuses it and emits a surface with `human_only: true`. You do not check severities yourself.

**Baseline comparison failure** (step 3 b2, non-zero exit): rerun the script once without asking. If it fails again, surface the usual `retry` / `abort` line to the user and wait. Do not consult the principal; it cannot repair plumbing.

**Triage contract violation** (step 4, iteration limit fail-safe): surface to the user, never the principal; write the reply to `user-response.md` with no `source:` line, first renaming any existing one as in step 6.

### The end-of-run brief

In autonomy mode the scribe writes `review/autonomy-brief.md` alongside the summary: the decisions the principal made, the changes of significance, what is still open, and the size change. It is what a user who was away should read first.

After the scribe returns (Phase 4 step 2), Read `review/autonomy-brief.md` and only that file. This read is authorized: the loop is over, and the Read-discipline rule governs Phase 2. Then tell the user, in a few lines:

- the outcome and where the brief and the summary are;
- which items in the brief they are likely to mind, given what they said in the conversation, and why; or, plainly, that nothing stands out.

Do not restate the brief. Do not soften an item because the review ended clean.

### Files this mode adds to a session

```
review/principal-brief.md                      session-authored at setup; the principal reads it
review/autonomy-brief.md                       scribe-authored at the end; the session reads it once
iterations/<tier>-<N>/dispatches/principal.md  orchestrator-authored, paths only (iff the principal was consulted)
iterations/<tier>-<N>/user-response.<k>.md     an earlier response in an iteration that holds more than one (iff renamed by a later response)
iterations/<tier>-<N>/user-response.principal.<k>.md  a principal response not put into effect (iff triage set human_only, or the principal or a hard limit deferred)
```

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

## Per-install binding

If `~/.claude/adversarial-review.local.md` exists, read it and follow its per-install instructions before proceeding. This file is the skill's only per-install coupling point: it may point to a set of environment heuristics (for structural constraints) and/or declare a reviewer pool (`reviewers_dir`). If it is absent, proceed with the built-in defaults — bare install, fallback-safe.

When the `.local.md` points to a set of environment heuristics, discover structural constraints from them:

1. Check if `~/.claude/adversarial-review.local.md` exists.
   - If not: bare install. Note this in `SCOPE.md` and proceed with bundled defaults.
   - If present but unreadable, or its pointer is broken: warn that the binding appears misconfigured. Note in `SCOPE.md` and proceed.
   - Otherwise: follow its pointer to the heuristics and proceed to step 2.
2. Read the heuristics the `.local.md` points to.
3. Produce a **relevance map**: for each entry, state whether it applies to this review and a brief rationale. No silent dropping — every entry gets an explicit disposition.
4. For relevant entries, read those files and extract any structural constraints, spec checklists, naming conventions, routing rules, or other heuristics that apply to any file in the resolved scope.
5. Include all discovered information in `SCOPE.md` under "Binding source" and "Structural constraints."

### Pool source configuration

If `~/.claude/adversarial-review.local.md` declares `reviewers_dir` (directly, or via a pointer it forwards to), the value (a path or list of paths) becomes the per-install-configured pool source under the `binding` namespace. Each path is walked non-recursively. If unset, no `binding` pool exists — the skill runs with bundled defaults only unless the user supplies `--reviewers <ref>` or adds references at confirmation.
