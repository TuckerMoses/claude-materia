# Vault — internal agent contract

You are operating **inside** a knowledge vault. This file is the OS-contract for working in here:
where things live and the rules that never bend. It is distinct from `INSTRUCTION.md`, which is the
*external* handshake for skills binding *to* this vault — for the note-shape frontmatter contract,
field ownership, the query surface, and the per-install binding seam, **read `INSTRUCTION.md`**.

## Layout (immutable placement)

- `notes/` — the flat atomic-note pool. One concept per file. No subject subfolders; subject lives
  in `labels`, not in the path.
- `journal/` — the daily-notes capture surface AND the permanent ingest source. Time-indexed diary:
  one file per day (`YYYY-MM-DD.md`), written via Obsidian's daily-notes plugin or `/capture`. Day-files
  are permanent (the durable chronological diary). Ingest processes closed past day-files; the
  `ingested` frontmatter marker records which ones have been processed.
- `_machine/` — machine state. `labels.yml` is the label vocabulary; `ingest_paths.yml` is the
  input-side source registry. Logs/indexes/proposals live here too.
- `_archive/` — cold storage. Excluded from version control and sync.

**Placement is immutable.** Do not relocate these directories, do not introduce subject subfolders
under `notes/`, do not split `journal/` into `notes/`. The flat pool + labels is the architecture.

## Capture & ingest

**Single capture surface = daily notes.** Everything goes into today's `journal/YYYY-MM-DD.md` —
diary, ideas, todos, wellbeing — without sorting at write time.

**Ingest** processes **past, closed, un-`ingested` day-files** only (never today's). For each:

1. **Existing label → extract + label** the thought as an atomic note into `notes/`.
2. **Knowledge-worthy, no label fits → extract + `needs-label`** (parked, never dropped).
3. **Trivial narrative → diary-only** (not extracted).

After processing, ingest marks the day-file `ingested` in its frontmatter. Day-files are permanent;
the extracted atomic note and the frozen day-file coexist (the day-file is the immutable source).

**Vocabulary growth lives in the synthesizer, never ingest.** Ingest applies existing labels or parks
under `needs-label`; it never mints new vocabulary. The synthesizer's `resolve` pass scans all
`needs-label` notes, proposes coherent new labels in batch, and clears the holding label on confirm.

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
