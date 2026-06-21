# Vault Integration Handshake

External integration handshake for vault-aware skills. Thin and structural — it lets a generic skill
bind to this vault without a hard dependency. Read **live** from the vault on every invocation.

> Distinct from the vault's internal `CLAUDE.md` (the agent OS-contract for working *inside* the
> vault). This file is for *external consumers* binding *to* the vault.

## Identity

This is a knowledge vault at `{{VAULT_PATH}}`. Its label bank — the shared label vocabulary —
is `_machine/labels.yml` (a machine-read-and-written YAML schema, the inter-skill label API).
**Reference it; never restate the vocabulary here.**

## Note shape

Every note is a markdown file with this frontmatter contract:

```yaml
---
title: "…"                         # derived label only — NEVER strips body content
labels: [idea, ai-systems, todo]   # concept + action labels, one flat set; from _machine/labels.yml
status:                            # ABSENT at creation; written later by a consumer or human.
                                   # Read per label: absent ⇒ open (todos) / seedling (knowledge)
created: 2026-…
captured: 2026-…                   # capture-unit date; split-siblings share it
source: obsidian-inbox             # may be a compound `remote + path + commit` for external sources
handled: []                        # consumer names; written by consumers (or human), never ingest
related: ["[[…]]"]                 # Tier-1 factual links only
---
```

Iron rule: note **bodies preserve the full source verbatim**; `title` is a derived label only and
never licenses dropping body content.

## Field ownership (no overlap, no gap)

- **Ingest** writes content-derived fields: `title`, `labels`, `created` / `captured` / `source`.
  Ingest writes **neither** `status` **nor** `handled`.
- **Consumers** (and the human) write `status` and `handled`.

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

Add an entry to the `labels:` map in `_machine/labels.yml`, following its schema — a key (the
label name; **quote** any key containing a colon, e.g. `"workspace:astrophotography"`) mapping to
`when_to_apply` (the classification description; use a YAML block scalar `>` for long ones) and
`status` (default `active`):

```yaml
  <label>:
    when_to_apply: "…when this label applies…"
    status: active
```

Manager skills register `workspace:` / `project:` container labels there. Retiring a label is a
one-line `status: active` → `status: retired` edit on its entry.

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

**Every invocation:** read `~/.claude/<skill>.local.md` → read this `INSTRUCTION.md` +
`_machine/labels.yml` live → query → act.

**Brittleness:** only the vault *path* can go stale. Fail **loudly** ("vault not found"); the fix is
a one-line re-bootstrap.

## Consumer idempotency (two archetypes)

- **One-shot consumer** (e.g. session-planner): queries `label == X AND self ∉ handled`, then appends
  its own name to `handled` for **every note it evaluates** (seen, not just used) — so skipped notes
  don't re-enter its context. Evaluates each note exactly once, ever.
- **Lifecycle consumer** (e.g. a scheduler): queries `label AND status:open`, does **not** write
  `handled`, and re-sees still-open items until they resolve (`status → done`).

Ingest never writes `handled`.
