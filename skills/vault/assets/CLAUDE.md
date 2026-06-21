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
