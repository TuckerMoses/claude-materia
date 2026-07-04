# synthesizer Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the portable `synthesizer` skill in claude-materia — the vault's synthesis consumer: `scan` proposes note merges, associative links, and new labels for emergent themes; `resolve` drains the `needs-label` backlog through a shared minting machine — plus the three contract-cascade edits the spec assigns.

**Architecture:** A single-file markdown skill at `skills/synthesizer/SKILL.md` (no assets — it consumes a vault, it doesn't stamp one). It is a **pairwise consumer** (new archetype): seen-set watermark in the target vault's `_machine/synthesizer-state.yml`, never writes `handled`/`status`, effect-checks confirmed outcomes. Binding resolves `~/.claude/synthesizer.local.md` → `~/.claude/vault.local.md` → loud failure. Cascades: `skills/vault/SKILL.md` (Identity correction ×2), `skills/vault/assets/INSTRUCTION.md` (`related:` writer note, `labels`-after-creation ownership, pairwise archetype), README row + version bump.

**Tech Stack:** Markdown skill. Tools used by the skill's processes and this plan's validation steps: `ripgrep` (`rg`, the required query floor), a YAML parser (`python3 -c "import yaml"`), `jj` (the vault's VCS, relied on for merge-history preservation). No application runtime, no pytest.

## Global Constraints

Every task's requirements implicitly include this section. Values copied verbatim from the spec (`docs/superpowers/specs/2026-07-03-synthesizer-skill-design.md`).

- **Propose-confirm only.** "The synthesizer never auto-merges, never auto-links, never auto-mints." Every proposal shows its evidence. (spec §1)
- **Pairwise consumer.** Never writes `handled` (a note must re-enter consideration when new neighbors arrive); never writes `status`; state is a **seen-set only** in `_machine/synthesizer-state.yml` — **no rejection ledger** (incremental never re-judges old pairs by construction; `--full` SHOULD re-litigate). Confirmed outcomes are effect-checked, never stored. (spec §5)
- **Filter-then-read, never a full-vault read.** Cheap metadata (labels, titles) shortlists; bodies are read only for shortlisted candidates, only by subagents; the orchestrator stays context-lean. (spec §3, §7)
- **Iron-rule relationship stated explicitly.** The content-preservation iron rule governs *filing* (bodies verbatim at creation; minting never alters bodies). A human-approved merge rewrite is a distinct sanctioned refactor, licensed by archived originals (absorbed → `_archive/` verbatim; survivor → jj history). (spec §4)
- **Two sensors, one minter.** scan's theme detector + resolve's parked-orphan drain feed one minting machine: bank-recheck before minting, near-duplicate guard, singletons parked by default, retroactive sweep on every mint (skippable). Ingest stays frozen. (spec §2, §6)
- **Env-agnostic — zero `~/.claude/env` references, zero hardcoded vault paths** (no `~/Vault`, no `/Users/`). Binding via `~/.claude/synthesizer.local.md` → fallback `~/.claude/vault.local.md` → fail loudly. (spec §7)
- **All build edits inside claude-materia.** The live `~/Vault` is touched only at runtime first-use (state-file creation, INSTRUCTION.md mirror), never by this build. `~/.claude/plans/vault-design.md` is not touched. (spec §8)

---

## File Structure

All paths are under `~/claude-materia/`.

```
skills/synthesizer/
└── SKILL.md            # Tasks 1,2,3,4 — frontmatter, identity, binding, scan, merge/link, vocab growth, invariants
skills/vault/
├── SKILL.md            # Task 5 — Identity correction (×2 spots)
└── assets/INSTRUCTION.md  # Task 5 — related: comment, field ownership, pairwise archetype
README.md               # Task 6 — materia-table row
.claude-plugin/plugin.json  # Task 6 — version bump 0.11.0 → 0.12.0
```

The skill is a single `SKILL.md` deliberately: it consumes a vault's contracts (read live at runtime); it ships no templates of its own. The state-file schema is documented inline in the skill (created by the skill at runtime, in the *vault*, not in this repo).

---

### Task 1: SKILL.md frontmatter + identity + binding + routing

**Files:**
- Create: `skills/synthesizer/SKILL.md`

**Interfaces:**
- Produces: `SKILL.md` with `## Identity & role`, `## Per-install binding`, `## Subcommands and routing`. Tasks 2–4 append their sections to this file; they rely on the routing naming `scan` / `resolve` exactly, and on the binding order `synthesizer.local.md` → `vault.local.md` → loud failure.

- [ ] **Step 1: Create the skill directory and write the frontmatter + opening sections**

```bash
mkdir -p ~/claude-materia/skills/synthesizer
```

Write `skills/synthesizer/SKILL.md`:

````markdown
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
  `needs-label`; never mints); manager skills register container labels; **all topical vocabulary
  growth happens here**, batched, through user confirmation.

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
````

- [ ] **Step 2: Validate — frontmatter parses, routing names both subcommands, binding order present**

Run:
```bash
cd ~/claude-materia/skills/synthesizer
python3 -c "import yaml; t=open('SKILL.md').read(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['name']=='synthesizer'; assert 'needs-label' in d['description']; print('frontmatter OK:', d['name'])"
grep -c '/synthesizer scan\|/synthesizer resolve' SKILL.md          # expect: >=2
grep -c 'synthesizer.local.md' SKILL.md                             # expect: >=2
grep -c 'vault.local.md' SKILL.md                                   # expect: >=1 (fallback)
grep -ci 'fail loudly' SKILL.md                                     # expect: >=1
grep -c '~/.claude/env\|~/Vault\|/Users/' SKILL.md                  # expect: 0 (env-agnostic)
```
Expected: `frontmatter OK: synthesizer`, then counts meeting thresholds, final count `0`.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-materia
git add skills/synthesizer/SKILL.md
git commit -m "feat(synthesizer): SKILL.md frontmatter, identity/role, binding chain, routing"
```

---

### Task 2: `scan` pipeline + re-run model (pairwise consumer + state file)

**Files:**
- Modify: `skills/synthesizer/SKILL.md` (append `## scan` and `## Re-run model — the pairwise consumer`)

**Interfaces:**
- Consumes: the routing names from Task 1 (`scan`, `--full`), the binding chain.
- Produces: the state filename `_machine/synthesizer-state.yml` and the pipeline step names ("label-blocking", "global title sweep", "fan-out") that Tasks 3–4 and Task 6's coverage check reference. Emergent-theme proposals route to Task 4's "Vocabulary growth" section (referenced by name).

- [ ] **Step 1: Append the `## scan` section**

````markdown
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
2. **Label-blocking — `rg` over frontmatter only.** Group note paths by shared label → candidate
   neighborhoods. Zero body reads. Notes sharing a label are where merges and links concentrate.
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
````

- [ ] **Step 2: Append the `## Re-run model — the pairwise consumer` section**

````markdown
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
````

- [ ] **Step 3: Validate — pipeline steps, state file, and no-handled/no-status rules present**

Run:
```bash
cd ~/claude-materia/skills/synthesizer
grep -ci 'label-blocking\|global title sweep\|fan-out' SKILL.md      # expect: >=3
grep -c 'synthesizer-state.yml' SKILL.md                             # expect: >=2 (scan step 6 + re-run model)
grep -ci 'never writes .handled.\|never writes .status.' SKILL.md    # expect: >=2
grep -ci 'no rejection ledger' SKILL.md                              # expect: >=1
grep -ci 'pairwise consumer' SKILL.md                                # expect: >=2
grep -ci 'effect-checked' SKILL.md                                   # expect: >=1
grep -c -- '--full' SKILL.md                                         # expect: >=3
```
Expected: each count meets its threshold.

- [ ] **Step 4: Commit**

```bash
cd ~/claude-materia
git add skills/synthesizer/SKILL.md
git commit -m "feat(synthesizer): scan pipeline + pairwise-consumer re-run model with seen-set state"
```

---

### Task 3: Merge & link execution mechanics

**Files:**
- Modify: `skills/synthesizer/SKILL.md` (append `## Merge execution (on confirm)` and `## Link execution (on confirm)`)

**Interfaces:**
- Consumes: scan's confirm gate (Task 2 step 5 routes confirmed merges/links here by section name).
- Produces: the merge/link procedures Task 6's coverage check greps; the iron-rule-relationship paragraph the Invariants section (Task 4) references.

- [ ] **Step 1: Append the `## Merge execution (on confirm)` section**

````markdown
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
   hit to the survivor's wikilink.

**Iron-rule relationship (explicit):** the content-preservation iron rule governs *filing* —
bodies verbatim at creation; minting/resolve never alter bodies. A human-approved merge rewrite
is a **distinct sanctioned refactor**, licensed by the archived originals (absorbed → `_archive/`
verbatim; survivor → jj history). The rule guards against *silent, unreviewed* loss; a rewrite
read and approved in full is neither.
````

- [ ] **Step 2: Append the `## Link execution (on confirm)` section**

````markdown
## Link execution (on confirm)

- Write the `[[wikilink]]` into **both** notes' `related:` (bidirectional; `related:` has no
  directionality semantics).
- **One link field, not two.** The Tier-1/Tier-2 distinction is a *writer* constraint (ingest may
  auto-create only factual links; associative links require synthesizer-propose + human-confirm),
  not a storage schema. No consumer queries "factual links only"; a second field would fragment
  the link graph for a distinction nothing uses.
````

- [ ] **Step 3: Validate — merge procedure complete, iron-rule relationship stated, link rules present**

Run:
```bash
cd ~/claude-materia/skills/synthesizer
grep -ci 'survivor' SKILL.md                                         # expect: >=4
grep -ci 'append-verbatim' SKILL.md                                  # expect: >=1
grep -ci '_archive/. verbatim\|_archive/` verbatim' SKILL.md         # expect: >=1
grep -ci 'backlink sweep' SKILL.md                                   # expect: >=1
grep -ci 'iron rule\|iron-rule' SKILL.md                             # expect: >=2
grep -ci 'bidirectional' SKILL.md                                    # expect: >=1
grep -ci 'One link field, not two' SKILL.md                          # expect: 1
```
Expected: each count meets its threshold.

- [ ] **Step 4: Commit**

```bash
cd ~/claude-materia
git add skills/synthesizer/SKILL.md
git commit -m "feat(synthesizer): merge/link execution mechanics — survivor-absorbs, rewrite-by-default, iron-rule scope"
```

---

### Task 4: Vocabulary growth (two sensors, one minter) + Invariants

**Files:**
- Modify: `skills/synthesizer/SKILL.md` (append `## Vocabulary growth — two sensors, one minter` and `## Invariants (cross-cutting, hard)`)

**Interfaces:**
- Consumes: scan's emergent-theme routing (Task 2 step 5), the `needs-label` intrinsic label from Task 1's binding section.
- Produces: the minting-machine procedure and the `## Invariants` section Task 6's coverage check greps.

- [ ] **Step 1: Append the `## Vocabulary growth — two sensors, one minter` section**

````markdown
## Vocabulary growth — two sensors, one minter

Ingest never mints vocabulary; manager skills register container labels. **All topical vocabulary
growth happens here**, through two sensors feeding one minting machine:

**Sensor 1 — scan's theme detector.** Neighborhood subagents may report "these N notes circle a
concept no bank label names." Recurring themes become new-label proposals in scan's confirm gate.
This is how the vocabulary grows from notes that already fit *existing* labels — without it, the
vocabulary could only grow from its failures (unlabelable notes), never from emergent themes.

**Sensor 2 — `resolve`, the parked-orphan drain:**

1. **Gather** all `needs-label` notes (`rg`; the set itself is the scope — no scope argument).
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
````

- [ ] **Step 2: Append the `## Invariants (cross-cutting, hard)` section**

````markdown
## Invariants (cross-cutting, hard)

- **Propose-confirm only** — never auto-merge, auto-link, or auto-mint. Every proposal shows its
  evidence.
- **Never writes `handled`; never writes `status`** — the pairwise consumer's idempotency is the
  seen-set + effect-checking, nothing else.
- **Filter-then-read** — labels and titles shortlist; bodies are read only for shortlisted
  candidates, only by subagents; never a full-vault read.
- **Originals always survive a merge** — absorbed → `_archive/` verbatim; survivor's pre-merge
  body → jj history. This is what licenses the rewrite-by-default proposal.
- **Ingest stays frozen** — this skill is the only minter of topical vocabulary, and only through
  user confirmation.
- **Env-agnostic** — no environment paths in the skill body; binding via
  `~/.claude/synthesizer.local.md` → `~/.claude/vault.local.md` → loud failure.
- **`journal/` untouched** — day-files are never scanned, merged, linked, or relabeled; the
  synthesizer works the atomic-note pool (`notes/`) only.
````

- [ ] **Step 3: Validate — sensors, minter, retroactive sweep, and invariants present**

Run:
```bash
cd ~/claude-materia/skills/synthesizer
grep -ci 'two sensors' SKILL.md                                      # expect: >=1
grep -ci 'Recheck against the current bank' SKILL.md                 # expect: 1
grep -ci 'did you mean existing' SKILL.md                            # expect: 1
grep -ci 'Singletons stay parked' SKILL.md                           # expect: 1
grep -ci 'Retroactive sweep on every mint' SKILL.md                  # expect: 1
grep -ci 'Ingest stays frozen' SKILL.md                              # expect: >=1
grep -ci 'journal/. untouched\|journal/` untouched' SKILL.md         # expect: 1
grep -c '~/.claude/env\|~/Vault\|/Users/' SKILL.md                   # expect: 0 (still env-agnostic)
```
Expected: each count meets its threshold; final count `0`.

- [ ] **Step 4: Commit**

```bash
cd ~/claude-materia
git add skills/synthesizer/SKILL.md
git commit -m "feat(synthesizer): vocabulary growth (two sensors, one minter) + cross-cutting invariants"
```

---

### Task 5: Cascade edits — vault/SKILL.md Identity + INSTRUCTION.md template contract

**Files:**
- Modify: `skills/vault/SKILL.md` (Identity section + discuss section)
- Modify: `skills/vault/assets/INSTRUCTION.md` (note-shape comment, field ownership, consumer archetypes)

**Interfaces:**
- Consumes: the pairwise-consumer definition from Task 2 (the archetype text below must match its semantics: seen-set watermark, never writes `handled`, effect-checked outcomes).
- Produces: the corrected contracts Task 6's coverage check greps.

- [ ] **Step 1: Correct `skills/vault/SKILL.md` Identity (exact replacement)**

Replace this text in `skills/vault/SKILL.md`:

```markdown
- **Content-dependent → vault-local (NOT here).** Ongoing-ingest *classification* and the synthesizer
  depend on a vault's derived vocabulary; they belong in vault-local skills.
```

with:

```markdown
- **Content-dependent → vault-local (NOT here).** Ongoing-ingest *classification* depends on a
  vault's derived vocabulary; it belongs in a vault-local skill.
- **Consumers that read the vocabulary live → their own portable skills.** The synthesizer
  (`claude-materia:synthesizer`) is invariant logic — it blocks on labels, judges relatedness, and
  batch-mints vocabulary by reading `labels.yml`/`INSTRUCTION.md` live at runtime. The
  content-dependence is in the *data*, not the *skill*.
```

- [ ] **Step 2: Correct the `discuss` section's example (exact replacement)**

In `skills/vault/SKILL.md`, replace:

```markdown
label-based pool, how the contracts fit together, when a vault-local skill (ongoing-ingest,
synthesizer) is warranted vs. an addition here.
```

with:

```markdown
label-based pool, how the contracts fit together, when a vault-local skill (ongoing-ingest) or a
separate consumer skill (the synthesizer) is warranted vs. an addition here.
```

- [ ] **Step 3: Update `skills/vault/assets/INSTRUCTION.md` — the `related:` writer note (exact replacement)**

Replace:

```
related: ["[[…]]"]                 # Tier-1 factual links only
```

with:

```
related: ["[[…]]"]                 # Tier-1 factual (ingest) + confirmed associative (synthesizer / human)
```

- [ ] **Step 4: Update field ownership (exact replacement)**

In `skills/vault/assets/INSTRUCTION.md`, replace:

```markdown
- **Ingest** writes content-derived fields: `title`, `labels`, `created` / `captured` / `source`.
  Ingest writes **neither** `status` **nor** `handled`.
- **Consumers** (and the human) write `status` and `handled`.
```

with:

```markdown
- **Ingest** writes content-derived fields: `title`, `labels`, `created` / `captured` / `source`.
  Ingest writes **neither** `status` **nor** `handled`.
- **Consumers** (and the human) write `status` and `handled`.
- **`labels` after creation:** written only by the synthesizer's **confirmed** minting/resolve
  passes or the human (ingest owns it at creation; no other consumer touches it).
```

- [ ] **Step 5: Add the pairwise archetype (exact replacements)**

In `skills/vault/assets/INSTRUCTION.md`, replace the heading:

```markdown
## Consumer idempotency (two archetypes)
```

with:

```markdown
## Consumer idempotency (three archetypes)
```

and replace:

```markdown
- **Lifecycle consumer** (e.g. a scheduler): queries `label AND status:open`, does **not** write
  `handled`, and re-sees still-open items until they resolve (`status → done`).

Ingest never writes `handled`.
```

with:

```markdown
- **Lifecycle consumer** (e.g. a scheduler): queries `label AND status:open`, does **not** write
  `handled`, and re-sees still-open items until they resolve (`status → done`).
- **Pairwise consumer** (e.g. the synthesizer): judges *pairs/clusters* of notes, not single notes,
  so neither mechanism above fits. It never writes `handled` (a note must re-enter consideration
  when new neighbors arrive); its idempotency is a **seen-set watermark** in a `_machine/` state
  file (incremental runs = unseen × neighborhoods), and confirmed outcomes are **effect-checked**
  (a merged note is gone; a link sits in `related:`; a minted label sits in the bank).

Ingest never writes `handled`.
```

- [ ] **Step 6: Validate — all five cascade edits landed, nothing else drifted**

Run:
```bash
cd ~/claude-materia/skills/vault
grep -c 'claude-materia:synthesizer' SKILL.md                        # expect: 1
grep -ci 'they belong in vault-local skills' SKILL.md                # expect: 0 (old claim gone)
grep -ci 'separate consumer skill (the synthesizer)' SKILL.md        # expect: 1
grep -c 'confirmed associative (synthesizer / human)' assets/INSTRUCTION.md   # expect: 1
grep -c 'Tier-1 factual links only' assets/INSTRUCTION.md            # expect: 0 (old comment gone)
grep -ci 'labels. after creation' assets/INSTRUCTION.md              # expect: 1
grep -ci 'three archetypes' assets/INSTRUCTION.md                    # expect: 1
grep -ci 'Pairwise consumer' assets/INSTRUCTION.md                   # expect: 1
grep -c 'Ingest never writes .handled.' assets/INSTRUCTION.md        # expect: 1 (kept)
```
Expected: each count exactly as annotated.

- [ ] **Step 7: Commit**

```bash
cd ~/claude-materia
git add skills/vault/SKILL.md skills/vault/assets/INSTRUCTION.md
git commit -m "fix(vault): synthesizer cascades — Identity correction, related: writer note, labels ownership, pairwise archetype"
```

---

### Task 6: Integration — spec coverage + coherence gate + ship (README, version)

**Files:**
- Modify: `README.md` (add synthesizer to the materia table)
- Modify: `.claude-plugin/plugin.json` (version bump `0.11.0` → `0.12.0`)

**Interfaces:**
- Consumes: all of Tasks 1–5 (the full `SKILL.md` + cascades).
- Produces: the README entry + version bump that ship the skill.

- [ ] **Step 1: Spec coverage check — every spec § maps to skill/cascade text**

Run (each grep asserts coverage of a spec section):
```bash
cd ~/claude-materia
echo "§1 identity/home:";      grep -qi 'invariant across vaults' skills/synthesizer/SKILL.md && echo OK
echo "§2 surface:";            grep -q '/synthesizer scan' skills/synthesizer/SKILL.md && grep -q '/synthesizer resolve' skills/synthesizer/SKILL.md && echo OK
echo "§3 scan pipeline:";      grep -qi 'label-blocking' skills/synthesizer/SKILL.md && grep -qi 'title sweep' skills/synthesizer/SKILL.md && echo OK
echo "§4 merge/link:";         grep -qi 'append-verbatim' skills/synthesizer/SKILL.md && grep -qi 'One link field, not two' skills/synthesizer/SKILL.md && echo OK
echo "§5 re-run model:";       grep -qi 'pairwise consumer' skills/synthesizer/SKILL.md && grep -q 'synthesizer-state.yml' skills/synthesizer/SKILL.md && echo OK
echo "§6 vocab growth:";       grep -qi 'two sensors' skills/synthesizer/SKILL.md && grep -qi 'Retroactive sweep' skills/synthesizer/SKILL.md && echo OK
echo "§7 binding:";            grep -q 'synthesizer.local.md' skills/synthesizer/SKILL.md && grep -q 'vault.local.md' skills/synthesizer/SKILL.md && echo OK
echo "§8 cascades:";           grep -q 'claude-materia:synthesizer' skills/vault/SKILL.md && grep -qi 'three archetypes' skills/vault/assets/INSTRUCTION.md && echo OK
```
Expected: an `OK` after every section line.

- [ ] **Step 2: Coherence gate — adversarial review on the branch diff**

Per the repo's execution convention, run `/claude-materia:adversarial-review run default:coherence` scoped to the diff of Tasks 1–5 (the synthesizer SKILL.md + the two cascade files). Fix any findings and re-run until clean; fold fixes into a `fix(synthesizer): coherence-review findings` commit if any arise.

- [ ] **Step 3: Add the README materia-table row**

In `README.md`, append this row to the Skills table (after the `vault` row):

```markdown
| **synthesizer** | Command | Vault synthesis consumer. `scan` proposes note merges (semantic dedup as the degenerate case), associative links, and new labels for emergent cross-note themes — incremental via a seen-set, `--full` for a whole-vault re-pass, always propose-confirm. `resolve` drains the `needs-label` backlog: rechecks against the current bank, clusters the residue, mints coherent labels on confirm, retroactive sweep per mint. Never writes `handled`/`status`. Binds via `~/.claude/synthesizer.local.md` → `~/.claude/vault.local.md`. |
```

- [ ] **Step 4: Bump the plugin version**

In `.claude-plugin/plugin.json`, change `"version": "0.11.0"` → `"version": "0.12.0"`.

Validate:
```bash
cd ~/claude-materia
python3 -c "import json; v=json.load(open('.claude-plugin/plugin.json'))['version']; assert v=='0.12.0', v; print('version', v)"
grep -c 'synthesizer' README.md   # expect: >=1
```
Expected: `version 0.12.0`; README count `>=1`.

- [ ] **Step 5: Commit**

```bash
cd ~/claude-materia
git add README.md .claude-plugin/plugin.json
git commit -m "feat(synthesizer): ship skill — README entry + version bump (passes spec coverage + coherence gate)"
```

---

## Self-Review

**Spec coverage:** §1 (identity & home) → Task 1. §2 (surface, two sensors framing) → Task 1 routing + Task 4 sensors. §3 (scan pipeline) → Task 2. §4 (merge/link mechanics + iron-rule relationship) → Task 3. §5 (pairwise consumer, seen-set, no rejection ledger) → Task 2. §6 (two sensors, one minter, retroactive sweep, field-ownership refinement) → Task 4 + Task 5 Step 4. §7 (binding chain + fail loudly + first-use mirror) → Task 1. §8 (cascades) → Task 5; README/version → Task 6. §9 out-of-scope items (label-bank hygiene, mint-at-ingest, embeddings, scheduling) are not planned — correct.

**Placeholder scan:** no TBD/TODO/implement-later. The `notes/example-note.md` line in the state-file YAML is schema documentation (an example entry inside a documented schema block), not an authoring gap.

**Type/name consistency:** state file is `_machine/synthesizer-state.yml` in Tasks 2, 5 (archetype text says "a `_machine/` state file"), and 6. Subcommands `scan`/`resolve` and flag `--full` identical across Tasks 1, 2, 6. Binding chain `~/.claude/synthesizer.local.md` → `~/.claude/vault.local.md` identical in Tasks 1, 4 (invariants), 6 (README row). Section cross-references by exact name: "Merge execution" / "Link execution" (Task 2 step 5 → Task 3 headings), "Vocabulary growth" (Task 2 step 5 → Task 4 heading), "Re-run model" (Task 2 step 1 → Task 2 heading). Task 5's archetype text matches Task 2's semantics (seen-set watermark, never writes `handled`, effect-checked).

## Execution Handoff

After saving this plan, the executing agent should use **superpowers:subagent-driven-development** (fresh subagent per task, review between tasks) or **superpowers:executing-plans** (inline batch with checkpoints).
