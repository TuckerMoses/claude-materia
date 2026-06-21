# vault Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the portable, env-agnostic `vault` skill in claude-materia — a markdown skill (`SKILL.md` + instantiable asset templates) that creates born-correct knowledge vaults, registers ingest sources, and routes meta-discussion, distilling the one-time `~/Vault` bootstrap+migration into a reusable creation process.

**Architecture:** A markdown skill at `skills/vault/`. `SKILL.md` carries routing plus three subcommand processes (`create`, `add-source`, `discuss`) and documents the content-preservation iron rule as a hard invariant. `assets/` holds **the spec as instantiable templates** (single source of truth): a generalized `labels.yml`, a parameterized `INSTRUCTION.md`, a freshly-authored internal `CLAUDE.md`, an empty `ingest_paths.yml`, ignore files, and `.obsidian/` defaults. `create`'s deterministic Scaffold phase stamps these templates so every new vault is born in the final architecture and never needs migrating. Per-install coupling rides exclusively through `~/.claude/vault.local.md`.

**Tech Stack:** Markdown skill (`SKILL.md` + YAML/markdown templates). Tools used by the skill's processes and this plan's validation steps: a YAML parser (`python3 -c "import yaml"`), `jj` (version control; honors `.gitignore`), `ripgrep` (`rg`, the required query floor), `md5`/`md5sum` (iron-rule hashing). No application runtime, no pytest.

## Global Constraints

Every task's requirements implicitly include this section. Values copied verbatim from the spec (`docs/superpowers/specs/2026-06-20-vault-skill-design.md`).

- **Env-agnostic — zero `~/.claude/env` references anywhere in the skill.** Public-repo portability per the v0.9.0 `.local.md` convention. Any env reachability is via the per-install `.local.md`, never a hardcoded env path. (spec §8)
- **Content-preservation iron rule (Phase D of `create`).** Body-verbatim + hash-verified, abort-on-mismatch: record per-note `md5(body)` before, recompute after, assert identical; abort (leaving originals intact) on any mismatch or any non-empty body becoming empty. Documented as a hard invariant in `SKILL.md`. (spec §3D, §8)
- **Born-correct = final architecture directly.** `create` produces flat `notes/` + separate `journal/`, `labels[]`, **no `status`** in new notes, `labels.yml` + `INSTRUCTION.md` present — distilling the migration's corrections so a fresh vault never needs migrating. (spec §8)
- **Templates ARE the spec — single source of truth.** The deterministic Scaffold (Phase C) instantiates `assets/`. This is what makes a vault born-correct and carries cross-environment consistency; consistency rides in this skill, not in env/kinds. (spec §5, §6)
- **Portable per-install via `~/.claude/vault.local.md`.** One canonical environment-vault pointer (path + `INSTRUCTION.md` location), written by `create`, read by `add-source`/`discuss`. A deliberate extension of the per-skill `.local.md` seam, justified by the one-vault-per-environment singleton invariant. (spec §7)
- **Singleton-aware.** The skill produces a singular result per environment (like the dotfiles/stow bootstrap); it does not spawn or manage N within-environment instances. (spec §1)
- **Two writers, one schema.** `add-source` writes new `ingest_paths.yml` entries; the future ongoing-ingest skill writes `last_read` watermarks on vcs entries only. The schema is defined once (here / in `INSTRUCTION.md`). (spec §4)
- **Decoupled env-taxonomy.** The singleton-vs-kind registration question routes to `kind-bootstrapper discuss`; it gates only the (small) registration action in Tucker's env, never this skill's build or behavior. (spec §6, §7, §9)

---

## File Structure

All paths are under `~/claude-materia/`.

```
skills/vault/
├── SKILL.md                 # Tasks 2,3,4,5 — frontmatter, routing, 3 processes, iron-rule invariant
└── assets/                  # Task 1 — THE SPEC as instantiable templates
    ├── labels.yml           # generalized: action labels + container scheme comments only
    ├── INSTRUCTION.md       # parameterized: {{VAULT_PATH}} placeholder, otherwise verbatim
    ├── CLAUDE.md            # authored fresh: vault-internal agent OS-contract
    ├── ingest_paths.yml     # empty/templated input registry with schema comment
    ├── gitignore            # stamped to .gitignore (leading-dot files stored dotless in assets)
    ├── jjignore             # stamped to .jjignore
    ├── stignore             # stamped to .stignore
    └── obsidian/            # stamped to .obsidian/ — defaults
        ├── app.json
        ├── appearance.json
        ├── core-plugins.json
        └── graph.json
```

Plus, outside the skill: `README.md` (materia table entry) and `.claude-plugin/plugin.json` (version bump), touched in Task 6.

**Note on dotfile asset naming.** Ignore files and the `.obsidian/` dir are stored **without** the leading dot inside `assets/` (`gitignore`, not `.gitignore`; `obsidian/`, not `.obsidian/`) so they are not themselves treated as ignore rules / hidden state inside the claude-materia repo. The Scaffold phase renames them on stamp. `CLAUDE.md` and `INSTRUCTION.md` keep their names (they are not dot-prefixed).

---

### Task 1: Skill dir + `assets/` templates distilled from live artifacts

**Files:**
- Create: `skills/vault/assets/labels.yml`
- Create: `skills/vault/assets/INSTRUCTION.md`
- Create: `skills/vault/assets/CLAUDE.md`
- Create: `skills/vault/assets/ingest_paths.yml`
- Create: `skills/vault/assets/gitignore`
- Create: `skills/vault/assets/jjignore`
- Create: `skills/vault/assets/stignore`
- Create: `skills/vault/assets/obsidian/app.json`
- Create: `skills/vault/assets/obsidian/appearance.json`
- Create: `skills/vault/assets/obsidian/core-plugins.json`
- Create: `skills/vault/assets/obsidian/graph.json`

**Interfaces:**
- Produces: the asset filenames above. Task 3's Scaffold phase references each by exact name; do not rename without updating Task 3.

- [ ] **Step 1: Create the skill + assets directories**

```bash
mkdir -p ~/claude-materia/skills/vault/assets/obsidian
```

- [ ] **Step 2: Author `assets/labels.yml` (generalized from the live bank)**

Distilled by **generalizing** `~/Vault/_machine/labels.yml`: keep the header/format + the four action labels (`todo`, `session-seed`, `idea`, `observation`) + the container-label *scheme comments* (`workspace:` / `project:`). STRIP all bespoke domain/topic/type vocabulary (those are derived per-vault at create time). Every entry keeps the `{when_to_apply, status: active}` schema.

```yaml
# Label Bank — the shared label vocabulary / inter-skill API for this vault.
# Machine-read (ingest uses when_to_apply for classification) AND machine-written
# (manager skills register labels; the project retirement gate flips status active→retired).
# status: active is the default; ingest applies only active labels to new notes.
# status: retired = marked-not-deleted: stays valid on existing notes for provenance,
# but ingest won't apply it to anything new. Lets container labels (esp. project:) be
# retired on completion without losing history.
#
# This is a SEED bank. The four action labels below are vault-invariant and ship with
# every vault. Domain / topic / type / facet labels are DERIVED PER VAULT at create time
# (Structure-lock, spec §3B) and appended here in this same schema — they are intentionally
# absent from the template.
#
# Container labels (workspace:<name>, project:<name>) are pull-vocabulary registered by
# their manager skills (workspace-manager, project-manager) — NOT by ingest, and NOT seeded
# here. The schemes are documented below as comments only; no concrete <name> entries ship.
#
# workspace:<name> scheme: one label per active workspace, registered by the workspace-manager
# skill at workspace creation, in this schema with status: active. Quote the key (it contains
# a colon): "workspace:<name>".
#
# project:<name> scheme: registered by the project-manager skill at project creation, in this
# schema with status: active. Subject to a RETIREMENT GATE: on project completion the manager
# flips that entry to status: retired (marked-not-deleted), so ingest stops applying it while
# existing notes keep their provenance. Quote the key: "project:<name>".

labels:
  # --- Action / type labels (vault-invariant; ship with every vault) ---
  todo:
    when_to_apply: >
      The canonical actionability label. Apply when a note requires a concrete action
      from you (vs. knowledge / observation / reference). Orthogonal to
      subject/container/type labels — a note can be [idea, todo] or bare todo. Apply with
      discipline (actionable, not aspirational) or it over-applies. Pairs with note-level
      status: open|done.
    status: active
  session-seed:
    when_to_apply: >
      A genuine "work-through-this-WITH-Claude" invitation, not knowledge to file. Handled
      by a session-planner puller. Orthogonal to container labels (a note may carry
      project:<name> + session-seed, or session-seed alone).
    status: active
  idea:
    when_to_apply: "An undeveloped concept / insight worth keeping."
    status: active
  observation:
    when_to_apply: "A noticed fact / pattern; knowledge, not action."
    status: active

  # --- Container labels (pull-vocabulary; registered later by manager skills) ---
  # workspace:<name> and project:<name> entries are added here by workspace-manager /
  # project-manager, NOT seeded at create. See the scheme comments in the header.

  # --- Domain / topic / type / facet labels ---
  # DERIVED PER VAULT at Structure-lock (corpus-seeded) or confirmed as a minimal seed
  # (cold start), then appended here in the {when_to_apply, status: active} schema above.
  # None ship in this template.
```

- [ ] **Step 3: Author `assets/INSTRUCTION.md` (parameterized from the live handshake)**

Distilled by **parameterizing** `~/Vault/INSTRUCTION.md`: replace the hardcoded vault path with the `{{VAULT_PATH}}` placeholder; otherwise keep it **verbatim** (it is the handshake — born-correct vaults get the same one). The only change from the live file is line 11's path.

```markdown
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
```

- [ ] **Step 4: Author `assets/CLAUDE.md` fresh (vault-internal OS-contract)**

There is no `CLAUDE.md` in `~/Vault` yet — author this fresh. Keep it **thin**: where things live, the immutable-placement + content-preservation rules, that `labels.yml` is the vocabulary, and a pointer to `INSTRUCTION.md` for the external contract. **Do not duplicate `INSTRUCTION.md`** (no note-shape frontmatter spec, no binding-schema, no query-surface — those are the external handshake's job; reference it).

```markdown
# Vault — internal agent contract

You are operating **inside** a knowledge vault. This file is the OS-contract for working in here:
where things live and the rules that never bend. It is distinct from `INSTRUCTION.md`, which is the
*external* handshake for skills binding *to* this vault — for the note-shape frontmatter contract,
field ownership, the query surface, and the per-install binding seam, **read `INSTRUCTION.md`**.

## Layout (immutable placement)

- `notes/` — the flat atomic-note pool. One concept per file. No subject subfolders; subject lives
  in `labels`, not in the path.
- `journal/` — dated/reflective entries, kept as a separate folder from `notes/`.
- `_inbox/inbox.md` — the single append-only capture inbox. Synced separately; not version-tracked.
- `_machine/` — machine state. `labels.yml` is the label vocabulary; `ingest_paths.yml` is the
  input-side source registry. Logs/indexes/proposals live here too.
- `_archive/` — cold storage. Excluded from version control and sync.

**Placement is immutable.** Do not relocate these directories, do not introduce subject subfolders
under `notes/`, do not split `journal/` into `notes/`. The flat pool + labels is the architecture.

## Content-preservation (iron rule)

Note **bodies preserve the full source verbatim**. A note's `title` is a *derived label only* — it
never licenses dropping, truncating, or summarizing body content. Any bulk operation that rewrites
note bodies must verify content is preserved (hash before/after) and abort on mismatch rather than
risk silent loss. This is the single rule that most protects the corpus.

## Vocabulary

`_machine/labels.yml` is the authoritative label vocabulary — the shared inter-skill API. Apply only
labels that exist there (`status: active`). To add one, follow the schema and procedure documented in
`INSTRUCTION.md` ("Register a missing label"). Never invent ad-hoc labels in note frontmatter.

## External contract

For anything an *external* skill needs — note frontmatter shape, who writes which field, how to query
the vault, how to bind per-install — see `INSTRUCTION.md`. This file does not restate it.
```

- [ ] **Step 5: Author `assets/ingest_paths.yml` (empty/templated input registry)**

The live file is empty. Ship a documented empty template carrying the schema both writers share (spec §4).

```yaml
# Ingest source registry — the input-side pull registry (additive-surface model).
# Each entry is a deliberate accepted-read-exposure: "I agree to send this source through ingest."
# Written by `vault add-source` (new entries). The future ongoing-ingest skill writes the
# `last_read` watermark on vcs entries ONLY (destructive entries carry no stored state — the
# residue is by definition unprocessed). Two writers, one schema; defined here and in INSTRUCTION.md.
#
# Entry schema:
#   - path: <absolute path to the source>
#     track: vcs | destructive          # vcs = read commits since last_read; destructive = drained
#     lens: [<label>, ...]              # a subset of _machine/labels.yml; every label MUST exist there
#     description: "<non-selector human note>"   # optional
#     # --- vcs only ---
#     remote: <git/jj remote>
#     branch: <branch>
#     last_read: <commit>               # baseline; initialized at registration, advanced by ingest

sources: []
```

- [ ] **Step 6: Author the ignore files (stored dotless; renamed on stamp)**

`assets/gitignore`:

```
# jj honors .gitignore (not .jjignore). Mirrors .jjignore so exclusions actually apply.
# Inbox is synced separately (iCloud/Syncthing), not jj-tracked. Archive is cold storage,
# excluded from BOTH jj and Syncthing.
_inbox/
_archive/
.obsidian/workspace*
.obsidian/cache/
.obsidian/community-plugins.json
.obsidian/plugins/
```

`assets/jjignore`:

```
_inbox/
_archive/
.obsidian/workspace*
.obsidian/cache/
.obsidian/community-plugins.json
```

`assets/stignore`:

```
// Syncthing ignore patterns (for later Phase 3 sync setup).
// Archive is cold storage — excluded from sync. .jj internal state is not synced.
_archive/
.jj/
```

- [ ] **Step 7: Author the `.obsidian/` defaults (stored under `assets/obsidian/`)**

Copy verbatim from the live vault's `.obsidian/`.

`assets/obsidian/app.json`:

```json
{
  "alwaysUpdateLinks": true,
  "newLinkFormat": "shortest",
  "useMarkdownLinks": false,
  "attachmentFolderPath": "_archive/attachments"
}
```

`assets/obsidian/appearance.json`:

```json
{}
```

`assets/obsidian/core-plugins.json`:

```json
{
  "file-explorer": true,
  "global-search": true,
  "switcher": true,
  "graph": true,
  "backlink": true,
  "outgoing-link": true,
  "tag-pane": true,
  "properties": true,
  "page-preview": true,
  "templates": false,
  "note-composer": true,
  "command-palette": true,
  "editor-status": true,
  "bookmarks": true,
  "outline": true,
  "word-count": true,
  "file-recovery": true,
  "canvas": true,
  "footnotes": false,
  "daily-notes": true,
  "slash-command": false,
  "markdown-importer": false,
  "zk-prefixer": false,
  "random-note": false,
  "slides": false,
  "audio-recorder": false,
  "workspaces": false,
  "publish": false,
  "sync": true,
  "bases": true,
  "webviewer": false
}
```

`assets/obsidian/graph.json`:

```json
{
  "collapse-filter": true,
  "search": "",
  "showTags": false,
  "showAttachments": false,
  "hideUnresolved": false,
  "showOrphans": true,
  "collapse-color-groups": true,
  "colorGroups": [],
  "collapse-display": true,
  "showArrow": false,
  "textFadeMultiplier": 0,
  "nodeSizeMultiplier": 1,
  "lineSizeMultiplier": 1,
  "collapse-forces": true,
  "centerStrength": 0.5,
  "repelStrength": 10,
  "linkStrength": 1,
  "linkDistance": 250,
  "scale": 0.5,
  "close": false
}
```

- [ ] **Step 8: Validate — every YAML asset parses and is shaped correctly**

Run:
```bash
cd ~/claude-materia/skills/vault/assets
python3 -c "import yaml,sys; d=yaml.safe_load(open('labels.yml')); assert set(['todo','session-seed','idea','observation']) <= set(d['labels']), 'missing action labels'; assert all('when_to_apply' in v and v.get('status')=='active' for v in d['labels'].values()), 'bad entry shape'; assert not any(k.startswith(('workspace:','project:')) for k in d['labels']), 'container labels must NOT be seeded'; print('labels.yml OK', list(d['labels']))"
python3 -c "import yaml; d=yaml.safe_load(open('ingest_paths.yml')); assert d=={'sources':[]} or d.get('sources')==[], 'sources must be empty'; print('ingest_paths.yml OK')"
python3 -c "import json; [json.load(open(f'obsidian/{f}')) for f in ['app.json','appearance.json','core-plugins.json','graph.json']]; print('obsidian JSON OK')"
```
Expected:
```
labels.yml OK ['todo', 'session-seed', 'idea', 'observation']
ingest_paths.yml OK
obsidian JSON OK
```

- [ ] **Step 9: Validate — INSTRUCTION.md is parameterized, CLAUDE.md doesn't duplicate it**

Run:
```bash
cd ~/claude-materia/skills/vault/assets
grep -c '{{VAULT_PATH}}' INSTRUCTION.md            # expect: 1
grep -c '/Users/johnmoses' INSTRUCTION.md          # expect: 0 (no hardcoded path)
grep -ci 'binding schema\|query surface\|frontmatter contract' CLAUDE.md   # expect: 0 (no dup of handshake)
grep -ci 'INSTRUCTION.md' CLAUDE.md                # expect: >=1 (pointer present)
grep -ci 'iron rule\|verbatim' CLAUDE.md           # expect: >=1 (content-preservation present)
```
Expected: `1`, then `0`, then `0`, then a number `>=1`, then `>=1`.

- [ ] **Step 10: Commit**

```bash
cd ~/claude-materia
git add skills/vault/assets
git commit -m "feat(vault): add asset templates distilled from live vault (labels, INSTRUCTION, CLAUDE, ignores, obsidian)"
```

---

### Task 2: SKILL.md frontmatter + identity/principle + subcommand routing

**Files:**
- Create: `skills/vault/SKILL.md`

**Interfaces:**
- Consumes: asset filenames from Task 1 (referenced in the identity/routing text).
- Produces: `SKILL.md` with an `## Identity & organizing principle`, `## Per-install binding`, and `## Subcommands and routing` section. Tasks 3–5 append their subcommand process sections to this file; they rely on the routing table naming `create` / `add-source` / `discuss` exactly.

- [ ] **Step 1: Write the frontmatter + identity/principle + routing**

Write `skills/vault/SKILL.md`:

````markdown
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
````

- [ ] **Step 2: Validate — frontmatter parses and routing names all three subcommands**

Run:
```bash
cd ~/claude-materia/skills/vault
python3 -c "import yaml; t=open('SKILL.md').read(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['name']=='vault'; assert 'create a vault' in d['description']; print('frontmatter OK:', d['name'])"
grep -c '/vault create\|/vault add-source\|/vault discuss' SKILL.md   # expect: 3
grep -c '~/.claude/vault.local.md' SKILL.md                          # expect: >=1
grep -c '~/.claude/env' SKILL.md                                     # expect: 0 (env-agnostic)
```
Expected: `frontmatter OK: vault`, then `3`, then a number `>=1`, then `0`.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-materia
git add skills/vault/SKILL.md
git commit -m "feat(vault): SKILL.md frontmatter, identity/principle, per-install binding, routing"
```

---

### Task 3: `create` — the 4-phase corpus-adaptive bootstrap

**Files:**
- Modify: `skills/vault/SKILL.md` (append the `## create` section)

**Interfaces:**
- Consumes: every asset filename from Task 1 (`labels.yml`, `INSTRUCTION.md`, `CLAUDE.md`, `ingest_paths.yml`, `gitignore`, `jjignore`, `stignore`, `obsidian/`), the `{{VAULT_PATH}}` placeholder, and the `~/.claude/vault.local.md` pointer named in Task 2.
- Produces: the documented Scaffold output structure (the born-correct vault shape) that Task 6 conformance-checks.

- [ ] **Step 1: Append the `## create` section to `SKILL.md`**

Append the following. The prose for the four phases must use the **load-bearing exact wording** below; the per-phase detail may be a tight outline but must not be a vague "do the analysis" placeholder.

````markdown
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
3. Stamp `assets/obsidian/ → .obsidian/`.
4. Create `_inbox/inbox.md` (single append-only inbox), `notes/` (flat pool), `journal/` (separate
   folder), `_archive/`, `_machine/`.
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
abort the pass and leave all originals untouched.
````

- [ ] **Step 2: Validate — the `create` section documents all four phases, the gate, and the iron rule**

Run:
```bash
cd ~/claude-materia/skills/vault
grep -c 'A · Analyze\|B · Structure-lock\|C · Scaffold\|D · File' SKILL.md   # expect: >=4
grep -ci 'HARD GATE\|Nothing scaffolds until the structure is locked' SKILL.md  # expect: >=1
grep -ci 'corpus-adaptive\|cold start' SKILL.md                              # expect: >=1
grep -c 'md5(body)\|abort' SKILL.md                                          # expect: >=2 (iron rule)
grep -ci 'NO .status.\|no .status.' SKILL.md                                 # expect: >=1 (born-correct)
grep -c '{{VAULT_PATH}}' SKILL.md                                            # expect: >=1 (stamp step)
```
Expected: each count meets its threshold.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-materia
git add skills/vault/SKILL.md
git commit -m "feat(vault): create subcommand — 4-phase corpus-adaptive bootstrap with iron-rule File phase"
```

---

### Task 4: `add-source` — register an ingest source

**Files:**
- Modify: `skills/vault/SKILL.md` (append the `## add-source` section)

**Interfaces:**
- Consumes: the `ingest_paths.yml` schema authored in Task 1 (Step 5), the `_machine/labels.yml` vocabulary, and the `~/.claude/vault.local.md` pointer from Task 2.
- Produces: the entry schema referenced by Task 6's coverage check.

- [ ] **Step 1: Append the `## add-source` section**

````markdown
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

- `path` resolves.
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
````

- [ ] **Step 2: Validate — `add-source` documents the schema, validation, and two-writers rule**

Run:
```bash
cd ~/claude-materia/skills/vault
grep -ci 'track: vcs\|destructive' SKILL.md                       # expect: >=1
grep -ci 'last_read' SKILL.md                                     # expect: >=2 (vcs-only baseline + two-writers)
grep -ci 'Two writers, one schema' SKILL.md                       # expect: 1
grep -ci 'Every lens label exists in' SKILL.md                    # expect: 1
grep -ci 'vault.local.md' SKILL.md                                # expect: >=2 (binding + add-source)
```
Expected: each count meets its threshold.

- [ ] **Step 3: Commit**

```bash
cd ~/claude-materia
git add skills/vault/SKILL.md
git commit -m "feat(vault): add-source subcommand — ingest registration, validation, two-writers schema"
```

---

### Task 5: `discuss` + canonical pointer mechanics + iron-rule invariant section

**Files:**
- Modify: `skills/vault/SKILL.md` (append `## discuss` and a top-level `## Invariants` section)

**Interfaces:**
- Consumes: the iron-rule wording from Task 3 and the pointer from Task 2.
- Produces: the `## Invariants` section Task 6 greps as the cross-cutting-invariants coverage check.

- [ ] **Step 1: Append the `## discuss` section**

````markdown
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
````

- [ ] **Step 2: Append the consolidated `## Invariants` section**

````markdown
## Invariants (cross-cutting, hard)

- **Content-preservation iron rule** — Phase D of `create` is body-verbatim + hash-verified,
  abort-on-mismatch (see "Iron rule" under create). The exact step that nearly lost the corpus before.
- **Born-correct** — `create` produces the final architecture directly (flat `notes/`, separate
  `journal/`, `labels[]`, **no `status`** in new notes, `labels.yml` + `INSTRUCTION.md` present), so a
  fresh vault never needs migrating.
- **Templates-as-spec** — `assets/` is the single source of truth; Scaffold only instantiates it. This
  is what carries cross-environment consistency.
- **Env-agnostic** — zero `~/.claude/env` references anywhere in this skill. Any env reachability is
  via `~/.claude/vault.local.md`, never a hardcoded env path.
- **Output-contract sharing** — Phase D and the future ongoing-ingest skill both emit notes conforming
  to `INSTRUCTION.md`'s note shape. They share that *contract*, not filing code (Phase D is a one-time
  bulk scripted pass; ongoing-ingest is recurring incremental classification).
- **Decoupled env-taxonomy** — singleton-vs-kind registration is handled via `kind-bootstrapper
  discuss`; it gates only the small registration action in the user's env, not this skill.
````

- [ ] **Step 3: Validate — discuss routes to kind-bootstrapper and invariants are present**

Run:
```bash
cd ~/claude-materia/skills/vault
grep -ci 'kind-bootstrapper discuss' SKILL.md                              # expect: >=2 (routing + invariant)
grep -ci 'Content-preservation iron rule' SKILL.md                        # expect: >=2
grep -ci 'Born-correct\|Templates-as-spec\|Env-agnostic\|Output-contract sharing\|Decoupled env-taxonomy' SKILL.md  # expect: >=5
grep -c '~/.claude/env' SKILL.md                                          # expect: 0
```
Expected: counts meet thresholds; the final `~/.claude/env` count is `0`.

- [ ] **Step 4: Commit**

```bash
cd ~/claude-materia
git add skills/vault/SKILL.md
git commit -m "feat(vault): discuss subcommand + consolidated cross-cutting invariants section"
```

---

### Task 6: Integration — `create` dry-run conformance + spec coverage check

**Files:**
- Modify: `README.md` (add vault to the materia table)
- Modify: `.claude-plugin/plugin.json` (version bump)
- (No new skill files; this task validates the whole skill end-to-end.)

**Interfaces:**
- Consumes: all of Tasks 1–5 (the assets and the full `SKILL.md`).
- Produces: the README entry + version bump that ship the skill.

- [ ] **Step 1: Dry-run conformance — stamp the templates into a throwaway dir and verify born-correct shape**

This simulates Phase C (Scaffold) deterministically — instantiating the `assets/` templates yields a vault whose structure matches the live `~/Vault` shape (flat `notes/` + separate `journal/`, parseable `_machine/labels.yml`, present `INSTRUCTION.md`, and — when notes are added — no `status`).

Run:
```bash
set -e
A=~/claude-materia/skills/vault/assets
V=$(mktemp -d)/vault
mkdir -p "$V"/{notes,journal,_archive,_machine,_inbox} "$V/.obsidian"
: > "$V/_inbox/inbox.md"
cp "$A/gitignore"  "$V/.gitignore"
cp "$A/jjignore"   "$V/.jjignore"
cp "$A/stignore"   "$V/.stignore"
cp "$A"/obsidian/*.json "$V/.obsidian/"
cp "$A/labels.yml" "$V/_machine/labels.yml"
cp "$A/ingest_paths.yml" "$V/_machine/ingest_paths.yml"
sed "s|{{VAULT_PATH}}|$V|g" "$A/INSTRUCTION.md" > "$V/INSTRUCTION.md"
cp "$A/CLAUDE.md" "$V/CLAUDE.md"
# Simulate one filed note (no status, body verbatim) to exercise born-correct note shape:
printf -- '---\ntitle: Sample Note\nlabels: [idea]\ncreated: 2026-06-20\nsource: dry-run\n---\n\nVerbatim body.\n' > "$V/notes/sample.md"

# --- assertions ---
test -d "$V/notes" && test -d "$V/journal" && echo "flat notes/ + journal/ OK"
test -f "$V/INSTRUCTION.md" && ! grep -q '{{VAULT_PATH}}' "$V/INSTRUCTION.md" && echo "INSTRUCTION.md present + parameter filled OK"
python3 -c "import yaml; yaml.safe_load(open('$V/_machine/labels.yml')); print('labels.yml parses OK')"
! grep -q '^status:' "$V/notes/sample.md" && echo "no status in new note OK"
test ! -d "$V/notes/philosophy" && echo "no subject subfolders (flat pool) OK"
echo "DRY-RUN CONFORMANCE PASS"; rm -rf "$(dirname "$V")"
```
Expected (final lines):
```
flat notes/ + journal/ OK
INSTRUCTION.md present + parameter filled OK
labels.yml parses OK
no status in new note OK
no subject subfolders (flat pool) OK
DRY-RUN CONFORMANCE PASS
```

- [ ] **Step 2: Spec coverage check — every spec § maps to skill text**

Run (each grep asserts the SKILL.md/assets cover a spec section):
```bash
cd ~/claude-materia/skills/vault
echo "§1 identity/principle:";  grep -cqi 'Invariant-across-vaults' SKILL.md && echo OK
echo "§2 subcommand surface:";  grep -cq '/vault create\|/vault add-source\|/vault discuss' SKILL.md && echo OK
echo "§3 create 4 phases:";     grep -cq 'Analyze\|Structure-lock\|Scaffold\|D · File' SKILL.md && echo OK
echo "§4 add-source:";          grep -cqi 'Two writers, one schema' SKILL.md && echo OK
echo "§5 discuss/routing:";     grep -cqi 'kind-bootstrapper discuss' SKILL.md && echo OK
echo "§6 assets layout:";       ls assets/labels.yml assets/INSTRUCTION.md assets/CLAUDE.md assets/ingest_paths.yml >/dev/null && echo OK
echo "§7 canonical pointer:";   grep -cq '~/.claude/vault.local.md' SKILL.md && echo OK
echo "§8 invariants:";          grep -cqi 'Content-preservation iron rule' SKILL.md && echo OK
```
Expected: an `OK` printed after every section line.

- [ ] **Step 3: Add the README materia-table entry**

Add a `vault` row to the materia table in `~/claude-materia/README.md` (match the existing table's column shape; describe it as the portable vault create / add-source / discuss skill).

- [ ] **Step 4: Bump the plugin version**

Increment the `version` field in `~/claude-materia/.claude-plugin/plugin.json` (per the repo's "bump for any content change" convention).

Validate:
```bash
cd ~/claude-materia
python3 -c "import json; print('version', json.load(open('.claude-plugin/plugin.json'))['version'])"
grep -ci 'vault' README.md   # expect: >=1
```
Expected: the new version prints; README count `>=1`.

- [ ] **Step 5: Commit**

```bash
cd ~/claude-materia
git add README.md .claude-plugin/plugin.json
git commit -m "feat(vault): ship skill — README entry + version bump (passes dry-run conformance + spec coverage)"
```

---

## Self-Review

**Spec coverage:** §1 → Task 2 (identity/principle). §2 → Task 2 (routing) + §2-backlog noted out of scope. §3 (A/B/C/D) → Task 3. §4 → Task 4. §5 (discuss) → Task 5. §6 (assets layout) → Task 1, validated in Task 6 Step 2. §7 (canonical pointer) → Task 2 binding + Task 3 Step C9. §8 (invariants) → Task 5 `## Invariants` + Task 3 iron rule. §9 out-of-scope items are not planned (correct).

**Placeholder scan:** the only intentional placeholder is `{{VAULT_PATH}}` in `assets/INSTRUCTION.md`, which is a *runtime template parameter* (replaced at Scaffold), not a plan-authoring gap. No "TBD"/"implement later" remain.

**Type/name consistency:** asset filenames (`labels.yml`, `INSTRUCTION.md`, `CLAUDE.md`, `ingest_paths.yml`, `gitignore`/`jjignore`/`stignore`, `obsidian/`) are identical across Tasks 1, 3, and 6. The pointer is `~/.claude/vault.local.md` everywhere. Subcommand names `create`/`add-source`/`discuss` are identical across Tasks 2–6. `track: vcs|destructive` and `last_read` (vcs-only) are consistent between Task 1's schema and Task 4's procedure.

## Execution Handoff

After saving this plan, the executing agent should use **superpowers:subagent-driven-development** (fresh subagent per task, review between tasks) or **superpowers:executing-plans** (inline batch with checkpoints).
