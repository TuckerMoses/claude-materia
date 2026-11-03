# Vault Integration Handshake

External integration handshake for vault-aware skills. Thin and structural — it lets a generic skill
bind to this vault without a hard dependency. Read **live** from the vault on every invocation.

> Distinct from the vault's internal `CLAUDE.md` (the agent OS-contract for working *inside* the
> vault). This file is for *external consumers* binding *to* the vault.

## Identity

This is a knowledge vault at `{{VAULT_PATH}}`. Its label bank — the shared label vocabulary —
is `$AGENT_LIB/data/labels.yml` when a standard library exists, else `_machine/labels.yml` (a machine-read YAML file, the inter-skill label API; a binding may override the path).
**Reference it; never restate the vocabulary here.** The vault is a sink: it holds thought, intent and
outcome records, and acts on nothing.

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
routed_to: [{container, artifact, name}]  # audit: targets whose writes succeeded; ingest only
outcome: done                      # done | dropped; only for a note that had a backlog item; note-outcome only
resolved: 2026-…                   # the date of that outcome; note-outcome only
---
```

Older notes may carry `status` or `handled`. Both are retired: nothing new writes them. `status` is read by
nothing, and `handled` only marks a note as closed.

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
  and `routed_to` (audit: the targets whose writes succeeded).
- **`outcome` / `resolved`** are written only by the `note-outcome` script, when a backlog item with a
  vault copy is done or dropped. Never read to select or schedule work. Their readers are ingest's re-run
  guard (skip non-vault targets for a note carrying `outcome`), `ingest status` reconciliation, and
  the legacy routing pass.
- **`labels` after creation:** written only by the synthesizer's **confirmed** minting/resolve
  passes, ingest's interactive gate, or the human (no other consumer touches it).
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
renders in-app), never a headless query path.

## Register a missing label

Call the standard library's `label-register`, the sole writer of the vocabulary:

```sh
"$AGENT_LIB/syscalls/label-register" --name <label> --when-to-apply "…when this label applies…"
```

Manager skills register `workspace:` / `project:` container labels through `container-register`. Never edit
the vocabulary by hand. Retiring a label is deferred: `label-retire` is not built.

## Source registry

`_machine/ingest_paths.yml` lists external ingest sources. **Loop guard:** any label appearing in a routing rule
whose targets include a non-`notes` artifact is *outbound*, and a source's lens may never include one. `ingest status` flags a violation.
A vault-minted id is a note's slug, its filename without `.md`. Skip a source line containing `[[<slug>]]` or `<container>/<slug>` for an existing note: that line came from this vault.

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
`related:`; a minted label sits in the bank).

A consumer that acts on pending work reads backlogs, not notes. A reader of note frontmatter reports a note
that fails to parse as an anomaly and continues; none stops on it.
