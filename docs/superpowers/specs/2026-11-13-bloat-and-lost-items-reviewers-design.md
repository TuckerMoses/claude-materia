# Bloat and lost-items reviewers for adversarial-review: design

Status: approved 2026-11-18 (passed adversarial review 2026-11-13). Target: claude-materia plugin 0.14.0 → 0.15.0.

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
- Attributing edits the user makes to scope files mid-loop. They are judged like loop changes; the user accept-risks any resulting lost-items or bloat finding.

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

This happens after the step-2 VCS checkpoint, so for files in the checkpointed scope the baseline equals the content at `pre_review_vcs_ref`. A file added to the scope when the user edits `locations` at step 4 was not in the checkpoint; its baseline copy is its content at step 5, which is the pre-review state for the loop's purposes. The baseline is written once and never updated, in both `live` and `pinned` scope modes and across the tier promotion.

`review/session-meta.json` gains `baseline_dir` (the absolute path of `review/baseline/`).

### 2. Per-iteration baseline comparison (SKILL.md, Phase 2)

At the start of every numbered iteration, immediately before dispatching reviewers (step 3 `continue`, between b and c), the orchestrator runs one Bash command, `bash "<skill-directory>/scripts/baseline-compare.sh" <session-dir> <iteration-dir> >/dev/null 2>&1` (`<skill-directory>` as in SKILL.md), which writes two files into the new iteration directory itself; the orchestrator discards stdout and stderr so nothing enters its context. Both arguments are absolute; `<iteration-dir>` is `<session-dir>/review/iterations/<tier>-<N>`, derived from the tier and N the orchestrator already tracks, exactly as for `route.json`, which is unchanged; the script reads `<session-dir>/review/baseline/` and `<iteration-dir>/scope.txt`.

- `iterations/<tier>-<N>/baseline.diff`: `diff -u` from `review/baseline/` to the current files, labelled `baseline` or `current` followed directly by the absolute path (`baseline/a/b`; `/dev/null` for a missing side). The file set is the union of the baseline's files and `scope.txt`. A file present on only one side is diffed against empty, so a deleted file appears as all-removed and a created file as all-added. A path absent from both sides is skipped (no diff, no size row). A rename appears as old path all-removed plus new path all-added; moved text is neither a loss (§5 rule 1) nor an addition (§6).
- `iterations/<tier>-<N>/baseline-sizes.tsv`: header `path<TAB>baseline_lines<TAB>current_lines<TAB>delta<TAB>baseline_words<TAB>current_words<TAB>word_delta`, each delta = current - baseline, a missing side counts 0, line counts include a final unterminated line, words are whitespace-separated (`wc -w`), rows sorted by path, last row path `TOTAL`. Words are counted because fixes that rewrite long lines in place grow the text without moving the line count. A file is binary when diff reports `Binary files`; it gets a row with `binary` in all six numeric columns, is excluded from `TOTAL`, and shows one `Binary files differ` diff line.

It runs unconditionally; the orchestrator does not reason about which reviewers need it. In iteration 1 of the cheap tier the diff is empty. The orchestrator branches only on the command's exit status, never on output. The script exits non-zero unless it wrote both files, and exits 0 whenever it did, including when diff reports differences (diff status 1); non-zero only for diff status >= 2 or an I/O error (unreadable baseline, unwritable output, missing `scope.txt`). A non-zero exit is surfaced under Surfacing exclusivity case 3 (extended in §10): one line naming the iteration directory, no reviewer dispatched. On `retry` the orchestrator reruns the script itself (no triage dispatch, no `user-response.md`); on `abort` it dispatches the scribe with `termination_kind` aborted; any other reply re-surfaces the same one-liner.

The orchestrator does not resolve scope and reads no scope source (`manifest.yml`, `scope-pinned.json`). Triage is the sole scope resolver during Phase 2 (Phase 1 resolution is unchanged; triage.md §8): alongside each next iteration's dispatch prompts it writes `iterations/<tier>-<N+1>/scope.txt`, one absolute path per line, as the de-duplicated union of the freshly resolved scope and iteration N's `scope.txt` (including fixer appends); a path is never dropped by this union (deleted files are handled by the baseline side). Triage-init writes the freshly resolved scope for the first iteration of each tier; for `o-1` it takes the union with the last cheap-tier `scope.txt` in place of N's. The script consumes `scope.txt` and the baseline directory listing; the orchestrator never Reads either. Because the fixer runs after triage writes `scope.txt`, the fixer appends the new path of each file it creates or renames to it (see §4). Deleted files need no handling: they remain in the baseline side of the union.

The orchestrator generates this, rather than triage, because triage authors round N+1's dispatch prompts before the round-N fixer runs; the post-fix state does not exist yet when triage writes them.

Both files, and `scope.txt`, are added to the Read-discipline rule's MUST NOT Read list. The rule's authorized-reads list is unchanged: `iterations/<tier>-<N>/route.json` remains the orchestrator's only authorized Phase 2 read. The Bash command's inputs (`scope.txt`, `review/baseline/`) are consumed by the shell, not read into orchestrator context.

### 3. Dispatch prompt (agents/triage.md §3)

The reviewer dispatch template gains a section, written identically for every reviewer so triage never special-cases a reviewer by name:

```markdown
## Session inputs
- Baseline (pre-review original): <baseline_dir>
- Baseline diff for this iteration: iterations/<tier>-<N+1>/baseline.diff
- Size table for this iteration: iterations/<tier>-<N+1>/baseline-sizes.tsv
- Scope list for this iteration: iterations/<tier>-<N+1>/scope.txt (authoritative; supersedes the Scope section above; a listed path absent from disk was deleted or renamed and is not an error)
- Fixer changelogs: [every changelog in the session, both tiers, oldest first, including iterations/<tier>-<N>/fixer-changelog.md whenever triage emits fixer_brief_path, since the fixer runs before reviewers are dispatched; "none" if no fixer has run]
- Triage outputs: [every triage output in the session, both tiers, oldest first]
```

Triage's dispatch context gains `baseline_dir`, `next_baseline_diff_path`, `next_baseline_sizes_path`, and `next_scope_list_path` so it writes these paths without computing them. The files at the two `next_baseline_*` paths do not exist when triage writes the prompt; the orchestrator creates them before the reviewer is dispatched. Triage itself writes `next_scope_list_path` (see §2).

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

Each "Findings addressed" entry also gains `**Restores**: <baseline file, heading> -> <current file, section>: "<restored text, in full>" | none`.

A rewrite counts as a removal when any statement the old text made is no longer made by the new text.

New constraint: do not delete, weaken, or drop content unless the finding being addressed calls for it. Content that must move or merge keeps its full meaning at the destination. When executing a consolidation, every distinct condition, exception, and example in the passages being merged survives the merge.

If the fixer creates or renames a scope file, it appends the new absolute path to the next iteration's `scope.txt` (path supplied in the fixer brief as `next_scope_list_path`). This is the only file outside the scope that the fixer writes besides its changelog. For a deletion nothing is appended; the baseline side of the union covers it.

fixer.md edits by section: "What you change" allows appending to the brief's scope list path; "Output: fixer changelog" gains Removals and the `Restores` field; "Constraints" gains the preservation constraint. "What you read" gains the baseline directory as a read-only source for restoring lost content. triage.md §3's fixer brief template gains `next_scope_list_path` and `baseline_dir` (read-only).

The ledger does not need to be trustworthy to be useful. An accidental drop is by nature unlogged, and an unlogged loss is exactly what lost-items reports; a fixer may log it later (§5 rule 2).

### 5. `defaults/reviewers/lost-items.md`

Frontmatter:

- `name: lost-items` (filename stem), `description`, `role: reviewer`
- `required: true`, `trigger: null`
- `precondition`: "The fixer has modified at least one scope file since the pre-review baseline, and the current state has not been checked against the baseline for lost content within the current tier"
- `severity_guidance`: `dropped_content` high; `weakened_requirement` high; `dropped_detail` medium; `baseline_unavailable` high; `incomplete_check` high

What it checks, working from the removed lines in `baseline.diff` and confirming against the baseline and current files:

- **dropped_content**: a point, rule, requirement, or section the baseline stated that the current scope states nowhere.
- **weakened_requirement**: a constraint that survives in softer form: `must` became `should`, a condition or exception was added that narrows it, a number loosened, a prohibition became advice.
- **dropped_detail**: an example, edge case, rationale, or qualifier that supported a surviving point and is gone.

A removal is **not** a finding when any one of these holds:

1. The meaning appears elsewhere in the current scope (`scope.txt`; moved, merged, renamed, or reworded). Wording changes are never findings; only meaning is compared.
2. A fixer changelog's Removals section, in any fixer changelog in the session, logs it against a finding id `f-<tier>-<N>-<seq>`, and that finding, looked up in `iterations/<tier>-<N>/triage-output.json`, did call for removing or replacing that meaning. An id absent there, or a finding that did not call for the removal, does not excuse it.

Accepted risks are matched by triage, not the reviewer (§7).

Each finding's `location` is a stable locator: baseline file, section heading, and a short quote. It also states which current file the meaning should live in. The suggestion is to restore the meaning in the fewest words that carry it (or, for a removal a resolved finding plausibly called for, to log it in this round's Removals against that id), at the place the current structure puts such content; it does not ask for the original wording back.

Does not check: whether the lost content was good, whether the artifact is consistent, anything about added text.

Baseline signals (shared with bloat): no `## Session inputs` section (the single-pass `run` subcommand) means "no baseline provided" and no findings. Section present with an empty diff and a size table showing no delta means no findings. Section present but a Session inputs path (baseline dir, diff, size table, scope list, named changelogs and triage outputs) is missing or unreadable, or the diff is empty while the size table shows a non-zero delta, is a high `baseline_unavailable` finding. If the reviewer cannot read the whole diff, it emits a high `incomplete_check` naming what it did not cover.

### 6. `defaults/reviewers/bloat.md`

Frontmatter:

- `name: bloat` (filename stem), `description`, `role: reviewer`
- `required: true`, `trigger: null`
- `precondition`: "The fixer has modified at least one scope file since the pre-review baseline, and the current state has not been checked for loop-added bloat within the current tier"
- `severity_guidance`: `redundant_restatement` medium; `patch_on_patch` medium; `unmotivated_addition` medium; `defensive_padding` low; `baseline_unavailable` high; `incomplete_check` high

What it checks, working from the added lines in `baseline.diff` and the size table:

- **redundant_restatement**: added text that restates something the scope already says elsewhere (in the baseline or in another addition).
- **patch_on_patch**: added text that qualifies, corrects, or explains other added text, where rewriting the earlier passage once would say the same thing in less.
- **unmotivated_addition**: added content that no fixer changelog Action/Location entry accounts for. Lack of attribution is necessary but not sufficient: the reviewer also quotes the passage and says why it carries no required meaning.
- **defensive_padding**: hedges, caveats, repeated warnings, or explanations of why a rule exists, added where the finding required only the rule.

Rules:

- Only text absent from the baseline is in scope. Baseline text is never a bloat finding, however verbose.
- Growth alone is never a finding. Every finding quotes a specific added passage and says what makes it surplus. The size table directs attention to the files that grew most; it is not evidence.
- Every suggestion is a meaning-preserving consolidation: it names the passages to merge or the restatement to delete and says where the meaning continues to live. A suggestion may never ask for meaning to be removed. If a passage cannot be shortened without losing a condition, exception, or example, it is not bloat.

The cumulative diff does not say which iteration added a passage. Attribution comes only from changelog Action/Location text; an unattributable addition is judged on its content alone.

Does not check: whether content was lost, whether added content is correct, the original's verbosity.

Baseline signals as in §5. Moved text is not an addition.

### 7. Triage changes (agents/triage.md)

- **§3 dispatch template**: the Session inputs section above; the fixer brief template gains `next_scope_list_path` and `baseline_dir` (§4).
- **Accepted risks**: lost-items findings keep a stable id for a recurring loss (existing rule: ids stable for the same issue), so triage's existing accepted-risk filtering applies; reviewers do not read `accepted-risks.json`.
- **§5 diagnosis**: add a fifth pattern, **Growth**: total scope size in words rising (current total > previous iteration's total > the total before that, counting across tiers; fewer than three data points means no Growth diagnosis), computed from the `scope_size` fields in prior iterations' `triage-output.json` (which triage already receives as history) plus the `TOTAL` row of the current iteration's `baseline-sizes.tsv`. Triage records the current totals in `triage-output.json` as `scope_size: {baseline_lines, current_lines, baseline_words, current_words}` and names the trend in `user-surface.md`. Triage's dispatch context gains the path to the current iteration's `baseline-sizes.tsv`; it is not handed earlier tables. triage.md "Context you receive" (and §11 tier-init) gains that path plus `baseline_dir`, `next_baseline_diff_path`, `next_baseline_sizes_path`, and `next_scope_list_path`. Growth is a diagnosis for the user; it never blocks the gate by itself.
- **§1 normalization, conflict rule**: when, in one iteration, a finding asks to cut a passage and another asks to restore or keep the same meaning, triage merges them into one finding (highest source severity, trace shape synthesis) whose suggestion is "state this meaning once, in the fewest words that carry it". Preserving meaning takes precedence over brevity. The rule is phrased by finding content, not reviewer name.
- **Sequential cycle**: a cut/consolidate finding whose stated reason is surplus wording (restatement, padding, patch-on-patch, unmotivated addition) and whose suggestion would cut or shorten a passage that overlaps a changelog `Restores` entry's recorded text at that entry's current location, with that text still appearing verbatim, is downgraded to low with `status: deferred`, so the fixer skips it; triage never reopens a finding deferred under this rule while the `Restores` text still appears verbatim. A finding that says the text is wrong, contradictory, or harmful is judged normally, as is any other finding. A finding deferred under this rule does not count as a recurrence for §5 oscillation or §12 escalation. The downgrade carries across the cheap-to-opus boundary (triage receives the cheap-tier history at `o-init`).
- Recurrence of such a pair across iterations is diagnosed as oscillation under §5 and escalated per §12 (3+ recurring iterations after the user has been notified once).
- **Baseline plumbing failures**: triage does not route `baseline_unavailable` or `incomplete_check` to the fixer. It emits `control: escalate` in the same iteration with options `accept-risk <id>` and `abort`. Acceptance is per finding id: the reviewer keeps running and its other findings gate normally, and triage gives every later finding of the same type (`baseline_unavailable` or `incomplete_check`) from that reviewer the id accepted for that type; the other type, if it appears, is a new finding; `user-surface.md` says this.

### 8. Auditor (agents/auditor.md)

Reject signal 4 (External-state-dependent) gains one clarifying sentence (wording left to the builder): inputs the session supplies through the dispatch prompt (scope files, `SCOPE.md`, manifest, triage history, baseline, baseline diff, size table, scope list, fixer changelogs) are not external state.

Bundled defaults skip the semantic audit, so this is not needed for the two new files to load; it keeps the stated contract true and lets user-supplied reviewers use the baseline.

### 9. How a round runs after this change

1. Round 1: coherence, design, detail run as today. Bloat and lost-items are dormant (precondition not met: the fixer has not run).
2. Triage blocks the gate; evaluating prospectively, both new preconditions are `met` for round 2.
3. Fixer applies fixes and writes its changelog with the Removals ledger. Commit.
4. Orchestrator writes round 2's `baseline.diff` and `baseline-sizes.tsv`.
5. Round 2 reviewers run, bloat and lost-items among them.
6. Triage normalizes. A `dropped_content` finding (high) blocks the gate; the fixer restores it in round 2's fix step; round 3 re-checks.
7. `exit_clean` requires, under the existing coverage rule, that both have run against the final state with no medium+ finding. Same again on the opus tier. Both preconditions are scoped per tier ("within the current tier"), so at `o-init` the clause is true by construction: no check has yet run in the opus tier. Triage evaluates them at `o-init` as `met` iff any cheap-tier `fixer-changelog.md` exists or the last cheap `scope_size` has `current_lines != baseline_lines` or `current_words != baseline_words`; either suffices. If neither holds, both stay dormant.

### 10. Docs and version

- New `scripts/baseline-compare.sh` (§2).
- SKILL.md: Surfacing exclusivity case 3 gains "orchestrator-run baseline comparison failed (non-zero exit)" with the §2 retry/abort handling, and Iteration validity invariant (c) also permits branching on that exit status and the user's retry/abort reply; Phase 2 step 3d, the tier-init dispatch, and the user-response re-dispatch path lists gain the five paths above (`baseline_dir` from `session-meta.json`; the other four by the `iterations/<tier>-<N>` convention, as for `route.json`); "three default reviewers" → five, at the SKILL.md line 12 count and any other occurrence (grep); session layout shows `review/baseline/`; iteration layout shows `scope.txt`, `baseline.diff`, `baseline-sizes.tsv`; Phase 1 step 5 and Phase 2 step 3 as above.
- README.md materia table: five default reviewers, named (and its own "three" count if present).
- `.claude-plugin/plugin.json`: 0.14.0 → 0.15.0.
- Branch `adversarial-review/bloat-and-lost-items` off `origin/main`. `feat/capture-to-week` carries an unmerged commit touching SKILL.md Phase 2 step 1 and triage §9–10; this change edits other sections.

## Calls made without asking

- Plain file copy for the baseline rather than the VCS ref.
- Both reviewers `required: true` rather than optional.
- `defensive_padding` is low, so it is fixed only when something else blocks the gate, otherwise deferred.
- Session inputs go to every reviewer, not only these two.
- The Growth diagnosis is informational, with no numeric threshold.
- Medium bloat findings block the gate even though bloat is partly subjective: otherwise loop-added padding would exit clean, which is the regression being fixed. The sequential-cycle rule (§7) bounds the cost.

## Left to the builder

- The body of `scripts/baseline-compare.sh` (formats in §2; must handle one-sided and binary files and print nothing).
- Wording of the reviewer bodies beyond the rules above, following the section layout of `defaults/reviewers/coherence.md`.
- A verification pass: a fixture pair (baseline containing a point, current without it, and a current with a patch-on-patch passage) dispatched directly to each new reviewer as a subagent with a hand-written dispatch prompt that includes the baseline, diff, and size-table paths (not via `/adversarial-review run`, which supplies no baseline and so yields only the no-baseline null result), confirming each reviewer reports it; plus one full loop on a small file confirming `review/baseline/`, the two per-iteration files, and round-2 activation.
