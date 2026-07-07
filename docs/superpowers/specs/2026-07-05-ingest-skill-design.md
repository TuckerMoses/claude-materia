# Design — the `ingest` skill (claude-materia)

> **Status:** Design approved 2026-07-05. Next: implementation plan (writing-plans), then execution
> in a **fresh session** (context-pollution split agreed with Tucker: design/spec/plan in the design
> session, build elsewhere via the plan's execution skills).
> **Context:** The last unbuilt Phase-4 organ of the vault system. The vault at `~/Vault/` is live
> (flat `notes/` + `journal/`, `_machine/labels.yml`, `INSTRUCTION.md`); the synthesizer
> (2026-07-03 spec, shipped v0.12.0) consumes the pool and owns vocabulary growth. Ingest is the
> *intake*: it drains closed journal day-files and registered external sources into labeled atomic
> notes. Until it exists, the vault only gets cleaner, never fuller.
> **Full architecture reference:** `~/.claude/plans/vault-design.md` (2026-06-21 capture-model
> revision + 2026-06-19 revision authoritative). Design diagram:
> `2026-07-05-ingest-skill-design.svg` (sibling file).
> **Build gate:** every build follows the repo convention — an
> `adversarial-review run default:coherence` pass on the diff before ship (Tucker, 2026-07-05).

---

## 1. Identity & home

A **portable, env-agnostic** claude-materia skill named `ingest`. This closes the question the
synthesizer build deliberately left open: `vault/SKILL.md` still claims ongoing-ingest
*classification* belongs vault-local. That claim falls for the same reason the synthesizer's did,
plus a stronger one:

- **Same reason:** ingest's *logic* is invariant across vaults — read the journal delta, split,
  classify against `labels.yml`'s `when_to_apply` descriptions (read **live**), file per the note
  contract. The vocabulary is data, not skill body; the `.local.md` seam exists for exactly this.
- **Stronger reason — the work-vault future:** `vault create` exists to stamp vaults on other
  machines, but a born-correct vault with no ingest is a dead vault. Vault-local ingest means
  re-authoring or copying per vault; copies drift — the define-once violation the architecture
  exists to prevent. Portable ingest makes the *system* replicable, not just the skeleton.

**What it is** (design-doc Phase-4 deliverable #1, per the 2026-06-21 capture model): the intake
pipeline. Job frozen at **split → label → file**. It writes no `status`, writes no `handled`,
knows nothing about consumers, and never mints vocabulary. New capability = a new consumer skill;
ingest is never edited to add one.

**Hard posture:** propose-confirm by default. The model is a smart suggester, not an autonomous
librarian (principle 3). `--silent` is the one sanctioned exception — see Amendment (2026-07-06).

## 2. Subcommand surface (locked)

`/ingest [source?] [--today] [--silent]` · `/ingest status`. (`help` via the kernel-level
universal convention; no `discuss`.) `--silent` added by Amendment (2026-07-06); composes with
scope and `--today`.

- **Bare `/ingest`** = the full drain: journal first (freshest thoughts), then every registered
  source. The registry knows what exists; the user shouldn't have to.
- **`[source?]`** scopes: `journal`, or a registered source's path/name.
- **`--today`** widens the journal window to include the open day (§3).
- **`/ingest status`** — read-only health (principle 7: surface on demand, never nag):
  unprocessed day-file count, per-source pending delta (`last_read..HEAD`), `needs-label` backlog
  size, **marked-then-modified day-files** (§6), and the journal-squatter count (§3).

## 3. Journal drain

1. **Day-file definition (strict):** a journal ingest source is a file matching
   `journal/YYYY-MM-DD.md`, dated **strictly before today**, lacking `ingested: true`. Anything
   else in `journal/` is not ingest's business — the strict filename gate is what makes the 35
   migrated topical notes currently squatting in `journal/` harmless to correctness.
2. **Squatters:** those 35 notes should move to `notes/` (they're fully-labeled atomic notes,
   invisible to the synthesizer where they sit) — but relocation is **not ingest's job** (ingest
   never moves notes; no one-time migration baked into a recurring skill). `/ingest status`
   reports the anomaly loudly; the move is a one-time human-confirmed refactor done in a vault
   session.
3. **Three-way extraction, label-driven** (2026-06-21 revision, verbatim semantics): per closed
   day-file, split into atomic thoughts; each thought → (a) matches active label(s) → extract +
   label into `notes/`; (b) knowledge-worthy but nothing fits → extract + `needs-label` (parked,
   never dropped; the synthesizer's `resolve` drains it); (c) trivial narrative → stays
   diary-only. "Knowledge-worthy" is label-driven, not significance-driven — affective/state
   lines extract under `self-state`/`mental-health` etc. so the synthesizer can see patterns.
4. **Split & fields:** day-file = capture unit. Sub-bullets stay with their parent thought.
   Split-siblings share `captured:` (= the day date) and receive Tier-1 factual `related:` links
   to each other — the one link class ingest may auto-create (lesson #4; associative links are
   the synthesizer's). `created:` = filing date; `source: journal/YYYY-MM-DD`; **no `status`, no
   `handled`**. Bodies **verbatim** from the day-file's lines — extraction copies, never rewrites
   (iron rule, fully binding).
5. **Marker:** `ingested: true` is written to a day-file's frontmatter only after *all* its
   confirmed notes are filed and verified — the per-file commit point. The day-file is never
   modified beyond the marker (it is the permanent diary; content duplication between frozen
   day-file and derived note is the one sanctioned denormalization).
6. **`--today` (same-day actionables):** drains closed days as normal *plus* extracts from
   today's file **without writing the marker**. Rationale: a morning "spin up a session about X"
   must not be blocked until tomorrow's drain. Safety: naive force-marking would lose evening
   additions; not marking would duplicate tomorrow — so `--today` rests on idempotent filing
   (§6.1) instead of the marker. Repeated `--today` runs skip already-extracted thoughts by
   body-match; the closing drain marks the file and skips everything `--today` took. Known edge,
   accepted: a thought *edited* after extraction re-extracts as a second note (same
   edited-in-place limitation as vcs sources; the synthesizer is the designed net).

## 4. Sources drain (`ingest_paths` registry)

- **`track: vcs`** — live repos, kept intact. Read committed state on the registered branch;
  process `diff(last_read..HEAD)`. Subagents read a changed file whole for *awareness* but
  extract **only from changed hunks**. `last_read → HEAD` per-source, only after that source's
  confirmed notes are filed. Provenance: `source: <remote> <path> @<commit>`.
- **`track: destructive`** — staging dirs, drained. Consume current contents;
  **archive-not-delete** (corrects the design doc's "removes them"): consumed files move to
  `_machine/logs/ingest/<date>/` in the vault. Literal `rm` would destroy out-of-lens content
  that was never extracted — silent data loss. Drain semantics survive (residue in staging = by
  definition unprocessed; no stored state).
- **Lens = filter, not classifier.** Extract only thoughts matching the lens labels (each label's
  `when_to_apply` is the extraction instruction). **`needs-label` is journal-only**: the journal
  is the unfiltered brain-stream, so unfittable-but-worthy thoughts park; a registered source was
  pointed at the vault through a deliberate lens, so out-of-lens content is out of *scope*, not
  unfittable — it stays in the source, unextracted.
- **Dispatch shape:** one subagent per registered source (isolation + its lens); journal
  day-files batch to subagents likewise. All proposals flow to a single **serial filer** (§7)
  that dedups cross-proposal (journal and a source can surface the same thought) and performs all
  writes. One confirm gate for everything (§5).

## 5. Confirmation model — interactive batch gate; headless deferred

> **Amendment (2026-07-06):** The "headless deferred" stance below was superseded. `--silent` ships
> in vault v1.1.0. See Amendment section at end of this doc for full semantics.

- **One consolidated gate per run**, grouped by day-file/source: each proposed note's title,
  labels, disposition (extract / `needs-label` / diary-only), with the **verbatim body as its own
  evidence**. Batch-friendly responses: approve-all-with-exceptions; per-item relabel, re-split,
  demote-to-diary, promote; conversational corrections (capability #8). A week's backlog must be
  a five-minute review, not fifty questions.
- **Nothing is written before confirmation** (interactive mode). After confirm, the filer writes
  and only then commits watermarks (§6.2). Under `--silent`, the gate is skipped — see Amendment.
- **Rejections need no memory:** a rejected split stays in the day-file as diary narrative; the
  file's marker means it is never revisited.
- **Headless mode (unattended cron/loop drain, no gate) was deferred at v1, deliberately:** (a)
  YAGNI — no capture surface was live; volume and classification accuracy were unknown; (b)
  principle 3 is explicit that the user confirms or corrects; (c) deferral costs nothing — the
  `needs-label` freeze was designed so ingest never needs a mid-run decision, so headless later
  is purely additive (a `--yes` flag / cron invocation skipping the gate), zero redesign.
  **Trigger condition (met 2026-07-06):** the observed correction rate at the gate was ≈ zero on
  the first real gate run — see Amendment.

## 6. Idempotency & failure

1. **Idempotent filing — the core primitive:** a thought is already-filed iff a note exists with
   the same `source` provenance and an **identical verbatim body** (cheap: `rg` the source,
   compare bodies; deterministic because extraction is verbatim). Filing skips already-filed
   thoughts. This one primitive carries `--today` re-runs, crash re-runs, and
   filed-but-unmarked recovery. No state file exists — ingest's idempotency needs none.
2. **Ordered commit points:** notes written → md5-verified → *then* `ingested` markers →
   `last_read` advances → destructive staging moves. A crash at any point leaves either
   unprocessed state (re-run redoes) or filed-but-unmarked state (re-run body-match-skips, then
   commits the marker). No partial state survives a re-run.
3. **Late phone-sync edits to marked day-files** (phone appends Wednesday, syncs Friday; Wednesday
   already marked): **detection net, not prevention machinery.** `/ingest status` compares each
   marked day-file's jj modification against its marker and flags "modified after ingest"; the fix
   is unmark → re-drain (safe and duplicate-free via §6.1). Re-diffing every marked file every run
   is the commit-churn the design explicitly rejected.
4. **Durable working state:** subagent proposals persist to `_machine/logs/ingest/<run>/`
   *before* the gate (lesson #8 — never `/tmp`; a crash mid-review must not lose the analysis).
   The run log records the jj change-id at drain start, keeping whole-run undo a one-liner.

## 7. Deterministic shell, semantic core (scripts)

Mechanical work is never freehanded by the model — the 412-truncated-notes incident enforced in
code. The skill ships `skills/ingest/scripts/` (claude-materia's first script-bearing skill;
precedented by superpowers' skills and mandated in spirit by `vault create`'s scripted Phase D):

- **`journal-candidates`** — emits the day-file window (closed, unmarked; `--today` widens).
  Pure date/frontmatter logic.
- **`source-delta`** — per vcs source, emits changed files + hunks for `last_read..HEAD`.
- **`file-notes`** — the serial filer: consumes the confirmed-proposals manifest; cross-proposal
  dedup → idempotent writes (§6.1) → md5 verify with abort-on-mismatch → ordered commit points
  (§6.2). The iron-rule enforcer is mechanical.
- **`ingest-status`** — the read-only status computation (§2), including modified-after-ingest
  detection and the squatter count.

All env-agnostic: the vault path arrives as an argument from the binding chain; bash/python3
only; no hardcoded paths. **The model owns:** split boundaries, three-way disposition, labeling,
title generation, and the gate conversation. **The scripts own:** windows, deltas, dedup,
verification, and commits.

## 8. Per-install binding

Identical chain to the synthesizer:

1. `~/.claude/ingest.local.md` if present (vault pointer, overrides, per-machine specifics);
2. else `~/.claude/vault.local.md` (the canonical environment-vault pointer);
3. else **fail loudly** — never guess a path.

Every invocation reads `INSTRUCTION.md` + `_machine/labels.yml` **live**. Query surface per the
handshake's preference order; ripgrep is the required floor. Field ownership per INSTRUCTION.md:
ingest writes `title`, `labels` (at creation), `created`/`captured`/`source`, Tier-1 `related:`
sibling links — never `status`, never `handled`.

## 9. Cascade edits (shipped with this skill; all inside claude-materia)

1. **`skills/vault/SKILL.md` — Identity section:** remove the last vault-local claim
   (ongoing-ingest classification) — it joins the synthesizer under "portable consumers reading
   the vocabulary live." The vault-local category empties; the question closes.
2. **`README.md`** — materia-table row. **`.claude-plugin/plugin.json`** — version
   `0.12.0 → 0.13.0`.
3. **No INSTRUCTION.md edits needed** — field ownership and the `source:` journal format were
   already updated by the synthesizer build's cascades.

**Runtime-only effects at first use (not build edits):** `_machine/logs/ingest/` created on first
run. **Not touched:** `~/.claude/plans/vault-design.md` (parallel session), `labels.yml`
(read-only to ingest), any env file, the live `~/Vault` during build.

## 10. Out of scope (v1)

- **Headless/unattended mode** — shipped as `--silent` (vault v1.1.0, Amendment 2026-07-06); no longer deferred.
- **Squatter relocation** — a one-time human refactor in a vault session, surfaced by `status`,
  never performed by ingest.
- **Capture surfaces** (`/capture`, `/sanitize`, phone Shortcut) — Phase 5, separate work; ingest
  consumes whatever lands in the journal regardless of how.
- **Sync setup** (Syncthing/Möbius) — Phase 3, orthogonal.
- **Interactive mint-at-ingest** — the `needs-label` + synthesizer path is the durable floor
  (design doc, 2026-06-21); an on-the-spot label offer remains an optional later additive.
- **Stable per-source-item ids** for edited-in-place thoughts — the accepted limitation stands;
  the synthesizer dedups.

---

## Amendment (2026-07-06) — `--silent` mode

Supersedes §5's "interactive-only v1" and resolves the headless BACKLOG item. Decided with Tucker
after the first real gate run (a month of Apple Notes backlog) came back clean — the named trigger
(correction rate ≈ 0) was met on first contact.

- **`--silent` flag on the drain** (composes with scope and `--today`): skips the confirm gate
  only. Everything else is unchanged — three-way extraction against the frozen vocabulary
  (no-fit → `needs-label`; silent never mints or suggests labels), scripted verbatim filing,
  ordered commit points, idempotency.
- **Action labels still applied silently** — their consumers all carry their own human gates
  (session-planner asks; schedulers preview), so over-application is caught at the point of
  action.
- **Mandatory digest** — surfaced to the user and persisted to
  `_machine/logs/ingest/<run>/digest.md`: notes filed (title/labels/source), parked, diary-only,
  plus the file-notes report. Principle 3's "reviewable" shifts from pre-write to post-write;
  silent is never invisible. Undo remains one jj command via the run log's change-id.
- **Explicitly not extended to the synthesizer** — merges are drafted rewrites and links are
  noise-prone graph writes; pre-write human approval is the license for those operations. The
  synthesizer remains propose-confirm always.
