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

## Glossary

Terms used throughout this document:

- **`<skill-directory>`** — resolves at runtime to the directory containing the running skill's SKILL.md. In source: `/Users/johnmoses/claude-materia/skills/adversarial-review/`. At runtime under a plugin install: the resolved skill path. The trust-by-source check (2.5) compares against this resolved path.
- **Namespaces** — the four pool-source namespaces are `default`, `env`, `override`, `manual`. They are declared authoritatively in 4.3. References elsewhere (3.1, 3.5, 6.6, 6.7) resolve to that authoritative declaration.

For consistency, this document uses `<skill-directory>` everywhere. Any earlier `<skill>` references should be read as `<skill-directory>`.

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

Every finding also has an `interpretation_note` field (REQUIRED for `region` and `synthesis` shapes; OPTIONAL for `quote` — empty string is acceptable when the quoted text appears verbatim within a single reviewer-output paragraph). Non-empty notes explain why the trace shape was chosen.

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
| `trigger` | no default — required when `required: false` (see 2.3) |
| `precondition` | `"always met"` (agent runs every iteration) |
| `severity_guidance` | `null` (triage uses own calibration per 1.3) |

`trigger` has no default because the only case where it's meaningful is `required: false`, and in that case it is mandatory (per 2.3) — an absent trigger on an optional agent makes the agent uninvokable, which is a hard reject, not a soft warning.

If an agent file has a `role` field, the skill ignores it. Other skills are free to use it; agents are now cross-skill-compatible.

### 2.3 — Hard rejects (excluded from pool)

| Reject | Reason |
|---|---|
| Frontmatter doesn't parse as YAML | Auditor can't read the file |
| Missing or empty `name` | Orchestrator can't reference it |
| Empty prompt body | Nothing to dispatch |
| `precondition` references another agent by name in a runtime-dependency pattern (e.g., `after:<agent-name>`, `requires:<agent-name>`, or any pattern indicating one agent depends on another's prior execution). Innocuous prose mentions (e.g., "designed to detect coherence violations") are not rejected — the rule targets coupling, not vocabulary. | Loop self-regulation invariant |
| `required: false` without `trigger` | Optional agent with no way to be auto-included is uninvokable |
| Auditor verdict: reject | Semantic audit failure (skipped for bundled defaults; cache-hit verdicts count) |

**Name collisions are not rejects** — they're resolved by namespacing (see below).

### 2.4 — Soft warnings (accepted with flag)

- Missing `description` — pool listing sparse
- Missing `precondition` — agent runs every iteration; can't self-regulate
- Unknown frontmatter fields (other than `role`, which is silently ignored per 2.2) — probable typo of a known field

Soft warnings do not affect pool inclusion. A soft-warned agent is fully audit-cleared and proceeds into Stage B's recommendation logic identically to a clean agent. Warnings are surfaced alongside the agent at confirmation for user awareness — they don't gate inclusion.

### 2.5 — Audit pipeline at Phase 1 Step 3a

Four-step pipeline runs before pool confirmation (the term **Step** is used here to keep "Stage" reserved for the top-level A/B/C taxonomy in Topic 3):

```
Step 1: Pre-check (cheap, deterministic, runs on all candidates)
  - Parse frontmatter, check 2.3 structural rejects
  - Sanity-checks even bundled defaults haven't been corrupted

Step 2: Semantic audit (LLM-driven, with caching per 3.6)
  - SKIP for candidates from <skill-directory>/defaults/reviewers/
    → verdict: accept (trusted: bundled default by repo convention)
  - RUN for all other candidates
    → auditor evaluates the full 2.6 rubric: signal list + verdict logic + signal-by-signal output format, emits verdict + reasoning
    → cache lookup short-circuits on (auditor_hash, agent_hash) hit

Step 3: Soft warning attachment

Step 4: Compile audit report
  - Write `review/agent-audit.md`, present at pool confirmation
```

The trust-by-source rule scopes only to `<skill-directory>/defaults/reviewers/`. Env-declared pools, `--reviewers` overrides, and ad-hoc references all get audited.

**Trust-by-source for bundled defaults — what this guarantees and what it doesn't.** Bundled defaults are trusted by *repo convention*: the audit step is skipped because the repo's review process is expected to enforce audit-passing at merge time, not at session time. The recommended authoring path is `/adversarial-review create-default` (5.5), which runs the auditor heuristics inline before writing the file — but this is a **point-in-time** check: the self-audit verifies a default against the auditor heuristics *current at authoring time*. When `agents/auditor.md` later evolves (new accept/reject signals, changed verdict logic), previously-authored defaults are **not** re-audited automatically; they remain trusted by repo convention, not by audit-being-fresh. Hand-authored defaults (a contributor edits `defaults/reviewers/*.md` directly) are **author-responsible**: the contributor is on the hook for verifying audit-passing before merging, since the session-time pipeline will not catch a malformed default. This is a deliberate trade — zero session-time cost on the trusted hot path; the audit-passing claim is point-in-time, with a maintenance obligation to re-run `create-default` (or a future `audit-defaults` maintenance subcommand) over existing defaults whenever `auditor.md` changes.

**The auditor itself is not audited.** `agents/auditor.md` is a system agent (lives in `agents/`, not `defaults/reviewers/`) and is never a candidate for the reviewer pool. It is therefore never audited at session-time or authoring-time — neither by the discovery pipeline nor by `create-default`. Quality of the auditor is purely author-responsible (enforced at PR-review time on this repo). Auditing the auditor with itself would be incoherent.

**"Audited" includes cache-hits.** When 2.3 lists "Auditor verdict: reject" as a hard reject, that verdict can come from either a fresh auditor dispatch or a cache-hit on `(auditor_content_hash, agent_content_hash)`. A cached verdict *is* the audit result for that content pair until either input changes. There is no separate "stale cache" failure mode at the 2.3 level — content-hash keying makes cache invalidation automatic.

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

Joins `triage.md` and `fixer.md` as a third system agent. Runs on opus. Inputs: candidate agent file. **`agents/triage.md`'s prompt body is the canonical declaration of the triage data-model schema** (findings schema with source_trace shapes, severity calibration, gate JSON structure from 1.2). Auditor's prompt body **mirrors** that schema declaration inline — it does not redeclare it independently. Treat any change to triage.md's schema declaration as requiring a matching edit to auditor.md, and vice versa: the two must move together. This couples them deliberately, avoiding a separate doc file. (Future work: a CI check or post-edit reminder could enforce this lockstep automatically.) Outputs: verdict + signal-by-signal reasoning.

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

Three sources, all additive. No source replaces another.

| Source | Namespace | Trust | When scanned | How agents are picked up |
|---|---|---|---|---|
| Bundled defaults | `default` | Trusted (repo convention; see 2.5) | Always | Skill scans `<skill-directory>/defaults/reviewers/` |
| Env-configured | `env` | Audited | Always (if env declares anything) | Env lists explicit paths the user wants always-included |
| Ad-hoc references | `override` (via flag) / `manual` (confirmation-time) | Audited | Only when explicitly named | `--reviewers <ref>`, confirmation-time addition, or `run <ref>` resolves `<ref>` per the rules in 3.5 |

**Key shift from prior drafts.** There is no "default user pool" auto-scanned from `~/.claude/agents/`. The only always-on sources are bundled defaults plus whatever the env declares. `~/.claude/agents/` is traversed *only* when the user explicitly references an agent by bare name (3.5). First-run audit cost is therefore bounded by user intent — only agents the user explicitly references get audited — not by directory contents.

To use only one source, prune the others at pool confirmation.

### 3.2 — Bundled defaults shipped

The skill ships `coherence`, `design`, `detail` at `<skill-directory>/defaults/reviewers/`. Three reasons:
1. Zero-config UX matters — works the moment the plugin is installed, with no env configuration required.
2. The three reviewers are good baseline content for any artifact.
3. They serve as canonical examples of the preferred shape (reduces triage workload for users writing custom reviewers).

### 3.3 — No project-local source in v1

Not adding a fourth source like `.claude/adversarial-review/reviewers/` in cwd. Env-declared pools can already point at project-local paths if needed. YAGNI.

### 3.4 — Discovery is non-recursive

Each source directory is walked non-recursively. Every `*.md` file at the top level is a candidate; subdirectories are ignored. Subdirs can serve as user-managed staging areas for in-progress reviewers.

### 3.5 — Source configuration and reference resolution

**Bundled defaults** resolve to `<skill-directory>/defaults/reviewers/`. Always scanned, trusted by repo convention (see 2.5).

**Env-configured pools** are declared in `~/.claude/env/index.md` under `adversarial-review.reviewers_dir`. The value may be a single path or a list of paths. Each path is walked per 3.4 (non-recursive). If the env file is absent or doesn't declare this key, no env-configured pool is contributed — the skill simply runs with bundled defaults plus any ad-hoc references the user provides.

**Edge cases for env-declared paths** (mirroring 3.6's edge cases):
- Path doesn't exist → warn at discovery, exclude from sources, continue.
- Path exists but is a file (not directory) → treat as single-file source (most charitable), or warn and skip if unreadable.
- Empty directory → warn ("env declares X but found no `*.md` files"), continue.
- Malformed YAML value → warn and skip that entry.
- All warnings surfaced at confirmation alongside the candidate list, so silent zero-contribution is impossible.

**Ad-hoc references** are how the user names an additional agent at any of three entry points: the `--reviewers <ref>` invocation flag, confirmation-time additions (4.1), or the `run <ref>` subcommand (5.3). The same resolution rules apply at all three:

| Pattern | Resolution |
|---|---|
| Starts with `/` | Absolute path |
| Starts with `./` or `../` | Cwd-relative path |
| Starts with `~/` | Home-relative path |
| Contains `/` (anywhere else) | Treated as path |
| Starts with `<known-namespace>:` (where known namespace is one of `default`, `env`, `override`, `manual` per 4.3) | Namespace-prefixed reference of the form `<namespace>:<name>`; the name resolves within that source's discovered candidates. Useful when referring to an already-discovered agent by the same string the audit report and output filenames use. If a colon is present but the prefix is not a known namespace, treat as a hard error (do not fall through to other patterns) — unknown-namespace references almost certainly indicate a typo. |
| Otherwise (bare name) | Resolved via traversal of `~/.claude/agents/` — find first `*.md` file matching the name |

A resolved path can point at a file (single agent) or a directory (multi-agent source, walked per 3.4 — non-recursive). (Note: a directory reference can expand the candidate count significantly; the cost is made visible at the pre-audit summary in 3.6 before any auditor dispatch.)

The bare-name case is the only path on which `~/.claude/agents/` is touched. The skill does not auto-scan that directory; it only traverses it to resolve a name the user has explicitly typed.

### 3.6 — Audit caching (content-hash keyed)

Even with audit scope bounded by explicit user reference, repeated sessions against the same agents would re-pay LLM cost on every run. Solution: cache verdicts keyed on `(auditor_content_hash, agent_content_hash)`.

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

Pipeline integration (Step 2 of 2.5's audit pipeline):

```
For each candidate that passed pre-check:
  a. SKIP if source is bundled defaults (trusted)
  b. Compute auditor_hash = SHA-256(<skill-directory>/agents/auditor.md)
     Compute agent_hash   = SHA-256(<candidate-file>)
  c. Cache lookup at audit-cache.json[auditor_hash][agent_hash]:
       HIT  → use cached verdict, mark "from cache" in audit report
       MISS → dispatch auditor, write result to cache
  d. Apply verdict (cache-hits count as audit verdicts per 2.5)
```

Cost transformation: from O(sessions × agents) LLM calls to O(unique-content-versions × auditor-versions) LLM calls. With the source model in 3.1 the audited set is already small (env-configured paths plus explicitly-referenced ad-hoc agents — bundled defaults skip outright); caching collapses repeat-cost on top of that. Stable references with a stable auditor → effectively one audit per agent, ever.

Edge cases:
- Cache file missing → create on first write
- Cache file malformed → warn, treat as empty for this session, overwrite on next write (cache is optimization, not load-bearing)
- Concurrent sessions → both audit, last writer wins, verdicts identical anyway

The audit report (`review/agent-audit.md`) annotates each verdict as "from cache" or "fresh audit" for provenance.

**Pre-audit summary at confirmation.** Before dispatching the auditor, the orchestrator computes the candidate count per source and the cache-miss count (how many would require fresh audit). At confirmation, the user sees this summary and can abort if the cost is unexpected. Format: `env: 12 candidates (3 require fresh audit). manual: 2 candidates (2 require fresh audit). default: 3 candidates (skip — trusted).`

The summary is computed once before the initial confirmation prompt. Confirmation-time additions (per 4.1) audit immediately on supply with the auditor's verdict shown inline; the per-addition cost is surfaced as each reference is supplied. The cost-abort affordance applies to the initial summary; users adding references during confirmation see verdicts (and cache-hit/miss status) per addition. When a confirmation-time addition resolves to a directory (multi-agent source per 4.2), a brief per-batch summary is shown before dispatch — e.g., `manual addition <path> resolves to N candidates, M require fresh audit — proceed?` — preserving the cost-preview affordance for that path. Single-file additions skip the pre-batch summary and use the inline-verdict pattern unchanged.

**Cache-invalidation property.** Any edit to `agents/auditor.md` (including formatting-only changes) changes its content hash, invalidating every cached verdict under the old auditor. Subsequent sessions re-pay the full audit cost across all sessions on next run. This is a deliberate trade — the alternative (extracting only heuristic-bearing portions for hashing) requires a stable extraction rule and adds maintenance complexity. Mitigation: include "auditor changed; full audit re-run" as a notice in the audit report when the auditor hash differs from the previous session's. To amortize the full-cache invalidation cost across users, auditor.md edits should be batched with triage.md schema changes when possible (since both must move together per the lockstep obligation in 2.6's "New system agent" subsection). No structural mitigation in v1 — shared-snippet machinery is over-engineering for current scale.

**Previous-session auditor hash bookkeeping.** The audit cache file's top-level structure includes a `last_auditor_hash` field; on session start, the orchestrator compares the current auditor.md hash against this field. If different, the session-start audit report includes "auditor changed; full audit re-run" as a notice. The field is updated to the current hash after the session's audits complete.

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
  Iterations run with a LOCKED source set
    ←── 4.5: no new agents discovered, audited, or added
  Pool MEMBERSHIP may shift across iterations:
    - triage's `precondition_evaluations` promotes dormant candidates
      whose preconditions become satisfied as the artifact evolves
    - triage's `next_reviewers` selects which currently-eligible agents
      run next iteration
```

### 4.1 — Confirmation-time additions go through the audit pipeline

During the Phase 1 confirmation step (before pool lock), the user can supply additional references. Each reference resolves per the rules in 3.5 — it can be an absolute, cwd-relative, home-relative, or otherwise-pathy string, or a bare name resolved against `~/.claude/agents/`. Each resolved candidate runs through Step 1 + Step 2 of the audit pipeline (with caching per 3.6). Auditor's verdict shown; user can accept or override.

### 4.2 — Reference can resolve to file or directory

A reference supplied at confirmation can resolve to:
- A file path (`*.md`) → single-agent source
- A directory path → multi-agent source (non-recursive walk per 3.4)

Bare-name resolution always lands on a single `*.md` file (the first match in `~/.claude/agents/`). Path-form references can point at either.

Principle of least surprise — point at one thing, get one thing.

### 4.3 — Confirmation-time additions get namespace `manual`

| Source | Namespace |
|---|---|
| Invocation flag (`--reviewers`) | `override` |
| Confirmation-time addition | `manual` |
| Env pool | `env` |
| Bundled defaults | `default` |

Within the `manual` namespace, duplicate references (same agent supplied twice in one confirmation) are deduplicated — the user's intent is interpreted as "include this agent," not "run it twice." Cross-source collisions (e.g., `default:coherence` and `manual:coherence`) still coexist as distinct agents per 2.3.

### 4.4 — Pruning is per-session only

User pruning at confirmation is a per-session decision. No state persists across sessions. No `.disabled` markers, no permanent disable mechanism. If repeated pruning of the same default emerges as a pattern, future v2 candidate is `adversarial-review.disable_defaults: [coherence]` env field. Not in v1.

### 4.5 — Pool source set is locked after Phase 1 confirmation; pool *membership* may be reevaluated each iteration

Once confirmed, no new agents can be discovered, audited, or added — the set of source files is sealed. But within that locked set, triage's `precondition_evaluations` may promote dormant candidates (those that didn't run in iteration 1 because their preconditions weren't met) into the active roster as the artifact evolves. This preserves the audit-cost invariant the lock was designed to protect (no mid-loop LLM dispatches for new audits) without freezing the iteration-1 view of which agents apply. Mid-loop additions of *new* agent sources remain a future enhancement; they would require both new audit dispatches and reevaluation of iteration history coherence.

---

## Topic 5 — Subcommands + authoring tooling (RATIFIED)

The `add` and `remove` subcommands existed to manage agents inside a closed plugin. The new architecture removes the need entirely. Authoring tooling for skill authors is reintroduced as a separate, source-repo-gated subcommand.

### 5.1 — Drop `/adversarial-review add <agent-file>`

End-users add reviewers either by reference at session start (`--reviewers <ref>` or confirmation-time addition, resolved per 3.5) or by declaring the path under `adversarial-review.reviewers_dir` in their env file for always-on inclusion. No subcommand needed.

### 5.2 — Drop `/adversarial-review remove <agent-name>`

End-users remove via filesystem (delete from pool source) or per-session pruning at confirmation. No subcommand needed.

### 5.3 — Keep `/adversarial-review run <ref> [path]`

Reframed as **scaffolded single-reviewer dispatch for rapid iteration during artifact development**. Behavior:
- Runs same discovery + audit pipeline as full loop, restricted to the agent identified by `<ref>`
- Builds `ARTIFACT.md` (Phase 1 Step 1 logic)
- Builds minimal flags file
- Resolves `<ref>` per the rules in 3.5 (absolute / cwd-relative / home-relative / pathy / bare name against `~/.claude/agents/`)
- If `<ref>` already corresponds to a discovered candidate from bundled defaults or env-configured pool (matched by namespace + name or by resolved path), the existing audit verdict is reused
- Dispatches the named agent in single-pass mode (no triage, no fixer, no loop)

Display in single-pass mode follows the same shortest-unambiguous-form rule as the full loop (just the agent name when unambiguous, namespaced form when not).

Distinction vs raw Task dispatch: `run` provides the calling-convention scaffolding (ARTIFACT.md, flags, audit gate) that reviewers expect. Raw dispatch is always available as an escape hatch for users who explicitly want no ceremony.

### 5.4 — Update `argument-hint` frontmatter

```
[subcommand] [args] — run <ref> [path], create-default (author mode), or just [artifact-path] for the full loop
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
7. Self-audit: run the full 2.6 rubric: signal list + verdict logic + signal-by-signal output format inline (Claude evaluating against the rubric in the same context as authoring). This is a **point-in-time** check against the auditor heuristics current at authoring time — drift over time (when `auditor.md` evolves) is handled by repo conventions or a future `audit-defaults` maintenance subcommand, not by re-auditing on each session.
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
| `agents/fixer.md` | Minor — confirm reads `findings[]` from triage's structured output (still works post-rewrite). Add note: fixer ignores `source_trace`/`interpretation_note` (triage-internal fields per 1.2). |
| `agents/auditor.md` | **Brand new.** Must enumerate the 4 accept signals and 5 reject signals from 2.6 by name. Must apply the verdict logic from 2.6 verbatim. Output must follow the format template in 2.6 (signal-name + strength + reasoning + verdict line). Must mirror `agents/triage.md`'s findings schema declaration inline (source_trace shapes, severity calibration, gate JSON structure) — `triage.md` is the canonical source. Treat any change to triage.md's schema as requiring a matching edit here, and vice versa. |

### 6.3 — SKILL.md rewrites

Sections to rewrite:

1. **Phase 1 Step 3** — replace "build agent pool from skill's `agents/`" with the discovery + audit pipeline (Steps 1-4 from 2.5, with caching per 3.6) + recommendation (3.1-3.5).
2. **Phase 1 Step 4** — pool confirmation now operates on audit-cleared candidates with namespace display, includes 4.1-4.4 mechanics. Pool locks after confirmation per 4.5.
3. **Phase 2** — minor updates referencing triage's expanded role (extraction + normalization + source traces).
4. **Adding a Reviewer** section — **delete entirely.** Replaced by short paragraph: "To add a reviewer at session start, pass `--reviewers <ref>` or supply it at the confirmation prompt. To make a reviewer always-on, declare its path in `~/.claude/env/index.md` under `adversarial-review.reviewers_dir`. The skill discovers and audits it on the next session."
5. **Removing a Reviewer** section — **delete entirely.** Same treatment.
6. **`## Environment` section** — update to declare the source-config contract (`adversarial-review.reviewers_dir`).
7. **Frontmatter** — update `argument-hint` per 5.4.
8. **Subcommands list** at top — remove `add` and `remove` entries; add `create-default`.
9. **New section: "Pool sources and namespacing"** — document the four namespaces (default/env/override/manual), how discovery resolves them, how ad-hoc references resolve (3.5), and how to configure the env path.
10. **New section: "create-default (author mode)"** — document the source-repo-gated authoring subcommand per 5.5.

### 6.4 — Repo-level documentation

| File | Update |
|---|---|
| `claude-materia/CLAUDE.md` | Update the skill's directory structure (defaults/, new auditor agent). Note the relaxed-contract / consumer-side audit philosophy. |
| `claude-materia/README.md` | New section: "Writing a custom reviewer" — minimum contract (name + body), recommended shape, where to put the file. |

### 6.5 — Version bump

`.claude-plugin/plugin.json`: bump to **0.5.0**. Significant new capability (injectable agents, audit pipeline) + breaking removal (`add`/`remove` subcommands gone, agent location moved). Users who relied on the `add`/`remove` subcommands need to migrate: drop the file in their pool source (or use ad-hoc `--reviewers <path>`) instead. No deprecation period — the subcommands are removed cleanly at 0.5.0.

### 6.6 — Cleanup

After execution and verification:
- Delete `skills/adversarial-review/MIGRATION.md` (transient working file, this document).
- Verify the per-session agent snapshot logic. Snapshot semantics post-migration: the per-session agent snapshot copies the resolved-and-confirmed pool (output of Stage A+B+C) into `sessions/<id>/agents/`. Filenames use namespace-prefixed form: `default__coherence.md`, `manual__custom-thing.md`, etc. — matching the output-file naming convention from 2.3. This snapshot reflects the actual locked pool, not source directory contents. Verify by: (a) grep the skill source code for hardcoded reviewer-pool paths — e.g., `grep -rn 'agents/coherence' skills/adversarial-review/ --exclude-dir=sessions` (and similar for `agents/design`, `agents/detail`) — to confirm no literal hardcoded path remains in the snapshot or discovery logic; (b) reading the snapshot code path and confirming pool location is derived from runtime discovery, not a literal string. If either check fails (literal hardcoded path found in step a, or pool location not derived from runtime discovery in step b), surface as a step 9 failure — fix before proceeding to step 10.
- Confirm no other file references `<skill-directory>/agents/coherence.md` etc. directly.

### 6.7 — Execution sequence

**Atomicity contract**: execute the sequence on a fresh git branch (e.g., `migration/injectable-reviewers`). Each step's changes are staged but not committed until step 9 verification passes. On any failure during steps 1-8, do not commit — surface the failure to the user, leave the working tree as-is for inspection. Step 10 (MIGRATION.md deletion) only happens after step 9 passes per its specified criterion.

```
1. Create defaults/reviewers/ directory; move three reviewer files.
2. Write new agents/auditor.md (with heuristics from 2.6).
3. Rewrite agents/triage.md (normalization, source_trace, severity-as-hint).
4. Update agents/fixer.md (minor).
5. Rewrite SKILL.md (largest single change — see 6.3 for sections).
6. Update claude-materia/CLAUDE.md.
7. Update claude-materia/README.md.
8. Bump .claude-plugin/plugin.json to 0.5.0.
9. Post-execution verification: dispatch the full `/adversarial-review` loop
   against the rewritten SKILL.md. The loop runs all bundled-default reviewers
   (coherence, design, detail) with triage, producing structured findings with
   severity. Step 9 executes from the source checkout
   (`/Users/johnmoses/claude-materia/`), with the migration's working-tree
   changes in place. `<skill-directory>` resolves to
   `skills/adversarial-review/` within that checkout — *not* the installed
   plugin path.

   Pass criterion: halt if any finding has severity `high` or `critical` — do
   not proceed to step 10. Surface findings with the context that step 10
   (MIGRATION.md deletion) is blocked pending resolution. Medium/low findings
   are advisory; log them and proceed. Always preserve the loop's output at
   `review/post-migration-verification.md` regardless of outcome.

   Lockstep verification (alongside the full-loop dispatch): verify that
   `agents/auditor.md` contains a canonical anchor string from
   `agents/triage.md`'s schema declaration — e.g., grep for
   `source_trace.shape == 'quote'` or another distinctive token from triage's
   findings format. If absent, the lockstep coupling declared in 2.6's "New
   system agent" subsection has been broken — surface as a step 9 failure.
10. Delete MIGRATION.md.
```

---

## Open architectural points (surfaced, deferred)

- Mid-loop pool modification (adding/removing *new agent sources* during Phase 2). Deferred to future enhancement; the pool source set is locked after Phase 1 confirmation in v1, though pool *membership* may shift via precondition reevaluation per 4.5.
- Permanent disable mechanism for unwanted defaults (`adversarial-review.disable_defaults: [coherence]` env field). Deferred until repeated pruning of same default emerges as a real friction pattern.
- A `/adversarial-review audit <file>` subcommand that runs the auditor against a candidate without adding it to a pool. Useful for authors and curious users; not required for v1.
