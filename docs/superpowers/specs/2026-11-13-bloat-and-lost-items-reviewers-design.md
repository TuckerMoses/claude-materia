# Bloat and lost-items reviewers for adversarial-review: design

Status: draft, awaiting approval. Target: claude-materia plugin 0.14.0 → 0.15.0.

All paths below are relative to `skills/adversarial-review/` unless they start with `review/` or `iterations/`, which are relative to a session directory (`<plugin-data-dir>/sessions/<id>/`; `iterations/` is shorthand for `review/iterations/`).

## Intent

The review loop has two regressions it cannot see today:

1. **Loss.** If the round-1 fixer drops important point A, round 2's reviewers see only the current files. Nothing tells them A was ever there, so nothing blocks the loop from exiting clean without it.
2. **Bloat.** Each round's fixer adds text to answer that round's findings, often text that qualifies or repairs text an earlier round added. Nothing checks that the artifact's size stays proportionate to what it says.

Both are invisible for the same reason: no agent in the loop can see the pre-review original. Reviewers receive the current scope files, `SCOPE.md`, the manifest, and prior triage output. `pre_review_vcs_ref` is recorded but only the scribe receives it.

## Goals

- A dropped or weakened point from the original blocks the gate until it is restored or the user accepts the loss.
- Text the loop added that carries no new required meaning blocks the gate until it is consolidated.
- Both checks run on every round after the fixer first changes the scope, including the opus tier, and must pass before `exit_clean`.
- Works with git, jj, or no VCS.

## Non-goals

- Judging bloat that was already in the original. Only loop-added text is in scope.
- Judging whether the original's points were good. Lost-items protects what was there; design and coherence judge it.
- Changing the scribe, the `route.json` schema, or the gate rule.
- Giving reviewers the ability to run commands. Reviewers stay passive readers.

## Anti-goals

- The two reviewers fighting each other (bloat says cut, lost-items says restore) round after round.
- Lost-items re-raising, every round, a removal that a finding legitimately called for.
- The orchestrator reading substance to support any of this.

## Approaches considered

**A. Baseline snapshot plus removal ledger (chosen).** Copy the original scope files into the session at setup. Each round, a deterministic diff of baseline against current is written to a file. Both reviewers read baseline, diff, and the fixer changelogs. The fixer logs every removal against the finding that called for it.
Trade-off: touches SKILL.md, triage, fixer, and auditor, not just two new files. The cumulative diff grows as the loop runs, so each round's check costs more than the last.

**B. Up-front inventory.** At tier-init an agent extracts a list of the original's important points; lost-items checks the current scope against the list each round.
Rejected: the extraction is itself a lossy LLM pass. It can drop point A exactly as the fixer did, and then nothing downstream can recover it. The raw original cannot lose anything.

**C. Reviewers diff against the VCS ref themselves.** Hand reviewers `pre_review_vcs_ref` and let them run `git diff`.
Rejected: reviewers are required to be passive observers (auditor reject signal 1), and it fails with no VCS.

**D. Per-round diffs only (previous round → current).** Cheaper per round.
Rejected: a reviewer that misses a loss in the round it happened never sees it again, which is the exact failure being fixed. Comparison must always be against the original.

## Design

### 1. Baseline snapshot (SKILL.md, Phase 1 step 5)

When the session directory is populated, the orchestrator copies every file in the resolved scope to `review/baseline/`, mirroring each file's absolute path with the leading `/` removed (`/a/b/c.md` → `review/baseline/a/b/c.md`). The copy is done with Bash `cp`; the orchestrator never Reads the files.

This happens after the step-2 VCS checkpoint, so the baseline equals the content at `pre_review_vcs_ref`. The baseline is written once and never updated, in both `live` and `pinned` scope modes and across the tier promotion.

`review/session-meta.json` gains `baseline_dir` (the absolute path of `review/baseline/`).

### 2. Per-iteration baseline comparison (SKILL.md, Phase 2)

At the start of every numbered iteration, immediately before dispatching reviewers (step 3 `continue`, between b and c), the orchestrator runs one Bash command that writes two files into the new iteration directory, with all output redirected to those files so nothing enters orchestrator context:

- `iterations/<tier>-<N>/baseline.diff`: unified diff from `review/baseline/` to the current files. The file set compared is the union of the baseline's files and the current resolved scope. A file present on only one side is diffed against empty, so a deleted file appears as all-removed and a created file as all-added.
- `iterations/<tier>-<N>/baseline-sizes.tsv`: one row per file in that union: path, baseline lines, current lines, delta; plus a `TOTAL` row. A missing side counts as 0.

It runs unconditionally, whether or not either new reviewer is dispatched; the orchestrator does not reason about which reviewers need it. In iteration 1 of the cheap tier the diff is empty. The orchestrator obtains the current resolved scope the same way Phase 1 does (expand `locations` minus `exclude` for `live`; read `scope-pinned.json` for `pinned`).

The orchestrator generates this, rather than triage, because triage authors round N+1's dispatch prompts before the round-N fixer runs; the post-fix state does not exist yet when triage writes them.

Both files are added to the Read-discipline rule's MUST NOT Read list.

### 3. Dispatch prompt (agents/triage.md §3)

The reviewer dispatch template gains a section, written identically for every reviewer so triage never special-cases a reviewer by name:

```markdown
## Session inputs
- Baseline (pre-review original): <baseline_dir>
- Baseline diff for this iteration: iterations/<tier>-<N+1>/baseline.diff
- Size table for this iteration: iterations/<tier>-<N+1>/baseline-sizes.tsv
- Fixer changelogs so far: [paths, oldest first; "none" if the fixer has not run]
- Accepted risks: review/accepted-risks.json
```

Triage's dispatch context gains `baseline_dir`, `next_baseline_diff_path`, and `next_baseline_sizes_path` so it writes these paths without computing them. The files at the two `next_*` paths do not exist when triage writes the prompt; the orchestrator creates them before the reviewer is dispatched.

Reviewers that do not need these inputs ignore them. User-supplied reviewers may use them.

### 4. Removal ledger (agents/fixer.md)

The changelog template gains a required section between "Findings addressed" and "File operations":

```markdown
## Removals
[One entry per passage whose meaning no longer appears at its original location. "None" if there are none.]

- **File**: A.md
  **Removed**: [quote, or a precise description if longer than a few lines]
  **Finding**: f-c-2-1
  **Disposition**: deleted | moved to <file, section> | merged into <file, section>
```

A rewrite counts as a removal when any statement the old text made is no longer made by the new text.

New constraint: do not delete, weaken, or drop content unless the finding being addressed calls for it. Content that must move or merge keeps its full meaning at the destination. When executing a consolidation, every distinct condition, exception, and example in the passages being merged survives the merge.

The ledger does not need to be trustworthy to be useful. An accidental drop is by nature unlogged, and an unlogged loss is exactly what lost-items reports.

### 5. `defaults/reviewers/lost-items.md`

Frontmatter:

- `required: true`, `trigger: null`
- `precondition`: "The fixer has modified at least one scope file since the pre-review baseline, and the current state has not been checked against the baseline for lost content"
- `severity_guidance`: `dropped_content` high; `weakened_requirement` high; `dropped_detail` medium

What it checks, working from the removed lines in `baseline.diff` and confirming against the baseline and current files:

- **dropped_content**: a point, rule, requirement, or section the baseline stated that the current scope states nowhere.
- **weakened_requirement**: a constraint that survives in softer form: `must` became `should`, a condition or exception was added that narrows it, a number loosened, a prohibition became advice.
- **dropped_detail**: an example, edge case, rationale, or qualifier that supported a surviving point and is gone.

A removal is **not** a finding when any one of these holds:

1. The meaning appears elsewhere in the current scope (moved, merged, or reworded). Wording changes are never findings; only meaning is compared.
2. A fixer changelog's Removals section logs it against a finding, and that finding's description or suggestion in the cited `triage-output.json` did call for removing or replacing that meaning. A ledger entry citing a finding that did not call for the removal does not excuse it.
3. An entry in `accepted-risks.json` covers it.

Each finding quotes the baseline text, names the baseline file and location, states which current file it should live in, and (when known from the changelogs) the iteration that removed it. The suggestion is to restore the meaning in the fewest words that carry it, at the place the current structure puts such content; it does not ask for the original wording back.

Does not check: whether the lost content was good, whether the artifact is consistent, anything about added text.

If the dispatch prompt carries no baseline (the single-pass `run` subcommand), it states that no baseline was provided and emits no findings.

### 6. `defaults/reviewers/bloat.md`

Frontmatter:

- `required: true`, `trigger: null`
- `precondition`: "The fixer has modified at least one scope file since the pre-review baseline, and the current state has not been checked for loop-added bloat"
- `severity_guidance`: `redundant_restatement` medium; `patch_on_patch` medium; `unmotivated_addition` medium; `defensive_padding` low

What it checks, working from the added lines in `baseline.diff` and the size table:

- **redundant_restatement**: added text that restates something the scope already says elsewhere (in the baseline or in another addition).
- **patch_on_patch**: text added to qualify, correct, or explain text that an earlier iteration added, where rewriting the earlier passage once would say the same thing in less.
- **unmotivated_addition**: added content that no finding in any fixer changelog accounts for.
- **defensive_padding**: hedges, caveats, repeated warnings, or explanations of why a rule exists, added where the finding required only the rule.

Rules:

- Only text absent from the baseline is in scope. Baseline text is never a bloat finding, however verbose.
- Growth alone is never a finding. Every finding quotes a specific added passage and says what makes it surplus. The size table directs attention to the files that grew most; it is not evidence.
- Every suggestion is a meaning-preserving consolidation: it names the passages to merge or the restatement to delete and says where the meaning continues to live. A suggestion may never ask for meaning to be removed. If a passage cannot be shortened without losing a condition, exception, or example, it is not bloat.

Does not check: whether content was lost, whether added content is correct, the original's verbosity.

No baseline in the dispatch prompt → states so and emits no findings.

### 7. Triage changes (agents/triage.md)

- **§3 dispatch template**: the Session inputs section above.
- **§5 diagnosis**: add a fifth pattern, **Growth**: total scope size rising across iterations, read from each iteration's `baseline-sizes.tsv` `TOTAL` row. Triage records the totals in `triage-output.json` as `scope_size: {baseline_lines, current_lines}` and names the trend in `user-surface.md`. Triage's dispatch context gains the path to the current iteration's `baseline-sizes.tsv`. Growth is a diagnosis for the user; it never blocks the gate by itself.
- **§1 normalization, conflict rule**: when, in one iteration, a finding asks to cut a passage and another asks to restore or keep the same meaning, triage merges them into one finding whose suggestion is "state this meaning once, in the fewest words that carry it". Preserving meaning takes precedence over brevity. The rule is phrased by finding content, not reviewer name.
- Recurrence of such a pair across iterations is already covered by §12 (oscillation escalates to the user after 3 iterations).

### 8. Auditor (agents/auditor.md)

Reject signal 4 (External-state-dependent) gains one clarifying sentence: inputs the session supplies through the dispatch prompt (scope files, `SCOPE.md`, manifest, triage history, baseline, baseline diff, size table, fixer changelogs, accepted risks) are not external state.

Bundled defaults skip the semantic audit, so this is not needed for the two new files to load; it keeps the stated contract true and lets user-supplied reviewers use the baseline.

### 9. How a round runs after this change

1. Round 1: coherence, design, detail run as today. Bloat and lost-items are dormant (precondition not met: the fixer has not run).
2. Triage blocks the gate; evaluating prospectively, both new preconditions are `met` for round 2.
3. Fixer applies fixes and writes its changelog with the Removals ledger. Commit.
4. Orchestrator writes round 2's `baseline.diff` and `baseline-sizes.tsv`.
5. Round 2 reviewers run, bloat and lost-items among them.
6. Triage normalizes. A `dropped_content` finding (high) blocks the gate; the fixer restores it in round 2's fix step; round 3 re-checks.
7. `exit_clean` requires, under the existing coverage rule, that both have run against the final state with no medium+ finding. Same again on the opus tier, where the precondition is met at `o-init` if the cheap tier changed anything.

### 10. Docs and version

- SKILL.md: "three default reviewers" → five, in the intro and frontmatter-adjacent prose; iteration directory layout shows `baseline.diff` and `baseline-sizes.tsv`; Phase 1 step 5 and Phase 2 step 3 as above.
- README.md materia table: five default reviewers, named.
- `.claude-plugin/plugin.json`: 0.14.0 → 0.15.0.
- Branch `adversarial-review/bloat-and-lost-items` off `origin/main`. `feat/capture-to-week` carries an unmerged commit touching SKILL.md Phase 2 step 1 and triage §9–10; this change edits other sections.

## Calls made without asking

- Plain file copy for the baseline rather than the VCS ref.
- Both reviewers `required: true` rather than optional.
- `defensive_padding` is low, so it is fixed only when something else blocks the gate, otherwise deferred.
- Session inputs go to every reviewer, not only these two.
- The Growth diagnosis is informational, with no numeric threshold.

## Left to the builder

- The exact Bash for the diff and size table (must handle one-sided files and binary files without error, and print nothing).
- Wording of the reviewer bodies beyond the rules above, following the section layout of `defaults/reviewers/coherence.md`.
- A verification pass: a fixture pair (baseline containing a point, current without it, and a current with a patch-on-patch passage) run through `/adversarial-review run` with a hand-written dispatch prompt, confirming each reviewer reports it; plus one full loop on a small file confirming `review/baseline/`, the two per-iteration files, and round-2 activation.
