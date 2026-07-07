---
name: ingest
description: "Drain captured thoughts into a knowledge vault as labeled atomic notes — the vault's intake pipeline. Subcommands: ingest [source?] [--today] [--silent] (drains closed journal day-files and registered external sources: split into atomic thoughts, three-way label-driven extraction against the vault's frozen vocabulary, one propose-confirm gate, scripted verbatim filing; --today additionally extracts from the open day so same-day actionables aren't blocked; --silent skips the gate — applies existing labels and files autonomously, never minting, ending with a mandatory digest), status (read-only health: pending day-files, per-source deltas, needs-label backlog, anomalies). Use whenever the user wants to ingest or drain their journal, process captured thoughts or notes into the vault, run the vault intake, pull from a registered ingest source, or check what's pending. Trigger phrases: 'ingest my journal', 'drain the journal', 'process my captures', 'run ingest', 'ingest today', 'silent ingest', 'ingest status', 'what's pending ingest'."
user-invocable: true
argument-hint: "[source?] [--today] [--silent] | status"
---

# ingest

Drain captured thoughts into a **populated vault** as labeled atomic notes. The intake half of the
vault's pull architecture: the journal (permanent capture surface) and registered external sources
in, labeled notes out, consumers downstream. Job **frozen** at split → label → file — ingest
writes no `status`, writes no `handled`, knows nothing about consumers, and never mints
vocabulary. New capability = a new consumer skill; ingest is never edited to add one.

## Identity & role

Portable and invariant across vaults: the logic (window the sources, split, classify against the
bank's `when_to_apply` descriptions read **live**, file per the note contract) doesn't depend on
any vault's content. The vocabulary is data, not skill body.

**Deterministic shell, semantic core.** Mechanical work is never freehanded by the model. The
`scripts/` directory owns windows, deltas, dedup, verification, and commit points; the model owns
split boundaries, three-way disposition, labeling, title generation, and the gate conversation.
Every script takes the vault path as an argument — no script knows where any vault lives.

**Hard posture: propose-confirm by default.** Nothing is written before you confirm at the gate.
The model is a smart suggester, not an autonomous librarian. `--silent` is the one sanctioned
exception (see "Silent mode"): it shifts review from pre-write to post-write via a mandatory
digest — and even silent, the vocabulary stays frozen and every write remains scripted, verbatim,
and jj-reversible.

## Per-install binding

This skill is portable. It names **no** environment paths in its body. Binding resolves in order:

1. **`~/.claude/ingest.local.md`** — if present, read and follow it: vault pointer, per-machine
   specifics.
2. **`~/.claude/vault.local.md`** — the canonical environment-vault pointer written by
   `vault create`.
3. **Neither exists → fail loudly** ("no vault registered — run `vault create` first, or write
   `~/.claude/ingest.local.md` pointing at a vault"). Never guess a path.

**Every invocation:** resolve the vault → read its `INSTRUCTION.md` + `_machine/labels.yml`
**live** → act. Query per the handshake's preference order; ripgrep is the required floor.

## Subcommands and routing

- `/ingest` — the full drain: journal first (freshest), then every registered source.
- `/ingest <source>` — scope to `journal` or one registered source (path or name).
- `/ingest --today` — the drain, plus extract from the open day **without marking** (see
  "Journal drain").
- `/ingest --silent` — the drain without the gate: applies existing labels and files
  autonomously, never minting; ends with a mandatory digest. Composes with a scope and
  `--today`. See "Silent mode".
- `/ingest status` — read-only health. See "status".

**`help` subcommand:** when invoked as `/ingest help`, summarize this skill and its subcommands
from the sections below rather than executing them.

## The drain (both source classes)

1. **Window** — run `scripts/journal-candidates <vault> [--today]` and
   `scripts/source-delta <vault>`: the eligible closed day-files, the open day (if `--today`),
   and each vcs source's changed files + hunks / each destructive source's current contents.
   Deterministic; zero model judgment.
2. **Split + label (subagents — the semantic core).** One subagent per registered source
   (isolation + its lens); journal day-files batched to subagents. Each: split into atomic
   thoughts (sub-bullets stay with their parent; a continuing thought is one thought), apply the
   three-way rule (below), label from **active** bank entries only, derive a short searchable
   title, and emit structured proposals with **verbatim bodies**. Subagents return proposals,
   never file dumps.
3. **Persist proposals** to `_machine/logs/ingest/<run>/proposals.json` *before* the gate — a
   crash mid-review must not lose the analysis. The run log records the vault's jj change-id at
   drain start (whole-run undo stays a one-liner).
4. **ONE batch confirm gate** *(skipped under `--silent` — see "Silent mode")*. Grouped by
   day-file/source: each proposed note's title, labels,
   disposition, and verbatim body as its own evidence. Batch-friendly:
   approve-all-with-exceptions; per-item relabel / re-split / demote-to-diary / promote;
   conversational corrections. A week's backlog is a five-minute review, not fifty questions.
5. **File (scripted).** `scripts/file-notes <vault> <confirmed-manifest.json>`: cross-proposal
   dedup → idempotent writes → md5 verify (abort-on-mismatch) → **then, in order:** `ingested`
   markers → `last_read` advances → destructive staging moves. Emits a written/skipped report;
   surface it. Then record `run.json` (`ts` = epoch-seconds time of recording, taken after markers
   land; `marked` day-files) in the run log — `status`'s marked-then-modified net reads it.

## Journal drain

- **Day-file definition (strict):** `journal/YYYY-MM-DD.md`, dated strictly before today, lacking
  `ingested: true`. Anything else in `journal/` is not ingest's business (`status` flags
  non-day-file squatters; relocation is a human refactor, never ingest's).
- **Three-way extraction, label-driven:** per thought — matches active label(s) → extract +
  label; knowledge-worthy but nothing fits → extract + `needs-label` (parked, never dropped; the
  synthesizer's `resolve` drains it); trivial narrative → stays diary-only. Knowledge-worthy is
  label-driven, not significance-driven: affective/state lines extract under their labels so the
  synthesizer can see patterns. The labels you define are the lever.
- **Fields:** split-siblings share `captured:` (= day date) and get Tier-1 factual `related:`
  links to each other — the one link class ingest may auto-create. `created:` = filing date;
  `source: journal/YYYY-MM-DD`; no `status`, no `handled`. Bodies verbatim.
- **Marker = per-file commit point:** `ingested: true` lands only after all of that file's
  confirmed notes are filed and verified. The day-file is never modified beyond the marker — it
  is the permanent diary; the day-file/note duplication is the one sanctioned denormalization.
- **`--today`:** extracts from the open day **without writing the marker** — same-day
  actionables (a morning session-seed) must not wait for tomorrow's drain. Safe under repeat
  runs and tomorrow's closing drain because filing is idempotent (provenance + verbatim-body
  match skips already-extracted thoughts). Known edge, accepted: a thought *edited* after
  extraction re-extracts as a second note; the synthesizer is the designed net.

## Sources drain

- **`track: vcs`:** committed state at the source's current checkout; process `diff(last_read..HEAD)`.
  Read a changed file whole for awareness; extract **only from changed hunks**. Provenance:
  `source: <remote> <path> @<commit>`. `last_read → HEAD` per-source, only after that source's
  notes are filed.
- **`track: destructive`:** consume current contents; **archive-not-delete** — consumed files
  move to `_machine/logs/ingest/<date>/` (literal `rm` would destroy out-of-lens content that
  was never extracted). Residue in staging = by definition unprocessed; no stored state.
- **Lens = filter, not classifier:** extract only thoughts matching the lens labels (each
  label's `when_to_apply` is the extraction instruction). Out-of-lens content is out of scope —
  it stays in the source, unextracted, never parked. `needs-label` is journal-only: the journal
  is the unfiltered brain-stream; a registered source was pointed here through a deliberate lens.

## Silent mode (`--silent`)

The drain without the gate: proposals are auto-confirmed as emitted and filed directly. For
unattended or low-friction runs (a cron drain; a routine morning `/ingest --today --silent`) once
the vocabulary has stabilized — the interactive gate's observed correction rate is the signal for
whether silent is safe yet.

What changes, and what doesn't:

- **Skipped:** the confirm gate (drain step 4). Nothing else.
- **Unchanged:** three-way extraction against the **frozen** vocabulary — no-fit thoughts still
  park under `needs-label`; silent **never mints or suggests labels** — plus scripted verbatim
  filing, ordered commit points, and idempotency.
- **Action labels (`todo`, `session-seed`) are still applied.** Safe because their consumers all
  carry their own human gates (session-planner asks before spinning anything up; schedulers
  preview before writing) — over-application is caught at the point of action, never silently
  executed.
- **Mandatory digest:** every silent run ends with a digest — each note filed (title + labels +
  source), everything parked under `needs-label`, everything left diary-only, plus the
  `file-notes` report — surfaced to the user AND persisted to
  `_machine/logs/ingest/<run>/digest.md`. Silent shifts review from pre-write to post-write; it
  is never invisible. Whole-run undo stays a one-liner via the run log's jj change-id.
- **Deliberately not extended to the synthesizer:** merges (drafted rewrites) and associative
  links require pre-write human eyes — that skill's gates are the license for its operations,
  not friction.

## status

`scripts/ingest-status <vault>` — read-only, principle 7 (surface on demand, never nag):

- unprocessed closed day-files (count + list)
- per-source pending delta (`last_read..HEAD` commit count)
- `needs-label` backlog size (the synthesizer's queue)
- **marked-then-modified day-files** — a marked file whose mtime postdates its marking run (late
  phone-sync detection net; fix = remove the marker, re-drain — idempotent filing makes that
  duplicate-free)
- journal squatters (non-day-file notes in `journal/` — relocate to `notes/`, manually)

## Invariants (cross-cutting, hard)

- **Propose-confirm by default** — nothing written before the gate. `--silent` is the one
  sanctioned exception: gate skipped, mandatory digest surfaced + persisted to
  `_machine/logs/ingest/<run>/digest.md` (review-after), vocabulary still frozen, writes still
  scripted and verbatim.
- **Never writes `status`, never writes `handled`** — field ownership per INSTRUCTION.md.
- **Vocabulary frozen** — active labels or `needs-label`; minting is the synthesizer's.
- **Verbatim bodies, scripted filing** — extraction copies; `file-notes` verifies (md5,
  abort-on-mismatch); the model never freehands writes.
- **No state file** — idempotency is provenance + verbatim-body match; rejections need no memory
  (a rejected split stays diary narrative under a marked file).
- **Ordered commit points** — markers/watermarks/moves strictly after verified filing; no
  partial state survives a re-run.
- **Env-agnostic** — binding via `~/.claude/ingest.local.md` → `~/.claude/vault.local.md` →
  loud failure; scripts take the vault path as an argument.
