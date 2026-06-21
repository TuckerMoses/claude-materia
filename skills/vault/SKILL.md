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
