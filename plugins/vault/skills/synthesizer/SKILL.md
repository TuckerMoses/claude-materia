---
name: synthesizer
description: "Operate on a populated knowledge vault as its synthesis consumer: scan the note pool for merge/link opportunities and own the growth of its label vocabulary. Two subcommands: scan (relatedness pass — proposes merging near-duplicate notes, linking notes that form a larger insight, and minting labels for emergent cross-note themes; incremental by default, --full for a whole-vault re-pass), resolve (vocabulary pass — batch-resolves notes parked under needs-label: rechecks them against the current label bank, clusters the residue, and mints coherent new labels on confirm). Use whenever the user wants to synthesize or consolidate vault notes, find duplicate or related notes, merge notes, propose links between notes, resolve needs-label notes, mint or grow the label vocabulary, or surface cross-domain connections. Trigger phrases: 'synthesize my vault', 'scan the vault', 'dedup my notes', 'merge duplicates', 'link related notes', 'resolve needs-label', 'propose new labels', 'grow the vocabulary'."
user-invocable: true
argument-hint: "[subcommand] [args] — scan [scope?] [--full], resolve"
---

# synthesizer

Operate on a **populated** vault as its synthesis consumer: surface the connections the pool has
accumulated (merge near-duplicates, link notes that form a larger insight) and own the growth of
its label vocabulary. A **pure-pull** consumer — self-scheduled, invoked when the user wants; the
vault triggers nothing.

## Identity & role

This skill is **invariant across vaults**: it blocks on labels, judges relatedness, and batch-mints
vocabulary by reading the target vault's `labels.yml` + `INSTRUCTION.md` **live** at every
invocation. The content-dependence lives in the *data*, not the *skill* — which is why it is a
portable claude-materia skill (the session-planner archetype: a recurring operational consumer with
its own cadence and binding), not a vault-local skill and not a `vault` subcommand.

Two jobs (one skill because they share the minting machinery — see "Vocabulary growth"):

- **Relatedness surfacing** (`scan`) — propose merges of near-duplicate notes (semantic dedup is
  the degenerate case) and associative links between notes that form a larger insight. This is the
  deferred Tier-2 link tier and the deferred semantic-dedup layer, landing in their designed home.
- **Vocabulary growth** (`resolve` + scan's theme sensor) — own the `needs-label` backlog and the
  evolution of the topical vocabulary. Ingest stays frozen (applies existing labels or parks under
  `needs-label`; never mints); manager skills register container labels; **all post-bootstrap
  topical vocabulary growth happens here**, batched, through user confirmation. (Bootstrap
  vocabulary is vault's domain — `vault create` derives and mints the seed domain/topic labels
  during scaffold; this skill takes over from that point forward.)

**Hard posture: propose-confirm only.** The synthesizer never auto-merges, never auto-links, never
auto-mints. Every proposal shows its evidence; nothing is applied sight-unseen. A confirmed merge is
the sanctioned user-confirmed manual refactor (placement is otherwise immutable), with this skill as
executor.

## Per-install binding

This skill is portable. It names **no** environment paths in its body. Binding resolves in order:

1. **`~/.claude/synthesizer.local.md`** — if present, read and follow it: vault pointer,
   listened-label overrides (intrinsic default: `needs-label`), MCP endpoint (per-machine).
2. **`~/.claude/vault.local.md`** — the canonical environment-vault pointer written by
   `vault create`. If the skill has no `.local.md` of its own, bind to this vault with intrinsic
   defaults.
3. **Neither exists → fail loudly** ("no vault registered — run `vault create` first, or write
   `~/.claude/synthesizer.local.md` pointing at a vault"). Never guess a path.

**Every invocation:** resolve the vault → read its `INSTRUCTION.md` + `_machine/labels.yml`
**live** → query per the handshake's preference order (`obsidian` CLI when the app is running;
**ripgrep is the required floor**; never a full-vault read) → act.

**First use against a vault:** if its `INSTRUCTION.md` predates this skill's contract lines (the
`related:` writer note, the `labels`-after-creation ownership line, the pairwise-consumer
archetype), propose mirroring those edits into the live copy before the first scan.

## Subcommands and routing

- `/synthesizer` — infer the subcommand from arguments and conversation context.
- `/synthesizer scan [scope?] [--full]` — the relatedness pass: one computation, three proposal
  kinds (merge / link / new-label). See "scan".
- `/synthesizer resolve` — the vocabulary pass over the `needs-label` set. See "Vocabulary growth".

**`help` subcommand:** when invoked as `/synthesizer help`, summarize this skill and its
subcommands from the sections below rather than executing them.

## scan

The relatedness pass over `notes/`. One computation, **three verdicts**: merge proposals, link
proposals, and new-label (emergent-theme) proposals. Never a full-vault read — cheap metadata
(labels, titles) decides what is worth comparing; bodies are read only for shortlisted candidates,
and only by subagents.

1. **Scope the run.** `scope` is optional: a label list or a free-text subset description, resolved
   against `labels.yml` (e.g. "everything philosophy-adjacent" → the philosophy domain + its facet
   labels). Default = the whole vault. Default mode is **incremental**: the working set is the
   notes not yet in the seen-set (see "Re-run model"), each compared against its
   label-neighborhoods. `--full` clears the working-set restriction and re-passes the whole vault.
2. **Label-blocking — frontmatter query only.** Group note paths by shared label via the query
   surface, per the handshake's preference order (`obsidian` CLI when the app is running; `rg`
   otherwise) → candidate neighborhoods. Zero body reads. Notes sharing a label are where merges
   and links concentrate.
3. **Global title sweep — one subagent.** All titles + label sets fit one context (titles are
   derived-searchable by design). It nominates cross-domain candidate pairs that share **no**
   label — the pairs label-blocking structurally misses, and exactly the cross-domain surfacing
   this skill exists for.
4. **Fan-out — one subagent per neighborhood**, plus one for the title sweep's cross-domain
   nominations. Large neighborhoods shard by facet label. Each subagent reads bodies **only within
   its assigned set** and returns **structured proposals only** — merge / link / emergent-theme,
   each with evidence (the specific overlapping claims, not vibes). Never file dumps; the
   orchestrator stays context-lean.
5. **Aggregate + dedup.** The same pair can surface via two shared labels; dedup cross-cluster,
   then present **one propose-confirm gate**. Confirmed merges and links execute per "Merge
   execution" / "Link execution" below. Emergent-theme proposals route to the minting machine
   (see "Vocabulary growth").
6. **Update the seen-set** in `_machine/synthesizer-state.yml` — every note evaluated this run,
   including ones that produced no proposal.

## Re-run model — the pairwise consumer

The synthesizer is **neither** of the handshake's existing consumer archetypes:

- `handled` (one-shot) is wrong: relatedness is *pairwise* — a note judged today must re-enter
  consideration whenever a new neighbor arrives. **This skill never writes `handled`.**
- A `status` filter (lifecycle) is wrong: no per-note status can express a *pair* verdict.
  **This skill never writes `status` either.**

**Third archetype — pairwise consumer.** State: `_machine/synthesizer-state.yml` in the target
vault, created by this skill on first `scan`:

```yaml
# Synthesizer working state (pairwise-consumer watermark; see INSTRUCTION.md).
# seen: note paths already evaluated by scan. Incremental scan = (pool − seen) × neighborhoods.
# No rejection ledger, deliberately: incremental never re-judges old pairs by construction,
# and --full SHOULD re-litigate (a fresh look is its purpose).
seen:
  - notes/example-note.md
```

- **Confirmed outcomes are effect-checked, never stored:** a confirmed merge visibly removes a
  note; a confirmed link sits in `related:`; a minted label sits in `labels.yml`.
- **Vault-resident state, deliberately:** the seen-set is per-vault and travels with it (the vault
  syncs across machines; state stranded in a plugin data dir would re-propose everything on the
  second machine). This is the sanctioned runtime-state category (`handled`, `last_read`) — not a
  derive-don't-store violation, and not consumer-routing knowledge on notes or in `labels.yml`.
- **Accepted trade:** incremental never re-judges old-vs-old pairs; improved judgment or
  merge-shifted meaning is caught only by a `--full` pass — the same efficiency-over-re-evaluation
  trade `handled` makes.
- `resolve` is **stateless**: the `needs-label` set is self-draining.

## Merge execution (on confirm)

Survivor + absorbed — never a synthesized third file:

1. One note (typically the richer/older) **survives at its existing path**; the other is absorbed.
   The proposal names which is which; the user may swap them at the gate. No new file — a third
   note would break every existing wikilink to both and erase the audit trail.
2. **Default proposal = a full drafted rewording** of the merged note, always shown in full at the
   gate. At confirm the user chooses: **accept the rewrite · downgrade to append-verbatim ·
   reject.** Never applied sight-unseen.
3. **Frontmatter union:** labels union; earliest `created` wins; `related:` union minus
   self-references; merge provenance recorded on the survivor (absorbed title, its
   `source`/`created`, merge date).
4. **Absorbed note → `_archive/` verbatim.** Never deleted. (jj history additionally preserves the
   survivor's pre-merge body.)
5. **Backlink sweep:** `rg` for the absorbed note's `[[wikilink]]` across `notes/`; rewrite each
   hit to the survivor's wikilink. (Deliberately `rg`, not the CLI, regardless of app state — the
   sweep is correctness-critical and must be exhaustive; a missed hit is a broken link.)

**Iron-rule relationship (explicit):** the content-preservation iron rule governs *filing* —
bodies verbatim at creation; minting/resolve never alter bodies. A human-approved merge rewrite
is a **distinct sanctioned refactor**, licensed by the archived originals (absorbed → `_archive/`
verbatim; survivor → jj history). The rule guards against *silent, unreviewed* loss; a rewrite
read and approved in full is neither.

## Link execution (on confirm)

- Write the `[[wikilink]]` into **both** notes' `related:` (bidirectional; `related:` has no
  directionality semantics).
- **One link field, not two.** The Tier-1/Tier-2 distinction is a *writer* constraint (ingest may
  auto-create only factual links; associative links require synthesizer-propose + human-confirm),
  not a storage schema. No consumer queries "factual links only"; a second field would fragment
  the link graph for a distinction nothing uses.

## Vocabulary growth — two sensors, one minter

Ingest never mints vocabulary; manager skills register container labels. **All post-bootstrap
topical vocabulary growth happens here**, through two sensors feeding one minting machine:
(Bootstrap vocabulary is vault's domain — `vault create` derives the seed domain/topic labels
during scaffold; this skill takes over from that point forward.)

**Sensor 1 — scan's theme detector.** Neighborhood subagents may report "these N notes circle a
concept no bank label names." Recurring themes become new-label proposals in scan's confirm gate.
This is how the vocabulary grows from notes that already fit *existing* labels — without it, the
vocabulary could only grow from its failures (unlabelable notes), never from emergent themes.

**Sensor 2 — `resolve`, the parked-orphan drain:**

1. **Gather** all `needs-label` notes via the query surface (CLI when the app is running; `rg`
   otherwise); the set itself is the scope — no scope argument.
2. **Recheck against the current bank first.** The vocabulary grew since parking; some notes now
   fit *existing* labels — apply those (propose-confirm), no minting. The cheapest defense against
   minting near-duplicates.
3. **Cluster the residue** → one proposed label per coherent cluster → the minting machine.

**The minting machine (shared by both sensors):**

- Proposal shape: proposed name (bank conventions: kebab-case; `parent/facet` paths allowed) +
  drafted `when_to_apply` + the member notes. The user approves / renames / rejects **per label**,
  not per note.
- **Near-duplicate guard:** check every proposed label against the bank; present overlap as "did
  you mean existing `X`?" before minting.
- **Singletons stay parked by default.** A cluster of one is a weak basis for permanent
  vocabulary; shown but flagged, default disposition "keep parked." Parked is the holding pen
  working, not a failure state.
- **On confirm:** register the label in `labels.yml` per INSTRUCTION.md's protocol
  (`status: active`) → apply it to the member notes → clear `needs-label` from them. Unresolved
  notes stay parked.
- **Retroactive sweep on every mint (skippable):** a title sweep nominates existing notes across
  the vault that should also carry the new label; targeted body reads verify; propose-confirm.
  Without this, a new label only ever covers the notes that birthed it.

**Field ownership refinement:** `labels` is written by ingest **at creation**; thereafter only by
this skill's **confirmed** minting/resolve passes or the human.

## Invariants (cross-cutting, hard)

- **Propose-confirm only** — never auto-merge, auto-link, or auto-mint. Every proposal shows its
  evidence.
- **Never writes `handled`; never writes `status`** — the pairwise consumer's idempotency is the
  seen-set + effect-checking, nothing else.
- **Filter-then-read** — labels and titles shortlist; bodies are read only for shortlisted
  candidates, only by subagents; never a full-vault read.
- **Originals always survive a merge** — absorbed → `_archive/` verbatim; survivor's pre-merge
  body → jj history. This is what licenses the rewrite-by-default proposal.
- **Ingest stays frozen** — this skill is the only minter of post-bootstrap topical vocabulary
  (runtime vocabulary growth after `vault create`'s seed-label phase), and only through user
  confirmation.
- **Env-agnostic** — no environment paths in the skill body; binding via
  `~/.claude/synthesizer.local.md` → `~/.claude/vault.local.md` → loud failure.
- **`journal/` untouched** — day-files are never scanned, merged, linked, or relabeled; the
  synthesizer works the atomic-note pool (`notes/`) only.
