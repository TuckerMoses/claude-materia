# Vault Integration Handshake

External integration handshake for vault-aware skills. Thin and structural — it lets a generic skill
bind to this vault without a hard dependency. Read **live** from the vault on every invocation.

> Distinct from the vault's internal `CLAUDE.md` (the agent OS-contract for working *inside* the
> vault). This file is for *external consumers* binding *to* the vault.

## Identity

This is a knowledge vault at `{{VAULT_PATH}}`. Its label bank — the shared label vocabulary, the
inter-skill label API — is `_machine/labels.yml`, a machine-read YAML file owned by this vault (schema:
the vault plugin's `scripts/labels.schema.json`). Its routing is `_machine/routing.yml`, also owned here.
The vault depends on nothing outside itself and the vault plugin.
**Reference the bank; never restate the vocabulary here.** The vault is a sink: it holds thought, intent
and outcome records, and acts on nothing.

## Note shape

Every note is a markdown file with this frontmatter contract:

```yaml
---
title: "…"                         # derived label only — NEVER strips body content
labels: [idea, ai-systems, todo]   # concept + action labels, one flat set; from the vocabulary
created: 2026-…
captured: 2026-…                   # capture-unit date; split-siblings share it
source: journal/YYYY-MM-DD         # or a compound `remote + path + commit` for external sources
related: ["[[…]]"]                 # Tier-1 factual (ingest) + confirmed associative (synthesizer / human)
routed_to: [{target, adapter}]     # audit: routing targets that delivered; ingest only
outcome: done                      # done | dropped; closes an actionable note; note-outcome only
resolved: 2026-…                   # the date of that outcome; note-outcome only
---
```

Older notes may carry `status` or `handled`. Both are retired: nothing new writes them. `status` is read by
nothing, and `handled` only marks a note as closed. Older `routed_to` entries have the shape
`{container, artifact, name}`; they stay as written and are read alongside the new shape.

Iron rule: note **bodies preserve the full source verbatim**; `title` is a derived label only and
never licenses dropping body content.

## Journal day-files

Files in `journal/` (`YYYY-MM-DD.md`) are **not** atomic notes — they do not carry the full frontmatter
contract above. They are the daily-notes capture surface and the permanent ingest source. Ingest writes
one marker on each processed day-file:

```yaml
ingested: true   # set by ingest when the day-file has been fully processed; absent = unprocessed
```

Day-files are never extracted to `notes/` — only the atomic thoughts *within* them are. The day-file
itself is the immutable source diary (permanent; never deleted or drained).

## Field ownership (no overlap, no gap)

- **Ingest** writes content-derived fields: `title`, `labels`, `created` / `captured` / `source`,
  and `routed_to` (audit: the routing targets that delivered).
- **`outcome` / `resolved`** are written only by the `note-outcome` script, the direct way to mark an
  actionable note done or dropped. Never read to select or schedule work. Their readers are ingest's
  re-run guard (skip targets other than notes for a note carrying `outcome`) and `ingest status`'s
  undelivered-actionables view.
- **`labels` after creation:** written only through the plugin's `relabel-notes` on a **confirmed**
  pass (the synthesizer's `resolve` sweeps after acceptance, the surgeon's operations), by
  `label-bank rename`, at ingest's interactive gate, or by the human (no other consumer touches it). A
  proposed label's name is never written to a note before it is accepted.
- **`related:`** written by ingest at creation for Tier-1 factual links; written by the synthesizer
  on confirm for associative links; human may edit directly.

## Query surface (preference order)

Per-machine specifics live in the consumer's `.local.md`; this is the abstract order.

1. `obsidian` CLI / built-in MCP — frontmatter-native, paths-first. **Only when the Obsidian app is
   running.**
2. **ripgrep over the markdown** — always available, app-independent. **This is the REQUIRED FLOOR**
   the headless loop depends on.
3. Never a full-vault read.

A stored `label → paths` index is **forbidden** — derive, don't store. Dataview is human-only (it
renders in-app), never a headless query path. **One sanctioned exception:** the proposal bank,
`_machine/label-proposals.yml`, stores each open proposal's evidence (source, verbatim quote, and the
note's slug). It is transient: an entry is deleted when its proposal is accepted or rejected.

## Asking for a label

**Ingest proposes, review accepts.** A missing label is *proposed*, never registered directly:

- **In the journal:** write `label:: <name>` on its own line inside the thought (Dataview's inline-field
  syntax; prose containing "label:" never triggers it). Ingest applies `<name>` if it is an active label;
  otherwise it opens (or adds evidence to) a proposal and parks the note under `needs-label`. A name
  previously rejected is reopened by an explicit request, carrying the old reason.
- **Implicitly:** ingest opens a proposal when no subject label fits a thought, and attaches thoughts that
  fit an open proposal's draft.
- **By hand or from a skill:** the vault plugin's `label-proposals open <vault> --name <label>
  --when-to-apply "…" [--explicit]`.

Proposals live in `_machine/label-proposals.yml`, written only by `label-proposals`. The synthesizer's
`resolve` sitting reviews them; `label-proposals accept` puts the label in the bank and deletes the
proposal in one commit; `reject` records the name and reason so ingest does not reopen it. Proposals
never expire. At ingest's interactive gate the human may accept an explicit request on the spot.

The bank itself, `_machine/labels.yml`, is written only by the plugin's `label-bank` (`add`, `update`,
`retire`, `rename`, `remove`; acceptance calls its `add`). Labels marked `origin: imported` (the container
labels `workspace:*` / `project:*`) are a read-only snapshot. Never edit either file by hand.

## Source registry

`_machine/ingest_paths.yml` lists external ingest sources. **Loop guard:** any label appearing in a rule of
`_machine/routing.yml` whose targets include one delivered by an adapter other than `notes` is *outbound*, and a
source's lens may never include one. `ingest status` flags a violation.
A vault-minted id is a note's slug, its filename without `.md`. Skip a source line containing `[[<slug>]]` or `<target>/<slug>` for an existing note: that line came from this vault.

## Routing

`_machine/routing.yml` declares `targets` (each naming the adapter that delivers to it, and its `params`) and
`rules` (a label match → target names; a set, every matching rule delivers). The vault ships with one target,
`notes`, the vault copy. Delivery anywhere else stays off until the plugin ships an adapter for it. Open
actionables are a live view over the notes (`ingest status`), never a stored list.

## Binding schema (the define-once home for the seam)

A skill binds **per-install** via a gitignored file `~/.claude/<skill-name>.local.md` (the documented
Claude Code per-install convention) — **not** by hardcoding paths in the skill body. Its frontmatter
records:

- **(a)** a pointer to this vault — path / this `INSTRUCTION.md`.
- **(b)** the labels this skill listens for *in this vault* — default to the skill's intrinsic label
  names, user-overridable. This override is what makes one skill body portable across vaults.
- **(c)** the vault's MCP endpoint, if configured (per-machine).

**Bootstrap (first use):** ask which vault → read this `INSTRUCTION.md` → write
`~/.claude/<skill>.local.md`.

**Every invocation:** read `~/.claude/<skill>.local.md` → read this `INSTRUCTION.md` + the
vocabulary live → query → act.

**Brittleness:** only the vault *path* can go stale. Fail **loudly** ("vault not found"); the fix is
a one-line re-bootstrap.

## Consumer idempotency

**Pairwise consumer** (e.g. the synthesizer): judges *pairs/clusters* of notes, not single notes. Its
idempotency is a **seen-set watermark** in a `_machine/` state file (incremental runs = unseen ×
neighborhoods), and confirmed outcomes are **effect-checked** (a merged note is gone; a link sits in
`related:`; an accepted label sits in the bank and its proposal is gone).

A reader of note frontmatter reports a note that fails to parse as an anomaly and continues; none stops on it.
