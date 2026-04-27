# Adversarial Review — Migration Decisions

Working notes capturing ratified design decisions for the migration to injectable reviewer agents. **Transient file — delete after migration is executed.**

## Status

| Topic | State |
|---|---|
| 1. Triage as normalizer | **Ratified** |
| 2. Relaxed agent contract + audit step | **Ratified** |
| 3. Pool discovery + bundled defaults | **Ratified** |
| 4. Mechanics of user-added agents | **Ratified** |
| 5. Fate of `add` / `remove` subcommands + new authoring tooling | **Ratified** |
| 6. Migration mechanics | **Ratified** |

---

## Topic 1 — Triage as normalizer (RATIFIED)

The reviewer/triage contract shifts: reviewers may emit free-form output; triage normalizes it into the loop's structured findings format. Pattern: contract enforcement at the *consumer*, not the *producer*.

### 1.1 — Consolidate, don't split

Triage absorbs the "extract findings + assign severity from free-form reviewer output" job. No new normalizer agent. Extraction and severity assignment answer one question ("what are the structured findings from this iteration?"); a pipeline boundary between them would be artificial. Triage already runs on opus, the right model for this work.

### 1.2 — Source trace per finding

Triage emits a `source_trace` per finding using one of three shapes:

- **`quote`** — verbatim text + reviewer name. For clean isomorphism. Highest audit value.
- **`region`** — reviewer name + range pointer (e.g., "paragraphs 2-3", "section 'Coupling'"). For multi-statement findings or findings whose context spans a region. Medium audit value.
- **`synthesis`** — reviewer name + note explaining derivation. For holistic findings drawn from the overall thrust, or absence-based observations. Lowest audit value but better than no trace.

Every finding also has an `interpretation_note` field (always present, may be empty for clean quote cases) where triage explains *why* this trace shape was chosen if non-trivial.

Reviewer output is preserved verbatim per-iteration in `review/iterations/<N>/<reviewer-name>-output.md`. The trace is a pointer into that file, not a duplicate of it.

The asymmetric audit cost (cheap for structured reviewers, richer for prose reviewers) is intentional — it makes the cost of the freedom prose-style reviewers buy visible per-finding.

### 1.3 — `severity_guidance` becomes a hint

Reviewers may emit severity per-finding or omit entirely. If present in the agent's frontmatter, triage uses it as a calibration hint for that reviewer's findings. If absent, triage falls back to its own calibration table. Reviewer-emitted severity loses its status as default authority.

### 1.4 — Don't preemptively split triage

Triage now does: extraction, severity assignment, precondition evaluation, roster control, cross-iteration diagnosis. That's a lot. If it ever feels overloaded in practice, the natural future split is *extraction+severity* into one agent and *roster+diagnosis* into another — **not** extraction as its own agent. But don't build the split now.

---

## Topic 2 — Relaxed agent contract + audit step (RATIFIED)

The contract on agent files lives entirely on the consumer side. Agent files describe what they do; the loop derives fitness from purpose via a semantic audit. No producer-side declarations or skill-specific tags.

### 2.1 — Hard contract: `name` + prompt body

Two requirements only:

| Field | Why required |
|---|---|
| `name` (frontmatter) | Orchestrator references it everywhere; no semantic equivalent |
| Prompt body | Empty agent is structurally undispatchable |

No `role` tag. No type discriminator. No opt-in flag. Pool inclusion is decided by **semantic audit**, not schema check.

### 2.2 — Soft contract with defaults

| Field | Default if absent |
|---|---|
| `description` | empty string |
| `required` | `true` |
| `trigger` | `null` (only meaningful when `required: false`) |
| `precondition` | `"always met"` (agent runs every iteration) |
| `severity_guidance` | `null` (triage uses own calibration per 1.3) |

If an agent file has a `role` field, the skill ignores it. Other skills are free to use it; agents are now cross-skill-compatible.

### 2.3 — Hard rejects (excluded from pool)

| Reject | Reason |
|---|---|
| Frontmatter doesn't parse as YAML | Auditor can't read the file |
| Missing or empty `name` | Orchestrator can't reference it |
| Empty prompt body | Nothing to dispatch |
| `precondition` references another agent by name | Loop self-regulation invariant |
| Auditor verdict: reject | Semantic audit failure (skipped for bundled defaults) |

**Name collisions are not rejects** — they're resolved by namespacing (see below).

### 2.4 — Soft warnings (accepted with flag)

- Missing `description` — pool listing sparse
- Missing `precondition` — agent runs every iteration; can't self-regulate
- `required: false` without `trigger` — agent can never auto-include
- Unknown frontmatter fields — probable typo of a known field

### 2.5 — Audit pipeline at Phase 1 Step 3a

Two-stage pipeline runs before pool confirmation:

```
Stage 1: Pre-check (cheap, deterministic, runs on all candidates)
  - Parse frontmatter, check 2.3 structural rejects
  - Sanity-checks even bundled defaults haven't been corrupted

Stage 2: Semantic audit (LLM-driven)
  - SKIP for candidates from <skill-directory>/defaults/reviewers/
    → verdict: accept (trusted: bundled default)
  - RUN for all other candidates
    → auditor evaluates 2.6 heuristics, emits verdict + reasoning

Stage 3: Soft warning attachment

Stage 4: Compile audit report
  - Write `review/agent-audit.md`, present at pool confirmation
```

The trust-by-source rule scopes only to `<skill-directory>/defaults/reviewers/`. User-configured pools, env-declared pools, and `--reviewers` overrides all get audited.

### 2.6 — Auditor heuristics (codified, not vibes)

Auditor agent's prompt enumerates explicit signals it must evaluate. Audit reasoning must address each signal by name.

**Accept signals** (positive — agent likely produces review-shaped output):

| Signal | What auditor looks for |
|---|---|
| Evaluative purpose | Agent's described purpose is to *find / identify / detect / critique / flag* something |
| Findings-shaped output | Output is described as issues, problems, weaknesses, gaps, defects, critiques |
| Specificity grounded | Prompt instructs the agent to cite locations, quote text, point to specifics |
| Discriminating stance | Prompt body identifies what kinds of things the agent flags as wrong (failure modes, anti-patterns) |

**Reject signals** (negative — any one firing → reject):

| Signal | Why disqualifying |
|---|---|
| Action-oriented | Agent runs commands, modifies files, calls APIs (must be passive observer) |
| Generative | Agent produces new content rather than evaluating existing content |
| Interactive | Agent requires mid-execution user input (can't run as one-shot subagent) |
| External-state-dependent | Agent needs other files, network, persistent state to function |
| Orchestration-focused | Agent's purpose is to manage other agents/processes, not read-and-report |

**Verdict logic:**
1. Any reject signal fires → reject
2. All accept signals fail to fire → reject (need positive evidence)
3. Mixed positive (1-2 weak) and no rejects → accept with caveat in reasoning
4. All accept fire strongly, no rejects → accept

Auditor must reference each signal by name in its reasoning output. Format example:

```markdown
## coherence (accepted)

- Evaluative purpose: strong — "find places where the artifact contradicts itself"
- Findings-shaped output: strong — emits `finding_type`, `location`, `description`
- Specificity grounded: strong — "Quote the conflicting statements"
- Discriminating stance: strong — enumerates contradiction, circular_definition, etc.
- No reject signals fired.

Verdict: accept.
```

### Namespacing (cross-cutting concern from 2.3)

Each pool source has a namespace. Agents are identified internally by `<namespace>:<name>`. Name collisions across sources coexist as distinct agents — both run, both produce output, triage consumes both.

- **Internal references** (orchestrator bookkeeping): triage's `next_reviewers`, output filenames (`<namespace>__<name>-output.md`), audit log keys
- **User-facing display**: short name (`coherence`) when unambiguous; full namespaced form (`default:coherence`, `user:coherence`) only when collision exists. "Shortest unambiguous form" pattern.

User override is additive by default. To replace a default with a custom version, prune the default at the pool-confirmation step. No special override syntax.

**Specific namespace strings deferred to Topic 3** (depends on what pool sources are settled).

### New system agent: `auditor.md`

Joins `triage.md` and `fixer.md` as a third system agent. Runs on opus. Inputs: candidate agent file + triage's data model description. Outputs: verdict + signal-by-signal reasoning.

---

---

## Topic 3 — Pool discovery + bundled defaults (RATIFIED)

The skill discovers candidate agents from multiple sources, all additive. After discovery + audit, the skill produces a recommendation; the user confirms.

### Discovery → recommendation → confirmation flow

Three distinct stages at session start:

```
Stage A: Discovery + audit (produces audit-cleared candidates)
  — what agents exist; are they shaped right
  — Result: full set of audit-cleared candidates from all sources

Stage B: Recommendation (skill applies judgment to candidates)
  — Required agents (required:true) → recommend (precondition pending check)
  — Optional agents (required:false) → recommend if trigger matches artifact
  — Cold-start preconditions → only recommend agents whose preconditions
    could be met on iteration 1
  — Result: proposed pool with per-agent reasoning

Stage C: User confirmation
  — Shows: proposed pool + audit-cleared-but-not-recommended candidates
  — User can add (promote a non-recommended candidate) or remove
    (drop a recommended one) anything from the audit-cleared set
  — Final pool is what user confirms
```

The skill **always** has a position on what should run. The user always has final say. This was implicit in original SKILL.md (preconditions, triggers); now explicit and central.

### 3.1 — Source taxonomy (additive, no replacement)

| Source | Namespace | Trust | Behavior |
|---|---|---|---|
| `--reviewers <path>` invocation flag | `override` | Audited | Adds candidates from this path |
| Environment-declared pool | `env` | Audited | Adds candidates from env-configured path |
| Bundled defaults | `default` | Trusted | Adds candidates from `<skill-directory>/defaults/reviewers/` |

All sources contribute additively. No source replaces another. To use only one source, prune the others at pool confirmation.

### 3.2 — Bundled defaults shipped

The skill ships `coherence`, `design`, `detail` at `<skill-directory>/defaults/reviewers/`. Three reasons:
1. Zero-config UX matters — works the moment the plugin is installed.
2. The three reviewers are good baseline content for any artifact.
3. They serve as canonical examples of the preferred shape (reduces triage workload for users writing custom reviewers).

### 3.3 — No project-local source in v1

Not adding a fourth source like `.claude/adversarial-review/reviewers/` in cwd. Env-declared pools can already point at project-local paths if needed. YAGNI.

### 3.4 — Discovery is non-recursive

Each source directory is walked non-recursively. Every `*.md` file at the top level is a candidate; subdirectories are ignored. Subdirs can serve as user-managed staging areas for in-progress reviewers.

### 3.5 — Source configuration

| Source | Resolution |
|---|---|
| Bundled defaults | `<skill-directory>/defaults/reviewers/` — always scanned, trusted |
| User pool | **Default: `~/.claude/agents/`** (canonical agent location). Env file at `~/.claude/env/index.md` may declare an alternative path or list of paths under `adversarial-review.reviewers_dir`. If declared, that's *the* user pool path(s). If not declared, the default applies. |
| Invocation override | `--reviewers <path>` — additive; one more path for this run |

The "env replaces the default" semantic is **configuration with a sensible default**, not a precedence-chain replacement. Same pattern as `$EDITOR` defaulting to `vi`.

### 3.6 — Audit caching (content-hash keyed)

Auto-scanning `~/.claude/agents/` is only viable if audit cost is bounded. Solution: cache verdicts keyed on `(auditor_content_hash, agent_content_hash)`.

```
Cache location: ~/.claude/skills/adversarial-review/audit-cache.json
Cache key: (SHA-256(auditor.md), SHA-256(agent_file))
Cache value: { verdict, reasoning, audited_at, agent_name_at_audit }
```

Cache structure:
```json
{
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

Pipeline integration (Stage 2 of 2.5's audit pipeline):

```
For each candidate that passed pre-check:
  a. SKIP if source is bundled defaults (trusted)
  b. Compute auditor_hash = SHA-256(<skill>/agents/auditor.md)
     Compute agent_hash   = SHA-256(<candidate-file>)
  c. Cache lookup at audit-cache.json[auditor_hash][agent_hash]:
       HIT  → use cached verdict, mark "from cache" in audit report
       MISS → dispatch auditor, write result to cache
  d. Apply verdict
```

Cost transformation: from O(sessions × agents) LLM calls to O(unique-content-versions × auditor-versions) LLM calls. Stable directories with stable auditor → effectively one audit per agent, ever.

Edge cases:
- Cache file missing → create on first write
- Cache file malformed → warn, treat as empty for this session, overwrite on next write (cache is optimization, not load-bearing)
- Concurrent sessions → both audit, last writer wins, verdicts identical anyway

The audit report (`review/agent-audit.md`) annotates each verdict as "from cache" or "fresh audit" for provenance.

---

---

## Topic 4 — Mechanics of user-added agents (RATIFIED)

The original "merge vs replace" framing dissolved into earlier decisions (namespacing in 2.3, additive sources in 3.1). What remains is mechanics around confirmation-time additions and the temporal boundary at pool lock.

### Timeline

```
Phase 1: Setup
  Step 1-3: Read artifact, audit candidates, compute recommendation
  Step 4: USER CONFIRMATION  ←── 4.1, 4.2, 4.3, 4.4 apply during this step
            confirmation ends with: POOL LOCKED  ←── 4.5 boundary
  Step 5: Write flags

Phase 2: Loop
  Iterations run with the LOCKED pool
  Triage's `next_reviewers` selects WHICH agents from the locked pool
  run next iteration. Pool itself doesn't change.
```

### 4.1 — Confirmation-time additions go through the audit pipeline

During the Phase 1 confirmation step (before pool lock), the user can supply additional paths. Each new candidate runs through Stage 1 + Stage 2 of the audit pipeline (with caching). Auditor's verdict shown; user can accept or override.

### 4.2 — Path can be file or directory

User-supplied paths at confirmation:
- File path (`*.md`) → single-agent source
- Directory path → multi-agent source (non-recursive walk)

Principle of least surprise — point at one thing, get one thing.

### 4.3 — Confirmation-time additions get namespace `manual`

| Source | Namespace |
|---|---|
| Invocation flag (`--reviewers`) | `override` |
| Confirmation-time addition | `manual` |
| Env pool | `env` |
| Bundled defaults | `default` |

Within `manual`, name collisions get numeric suffix: `manual:coherence`, `manual:coherence-2`. Rare; don't preemptively over-engineer.

### 4.4 — Pruning is per-session only

User pruning at confirmation is a per-session decision. No state persists across sessions. No `.disabled` markers, no permanent disable mechanism. If repeated pruning of the same default emerges as a pattern, future v2 candidate is `adversarial-review.disable_defaults: [coherence]` env field. Not in v1.

### 4.5 — Pool is locked after Phase 1 confirmation

Once confirmed, the pool is sealed for the rest of the session. No mid-loop additions or removals. Triage's `next_reviewers` controls *which* pool agents run *next iteration*, but only from the already-locked pool.

The lock is what keeps iteration history coherent — drift detection, precondition tracking, and `next_reviewers` evaluation all assume a stable pool. Loosening this is a real design change, deferred to future v2 if real demand emerges.

---

## Topic 5 — Subcommands + authoring tooling (RATIFIED)

The `add` and `remove` subcommands existed to manage agents inside a closed plugin. The new architecture removes the need entirely. Authoring tooling for skill authors is reintroduced as a separate, source-repo-gated subcommand.

### 5.1 — Drop `/adversarial-review add <agent-file>`

End-users add reviewers via filesystem (drop a file in their user pool, e.g., `~/.claude/agents/`). No subcommand needed.

### 5.2 — Drop `/adversarial-review remove <agent-name>`

End-users remove via filesystem (delete from pool source) or per-session pruning at confirmation. No subcommand needed.

### 5.3 — Keep `/adversarial-review run <agent-name> [path]`

Reframed as **scaffolded single-reviewer dispatch for rapid iteration during artifact development**. Behavior:
- Runs same discovery + audit pipeline as full loop
- Builds `ARTIFACT.md` (Phase 1 Step 1 logic)
- Builds minimal flags file
- Resolves agent name against discovered pool (shortest-unambiguous form, namespace disambiguation if collision)
- Dispatches the named agent in single-pass mode (no triage, no fixer, no loop)

Distinction vs raw Task dispatch: `run` provides the calling-convention scaffolding (ARTIFACT.md, flags, audit gate) that reviewers expect. Raw dispatch is always available as an escape hatch for users who explicitly want no ceremony.

### 5.4 — Update `argument-hint` frontmatter

```
[subcommand] [args] — run <agent-name> [path], create-default (author mode), or just [artifact-path] for the full loop
```

### 5.5 — Add `/adversarial-review create-default` (source-repo-gated authoring)

A new subcommand for skill authors to create new default reviewers via a guided dialog. Available **only when cwd is a claude-materia source checkout** — detected by walking up for `.claude-plugin/plugin.json` with `name: claude-materia`. End-users invoking this elsewhere get an immediate "this is author tooling, only available in claude-materia source."

Flow:
1. Purpose statement (what the agent checks for, why)
2. Naming (suggest kebab-case from purpose, author confirms)
3. Required vs optional + trigger (if optional)
4. Precondition (suggest based on what the agent depends on)
5. Severity guidance (propose finding types and severities from purpose)
6. Body sections (What you check / What you do NOT check / How to report findings / Tone — generate drafts, iterate with author)
7. Self-audit: run the auditor heuristics from 2.6 inline (Claude evaluating against the rubric in the same context as authoring)
8. On accept: write file to `skills/adversarial-review/defaults/reviewers/<name>.md`, bump `.claude-plugin/plugin.json` patch version, print diff summary, remind to commit
9. On reject: explain failed signals, offer to revise rather than ship a default that wouldn't pass its own audit

Doesn't auto-commit. Doesn't push. Source-repo only.

### 5.6 — No `delete-default` subcommand

Removing a default is rare and trivially handled manually (`rm` + version bump). Don't build a subcommand for a once-in-a-while operation.

---

## Topic 6 — Migration mechanics (RATIFIED)

Sequenced by dependency: agent files first (the contract), then SKILL.md (orchestration), then docs (description of steady state).

### 6.1 — File reorganization

In `/Users/johnmoses/claude-materia/skills/adversarial-review/`:

```
Before                          After
─────────────────────────────────────────────────────────────
agents/coherence.md       →    defaults/reviewers/coherence.md
agents/design.md          →    defaults/reviewers/design.md
agents/detail.md          →    defaults/reviewers/detail.md
agents/triage.md          →    agents/triage.md       (stays)
agents/fixer.md           →    agents/fixer.md        (stays)
                          (new) agents/auditor.md
```

System agents stay in `agents/`; reviewer defaults move to `defaults/reviewers/`. The new auditor system agent gets created.

### 6.2 — Agent file changes

| File | Change |
|---|---|
| `defaults/reviewers/coherence.md` | Move only. Content already portable (no env-specific references — verified). |
| `defaults/reviewers/design.md` | Move only. |
| `defaults/reviewers/detail.md` | Move only. |
| `agents/triage.md` | **Significant rewrite.** Add normalization role (1.1), `source_trace` per finding with three shapes (1.2), severity_guidance as hint (1.3), `interpretation_note` field. New JSON schema reflecting these additions. |
| `agents/fixer.md` | Minor — confirm reads `findings[]` from triage's structured output (still works post-rewrite). Add note: fixer ignores `source_trace`/`interpretation_note`/`raw_extractions` (triage-internal fields). |
| `agents/auditor.md` | **Brand new.** Heuristics from 2.6 (4 accept signals, 5 reject signals). Verdict logic. Output format with signal-by-signal reasoning. |

### 6.3 — SKILL.md rewrites

Sections to rewrite:

1. **Phase 1 Step 3** — replace "build agent pool from skill's `agents/`" with the discovery + audit pipeline (Stages 1-4 from 2.5/3.6) + recommendation (3.1-3.5).
2. **Phase 1 Step 4** — pool confirmation now operates on audit-cleared candidates with namespace display, includes 4.1-4.4 mechanics. Pool locks after confirmation per 4.5.
3. **Phase 2** — minor updates referencing triage's expanded role (extraction + normalization + source traces).
4. **Adding a Reviewer** section — **delete entirely.** Replaced by short paragraph: "To add a reviewer, drop a `*.md` file in your pool source directory. The skill discovers and audits it on the next session."
5. **Removing a Reviewer** section — **delete entirely.** Same treatment.
6. **`## Environment` section** — update to declare the source-config contract (`adversarial-review.reviewers_dir`).
7. **Frontmatter** — update `argument-hint` per 5.4.
8. **Subcommands list** at top — remove `add` and `remove` entries; add `create-default`.
9. **New section: "Pool sources and namespacing"** — document the four namespaces (default/env/override/manual), how discovery resolves them, how to configure via env.
10. **New section: "create-default (author mode)"** — document the source-repo-gated authoring subcommand per 5.5.

### 6.4 — Repo-level documentation

| File | Update |
|---|---|
| `claude-materia/CLAUDE.md` | Update the skill's directory structure (defaults/, new auditor agent). Note the relaxed-contract / consumer-side audit philosophy. |
| `claude-materia/README.md` | New section: "Writing a custom reviewer" — minimum contract (name + body), recommended shape, where to put the file. |

### 6.5 — Version bump

`.claude-plugin/plugin.json`: bump to **0.5.0**. Significant new capability (injectable agents, audit pipeline) + breaking removal (`add`/`remove` subcommands gone, agent location moved).

### 6.6 — Cleanup

After execution and verification:
- Delete `skills/adversarial-review/MIGRATION.md` (transient working file, this document).
- Verify session snapshot logic in `skills/adversarial-review/sessions/` still works against the new pool location (it copies discovered agents per-session — should be source-agnostic).
- Confirm no other file references `<skill>/agents/coherence.md` etc. directly.

### 6.7 — Execution sequence

```
1. Create defaults/reviewers/ directory; move three reviewer files.
2. Write new agents/auditor.md (with heuristics from 2.6).
3. Rewrite agents/triage.md (normalization, source_trace, severity-as-hint).
4. Update agents/fixer.md (minor).
5. Rewrite SKILL.md (largest single change — see 6.3 for sections).
6. Update claude-materia/CLAUDE.md.
7. Update claude-materia/README.md.
8. Bump .claude-plugin/plugin.json to 0.5.0.
9. Post-execution verification: dispatch coherence reviewer (from new
   defaults/reviewers/) against the final SKILL.md to verify implementation
   matches plan.
10. Delete MIGRATION.md.
```

---

## Open architectural points (surfaced, deferred)

- Mid-loop pool modification (adding/removing agents during Phase 2). Deferred to future enhancement; pool is locked after Phase 1 confirmation in v1.
- Permanent disable mechanism for unwanted defaults (`adversarial-review.disable_defaults: [coherence]` env field). Deferred until repeated pruning of same default emerges as a real friction pattern.
- A `/adversarial-review audit <file>` subcommand that runs the auditor against a candidate without adding it to a pool. Useful for authors and curious users; not required for v1.
