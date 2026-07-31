# Design — atomic ingest commits + vault CHANGELOG (claude-materia)

> **Status:** Design approved 2026-07-30 (Tucker). Next: implementation plan (writing-plans), then
> execution.
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
rollback-then-re-run-silent is a no-op loop: the same day-file through the same frozen vocabulary
produces the same proposals. The correction has to be supplied at the gate.

### 2.2 The vocabulary stays frozen in silent mode

Tucker's rule — *silent behaves identically to interactive except for the gate* — is adopted.
Applied correctly it yields **frozen**, because interactive ingest does not mint either. Four
files agree: ingest SKILL.md §identity and §invariants, synthesizer SKILL.md ("Ingest never mints
vocabulary… **all** post-bootstrap topical vocabulary growth happens here"), and `Vault/CLAUDE.md`.

**`labels_registered_this_run` in `run.json` is drift.** The field appears nowhere in the skill;
`run.json`'s spec records `ts` and `marked` only. It was improvised during the 2026-07-25 run to
record a label *Tucker* minted in conversation at the gate. Human minting mid-gate is sanctioned;
the ad-hoc field is not. It is removed from the run-log schema.

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
day while only ever reading immutable files.

If today-inclusive silent runs are ever wanted, the honest fix is a stabler dedup key, not a flag
change. Deferred until actually wanted.

### 2.4 The commit is scoped to the paths the run touched

**This is the one non-obvious mechanism in the design.** Everything else is a one-liner.

`jj commit [FILESETS]` (verified, 0.43): *"the selected changes stay in the current commit while
the remaining changes are moved to a new working-copy commit on top."* So a path-scoped commit
finalizes `@` containing only the run's files, and any unrelated dirt survives untouched in a fresh
working copy.

**The path list is not inferred — `file-notes` already emits it.** Its report carries `written`,
`marked`, `advanced`, and `moved`: the vault paths it just touched, produced by the code that
touched them. Add the run-log directory and `CHANGELOG.md` and the set is complete. No globbing, no
diffing, no heuristics, and `-a` never appears.

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
  the vault halts ingestion indefinitely and silently.

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
  each missed. This is the one genuinely new semantic requirement in this design; without it the
  Parked section degrades to a list of titles and the vocabulary-pressure signal is lost.
- **Abort ⇒ no commit.** `file-notes` exits 1 on empty body or md5 mismatch; the flow stops and
  never reaches the commit step. A broken run stays visible in the working copy rather than being
  buried in history.
- **No-op ⇒ no commit, no run directory, no changelog entry.** One guard, so an empty run does not
  produce an empty commit.
- **Message:** `ingest(<mode>): <run-id> — N notes, M days, P parked`.
- **No change-id capture.** An earlier draft captured `@`'s change-id before committing to embed it
  in the changelog. Dropped: the run-id already appears in both the commit message and the changelog
  entry, so it *is* the join key. Finding the commit is
  `jj log -r 'description(glob:"*<run-id>*")'`.
- **Ordering:** the commit is a new drain step 6, strictly after `file-notes` verification, markers,
  watermarks, and staging moves.

### 2.6 CHANGELOG.md — vault root, append-only, newest first

**Placement:** vault root. No contract conflict — the immutable-layout rule governs *directories*.
Consequence: it appears in Obsidian's explorer, search, and graph as a frontmatter-less node; the
fix, if it grates, is an Obsidian exclusion filter, not a move.

**Append-only, written inside the run's own commit.** This makes `jj abandon` remove the entry
automatically, keeping the file truthful about history with no extra bookkeeping.

A *derived* changelog (regenerated from run logs) was considered as insurance against sync
conflicts on an append-hot file. `.stignore` shows Syncthing is not yet set up ("for later Phase
3"), so the risk is deferred. `run.json` will carry the same data structured, so regeneration stays
possible later. **The regeneration script is not built now.**

**Format:**

```markdown
# Vault Changelog

Ingest run history, newest first. Each entry is one commit.
To undo a run: `jj log -r 'description(glob:"*<run-id>*")'`, then `jj abandon <change-id>`.

---

## 2026-07-30-1 · silent
**7 filed** from 3 day-files · **2 parked** · 4 diary-only · 1 skipped (already filed)

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
```

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

### 2.8 `digest.md` is collapsed into the changelog

**Flagged: decided during spec-writing, not in the design conversation — Tucker may veto.**

The 2026-07-06 amendment requires every silent run to end with a digest surfaced to the user *and*
persisted to `_machine/logs/ingest/<run>/digest.md`. The changelog entry is that digest, in a file
Tucker actually reads, with the same content. Keeping both means two overlapping records that can
drift.

`digest.md` is dropped. The mandatory-digest requirement is **preserved and satisfied** by the
changelog entry: still surfaced to the user at run end, still persisted, still inside the run's
commit. `run.json` retains the structured counts.

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

| File | Change |
|---|---|
| `plugins/vault/skills/ingest/scripts/commit-run` | **new** — scoped `jj commit` from the `file-notes` report; prepends the model-rendered `entry.md` to `CHANGELOG.md` |
| `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh` | **new** — scoping (unrelated dirt survives), no-op guard, abort path, changelog prepend |
| `plugins/vault/skills/ingest/SKILL.md` | drain step 6; split+label emits near-miss rationale for parked thoughts; §Silent mode (digest → changelog); §Invariants; `--today` loop guidance; run-log schema (drop `labels_registered_this_run`) |
| `plugins/vault/skills/vault/assets/CLAUDE.md` | document `CHANGELOG.md` in the layout section |
| `plugins/vault/skills/vault/assets/CHANGELOG.md` | **new** — seed stamped by `vault create` |
| `plugins/vault/skills/vault/SKILL.md` | seed the changelog on `vault create` |
| `plugins/vault/.claude-plugin/plugin.json` | version 1.1.0 → 1.2.0 |
| `BACKLOG.md` | reopen/annotate the `--silent` item; note the loop precondition |

## 5. Known edges, accepted

- **Path-scoped commits mean anything ingest does not touch stays uncommitted indefinitely.** By
  design — it is Tucker's work to commit — but the 257-file backlog will not self-resolve, and
  neither will the 35 journal squatters already tracked in BACKLOG.
- **Prerequisite:** commit the 257-file backlog manually before enabling the loop. Nothing breaks
  otherwise; it migrates to the new working copy and stays uncommitted. But running a
  per-run-commit system atop a six-week uncommitted blob defeats the point.
- **Abandoning a non-head run** rebases later runs, whose changelog hunks all target the top of the
  file — the likeliest conflict site. Low risk given §2.1's corrective path almost always abandons
  the most recent run.
- **`existing_match` is O(notes) per proposed note** — ~17k file reads on a 34-note run against 498
  notes. Fine now; revisit if the pool reaches a few thousand. Note the tension with
  INSTRUCTION.md's "never a full-vault read" (a query rule, not a filing rule, but adjacent).
- **`.stignore` excludes `.jj/`.** If Syncthing is ever enabled, a second machine gets files with no
  jj state and sees everything as changed. Out of scope; flagged.

## 6. Deferred

- **Lockfile for cross-skill mutual exclusion.** Real but low-severity (worst case a duplicate note,
  which the synthesizer already nets). Free mitigation first: schedule the loop off-hours. If
  collisions actually occur, it belongs in `Vault/CLAUDE.md` as a vault-wide rule for all writers,
  not bolted into ingest.
- **CHANGELOG regeneration script.** Until Syncthing exists.
- **Stabler dedup key** enabling today-inclusive silent runs.
- **The loop itself.** This spec makes ingest loop-*safe*; scheduling is a separate, trivial step
  (`/ingest --silent` on a cadence) and is not built here.
