# Design — the `synthesizer` skill (claude-materia)

> **Status:** Design approved 2026-07-03. Next: implementation plan (writing-plans).
> **Context:** Task #5 of the vault build — the last Phase-4 deliverable. The vault's flat
> label-based architecture (`notes/` + `journal/`, `_machine/labels.yml`, `INSTRUCTION.md`, the
> `.local.md` binding seam) is live at `~/Vault/` (303 notes, migrated). The synthesizer is the
> pure-pull consumer that keeps the pool coherent: it surfaces cross-domain connections
> (merges + links) and owns vocabulary growth (the `needs-label` backlog + emergent themes).
> **Full architecture reference:** `~/.claude/plans/vault-design.md` (2026-06-21 capture-model
> revision + 2026-06-19 revision authoritative). Design diagram:
> `2026-07-03-synthesizer-skill-design.svg` (sibling file).

---

## 1. Identity & home

A **portable, env-agnostic** claude-materia skill named `synthesizer`. It is a **recurring
operational consumer** of a populated vault — the session-planner archetype (own cadence, own
binding, own idempotency story) — not a vault-creation/registration tool, which is why it is a
separate skill and not a fourth `vault` subcommand.

**Placement rationale (corrects `vault/SKILL.md`):** the invariant/vault-local dividing line is
"is the *logic* invariant across vaults," not "does it touch the vocabulary." The synthesizer's
logic (block by shared labels, judge relatedness, batch-mint vocabulary) is vault-agnostic; it
reads `labels.yml` and `INSTRUCTION.md` **live** at runtime. What is content-dependent is the
*data*, not the *skill*. `vault/SKILL.md`'s Identity section is corrected accordingly (§8).

**What it is for** (design-doc deliverable #3/#5):

- **Relatedness surfacing** — suggest merging near-duplicate notes (subsumes semantic dedup as
  the degenerate case) and linking/combining notes that form a larger insight (principle 8,
  cross-domain idea surfacing; the deferred Tier-2 associative links).
- **Vocabulary growth** — own the `needs-label` backlog and the evolution of the topical label
  vocabulary. Ingest stays frozen (applies existing labels or parks under `needs-label`; never
  mints); managers register container labels; **all topical vocabulary growth happens here**,
  batched, through user confirmation.

**Hard posture:** propose-confirm only. The synthesizer never auto-merges, never auto-links,
never auto-mints. Placement is immutable (principle 4); a confirmed merge is the sanctioned
user-confirmed manual refactor, with the skill as executor.

## 2. Subcommand surface (locked)

`scan [scope?] [--full]` · `resolve`. (`help` via the kernel-level universal convention; no
`discuss` — the `vault` skill's `discuss` owns vault-architecture meta.)

- **`scan`** — the relatedness pass. One computation, **three verdicts**: merge proposals, link
  proposals, and new-label (emergent-theme) proposals. `scope` is optional: a label list or a
  free-text subset description resolved against `labels.yml`; default = whole vault.
- **`resolve`** — the vocabulary pass over the `needs-label` set. No scope argument — the set
  itself is the scope.

**Vocabulary growth = two sensors, one minter.** `scan` senses vocabulary pressure among
*already-labeled* notes (a theme emerging across notes that each individually fit existing
labels); `resolve` senses it from the *parked orphans* (`needs-label`). Both feed the same
minting machinery (§6). This closes the blind spot where the vocabulary could only grow from
its failures (unlabelable notes) and never from emergent themes.

## 3. `scan` — pipeline

1. **Scope the run.** Resolve `scope` (label list or free text) against `labels.yml`; default
   whole vault. Default mode is **incremental**: new notes = pool − seen-set (§5); each new note
   is compared against its label-neighborhoods. `--full` forces a whole-vault re-pass.
2. **Label-blocking** — `rg` over frontmatter only. Group note paths by shared label →
   candidate neighborhoods. Zero body reads (filter-then-read; a full-vault read is forbidden).
3. **Global title sweep** — one subagent takes *all* titles + label sets (trivially fits one
   context; titles are derived-searchable by design) and nominates cross-domain candidate pairs
   that share no label — the pairs label-blocking structurally misses.
4. **Fan-out** — one subagent per neighborhood (large clusters shard by facet labels), plus
   one for the title sweep's cross-domain nominations (pairs belonging to no shared-label
   neighborhood). Each reads bodies *only within its assigned set*, and returns
   **structured proposals only** (merge / link / emergent-theme, each with evidence) — never
   file dumps. The orchestrator stays context-lean.
5. **Aggregate + dedup** — the same pair can surface via two shared labels; the orchestrator
   dedups cross-cluster, then presents **one propose-confirm gate**. Every proposal shows its
   evidence. Emergent-theme proposals route to the minting machinery (§6).
6. **Execute confirmed verdicts** (§4 merge, §4 link).
7. **Update the seen-set** in `_machine/synthesizer-state.yml` (§5).

## 4. Merge & link mechanics (on confirm)

**Merge — survivor + absorbed:**

1. One note (typically the richer/older) **survives at its existing path**; the other is
   absorbed. The proposal names which is which, and the user may swap them at the gate. No new
   file — a synthesized third note would break every existing wikilink to both and erase the
   audit trail.
2. **Default proposal = a full drafted rewording** of the merged note, always shown in full at
   the gate. At confirm time the user chooses: **accept the rewrite · downgrade to
   append-verbatim · reject**. Never applied sight-unseen.
3. **Frontmatter union:** labels union; earliest `created` wins; `related:` union minus
   self-references; merge provenance recorded (absorbed title + its `source`/`created` + date).
4. **Absorbed note → `_archive/` verbatim.** Never deleted. (jj history additionally preserves
   the survivor's pre-merge body.)
5. **Backlink sweep:** `rg` for `[[absorbed-title]]` across `notes/`, rewrite to the survivor.

**Iron-rule relationship (explicit):** the content-preservation iron rule governs *filing* —
bodies verbatim at creation; `resolve`/minting never alter bodies. A human-approved merge
rewrite is a **distinct sanctioned refactor**, licensed by the archived originals (absorbed →
`_archive/` verbatim; survivor → jj history). The rule guards against *silent, unreviewed*
loss; a rewrite read and approved in full is neither.

**Link:**

- Confirmed associative links are written as `[[wikilinks]]` into **both** notes' `related:`
  (bidirectional; `related:` has no directionality semantics).
- **One link field, not two.** The Tier-1/Tier-2 distinction is a *writer* constraint (ingest
  may auto-create only factual links; associative links require synthesizer-propose +
  human-confirm), not a storage schema. No consumer queries "factual links only"; a second
  field would fragment the link graph for a distinction nothing uses. Cascade: `INSTRUCTION.md`
  note-shape comment updated (§8).

## 5. Re-run model — the pairwise consumer (new archetype)

The synthesizer is **neither** existing consumer archetype:

- `handled` (one-shot) is wrong: relatedness is *pairwise* — a note judged today must re-enter
  consideration whenever a new neighbor arrives. The synthesizer **never writes `handled`**.
- `status` filter (lifecycle) is wrong: no per-note status can express a *pair* verdict.

**Third archetype — pairwise consumer.** State: `_machine/synthesizer-state.yml`, holding a
**seen-set only** (evaluated note paths). Incremental scan = new (pool − seen) × their
neighborhoods; old-vs-old pairs are never re-judged except via `--full`.

- **No rejection ledger.** Under incremental runs a rejected pair is old-vs-old and never
  re-proposed by construction. Under `--full`, re-litigation is *the point* (a fresh look);
  and a new note C relating to a rejected pair (A, B) legitimately resurrects the {A, B, C}
  cluster — new evidence. A ledger would solve a non-problem and harm the one case it touches.
- **Confirmed outcomes are effect-checked, not stored:** a confirmed merge visibly removes a
  note; a confirmed link sits in `related:`; a minted label sits in `labels.yml`.
- **Vault-resident state, deliberately:** the seen-set is per-vault and must travel with it
  (the vault syncs across machines; state stranded in a plugin data dir would re-propose
  everything on the second machine). Principle 9 gives `_machine/` exactly this job. This does
  not violate "the vault never describes its consumers" — that bans routing/destination
  knowledge on notes and in `labels.yml`, not working state in `_machine/`. Same sanctioned
  runtime-state category as `handled` and `last_read`.
- **Accepted trade:** incremental never re-judges old pairs, so improved judgment or
  merge-shifted meaning goes unnoticed until a `--full` pass — mirroring the
  efficiency-over-re-evaluation trade the design already accepts for `handled`.
- `resolve` is **stateless**: the `needs-label` set is self-draining.

## 6. Vocabulary growth — two sensors, one minter

**Sensor 1 (scan):** neighborhood subagents may report "these N notes circle a concept no bank
label names." The orchestrator aggregates; recurring themes become label proposals in the
confirm gate.

**Sensor 2 (resolve):**

1. **Gather** all `needs-label` notes.
2. **Recheck against the current bank first.** The vocabulary grew since parking; some notes
   now fit *existing* labels — no minting. Cheapest defense against minting near-duplicates.
3. **Cluster the residue** → one proposed label per coherent cluster.

**The minter (shared by both sensors):**

- Proposal shape: proposed name (bank conventions: kebab-case, `parent/facet` paths allowed) +
  drafted `when_to_apply` + the member notes. User approves / renames / rejects **per label**,
  not per note.
- **Near-duplicate guard:** every proposed label is checked against the bank; overlap presented
  as "did you mean existing `X`?" before minting.
- **Singletons stay parked by default.** A cluster of one is a weak basis for permanent
  vocabulary; shown but flagged, default disposition "keep parked." Parked is the holding pen
  working, not a failure state.
- **On confirm:** register the label in `labels.yml` (per `INSTRUCTION.md`'s registration
  protocol, `status: active`) → apply it to the member notes → clear `needs-label` from them.
  Unresolved notes stay parked.
- **Retroactive sweep on every mint (skippable):** title sweep nominates existing notes across
  the vault that should also carry the new label; targeted body reads verify; propose-confirm
  list. Without this a new label only ever covers the notes that birthed it.

**Field-ownership refinement (cascade, §8):** `labels` is written by ingest **at creation**;
thereafter only by the synthesizer's **confirmed** minting/resolve pass or the human. Keeps
no-overlap-no-gap while legalizing what the design assigns to the synthesizer.

## 7. Per-install binding

Standard claude-materia seam, one extension:

- If `~/.claude/synthesizer.local.md` exists, read and follow it (vault pointer, listened-label
  overrides, MCP endpoint). If absent, **fall back to `~/.claude/vault.local.md`** (the
  canonical environment-vault pointer written by `vault create`).
- If neither exists: **fail loudly** ("no vault registered — run `vault create` first" or point
  the skill at a vault). Never guess a path.
- Every invocation reads `INSTRUCTION.md` + `_machine/labels.yml` **live** from the vault.
- Intrinsic label vocabulary: `needs-label` (overridable per the binding schema).
- Query surface per `INSTRUCTION.md` preference order: `obsidian` CLI when the app is running;
  **ripgrep as the required floor**; never a full-vault read.

## 8. Cascade edits (shipped with this skill; all inside claude-materia)

1. **`skills/vault/SKILL.md` — Identity section:** stop claiming the synthesizer belongs
   vault-local. The invariant/vault-local line keeps its claim only for ongoing-ingest
   *classification* (undecided, a future session's call).
2. **`skills/vault/assets/INSTRUCTION.md` template** (and, at runtime first-use, mirrored into
   the live vault's copy — a runtime behavior, not a build edit):
   - `related:` comment → "Tier-1 factual links (ingest) + confirmed associative links
     (synthesizer / human)."
   - Field ownership → `labels`: ingest at creation; thereafter confirmed synthesizer
     minting/resolve or the human.
   - Consumer-idempotency section gains the **pairwise consumer** archetype (state file in
     `_machine/`, never writes `handled`, effect-checks confirmations).
3. **`README.md`** — materia-table entry. **`.claude-plugin/plugin.json`** — version bump.

**Not touched:** `~/.claude/plans/vault-design.md` (owned by the parallel session), `journal/`,
any env file, the live `~/Vault` (runtime-only effects at first use).

## 9. Out of scope (v1)

- **Label-bank hygiene** (merging/retiring near-duplicate *labels* already in the bank) —
  additive later; the near-dup guard prevents new occurrences.
- **Interactive mint-at-ingest** (ingest offering a new label on the spot) — the design doc
  marks the `needs-label` + synthesizer path as the durable floor; this stays optional/later.
- **Embedding/semantic-index infrastructure** — label-blocking + title sweep is the v1
  shortlisting mechanism; revisit only if it demonstrably misses.
- **Scheduled/cron operation** — pure pull, manually invoked for now; a `/loop` or cron cadence
  is a user decision later, requiring no skill changes.
