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
