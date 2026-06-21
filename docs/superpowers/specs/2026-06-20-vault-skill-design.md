# Design — the `vault` skill (claude-materia)

> **Status:** Design approved 2026-06-20. Next: implementation plan (writing-plans).
> **Context:** Task #2 of the vault build. The vault's flat label-based architecture
> (`notes/` + `journal/`, `_machine/labels.yml`, `INSTRUCTION.md`, the `.local.md` binding seam)
> was built in tasks #4 + #3. This skill generalizes the one-time bootstrap + migration that
> produced it into a portable, reusable creation skill — so a *new* vault is born in the final
> architecture and never needs the #3 migration.
> **Full architecture reference:** `~/.claude/plans/vault-design.md` (the 2026-06-19 revision is authoritative).

---

## 1. Identity & organizing principle

A **portable, env-agnostic** claude-materia skill. It is the home for vault operations whose
logic is **invariant across vaults** — independent of any particular vault's content or vocabulary.

**Organizing principle (decides what belongs in this skill):**
- **Invariant-across-vaults → this portable skill.** Operations whose logic doesn't depend on a
  vault's content (create the structure; register an ingest source) live here, once.
- **Content-dependent → vault-local.** Operations that depend on a vault's derived vocabulary
  (ongoing-ingest *classification*; the synthesizer) live in vault-local skills, not here.

**Cross-environment consistency rides in this skill, not in env/kinds.** The skill **carries the
vault spec as templates** (§5). Two vaults in different environments stay consistent because they
were stamped from the same templates — not because any env machinery enforces it (it can't; see §4).

**Singleton-aware.** One-vault-per-environment is treated as an invariant (the connected-knowledge
value, the single inbox, a single canonical vault for bindings to point at, and the one integration
bus all only cohere at N=1 per environment). The skill therefore produces a **singular result** — like the
kernel's dotfiles/stow bootstrap — and does **not** spawn or manage N instances the way
`workspace-manager` does. Its plurality is *cross-environment* (a personal vault + a work vault),
which is repetition of a per-environment singleton, not within-environment plurality.

**Name:** `vault`. (Subcommands disambiguate intent.)

## 2. Subcommand surface (locked)

`create` · `add-source` · `discuss`.

**Backlog (explicitly out of scope for v1):** repair / update / validate-against-spec behaviors
(a `facelift`-like conform pass). Deferred because there is no within-environment plurality for
such a pass to reconcile, and a created vault is born-correct; revisit if a real need appears.

## 3. `create` — corpus-adaptive bootstrap (4 phases)

The reference bootstrap (`~/Vault/_machine/logs/vault-bootstrap-process-notes.md`) was
Analyze → Structure-lock → Scaffold → File. This skill encodes that **process** (per lesson #1:
analyze source → derive THIS vault's bespoke shape → scaffold → file), not a fixed pipeline. It is
**corpus-adaptive**: the same subcommand handles a corpus-seeded start and a cold start.

- **A · Analyze** *(corpus-seeded only)* — given a source corpus (a path to exported notes / a
  markdown directory), dispatch **map-reduce subagents** over it to characterize: candidate
  domain/topic labels, types, multi-thought fragments, and a sensitive-content scan. Output is a
  structure **hypothesis** — a starting point, never a commitment. *(Cold start → skip.)*
- **B · Structure-lock** *(hard gate, interactive)* — present the hypothesis; iterate with the user;
  **lock** the bespoke vocabulary (domain/topic labels) + this-vault shape rules + dispositions
  (live / archive / ignore) + multi-thought policy. **Nothing scaffolds until the structure is
  locked.** *(Cold start → confirm a minimal seed vocabulary instead of deriving one.)*
- **C · Scaffold** *(deterministic, from templates — §5)* — create the skeleton and the
  final-architecture files:
  - vault directory + `jj init`
  - `.gitignore`, `.jjignore`, `.stignore` (jj honors `.gitignore`, lesson #9)
  - `.obsidian/` (defaults)
  - `_inbox/inbox.md` (single append-only inbox)
  - `notes/` (flat pool), `journal/` (separate folder), `_archive/`
  - `_machine/labels.yml` (the YAML label bank), `_machine/ingest_paths.yml` (templated/empty)
  - `INSTRUCTION.md` (the external integration handshake)
  - the vault's internal `CLAUDE.md` (the agent OS-contract for working *inside* the vault —
    distinct from `INSTRUCTION.md`, which is the *external* handshake)
  - `labels.yml` is seeded with the action labels (`todo`, `session-seed`, `idea`, `observation`),
    the container-label *scheme* documented as comments (`workspace:` / `project:` — no concrete
    `<name>` entries; those are registered later by the manager skills), and the locked domain/topic
    vocabulary. **Every seeded entry conforms to the bank schema** (`label → {when_to_apply,
    status: active}`); the canonical shape lives in the `assets/labels.yml` template (§6).
  - **Writes `~/.claude/vault.local.md`** — the canonical environment-vault pointer (§6).
- **D · File** *(corpus-seeded only; iron-rule)* — a **deterministic scripted pass** filing the
  analyzed corpus into `notes/` / `journal/` as conformant labeled notes (`labels[]`, **no
  `status`**, bodies preserved **verbatim**) per the locked structure. **Content-preservation iron
  rule:** record per-note `md5(body)` before, recompute after, assert identical; abort (leaving
  originals intact) on any mismatch or any non-empty body becoming empty. Produces final-architecture
  notes directly — **born-correct**, never needs the #3 migration. *(Cold start → skip; vocabulary
  grows later via the future ongoing-ingest skill.)*

## 4. `add-source` — register an ingest source

Registers an external source in `_machine/ingest_paths.yml` (the input-side pull registry). The
logic is invariant across vaults (pure schema + procedure), which is why it lives here rather than
being re-implemented in each vault's local ingest skill.

- Accept: `path`, `track: vcs|destructive`, label-lens (a subset of `labels.yml`),
  `remote`/`branch` (vcs only), optional non-selector `description`.
- Validate: path resolves; every lens label exists in `labels.yml`; for vcs, the repo + branch
  resolve. For vcs, initialize the `last_read` baseline (destructive sources carry **no stored
  state** — the residue is by definition unprocessed).
- Append a conformant entry. This *is* the deliberate accepted-read-exposure registration
  (additive-surface model — every entry is an explicit "I agree to send this source through ingest").
- Operates on the vault named in `~/.claude/vault.local.md`.
- **Cold-start interaction:** a lens can only reference labels that already exist in `labels.yml`,
  so on a freshly cold-started vault (action/seed labels only) `add-source` lenses are limited to
  that vocabulary; richer lenses become available as the bank grows via ongoing-ingest.

**Two writers, one schema (no conflict):** `add-source` writes *new entries* (invariant
registration); the future ongoing-ingest skill writes *`last_read` watermarks* (runtime state) on
**vcs** entries (destructive entries have no watermark). Same pattern as `labels.yml` (managers
register, ingest reads). The schema is defined once, here / in `INSTRUCTION.md`.

## 5. `discuss` — meta

Meta-conversation about how the vault and this skill work. Explicitly **routes the env-registration
taxonomy question** — does the singleton definition widen to admit a *reusably-bootstrapped
per-environment singleton*, or is that a new category? — to **`kind-bootstrapper discuss`**. This
skill never writes to env itself; the taxonomy decision is decoupled (§7) and does not block builds.

## 6. Skill file layout (in claude-materia)

```
skills/vault/
├── SKILL.md          # routing + the three subcommand processes; iron-rule documented as invariant
└── assets/           # THE SPEC, as instantiable templates (single source of truth)
    ├── labels.yml            # action + container seed labels (domain/topic appended at create)
    ├── INSTRUCTION.md        # the external handshake template
    ├── CLAUDE.md             # the vault's internal agent OS-contract template
    ├── ingest_paths.yml      # templated/empty input registry
    ├── gitignore, jjignore, stignore
    └── obsidian/             # .obsidian defaults
```

**The templates ARE the spec.** The deterministic scaffold (Phase C) instantiates them. This is the
single source of truth for the final architecture, what makes a created vault born-correct, and what
carries cross-environment consistency.

## 7. The canonical `~/.claude/vault.local.md` pointer

`create` writes a **single** environment-vault pointer (path + `INSTRUCTION.md` location), justified
by the singleton invariant. `add-source` and `discuss` read it to locate the vault; future
consumer-skill bootstraps may read it as the default vault rather than re-asking the user. This is a
small, deliberate extension to the per-skill `.local.md` seam: one canonical pointer per environment,
because there is exactly one vault per environment.

## 8. Cross-cutting invariants

- **Content-preservation iron rule** — Phase D is body-verbatim + hash-verified, abort-on-mismatch;
  documented as a hard invariant in `SKILL.md`. This is the exact step that nearly lost the corpus
  before (lesson #2).
- **Born-correct** — `create` produces the final architecture directly (flat `notes/`, `labels[]`,
  no `status`, `labels.yml` + `INSTRUCTION.md`), distilling the #3 migration's corrections so a fresh
  vault never needs migrating.
- **Output-contract sharing** — Phase D and the future ongoing-ingest skill both emit notes
  conforming to `INSTRUCTION.md`'s note shape. They share that *contract*, not filing code (Phase D
  is a one-time bulk scripted pass; ongoing-ingest is recurring incremental classification).
- **Env-agnostic** — zero `~/.claude/env` references anywhere in the skill (public-repo portability,
  per the v0.9.0 `.local.md` convention). Any env reachability is via the per-install `.local.md`,
  never a hardcoded env path.
- **Decoupled env-taxonomy** — the singleton-vs-kind registration is handled separately via
  `kind-bootstrapper discuss`; it gates only the (small) registration action in Tucker's env, not
  this skill's build or behavior.

## 9. Out of scope

- The **ongoing-ingest** skill (vault-local; recurring split→label→file against the fixed
  vocabulary) — separate future deliverable.
- **Consumer** skills (session-planner, weekly-planner, workspace-sync) — already vault-aware via
  the `.local.md` seam (task #4).
- The **synthesizer** (#5) — content-dependent; separate.
- **Repair/update/validate-against-spec** — backlog (§2).
- The **env-registration action** itself — handled via `kind-bootstrapper discuss` (§5, §7).
- **Kind-aware sources (deferred — discuss after everything else, per Tucker 2026-06-20).** Make the
  vault's source-ingestion aware of the kind system — e.g. register kind-instances (workspaces /
  projects) as ingest sources and/or kind-aware source handling on the input side. The input-side
  mirror of the output-side `workspace-sync` puller; ties to the `ingest_paths` model and the
  `kind-bootstrapper discuss` taxonomy. Interpretation to be confirmed at discussion time. Applies
  to the live `~/Vault` as a concrete final step once the rest of the build is finished.
