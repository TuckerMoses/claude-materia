---
name: vault
description: "Create and operate a portable knowledge vault — a flat, label-based markdown note system. Three subcommands: create (bootstrap a new born-correct vault from a source corpus or cold, deriving its label vocabulary and filing notes verbatim), add-source (register an external ingest source in the vault's pull registry), discuss (meta-conversation about how the vault and this skill work). Use whenever the user wants to set up a knowledge vault / second brain / Zettelkasten / notes system, bootstrap a vault from exported notes (Apple Notes, Obsidian, a markdown dump), migrate a notes corpus into a structured labeled vault, register a repo or directory as an ingest source for a vault, or talk through vault architecture. Trigger phrases: 'create a vault', 'set up my notes', 'bootstrap a vault from these notes', 'turn this export into a vault', 'add an ingest source', 'register a source with my vault', 'how should my vault work'."
user-invocable: true
argument-hint: "[subcommand] [args] — create [corpus-path?], add-source [path], discuss [topic?]"
---

# vault

Create and operate a **portable, env-agnostic** knowledge vault: a flat pool of atomic markdown notes
(`notes/`) plus a separate `journal/`, organized by a label vocabulary (`_machine/labels.yml`) rather
than folders, with a thin external integration handshake (`INSTRUCTION.md`).

## Identity & organizing principle

This skill is the home for vault operations whose logic is **invariant across vaults** — independent
of any particular vault's content or vocabulary.

- **Invariant-across-vaults → here.** Create the structure; register an ingest source. These don't
  depend on a vault's content, so they live here, once.
- **Content-dependent → vault-local (NOT here).** Ongoing-ingest *classification* and the synthesizer
  depend on a vault's derived vocabulary; they belong in vault-local skills.

**The templates in `assets/` ARE the spec.** Cross-environment consistency rides in this skill: two
vaults stay consistent because they were stamped from the same `assets/` templates, not because any
env machinery enforces it. `assets/` is the single source of truth for the final architecture and
what makes a created vault born-correct.

**Singleton-aware.** One vault per environment is an invariant. This skill produces a *singular*
result per environment (like a dotfiles/stow bootstrap) and does not spawn or manage N within-
environment instances. Its plurality is cross-environment (a personal vault + a work vault).

## Per-install binding

This skill is portable. It names **no** environment paths in its body. It binds per-install through a
single canonical pointer:

- **`~/.claude/vault.local.md`** — the canonical environment-vault pointer: the vault path and its
  `INSTRUCTION.md` location. Written by `create` (spec §7). Read by `add-source` and `discuss` to
  locate the vault. This is the one-canonical-pointer extension of the standard `.local.md` seam,
  justified by the one-vault-per-environment singleton.

If `~/.claude/vault.local.md` is absent when `add-source`/`discuss` need it, fail **loudly** ("no
vault registered — run `vault create` first") rather than guessing a path.

## Subcommands and routing

- `/vault` — infer the subcommand from arguments and conversation context.
- `/vault create [corpus-path?]` — bootstrap a new vault. Corpus-adaptive: a path to exported
  notes / a markdown dir runs the corpus-seeded path (Analyze → Structure-lock → Scaffold → File);
  no path runs the cold start (skip Analyze/File, confirm a minimal seed vocabulary). See
  "create".
- `/vault add-source [path]` — register an external ingest source in the vault's
  `_machine/ingest_paths.yml`. See "add-source".
- `/vault discuss [topic?]` — meta-conversation about how the vault and this skill work; routes the
  env-registration taxonomy question to `kind-bootstrapper discuss`. See "discuss".

**`help` subcommand:** when invoked as `/vault help`, summarize this skill and its three subcommands
from the sections below rather than executing any of them.

## create

Bootstrap a new vault. **Corpus-adaptive:** the same subcommand handles a corpus-seeded start (a path
to exported notes / a markdown directory) and a cold start (no corpus). This encodes the bootstrap
*process* (analyze source → derive THIS vault's bespoke shape → scaffold → file), not a fixed
pipeline.

Four phases: **Analyze → Structure-lock → Scaffold → File.**

### A · Analyze  *(corpus-seeded only; cold start → skip)*

Given a source corpus, dispatch **map-reduce subagents** over it (do not full-read the corpus into one
context). Each mapper characterizes a shard; the reduce step merges. Characterize: candidate
domain/topic labels, note types, multi-thought fragments (single files holding several distinct
thoughts), and a **sensitive-content scan** (flag medical/financial/credential material). Persist
intermediate per-shard results to a durable scratch dir (not `/tmp`) so a crash doesn't lose the map.

Output is a structure **hypothesis** — a starting point, never a commitment.

### B · Structure-lock  *(HARD GATE, interactive)*

Present the hypothesis. Iterate with the user. Then **lock**: the bespoke vocabulary (domain/topic
labels), this-vault shape rules, per-note dispositions (live / archive / ignore), and the
multi-thought policy (how a multi-thought file splits into siblings). **Nothing scaffolds until the
structure is locked.**

*(Cold start → instead of deriving, confirm a minimal seed vocabulary with the user — the four action
labels plus any obvious starters — and lock that.)*

### C · Scaffold  *(deterministic, from `assets/` templates)*

Create the skeleton and the final-architecture files by instantiating `assets/`. The templates ARE
the spec; this phase only stamps them (plus the locked vocabulary). Steps:

1. Create the vault directory; `jj init` (jj honors `.gitignore`).
2. Stamp ignore files: `assets/gitignore → .gitignore`, `assets/jjignore → .jjignore`,
   `assets/stignore → .stignore` (rename — add the leading dot).
3. Stamp `assets/obsidian/ → .obsidian/` (includes `daily-notes.json` — configures the daily-notes
   plugin: `"folder": "journal"`, `"format": "YYYY-MM-DD"`, `"autorun": false` — the "open daily note
   on startup" toggle; suppresses empty root-note creation on app launch).
4. Create `notes/` (flat pool), `journal/` (daily-notes capture surface and permanent ingest source),
   `_archive/`, `_machine/`.
5. Stamp `assets/labels.yml → _machine/labels.yml`, then **append the locked domain/topic vocabulary**
   from Phase B, each entry conforming to the bank schema (`label → {when_to_apply, status: active}`).
   The four action labels are already present from the template; the container schemes stay as
   comments (no concrete `<name>` entries — those are registered later by the manager skills).
6. Stamp `assets/ingest_paths.yml → _machine/ingest_paths.yml` (empty registry).
7. Stamp `assets/INSTRUCTION.md → INSTRUCTION.md`, replacing `{{VAULT_PATH}}` with the absolute vault
   path.
8. Stamp `assets/CLAUDE.md → CLAUDE.md` (the vault's internal OS-contract; verbatim, no params).
9. **Write `~/.claude/vault.local.md`** — the canonical environment-vault pointer (path +
   `INSTRUCTION.md` location). See "Per-install binding".

### D · File  *(corpus-seeded only; cold start → skip)*

A **deterministic scripted pass** filing the analyzed corpus into `notes/` / `journal/` as conformant
labeled notes per the locked structure. Each filed note: `title` (derived label), `labels[]` (from the
locked vocabulary), the provenance fields (`created`/`captured`/`source`), **and NO `status`** (status
is absent at creation — written later by a consumer or human). Bodies are preserved **verbatim**.

**Content-preservation iron rule (see "Iron rule" below):** before writing, record per-note
`md5(body)`; after writing, recompute and assert identical. **Abort** the whole pass (leaving
originals intact) on any mismatch, or on any non-empty body becoming empty. This is a scripted,
all-or-nothing pass — never a best-effort one.

This produces final-architecture notes directly — **born-correct**, never needs a later migration.

*(Cold start → skip; the vocabulary grows later via the future ongoing-ingest skill.)*

### Iron rule (hard invariant)

Note **bodies preserve the full source verbatim**; `title` is a derived label only and never licenses
dropping body content. Phase D's hash-verify/abort-on-mismatch procedure is the mechanical enforcement
of this rule and is **mandatory** — it is the exact step that nearly lost the corpus during the
original bootstrap. Procedure, per note: `before = md5(body)` → write note → `after = md5(body_read_back)`
→ assert `before == after` and assert `not (len(body) > 0 and len(body_read_back) == 0)`; on any failure,
abort the pass and leave all originals untouched. On abort, emit a clear error naming the offending note
and reporting both the before and after `md5(body)` hashes so the failure is never silent or vague.

## add-source

Register an external source in the vault's `_machine/ingest_paths.yml` (the input-side **pull**
registry). The logic is invariant across vaults (pure schema + procedure), which is why it lives here
rather than being re-implemented in each vault's local ingest skill.

Operates on the vault named in `~/.claude/vault.local.md`. If that pointer is absent, fail loudly.

### Accept

- `path` — the source location.
- `track: vcs | destructive` — vcs = read commits since a watermark; destructive = drained residue.
- `lens` — a **subset of `_machine/labels.yml`** (the label-lens for this source).
- `remote` / `branch` — **vcs only**.
- `description` — optional, non-selector human note.

### Validate

- `path` resolves; if it does not, fail loudly (do not register a source at an unresolvable path).
- **Every lens label exists in `_machine/labels.yml`.** (This is why a freshly cold-started vault's
  lenses are limited to the action/seed vocabulary — see "Cold-start interaction".)
- For `vcs`: the repo + `branch` resolve. Initialize the `last_read` baseline (current tip commit).
- For `destructive`: store **no** `last_read` state — the residue is by definition unprocessed.

### Append

Append a conformant entry to `sources:` in `_machine/ingest_paths.yml`. This append **is** the
deliberate accepted-read-exposure registration (additive-surface model — every entry is an explicit
"I agree to send this source through ingest").

### Two writers, one schema (no conflict)

`add-source` writes **new entries** (invariant registration). The future ongoing-ingest skill writes
**`last_read` watermarks** (runtime state) on **vcs** entries only — destructive entries have no
watermark. Same pattern as `labels.yml` (managers register, ingest reads). The schema is defined once,
here and in `INSTRUCTION.md`; do not fork it.

### Cold-start interaction

A lens can only reference labels that already exist in `labels.yml`, so on a freshly cold-started vault
(action/seed labels only) `add-source` lenses are limited to that vocabulary. Richer lenses become
available as the bank grows via ongoing-ingest. Surface this to the user rather than silently dropping
an unknown lens label — an unknown label is a hard validation failure, not a warning.

## discuss

Meta-conversation about how the vault and this skill work — architecture questions, why a flat
label-based pool, how the contracts fit together, when a vault-local skill (ongoing-ingest,
synthesizer) is warranted vs. an addition here.

Operates against the vault named in `~/.claude/vault.local.md` when one is registered (so discussion
can reference the live vocabulary), but does not require it for pure meta-discussion.

**Routes the env-registration taxonomy question to `kind-bootstrapper discuss`.** The question — does
the singleton definition widen to admit a *reusably-bootstrapped per-environment singleton*, or is
that a new category? — is **not** decided here. This skill never writes to env itself; the taxonomy
decision is decoupled and does not block builds or behavior. When the conversation reaches that
question, hand it to `kind-bootstrapper discuss` rather than answering it inline.

## Invariants (cross-cutting, hard)

- **Content-preservation iron rule** — Phase D of `create` is body-verbatim + hash-verified,
  abort-on-mismatch (see "Iron rule" under create). The exact step that nearly lost the corpus before.
- **Born-correct** — `create` produces the final architecture directly (flat `notes/`, separate
  `journal/`, `labels[]`, **no `status`** in new notes, `labels.yml` + `INSTRUCTION.md` present), so a
  fresh vault never needs migrating.
- **Templates-as-spec** — `assets/` is the single source of truth; Scaffold only instantiates it. This
  is what carries cross-environment consistency.
- **Env-agnostic** — no hardcoded env-directory paths anywhere in this skill. Any env reachability is
  via `~/.claude/vault.local.md`, never a hardcoded env path.
- **Output-contract sharing** — Phase D and the future ongoing-ingest skill both emit notes conforming
  to `INSTRUCTION.md`'s note shape. They share that *contract*, not filing code (Phase D is a one-time
  bulk scripted pass; ongoing-ingest is recurring incremental classification).
- **Decoupled env-taxonomy** — singleton-vs-kind registration is handled via `kind-bootstrapper
  discuss`; it gates only the small registration action in the user's env, not this skill.
