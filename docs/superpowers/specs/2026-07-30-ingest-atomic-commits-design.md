# Design — atomic ingest commits + vault CHANGELOG (claude-materia)

> **Status:** Design approved 2026-07-30 (Tucker), **except §2.8** (dropping `digest.md`), which
> was decided during spec-writing and is pending Tucker's veto — see §2.8. Next: implementation
> plan (writing-plans) for the approved portions, then execution.
> **Context:** `--silent` was specified 2026-07-06 (vault v1.1.0) and marked complete in BACKLOG,
> but has **never been executed** — all five runs in `~/Vault/_machine/logs/ingest/` carry a
> `confirmed-manifest.json`, i.e. the interactive gate ran. The BACKLOG's stated next step ("cron
> invocation is now just `/ingest --silent` on a cadence") is blocked on a gap nobody specified:
> ingest has **never touched version control**. All five runs' output sits in a single jj
> working-copy change (`vtomukrwvlkq`, 257 files, 6,917 insertions), so no run is independently
> reversible.
> **Goal:** make each ingest run an atomic, individually-revertible commit, and give Tucker a
> human-readable record of what each run did — the two preconditions for running ingest on a loop.
> **Prior spec:** `2026-07-05-ingest-skill-design.md` (+ its 2026-07-06 `--silent` amendment).
> **Build gate:** repo convention — `adversarial-review run default:coherence` on the diff before
> ship.

---

## 1. Problem

Running ingest unattended requires two things it lacks:

1. **A rollback unit.** If a run labels things badly, Tucker needs to undo *that run* without
   touching anything else. Today there is no per-run boundary at all.
2. **A review surface.** Silent mode moves review from pre-write (the gate) to post-write. The
   existing design points that at `_machine/logs/ingest/<run>/digest.md` — a machine-space file
   per run, which is not a thing a human reads habitually.

## 2. Decisions

### 2.1 jj-native, not git-native

`~/Vault` is jj 0.43 colocated with git. Commits are `jj`; git remains the export target it
already is. Rationale: jj owns the working copy, the run log already reserves
`jj_change_id_at_drain_start`, and `jj abandon` is a genuine one-liner. A `git revert` in a
colocated repo introduces a second history writer and degrades jj's operation log.

**Corrective path (locked):** rollback → **re-run interactively**. This matters because
rollback-then-re-run-silent is a no-op loop: a silent re-run supplies no new information — same
day-file, same frozen vocabulary, same labelling subagent — so it cannot correct a labelling error
regardless of whether its output happens to be bit-identical to the run it replaces. The correction
has to be supplied at the gate.

### 2.2 The vocabulary stays frozen in silent mode

Tucker's rule — *silent behaves identically to interactive except for the gate* — is adopted.
Applied correctly it yields **frozen**, because interactive ingest does not mint either. Four
files agree: ingest SKILL.md §identity and §invariants, synthesizer SKILL.md ("Ingest never mints
vocabulary… **all** post-bootstrap topical vocabulary growth happens here"), and `Vault/CLAUDE.md`.

**`labels_registered_this_run` in `run.json` is drift.** The field appears nowhere in the skill.
`run.json`'s actual field set is `ts`, `marked`, `jj_change_id_at_drain_start` (already reserved
per §2.1), and — new under this design — the run's structured filed/parked/diary-only/skipped
counts (§2.8). It was improvised during the 2026-07-25 run to record a label *Tucker* minted
in conversation at the gate. Human minting mid-gate is sanctioned; the ad-hoc field is not. It is
removed from the run-log schema.

**Consequence for the changelog:** a silent run produces zero new vocabulary, always. What the
changelog records is the inverse — **what got parked under `needs-label`, and why nothing fit**.
That is the same signal ("the vocabulary needs to grow, here's the justification") recorded as
pressure rather than as an action taken.

**Draining the pile stays the synthesizer's, human-gated** (`resolve` is propose-confirm only).
The loop reports pressure; it never relieves it. This is the loop's designed-in backlog: 14 notes
are parked today against 94 active labels, and only a deliberate synthesizer session shrinks that.

### 2.3 `--today` is retained, interactive-only, and never used by the loop

Closed-days-only is already the default (day-file definition: `journal/YYYY-MM-DD.md`, *dated
strictly before today*, lacking `ingested: true`). `--today` is purely additive. It stays as an
interactive flag; the looped invocation is plain `/ingest --silent`.

Rationale: dedup is content-addressed — `file-notes:existing_match` matches on `source:` line
**and verbatim body**, both exact. Immutable sources make that exact; the open day-file is mutable
by definition and structurally *cannot* be marked `ingested: true`, so it is re-scanned every run
until midnight closes it. Under an hourly loop, a thought written at 09:00, sharpened at 10:30 and
expanded at 14:00 files three notes. `--today`'s justification (same-day actionables shouldn't wait
for tomorrow) is largely dissolved by the loop itself, which bounds capture-to-filed latency at one
day while only ever reading immutable files. This reasoning holds for loop intervals of roughly a
day or less, whatever cadence §6's deferred scheduling work eventually settles on; if that cadence
turns out coarser, `--today`'s interactive-only restriction is worth revisiting.

**`--silent --today` together is a validation error.** The skill refuses to run and exits non-zero
before touching the vault, rather than silently accepting the combination: running it would read
the mutable open day-file into a gate-free unattended flow — the exact duplicate-filing scenario
the paragraph above exists to prevent.

If today-inclusive silent runs are ever wanted, the honest fix is a stabler dedup key, not a flag
change. Deferred until actually wanted.

### 2.4 The commit is scoped to the paths the run touched

**This is the one non-obvious mechanism in the design.** Everything else is a one-liner.

`jj commit [FILESETS]` (verified, 0.43): *"the selected changes stay in the current commit while
the remaining changes are moved to a new working-copy commit on top."* So a path-scoped commit
finalizes `@` containing only the run's files, and any unrelated dirt survives untouched in a fresh
working copy.

**The path list is not inferred — `file-notes` already emits it.** Its report carries `written`
(notes filed to `notes/`), `marked` (day-files receiving `ingested: true` — see line 150 for the
worked case), `advanced` (watermarks advanced), and `moved` (staging moves): the vault paths it
just touched, produced by the code that touched them. Call this the **touched-path set** — the
only one of this paragraph's three named collections that can be empty, and what §2.5's no-op
guard evaluates. Add the run-log directory's
own files, enumerated by name rather than as a directory-glob fileset — `run.json`,
`proposals.json`, `entry.md`, `report.json`, plus `confirmed-manifest.json` on interactive runs
only (the propose-confirm gate produces it; silent runs never do) — call this the **run-log
sublist**: always non-empty, and what the four/five conditional below applies to. The touched-path
set, the run-log sublist, and `CHANGELOG.md` together make the **commit fileset** — always
non-empty, the complete thing `jj commit` finalizes. Because `confirmed-manifest.json` does not
exist on a silent run, `commit-run` builds the run-log sublist conditionally on the run's mode
(four names for silent, five for interactive) rather than passing a static five-name list and
relying on `jj commit` tolerating a named path absent from the working copy — that tolerance is
not verified, unlike the selected/unselected semantics above, and a spec should not carry an
unverified assumption in the one mechanism it calls non-obvious. `CHANGELOG.md` and the
touched-path set are added to the commit fileset unconditionally in every run; only the run-log
sublist varies by mode. No globbing, no diffing, no heuristics, and `-a` never appears. Each drain
invocation, including a retry after an aborted attempt, is assigned a fresh run-id, so a retry
never reuses a failed attempt's run-log directory; the run-log sublist therefore cannot sweep in
directory residue left behind by that prior attempt. (`CHANGELOG.md` is a distinct case — see §5's
process-kill bullet for the one way an orphaned entry can ride into the wrong run's commit
fileset.)

**Why scoping is required rather than nice-to-have.** A vault is a working tree a human is always
halfway through editing. Automation sharing that tree either scopes its writes or eventually
swallows the human's work. Three concrete cases, in ascending order of how badly they bite:

- **Today's journal.** Tucker journals on day D; the loop fires; ingest correctly never *reads*
  `journal/D.md` — but the file is modified in the working copy, so an unscoped commit takes it.
  Rolling back that run to fix labels would delete part of the diary. Sharpened by jj having no
  staging area and no untracked category: it auto-snapshots every non-ignored file, so a
  brand-new journal file is already part of `@` the moment it exists. The git intuition ("new
  files are untracked, `commit` skips them") does not hold.
- **A hand-edited note.** Editing a note in Obsidian acquires no lock and commits nothing.
- **An uncommitted synthesizer session — decisive.** The loop grows the park pile; the changelog
  reports the pressure; Tucker runs the synthesizer to drain it, approving merges (body rewrites)
  and links across many files. The loop fires that night. Every approved merge lands inside the
  ingest commit, and rolling back the ingest run reverts the synthesis work. Ingest and the
  synthesizer are designed to alternate — their working periods interleave *by construction*.

**Alternatives considered and rejected:**

- *Denylist (`jj commit 'all() ~ journal/<today>.md'`).* Covers the first case only. A denylist has
  to enumerate every category of dirty thing and stays correct only while that enumeration is
  complete; the vault already has three writers and the contract anticipates more (manager skills
  registering container labels, consumers writing `status`/`handled`). An allowlist derived from
  what the run did needs no maintenance, because it describes the run rather than the world.
  Note both designs converge on journal files: day D's file is committed by the run that ingests
  it, since that run writes its `ingested: true` marker and it appears in `marked`.
- *Lockfile.* Solves a real problem — concurrent *execution* of two vault writers, which could let
  `existing_match` read `notes/` mid-write and miss a note. But the commit problem is **residue**,
  not contention: a synthesizer session that ended cleanly at 21:00 and released its lock still has
  uncommitted merges at 03:00. The "commit before releasing the lock" variant would fix that for
  skills but not for the human — Obsidian participates in no protocol. A correct lockfile is also
  more code than the allowlist (stale detection, PID liveness, timeout, cleanup on abort).
  **Deferred** — see §6.
- *Require a clean tree, fail loudly.* Makes an unattended loop fragile: one stray edit anywhere in
  the vault halts ingestion indefinitely — and "loudly" fails into a log nobody is watching in real
  time on an unattended run, so in practice it is silent to Tucker unless something else pages him.

### 2.5 Commit mechanics

- **New script `scripts/commit-run <vault> <report.json> <entry.md> <run-id> <mode>`.** Committing
  is mechanical, so it is shell, not model — per the skill's deterministic-shell / semantic-core
  split. Takes the vault path as an argument, like every other script.
- **Rendering split (follows the same seam).** The changelog entry's *content* is semantic —
  note titles, labels, and especially the parked near-miss rationale — none of which exists in the
  `file-notes` report (paths only) or can be derived mechanically. So the model writes the rendered
  entry to `_machine/logs/ingest/<run>/entry.md`; `commit-run` prepends that file verbatim below the
  CHANGELOG header and commits. Model renders, script files — the same division as proposals vs.
  `file-notes`.
- **Near-miss rationale is a new output of the split+label step.** For every thought parked under
  `needs-label`, the labelling subagent must emit the nearest active labels it considered and why
  each missed, writing it as a new `near_miss` array on that item's entry in `proposals.json`. Each
  element is a `{label, reason}` object — no minimum or maximum count, every label seriously
  weighed goes in. Drain step 6 renders each element as `` `label` (reason) `` when composing
  `entry.md`'s Parked section, and an item whose `near_miss` array is empty renders "No active
  label was within consideration" rather than an empty body. Multiple elements are joined and
  preceded by whatever lead-in phrase the model chooses; per §2.6's existing acceptance that
  `entry.md`'s prose framing is model-authored and would not reproduce identically, the worked
  example's `, `-joined list and "Nearest active labels considered: " lead-in (§2.6) are
  illustrative of that framing, not a required template. This is the one genuinely new semantic
  requirement in this design; without it the Parked section degrades to a list of titles and the
  vocabulary-pressure signal is lost. After that mechanical list (or the empty-array fallback),
  drain step 6 additionally closes each Parked entry with one sentence of model-composed synthesis
  — not derived from `near_miss` data, but composed the same way the rest of `entry.md` is: per
  this section's rendering split, it is exactly the kind of content absent from the `file-notes`
  report and undeliverable mechanically — characterizing why nothing in the frozen vocabulary fit.
  Required on every itemized Parked entry, including the zero-`near_miss` case.
- **Abort ⇒ no commit.** `file-notes` exits 1 on empty body or md5 mismatch; the flow stops and
  never reaches the commit step. A broken run stays visible in the working copy rather than being
  buried in history.
- **`commit-run` failure ⇒ rollback, not orphan.** `commit-run` does two things in order: prepend
  `entry.md` to `CHANGELOG.md`, then `jj commit [FILESETS]`. If the `jj commit` invocation fails
  and returns control to `commit-run` — a non-zero exit, not a crash — `commit-run` reverts the
  `CHANGELOG.md` prepend before exiting non-zero. The run's own artifacts (the run-log sublist per
  §2.4: `run.json`, `proposals.json`, `entry.md`, `report.json`, plus `confirmed-manifest.json` on
  interactive runs) and the whole touched-path set — filed notes, `ingested`
  markers, watermark advances, and staging moves — stay uncommitted and visible in the working
  copy — the same "stays visible rather than buried" treatment as the
  `file-notes` abort case above — and `CHANGELOG.md` is never left holding an entry for a run that
  was never finalized, preserving
  §2.6's "each entry is one commit" guarantee. This guarantee covers failures that return control
  to the script; a process kill between the two writes — SIGKILL, OOM, host restart, power loss —
  is a separate, accepted residual risk, not detected or corrected here. See §5.
- **No-op (nothing touched) ⇒ no commit, no changelog entry.** One guard, living in `commit-run`
  itself — it checks whether §2.4's touched-path set (`file-notes`'s own report: `written`,
  `marked`, `advanced`, `moved`) is empty, checked *before* the run-log sublist and `CHANGELOG.md`
  are folded into the commit fileset per §2.4 — those are unconditional and would otherwise make
  the check vacuous — so an empty run does not produce an empty commit. The run directory's own
  files (`entry.md`, `report.json`) are
  written to disk by earlier drain steps before `commit-run` is ever invoked, so the guard cannot
  retroactively prevent the directory's existence — it stops the commit and the changelog entry,
  not the directory. See §5 for the accumulation this leaves behind.
- **Message:** `ingest(<mode>): <run-id> — N notes, M days, P parked`. `N`, `M`, `P` are defined in
  §2.6 against the changelog's own category names.
- **No change-id capture.** An earlier draft captured `@`'s change-id before committing to embed it
  in the changelog. Dropped: the run-id already appears in both the commit message and the changelog
  entry, so it *is* the join key. Finding the commit is
  `jj log -r 'description(glob:"*<run-id>*")'`.
- **Ordering:** the commit is a new drain step 6, strictly after `file-notes` verification, markers,
  watermarks, and staging moves — and, for interactive runs, strictly after the propose-confirm
  gate resolves. `entry.md` is rendered from the gate's final, human-approved proposal set, never
  from the labelling subagent's pre-gate output, so its content and the commit message's counts
  always match what `file-notes` actually wrote. Silent runs have no gate, so rendering follows
  immediately after staging moves as the ordering above already states. A declined gate leaves the
  touched-path set empty — `file-notes` never files anything, so no markers, watermarks, or staging
  moves occur — which is exactly what §2.5's no-op guard tests: no commit, no changelog entry.

### 2.6 CHANGELOG.md — vault root, append-only, newest first

**Placement:** vault root. No contract conflict — the immutable-layout rule governs *directories*.
Consequence: it appears in Obsidian's explorer, search, and graph as a frontmatter-less node; the
fix, if it grates, is an Obsidian exclusion filter, not a move.

**Append-only, written inside the run's own commit.** This makes `jj abandon` remove the entry
automatically, keeping the file truthful about history with no extra bookkeeping.

A *derived* changelog (regenerated from run logs) was considered as insurance against sync
conflicts on an append-hot file. `.stignore` shows Syncthing is not yet set up ("for later Phase
3"), so the risk is deferred. Between them, `run.json`'s counts and `proposals.json`'s per-item
titles, labels, and near-miss rationale (§2.5) carry the structured content a regeneration script
would need — though not `entry.md`'s exact prose framing, which is model-authored and would not
reproduce identically. **The regeneration script is not built now.**

**Format:**

```markdown
# Vault Changelog

Ingest run history, newest first. Each entry is one commit.
To undo a run: `jj log -r 'description(glob:"*<run-id>*")'`, then `jj abandon <change-id>`.

---

## 2026-07-30-1 · silent
**2 filed** from 3 day-files · **1 parked** · 4 diary-only · 1 skipped (already filed)

### Filed
- **Passion burned away with the illusions** — `narrative`, `philosophy` ← `2026-07-27`
- **Spin up drone firmware toolchain** — `todo`, `workspace:learning` ← `2026-07-28`

### Parked under `needs-label` — vocabulary pressure
- **On the texture of borrowed grief** ← `2026-07-28`
  Nearest active labels considered: `philosophy` (too broad), `ghosts-that-made-us`
  (book-specific, this isn't about the book). No label covers inherited or secondhand
  emotional experience.

### Diary-only
4 thoughts stayed in their day-files as narrative.

### Skipped
1 skipped — already filed.
```

**Category rendering rules:**
- **Filed** and **Parked** are itemized (title, labels or near-miss rationale, source day-file)
  whenever their count is nonzero; the subsection is omitted entirely when the count is zero.
- **Diary-only** gets a single summary sentence, never itemized by day-file, when nonzero; omitted
  when zero.
- **Skipped** gets a single summary sentence (e.g. "1 skipped — already filed.") when nonzero,
  never itemized; omitted when zero.
- `N`, `M`, `P` in the §2.5 commit message map onto these categories: `N` = filed count, `M` =
  distinct day-files touched by the run (whether filed, parked, diary-only, or skipped), `P` =
  parked count.

The header line is the scannable layer — fifty runs' headers read in seconds, with only unusual
counts worth opening.

The **Parked** section is what earns the file. Everything else is a receipt for work already done
correctly; parked entries are the only place the loop reports that it *needed something it did not
have*. Recording the nearest labels considered and why each missed converts "14 things are parked"
into a specific proposal for the synthesizer.

### 2.7 Universal, not silent-only

Commit + changelog entry apply to **every** ingest run, interactive included. The mechanism is
identical, and interactive runs leaving their work uncommitted is exactly how the 257-file backlog
accumulated — five runs with no boundary between them.

This is also a cost worth naming: interactive runs become permanent too. There is no more scratch
invocation without leaving a durable commit and changelog entry behind — undoing one needs `jj
abandon` plus a matching changelog edit, and §5 notes the rebase risk if the run being abandoned
isn't head. Accepted as the tradeoff for closing the exact gap that produced the 257-file backlog;
no dry-run or scratch mode is added.

### 2.8 `digest.md` is collapsed into the changelog

**Flagged: decided during spec-writing, not in the design conversation — Tucker may veto.**

The 2026-07-06 amendment requires every silent run to end with a digest surfaced to the user *and*
persisted to `_machine/logs/ingest/<run>/digest.md`. The changelog entry is that digest, in a file
Tucker actually reads, with the same content. The objection is not that two files sharing content
can drift — `entry.md` (§2.5) is written once and never updated, exactly like `digest.md` would be,
so neither is more drift-prone than the other. The objection is that `digest.md` is redundant once
the changelog exists: per §1, it is a machine-space file Tucker does not read habitually, so it was
never the user-facing record of the run — and an unread machine-space artifact serves no purpose
duplicating one that now exists. `entry.md` is a different thing: a rendering handoff that is
committed alongside the entry it produces, but never surfaced or read back on its own; the
CHANGELOG entry is the only user-facing record that survives.

`digest.md` is dropped. The mandatory-digest requirement is **preserved and satisfied** by the
changelog entry: still surfaced to the user at run end, still persisted, still inside the run's
commit, for every run that reaches one; §5 records the residual gap on the `commit-run`-failure
path, where the entry is rolled back and no digest survives in a user-facing form. `run.json`
retains the structured counts.

## 3. What does not change

- Propose-confirm remains the default; `--silent` remains the one sanctioned exception.
- Three-way extraction, frozen vocabulary, `needs-label` parking.
- Verbatim bodies; scripted filing; md5 verify with abort-on-mismatch.
- Ingest writes neither `status` nor `handled`.
- No state file — idempotency stays provenance + verbatim-body match.
- Ordered commit points; the new VCS commit is appended strictly after all of them.
- Env-agnostic: every script takes the vault path as an argument.
- The synthesizer is still excluded from silent operation.

## 4. Implementation surface

This table is derived from §2; any change to a §2 decision requires re-checking all three rows
against the full text of the changed subsection, not only the row that already cites it by number.

| File | Change |
|---|---|
| `plugins/vault/skills/ingest/scripts/commit-run` | **new** — scoped `jj commit` from the fileset it assembles per §2.4 (the `file-notes` report's touched-path set, the mode-conditional run-log sublist, and `CHANGELOG.md`); prepends the model-rendered `entry.md` to `CHANGELOG.md`; composes the commit message per §2.5's `ingest(<mode>): <run-id> — N notes, M days, P parked` format using §2.6's N/M/P counts; on `jj commit` failure, reverts the prepend and exits non-zero (§2.5) |
| `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh` | **new** — scoping (unrelated dirt survives, run-log sublist enumerated by name not globbed), run-log sublist construction per mode (interactive list includes `confirmed-manifest.json`, silent list omits it), commit message format (`N`/`M`/`P` counts per §2.5/§2.6), no-op guard (owned by `commit-run`), abort path, `jj commit`-failure rollback (prepend reverted, no orphan entry, touched-path set — markers/watermarks/moves — left in place and uncommitted), changelog prepend |
| `plugins/vault/skills/ingest/SKILL.md` | drain step 6 (after `file-notes` verification/markers/watermarks/staging moves; additionally after the propose-confirm gate resolves when one runs, rendering `entry.md` from the gate's final approved set rather than the pre-gate proposal set); split+label emits near-miss rationale for parked thoughts (new `near_miss` array of `{label, reason}` objects in `proposals.json`); drain step 6 additionally composes a one-sentence model-composed synthesis closing every itemized Parked entry, including the zero-`near_miss` case (§2.5); `entry.md` composition follows §2.6's category rendering rules (itemize/summarize/omit per category, `N`/`M`/`P` formula); §Silent mode (digest → changelog — **pending §2.8's veto; reverts to digest.md if vetoed**); §Invariants (add: "every successful run that touches at least one path (§2.4's touched-path set) produces exactly one commit; a run that touches at least one path produces zero commits if either `file-notes` aborts before the commit step is reached or a subsequently-invoked `commit-run` fails — in the latter case the `CHANGELOG.md` prepend is rolled back, per §2.5; a no-op run (nothing touched) produces none," per §2.5's abort, `commit-run`-failure, and no-op-guard contracts); `--today` loop guidance (`--silent --today` is a validation error); run-log schema (drop `labels_registered_this_run`; add per-category counts to `run.json`) |
| `plugins/vault/skills/vault/assets/CLAUDE.md` | document `CHANGELOG.md` in the layout section |
| `plugins/vault/skills/vault/assets/CHANGELOG.md` | **new** — seed stamped by `vault create` |
| `plugins/vault/skills/vault/SKILL.md` | seed the changelog on `vault create` |
| `plugins/vault/.claude-plugin/plugin.json` | version 1.1.0 → 1.2.0 |
| `BACKLOG.md` | reopen/annotate the `--silent` item; note the loop precondition |

## 5. Known edges, accepted

- **Path-scoped commits mean anything ingest does not touch stays uncommitted indefinitely.** By
  design — it is Tucker's work to commit — but the 257-file backlog will not self-resolve, and
  neither will the 35 journal squatters already tracked in BACKLOG.
- **Accepted risk, not enforced:** the 257-file backlog should be committed manually before
  enabling the loop — running a per-run-commit system atop a six-week uncommitted blob dilutes the
  feature's benefit, though nothing breaks if it isn't done; it just migrates to the new working
  copy and stays uncommitted. No startup check enforces this; catching it is handed to §6's
  deferred loop-scheduling work, alongside the loop's other unbuilt guarantees.
- **Abandoning a non-head run** rebases later runs, whose changelog hunks all target the top of the
  file — the likeliest conflict site. Low risk given §2.1's corrective path almost always abandons
  the most recent run.
- **`existing_match` is O(notes) per proposed note** — ~17k file reads on a 34-note run against 498
  notes. Fine now; revisit if the pool reaches a few thousand. Note the tension with
  INSTRUCTION.md's "never a full-vault read" (a query rule, not a filing rule, but adjacent).
- **`.stignore` excludes `.jj/`.** If Syncthing is ever enabled, a second machine gets files with no
  jj state and sees everything as changed. Out of scope; flagged.
- **Abort and `commit-run` failure paths leave no `CHANGELOG.md` trace.** Both accepted failure
  paths (§2.5's abort and rollback bullets) end with the run's partial content — any notes
  `file-notes` filed before the abort, or the run's own artifacts on a `commit-run` failure —
  sitting uncommitted and visible in the working copy, but neither writes a changelog entry,
  because entries are written only inside a successful commit (§2.6). On an unattended loop
  nobody is watching the working copy in real time, so the review surface §1 builds specifically
  for post-write review shows no trace that the run fired at all. This looks like the same
  "silent to Tucker" objection §2.4 raises against the rejected clean-tree alternative, but the
  two are not symmetric: the clean-tree alternative halts *every subsequent run* indefinitely on
  one stray edit anywhere in the vault, where an abort or `commit-run` failure is self-contained to
  the run that hit it — the next invocation gets a fresh run-id (§2.4) and proceeds normally, so
  the silence here costs a missed audit trail for one run, not a stalled loop.

  The two paths diverge, however, on whether the missed run self-heals, and the two do not share
  one remedy. **Abort is not data loss and needs no manual remedy.** §2.5's Ordering bullet places
  the commit strictly after markers, watermarks, and staging moves are written, and `file-notes`
  aborts during verification — before that point. The day-file never receives `ingested: true`, so
  §2.3's eligibility test still selects it, and the next run
  (silent or interactive) re-scans and correctly re-files or skips the same content, per §3's
  provenance and verbatim-body idempotency. **`commit-run` failure is not self-healing.** The
  failure occurs at drain step 6, strictly *after* markers, watermarks, and staging moves are
  already on disk (§2.5's Ordering bullet); the rollback reverts only the `CHANGELOG.md` prepend
  (§2.5's `commit-run`-failure bullet), so the `ingested: true` marker persists. §2.3's eligibility
  test reads that marker off the literal file on disk — §3 states there is no other state file —
  so every subsequent invocation, silent or interactive, skips the day-file permanently; re-scan
  does not reach it. The remedy for this path is manual and specific, not a re-run of ingest:
  Tucker re-invokes `commit-run` itself — `commit-run <vault> <report.json> <entry.md> <run-id>
  <mode>` (§2.5) — over the residual working-copy state, supplying the run-log sublist's
  still-present, uncommitted `report.json` and `entry.md` (§2.4), the same run-id the failed run
  used — the run-log directory's name under `_machine/logs/ingest/`, not a fresh one, since it is
  the join key to the `entry.md` already rendered into it (§2.5) — and the mode that run used
  (interactive if `confirmed-manifest.json` is in that directory, silent if not). The script's own
  prepend-then-commit sequence (§2.5) re-adds the reverted `CHANGELOG.md` entry and then commits,
  so the order is the script's to enforce, not the reader's to get right. No detection or new
  mechanism is added — this is the same
  accepted-residual-risk treatment already given to a process kill between `commit-run`'s two
  writes, immediately below, and to no-op accumulation, two bullets down: low-probability,
  self-limiting, hand-corrected, but for `commit-run` failure specifically the hand-correction is
  completing the interrupted commit, not re-running ingest. Revisit if it actually happens.
- **A process kill between `commit-run`'s two writes leaves an orphaned `CHANGELOG.md` entry.** If
  the process dies after the `CHANGELOG.md` prepend and before `jj commit` returns — SIGKILL, OOM,
  host restart, power loss — the revert-on-failure path in §2.5 never runs, and the orphaned entry
  rides into the next run's commit fileset (§2.4) instead of its own. No startup detection is
  added: a full-process death between two sequential writes is low-probability even under a nightly
  unattended cadence, and the fix is hand-correction — Tucker notices the misattributed entry at the
  next interactive run and edits `CHANGELOG.md` directly. Revisit if it actually happens.
- **No-op runs leave their own directory's files (`entry.md`, `report.json`) uncommitted on disk.**
  The no-op guard (§2.5) stops the commit and the changelog entry, but those files are written by
  earlier drain steps before the guard runs and are not retroactively removed. Because a no-op is
  the loop's most common outcome — most cadence firings find no closed, un-`ingested` day-file —
  these accumulate in `_machine/logs/ingest/` as steady-state clutter rather than a rare accident.
  Accepted: it is machine-space log residue, not vault content, and nothing downstream reads or is
  corrupted by it. Revisit (e.g. a periodic sweep) if the accumulation becomes a real problem.

## 6. Deferred

- **Lockfile for mutual exclusion — cross-skill and same-skill self-overlap.** Real but
  low-severity (worst case a duplicate note, which the synthesizer already nets). Covers both a
  concurrent human/synthesizer write and a scheduled invocation firing while a prior `/ingest
  --silent` is still running (a hung or overlong run). Free mitigation first: schedule the loop
  off-hours, and the scheduler must guarantee non-overlapping invocations (a `flock` around the
  whole `/ingest --silent` call is sufficient) — self-overlap is a scheduling responsibility, not a
  mechanism this spec builds. If collisions actually occur, a lockfile belongs in `Vault/CLAUDE.md`
  as a vault-wide rule for all writers, not bolted into ingest.
- **CHANGELOG regeneration script.** Until Syncthing exists.
- **Stabler dedup key** enabling today-inclusive silent runs.
- **The loop itself.** This spec makes ingest loop-*safe*; scheduling is a separate, trivial step
  (`/ingest --silent` on a cadence) and is not built here.
