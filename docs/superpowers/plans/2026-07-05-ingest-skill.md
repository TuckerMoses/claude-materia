# ingest Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **This plan is designed for execution in a fresh session** — it is self-contained; do not require the design conversation.

**Goal:** Build the portable `ingest` skill in claude-materia — the vault's intake pipeline: drains closed journal day-files and registered external sources into labeled atomic notes through a propose-confirm gate, with all mechanical work (windows, deltas, dedup, verification, commits) done by shipped scripts.

**Architecture:** A markdown skill at `skills/ingest/` = `SKILL.md` (orchestration + semantics) + `scripts/` (the deterministic shell: `journal-candidates`, `source-delta`, `file-notes`, `ingest-status` — python3 stdlib + PyYAML where noted, vault path always an argument, env-agnostic) + `scripts/tests/` (bash fixture tests). The model owns split/label/title/gate; scripts own everything mechanical. No state file — idempotency is provenance + verbatim-body match. Cascade: `skills/vault/SKILL.md` Identity (closes the last vault-local claim), README row, version `0.12.0 → 0.13.0`.

**Tech Stack:** Markdown skill + python3 scripts (stdlib; `yaml` import only where the file being read is YAML — same availability assumption the vault skill's validation already makes) + bash test harness. `rg` and `git` available at runtime.

**Lean-plan note (agreed with the user):** prose tasks carry NO grep-threshold validations — the task reviewer diffs the deliverable against this plan's content blocks instead (two grep-calibration errata in the prior build; content governs). Scripts carry REAL tests. One spec-coverage check + an adversarial-review coherence gate at ship.

## Global Constraints

Verbatim from the spec (`docs/superpowers/specs/2026-07-05-ingest-skill-design.md`):

- **Job frozen at split → label → file.** Ingest writes no `status`, no `handled`, knows nothing about consumers, never mints vocabulary (applies `status: active` labels only; no fit → `needs-label`, journal-only).
- **Iron rule, fully binding:** extraction copies day-file/source lines **verbatim** — never rewrites. Filing is scripted: md5 verify, abort-on-mismatch, non-empty-body check.
- **Idempotent filing:** a thought is already-filed iff a note exists with the same `source` provenance and identical verbatim body. This primitive carries `--today` re-runs, crash re-runs, and filed-but-unmarked recovery.
- **Ordered commit points:** notes written → verified → *then* `ingested` markers → `last_read` advances → destructive staging moves. Markers are closed-days-only; `--today` extracts without marking.
- **Lens = filter, not classifier.** Out-of-lens source content is out of scope, not parked. `needs-label` is the journal's valve only.
- **Archive-not-delete:** destructive sources' consumed files move to `_machine/logs/ingest/<date>/`, never `rm`.
- **Interactive-only v1:** one batch confirm gate; nothing written before confirmation; headless deferred (BACKLOG.md item, trigger: correction rate ≈ 0).
- **Env-agnostic:** zero `~/.claude/env` refs, zero hardcoded vault paths (`~/Vault`, `/Users/`) in skill or scripts. Binding `~/.claude/ingest.local.md` → `~/.claude/vault.local.md` → fail loudly.
- **All build edits inside claude-materia.** Live `~/Vault` untouched; `~/.claude/plans/vault-design.md` untouched.

---

## File Structure

```
skills/ingest/
├── SKILL.md                     # Task 1
└── scripts/
    ├── journal-candidates       # Task 2 (python3, executable, no extension)
    ├── file-notes               # Task 3
    ├── source-delta             # Task 4
    ├── ingest-status            # Task 4
    └── tests/
        ├── helpers.sh           # Task 2 — fixture + assert helpers
        ├── test-journal-candidates.sh   # Task 2
        ├── test-file-notes.sh           # Task 3
        └── test-source-delta-status.sh  # Task 4
skills/vault/SKILL.md            # Task 5 — Identity cascade (exact replacements)
README.md                        # Task 5 — materia row
.claude-plugin/plugin.json       # Task 5 — 0.12.0 → 0.13.0
```

---

### Task 1: SKILL.md — complete skill body

**Files:**
- Create: `skills/ingest/SKILL.md`

**Interfaces:**
- Produces: the orchestration contract Tasks 2–4's scripts implement. Script names (`journal-candidates`, `source-delta`, `file-notes`, `ingest-status`), the proposals-manifest JSON shape, and the run-log location `_machine/logs/ingest/<run>/` are referenced by later tasks exactly as named here.

- [ ] **Step 1: Write `skills/ingest/SKILL.md` with exactly this content**

````markdown
---
name: ingest
description: "Drain captured thoughts into a knowledge vault as labeled atomic notes — the vault's intake pipeline. Subcommands: ingest [source?] [--today] (drains closed journal day-files and registered external sources: split into atomic thoughts, three-way label-driven extraction against the vault's frozen vocabulary, one propose-confirm gate, scripted verbatim filing; --today additionally extracts from the open day so same-day actionables aren't blocked), status (read-only health: pending day-files, per-source deltas, needs-label backlog, anomalies). Use whenever the user wants to ingest or drain their journal, process captured thoughts or notes into the vault, run the vault intake, pull from a registered ingest source, or check what's pending. Trigger phrases: 'ingest my journal', 'drain the journal', 'process my captures', 'run ingest', 'ingest today', 'ingest status', 'what's pending ingest'."
user-invocable: true
argument-hint: "[source?] [--today] | status"
---

# ingest

Drain captured thoughts into a **populated vault** as labeled atomic notes. The intake half of the
vault's pull architecture: the journal (permanent capture surface) and registered external sources
in, labeled notes out, consumers downstream. Job **frozen** at split → label → file — ingest
writes no `status`, writes no `handled`, knows nothing about consumers, and never mints
vocabulary. New capability = a new consumer skill; ingest is never edited to add one.

## Identity & role

Portable and invariant across vaults: the logic (window the sources, split, classify against the
bank's `when_to_apply` descriptions read **live**, file per the note contract) doesn't depend on
any vault's content. The vocabulary is data, not skill body.

**Deterministic shell, semantic core.** Mechanical work is never freehanded by the model. The
`scripts/` directory owns windows, deltas, dedup, verification, and commit points; the model owns
split boundaries, three-way disposition, labeling, title generation, and the gate conversation.
Every script takes the vault path as an argument — no script knows where any vault lives.

**Hard posture: propose-confirm.** Nothing is written before you confirm at the gate. The model
is a smart suggester, not an autonomous librarian.

## Per-install binding

This skill is portable. It names **no** environment paths in its body. Binding resolves in order:

1. **`~/.claude/ingest.local.md`** — if present, read and follow it: vault pointer, per-machine
   specifics.
2. **`~/.claude/vault.local.md`** — the canonical environment-vault pointer written by
   `vault create`.
3. **Neither exists → fail loudly** ("no vault registered — run `vault create` first, or write
   `~/.claude/ingest.local.md` pointing at a vault"). Never guess a path.

**Every invocation:** resolve the vault → read its `INSTRUCTION.md` + `_machine/labels.yml`
**live** → act. Query per the handshake's preference order; ripgrep is the required floor.

## Subcommands and routing

- `/ingest` — the full drain: journal first (freshest), then every registered source.
- `/ingest <source>` — scope to `journal` or one registered source (path or name).
- `/ingest --today` — the drain, plus extract from the open day **without marking** (see
  "Journal drain").
- `/ingest status` — read-only health. See "status".

**`help` subcommand:** when invoked as `/ingest help`, summarize this skill and its subcommands
from the sections below rather than executing them.

## The drain (both source classes)

1. **Window** — run `scripts/journal-candidates <vault> [--today]` and
   `scripts/source-delta <vault>`: the eligible closed day-files, the open day (if `--today`),
   and each vcs source's changed files + hunks / each destructive source's current contents.
   Deterministic; zero model judgment.
2. **Split + label (subagents — the semantic core).** One subagent per registered source
   (isolation + its lens); journal day-files batched to subagents. Each: split into atomic
   thoughts (sub-bullets stay with their parent; a continuing thought is one thought), apply the
   three-way rule (below), label from **active** bank entries only, derive a short searchable
   title, and emit structured proposals with **verbatim bodies**. Subagents return proposals,
   never file dumps.
3. **Persist proposals** to `_machine/logs/ingest/<run>/proposals.json` *before* the gate — a
   crash mid-review must not lose the analysis. The run log records the vault's jj change-id at
   drain start (whole-run undo stays a one-liner).
4. **ONE batch confirm gate.** Grouped by day-file/source: each proposed note's title, labels,
   disposition, and verbatim body as its own evidence. Batch-friendly:
   approve-all-with-exceptions; per-item relabel / re-split / demote-to-diary / promote;
   conversational corrections. A week's backlog is a five-minute review, not fifty questions.
5. **File (scripted).** `scripts/file-notes <vault> <confirmed-manifest.json>`: cross-proposal
   dedup → idempotent writes → md5 verify (abort-on-mismatch) → **then, in order:** `ingested`
   markers → `last_read` advances → destructive staging moves. Emits a written/skipped report;
   surface it.

## Journal drain

- **Day-file definition (strict):** `journal/YYYY-MM-DD.md`, dated strictly before today, lacking
  `ingested: true`. Anything else in `journal/` is not ingest's business (`status` flags
  non-day-file squatters; relocation is a human refactor, never ingest's).
- **Three-way extraction, label-driven:** per thought — matches active label(s) → extract +
  label; knowledge-worthy but nothing fits → extract + `needs-label` (parked, never dropped; the
  synthesizer's `resolve` drains it); trivial narrative → stays diary-only. Knowledge-worthy is
  label-driven, not significance-driven: affective/state lines extract under their labels so the
  synthesizer can see patterns. The labels you define are the lever.
- **Fields:** split-siblings share `captured:` (= day date) and get Tier-1 factual `related:`
  links to each other — the one link class ingest may auto-create. `created:` = filing date;
  `source: journal/YYYY-MM-DD`; no `status`, no `handled`. Bodies verbatim.
- **Marker = per-file commit point:** `ingested: true` lands only after all of that file's
  confirmed notes are filed and verified. The day-file is never modified beyond the marker — it
  is the permanent diary; the day-file/note duplication is the one sanctioned denormalization.
- **`--today`:** extracts from the open day **without writing the marker** — same-day
  actionables (a morning session-seed) must not wait for tomorrow's drain. Safe under repeat
  runs and tomorrow's closing drain because filing is idempotent (provenance + verbatim-body
  match skips already-extracted thoughts). Known edge, accepted: a thought *edited* after
  extraction re-extracts as a second note; the synthesizer is the designed net.

## Sources drain

- **`track: vcs`:** committed state on the registered branch; process `diff(last_read..HEAD)`.
  Read a changed file whole for awareness; extract **only from changed hunks**. Provenance:
  `source: <remote> <path> @<commit>`. `last_read → HEAD` per-source, only after that source's
  notes are filed.
- **`track: destructive`:** consume current contents; **archive-not-delete** — consumed files
  move to `_machine/logs/ingest/<date>/` (literal `rm` would destroy out-of-lens content that
  was never extracted). Residue in staging = by definition unprocessed; no stored state.
- **Lens = filter, not classifier:** extract only thoughts matching the lens labels (each
  label's `when_to_apply` is the extraction instruction). Out-of-lens content is out of scope —
  it stays in the source, unextracted, never parked. `needs-label` is journal-only: the journal
  is the unfiltered brain-stream; a registered source was pointed here through a deliberate lens.

## status

`scripts/ingest-status <vault>` — read-only, principle 7 (surface on demand, never nag):

- unprocessed closed day-files (count + list)
- per-source pending delta (`last_read..HEAD` commit count)
- `needs-label` backlog size (the synthesizer's queue)
- **marked-then-modified day-files** — a marked file whose mtime postdates its marking run (late
  phone-sync detection net; fix = remove the marker, re-drain — idempotent filing makes that
  duplicate-free)
- journal squatters (non-day-file notes in `journal/` — relocate to `notes/`, manually)

## Invariants (cross-cutting, hard)

- **Propose-confirm only** — nothing written before the gate; v1 is interactive-only (headless
  is a BACKLOG item with a named trigger).
- **Never writes `status`, never writes `handled`** — field ownership per INSTRUCTION.md.
- **Vocabulary frozen** — active labels or `needs-label`; minting is the synthesizer's.
- **Verbatim bodies, scripted filing** — extraction copies; `file-notes` verifies (md5,
  abort-on-mismatch); the model never freehands writes.
- **No state file** — idempotency is provenance + verbatim-body match; rejections need no memory
  (a rejected split stays diary narrative under a marked file).
- **Ordered commit points** — markers/watermarks/moves strictly after verified filing; no
  partial state survives a re-run.
- **Env-agnostic** — binding via `~/.claude/ingest.local.md` → `~/.claude/vault.local.md` →
  loud failure; scripts take the vault path as an argument.
````

- [ ] **Step 2: Commit**

```bash
cd ~/claude-materia && git add skills/ingest/SKILL.md
git commit -m "feat(ingest): SKILL.md — drain orchestration, journal/sources semantics, gate, invariants"
```

*(No grep validation — the task reviewer diffs this file against the block above.)*

---

### Task 2: `scripts/journal-candidates` + test harness

**Files:**
- Create: `skills/ingest/scripts/journal-candidates` (executable)
- Create: `skills/ingest/scripts/tests/helpers.sh`
- Create: `skills/ingest/scripts/tests/test-journal-candidates.sh` (executable)

**Interfaces:**
- Produces: `journal-candidates VAULT [--today]` → JSON `{"closed": ["journal/YYYY-MM-DD.md", ...], "today": "journal/YYYY-MM-DD.md" | null}`. Closed = date strictly < today, no `ingested: true` in frontmatter (files without frontmatter count as unmarked). `today` non-null only with `--today` and the file existing. Consumed by SKILL.md drain step 1 and `ingest-status`.

- [ ] **Step 1: Write `tests/helpers.sh`**

```bash
#!/bin/bash
# Shared fixture + assert helpers for ingest script tests.
set -u
FAILS=0
new_vault() {  # new_vault -> prints path to a throwaway vault skeleton
  local v; v=$(mktemp -d)/vault
  mkdir -p "$v/journal" "$v/notes" "$v/_machine/logs"
  printf 'labels:\n  idea:\n    when_to_apply: "test"\n    status: active\n' > "$v/_machine/labels.yml"
  printf 'sources: []\n' > "$v/_machine/ingest_paths.yml"
  echo "$v"
}
assert_eq() {  # assert_eq LABEL EXPECTED ACTUAL
  if [ "$2" = "$3" ]; then echo "ok - $1"; else echo "FAIL - $1: expected [$2] got [$3]"; FAILS=$((FAILS+1)); fi
}
assert_contains() {  # assert_contains LABEL NEEDLE HAYSTACK
  case "$3" in *"$2"*) echo "ok - $1";; *) echo "FAIL - $1: [$2] not in output"; FAILS=$((FAILS+1));; esac
}
finish() { if [ "$FAILS" -gt 0 ]; then echo "$FAILS FAILURES"; exit 1; else echo "ALL PASS"; fi }
```

- [ ] **Step 2: Write the failing test `tests/test-journal-candidates.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")"; . ./helpers.sh
SCRIPT=../journal-candidates
V=$(new_vault)
TODAY=$(date +%F); OLD1="2026-01-02"; OLD2="2026-01-03"
printf 'morning thought\n' > "$V/journal/$OLD1.md"                             # closed, unmarked, no frontmatter
printf -- '---\ningested: true\n---\nprocessed\n' > "$V/journal/$OLD2.md"      # closed, marked
printf 'today thought\n' > "$V/journal/$TODAY.md"                              # open day
printf 'not a day file\n' > "$V/journal/some-topical-note.md"                  # squatter
OUT=$(python3 "$SCRIPT" "$V")
assert_contains "closed includes unmarked past"   "journal/$OLD1.md" "$OUT"
assert_eq "marked past excluded" "" "$(echo "$OUT" | grep -o "$OLD2" || true)"
assert_eq "today excluded without flag" "" "$(echo "$OUT" | grep -o "$TODAY" || true)"
assert_eq "squatter excluded" "" "$(echo "$OUT" | grep -o "some-topical" || true)"
OUT2=$(python3 "$SCRIPT" "$V" --today)
assert_contains "today included with --today" "journal/$TODAY.md" "$OUT2"
OUT3=$(python3 "$SCRIPT" "/nonexistent/vault" 2>&1 || true)
assert_contains "loud failure on bad vault" "not found" "$OUT3"
finish
```

- [ ] **Step 3: Run it — expect failure** (`bash tests/test-journal-candidates.sh` → errors: script missing)

- [ ] **Step 4: Write `scripts/journal-candidates`**

```python
#!/usr/bin/env python3
"""List journal day-files eligible for ingest.

Usage: journal-candidates VAULT_PATH [--today]
Emits JSON: {"closed": ["journal/YYYY-MM-DD.md", ...], "today": "journal/..." | null}
closed = date strictly before today, no `ingested: true` marker (no frontmatter = unmarked).
today key is non-null only when --today is passed and today's file exists.
"""
import json, re, sys
from datetime import date
from pathlib import Path

DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})\.md$')

def is_marked(p: Path) -> bool:
    text = p.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        return False
    end = text.find('\n---', 4)
    if end == -1:
        return False
    return re.search(r'^ingested:\s*true\s*$', text[4:end], re.M) is not None

def main():
    argv = sys.argv[1:]
    today_flag = '--today' in argv
    argv = [a for a in argv if a != '--today']
    if len(argv) != 1:
        sys.exit('usage: journal-candidates VAULT_PATH [--today]')
    vault = Path(argv[0]).expanduser()
    journal = vault / 'journal'
    if not journal.is_dir():
        sys.exit(f'vault not found (no journal/ under {vault})')
    closed, today_file = [], None
    t = date.today()
    for p in sorted(journal.iterdir()):
        m = DAY.match(p.name)
        if not m:
            continue
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            continue
        if d < t and not is_marked(p):
            closed.append(f'journal/{p.name}')
        elif d == t and today_flag:
            today_file = f'journal/{p.name}'
    print(json.dumps({'closed': closed, 'today': today_file}, indent=2))

if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run test — expect ALL PASS.** Also `chmod +x` both the script and the test.

- [ ] **Step 6: Commit**

```bash
cd ~/claude-materia && git add skills/ingest/scripts
git commit -m "feat(ingest): journal-candidates script + test harness (strict day-file window, --today)"
```

---

### Task 3: `scripts/file-notes` — the serial filer (iron-rule enforcer)

**Files:**
- Create: `skills/ingest/scripts/file-notes` (executable)
- Create: `skills/ingest/scripts/tests/test-file-notes.sh` (executable)

**Interfaces:**
- Consumes: the confirmed-proposals manifest (JSON, shape below), produced by the gate.
- Produces: notes in `<vault>/notes/`, markers/watermarks/moves, and a JSON report `{"written": [...], "skipped": [...], "marked": [...], "advanced": [...], "moved": [...]}` on stdout. Exit 1 with a clear message on any verify failure, BEFORE any commit point.

Manifest shape (documented in the script docstring; the SKILL.md gate produces it):

```json
{
  "notes": [{"title": "…", "labels": ["idea"], "created": "2026-07-05", "captured": "2026-07-01",
             "source": "journal/2026-07-01", "related": ["[[sibling-note]]"], "body": "verbatim text"}],
  "mark_ingested": ["journal/2026-07-01.md"],
  "advance": [{"path": "/abs/source/repo", "last_read": "abc1234"}],
  "archive_moves": [{"from": "/abs/staging/file.md", "date": "2026-07-05"}]
}
```

- [ ] **Step 1: Write the failing test `tests/test-file-notes.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")"; . ./helpers.sh
SCRIPT=../file-notes
V=$(new_vault)
printf 'raw day text\n' > "$V/journal/2026-01-02.md"
MF=$(mktemp)
cat > "$MF" <<EOF
{"notes": [{"title": "Test Thought", "labels": ["idea"], "created": "2026-07-05",
  "captured": "2026-01-02", "source": "journal/2026-01-02", "related": [], "body": "A verbatim thought."}],
 "mark_ingested": ["journal/2026-01-02.md"], "advance": [], "archive_moves": []}
EOF
OUT=$(python3 "$SCRIPT" "$V" "$MF")
assert_contains "note written" "test-thought.md" "$OUT"
assert_eq "body verbatim" "A verbatim thought." "$(sed -n '/^---$/,/^---$/!p' "$V/notes/test-thought.md" | sed '/^$/d')"
assert_contains "no status field" "" "$(grep -c '^status:' "$V/notes/test-thought.md" | grep -x 0)"
assert_contains "marker written" "ingested: true" "$(cat "$V/journal/2026-01-02.md")"
assert_contains "raw text preserved under marker" "raw day text" "$(cat "$V/journal/2026-01-02.md")"
# Idempotent re-run: same manifest → skipped, not duplicated
OUT2=$(python3 "$SCRIPT" "$V" "$MF")
assert_contains "re-run skips by source+body" '"skipped"' "$OUT2"
assert_eq "no duplicate file" "1" "$(ls "$V/notes" | grep -c 'test-thought')"
# Empty-body rejection (iron rule)
MF2=$(mktemp)
cat > "$MF2" <<EOF
{"notes": [{"title": "Empty", "labels": ["idea"], "created": "2026-07-05",
  "captured": "2026-01-02", "source": "journal/2026-01-02", "related": [], "body": ""}],
 "mark_ingested": [], "advance": [], "archive_moves": []}
EOF
if python3 "$SCRIPT" "$V" "$MF2" >/dev/null 2>&1; then echo "FAIL - empty body accepted"; FAILS=$((FAILS+1)); else echo "ok - empty body aborts"; fi
finish
```

- [ ] **Step 2: Run it — expect failure** (script missing)

- [ ] **Step 3: Write `scripts/file-notes`**

```python
#!/usr/bin/env python3
"""Serial filer: write confirmed notes idempotently, verify, then commit watermarks.

Usage: file-notes VAULT_PATH MANIFEST_JSON
Order (hard): write+verify ALL notes -> ingested markers -> last_read advances -> staging moves.
Aborts (exit 1) before any commit point on: empty body, md5 mismatch after write.
Idempotency: a note is already-filed iff an existing note has identical `source:` AND identical body.
"""
import hashlib, json, re, shutil, sys
from pathlib import Path

def slugify(title: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return s[:80] or 'untitled'

def md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def split_note(text: str):
    """Return (frontmatter, body) for a note file's text."""
    if not text.startswith('---\n'):
        return '', text
    end = text.find('\n---\n', 4)
    if end == -1:
        return '', text
    return text[4:end], text[end + 5:].lstrip('\n')

def existing_match(notes_dir: Path, source: str, body: str):
    """Path of an existing note with this exact source + verbatim body, else None."""
    for p in notes_dir.glob('*.md'):
        fm, b = split_note(p.read_text(encoding='utf-8'))
        if re.search(r'^source:\s*' + re.escape(source) + r'\s*$', fm, re.M) and b.rstrip('\n') == body.rstrip('\n'):
            return p
    return None

def emit_frontmatter(n: dict) -> str:
    lines = ['---', f'title: "{n["title"]}"', f'labels: [{", ".join(n["labels"])}]',
             f'created: {n["created"]}', f'captured: {n["captured"]}', f'source: {n["source"]}']
    if n.get('related'):
        lines.append('related: [' + ', '.join(f'"{r}"' for r in n['related']) + ']')
    lines.append('---')
    return '\n'.join(lines) + '\n\n'

def main():
    if len(sys.argv) != 3:
        sys.exit('usage: file-notes VAULT_PATH MANIFEST_JSON')
    vault = Path(sys.argv[1]).expanduser()
    notes_dir = vault / 'notes'
    if not notes_dir.is_dir():
        sys.exit(f'vault not found (no notes/ under {vault})')
    manifest = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    report = {'written': [], 'skipped': [], 'marked': [], 'advanced': [], 'moved': []}

    # Phase 1 — write + verify every note (no commit points yet).
    for n in manifest.get('notes', []):
        body = n['body']
        if not body.strip():
            sys.exit(f'ABORT (iron rule): empty body for "{n["title"]}" — nothing committed')
        if existing_match(notes_dir, n['source'], body):
            report['skipped'].append(n['title'])
            continue
        before = md5(body.rstrip('\n'))
        dest, i = notes_dir / f'{slugify(n["title"])}.md', 2
        while dest.exists():
            dest, i = notes_dir / f'{slugify(n["title"])}-{i}.md', i + 1
        dest.write_text(emit_frontmatter(n) + body.rstrip('\n') + '\n', encoding='utf-8')
        _, back = split_note(dest.read_text(encoding='utf-8'))
        after = md5(back.rstrip('\n'))
        if before != after or (len(body) > 0 and len(back) == 0):
            sys.exit(f'ABORT (iron rule): body verify failed for {dest.name} '
                     f'(before md5 {before}, after md5 {after}) — no watermarks committed')
        report['written'].append(str(dest.relative_to(vault)))

    # Phase 2 — commit points, strictly ordered.
    for rel in manifest.get('mark_ingested', []):
        p = vault / rel
        text = p.read_text(encoding='utf-8')
        if re.search(r'^ingested:\s*true\s*$', text[4:text.find('\n---', 4)] if text.startswith('---\n') else '', re.M):
            pass
        elif text.startswith('---\n'):
            p.write_text(text.replace('---\n', '---\ningested: true\n', 1), encoding='utf-8')
        else:
            p.write_text('---\ningested: true\n---\n' + text, encoding='utf-8')
        report['marked'].append(rel)
    if manifest.get('advance'):
        import yaml
        ip = vault / '_machine' / 'ingest_paths.yml'
        data = yaml.safe_load(ip.read_text(encoding='utf-8')) or {'sources': []}
        for adv in manifest['advance']:
            for s in data.get('sources') or []:
                if s.get('path') == adv['path']:
                    s['last_read'] = adv['last_read']
                    report['advanced'].append(adv['path'])
        ip.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    for mv in manifest.get('archive_moves', []):
        dest_dir = vault / '_machine' / 'logs' / 'ingest' / mv['date']
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(mv['from'], dest_dir / Path(mv['from']).name)
        report['moved'].append(mv['from'])

    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test — expect ALL PASS.** `chmod +x` script + test.

- [ ] **Step 5: Commit**

```bash
cd ~/claude-materia && git add skills/ingest/scripts
git commit -m "feat(ingest): file-notes serial filer — idempotent verbatim filing, md5 verify, ordered commit points"
```

---

### Task 4: `scripts/source-delta` + `scripts/ingest-status`

**Files:**
- Create: `skills/ingest/scripts/source-delta` (executable)
- Create: `skills/ingest/scripts/ingest-status` (executable)
- Create: `skills/ingest/scripts/tests/test-source-delta-status.sh` (executable)

**Interfaces:**
- `source-delta VAULT` → JSON list per registered source: `{"path", "track", "lens", "head", "files": [...], "hunks": {file: unified-diff-text}}` (vcs: `last_read..HEAD`, `-U0`; destructive: current file list, no hunks/head). Empty registry → `[]`.
- `ingest-status VAULT` → human-readable text: pending day-files, per-source delta counts, `needs-label` count, marked-then-modified flags (from run logs' timestamps vs. file mtime; silent-skip with a note when no run logs exist), squatter count.

- [ ] **Step 1: Write the failing test `tests/test-source-delta-status.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")"; . ./helpers.sh
V=$(new_vault)
# --- source-delta: vcs source with one new commit past last_read ---
REPO=$(mktemp -d)/src && mkdir -p "$REPO" && git -C "$REPO" init -q
printf 'first\n' > "$REPO/a.md" && git -C "$REPO" add . && git -C "$REPO" commit -qm one
BASE=$(git -C "$REPO" rev-parse HEAD)
printf 'first\nsecond\n' > "$REPO/a.md" && git -C "$REPO" commit -qam two
cat > "$V/_machine/ingest_paths.yml" <<EOF
sources:
  - path: $REPO
    track: vcs
    lens: [idea]
    last_read: $BASE
EOF
OUT=$(python3 ../source-delta "$V")
assert_contains "changed file listed" "a.md" "$OUT"
assert_contains "hunk contains new line" "second" "$OUT"
# --- ingest-status: pending day-file, needs-label note, squatter ---
printf 'unprocessed\n' > "$V/journal/2026-01-02.md"
printf 'squat\n' > "$V/journal/topical-squatter.md"
printf -- '---\ntitle: "P"\nlabels: [needs-label]\nsource: journal/2026-01-01\n---\n\nparked\n' > "$V/notes/p.md"
S=$(python3 ../ingest-status "$V")
assert_contains "pending day-file" "2026-01-02" "$S"
assert_contains "needs-label count" "needs-label: 1" "$S"
assert_contains "squatter flagged" "1 non-day-file" "$S"
assert_contains "source delta count" "1 commit" "$S"
finish
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Write `scripts/source-delta`**

```python
#!/usr/bin/env python3
"""Emit pending deltas for registered ingest sources.

Usage: source-delta VAULT_PATH
vcs: changed files + -U0 hunks for last_read..HEAD (git; error clearly on non-git).
destructive: current file listing. Empty registry -> [].
"""
import json, subprocess, sys
from pathlib import Path
import yaml

def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout

def main():
    if len(sys.argv) != 2:
        sys.exit('usage: source-delta VAULT_PATH')
    vault = Path(sys.argv[1]).expanduser()
    ip = vault / '_machine' / 'ingest_paths.yml'
    if not ip.is_file():
        sys.exit(f'vault not found (no _machine/ingest_paths.yml under {vault})')
    data = yaml.safe_load(ip.read_text(encoding='utf-8')) or {}
    out = []
    for s in data.get('sources') or []:
        src = Path(s['path']).expanduser()
        entry = {'path': str(src), 'track': s['track'], 'lens': s.get('lens', [])}
        if s['track'] == 'vcs':
            if not (src / '.git').exists():
                sys.exit(f'vcs source is not a git repo: {src}')
            head = sh(['git', 'rev-parse', 'HEAD'], src).strip()
            last = s.get('last_read') or head
            files = [f for f in sh(['git', 'diff', '--name-only', f'{last}..{head}'], src).splitlines() if f]
            entry.update(head=head, files=files,
                         hunks={f: sh(['git', 'diff', '-U0', f'{last}..{head}', '--', f], src) for f in files})
        else:
            entry['files'] = sorted(str(p) for p in src.rglob('*') if p.is_file())
        out.append(entry)
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Write `scripts/ingest-status`**

```python
#!/usr/bin/env python3
"""Read-only vault intake health. Usage: ingest-status VAULT_PATH"""
import json, re, subprocess, sys
from pathlib import Path
import yaml

DAY = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')

def main():
    if len(sys.argv) != 2:
        sys.exit('usage: ingest-status VAULT_PATH')
    vault = Path(sys.argv[1]).expanduser()
    if not (vault / 'journal').is_dir():
        sys.exit(f'vault not found (no journal/ under {vault})')
    here = Path(__file__).resolve().parent
    cand = json.loads(subprocess.run(
        [sys.executable, str(here / 'journal-candidates'), str(vault)],
        capture_output=True, text=True, check=True).stdout)
    print(f"pending closed day-files: {len(cand['closed'])}"
          + (f" ({', '.join(p.split('/')[-1] for p in cand['closed'])})" if cand['closed'] else ''))
    data = yaml.safe_load((vault / '_machine' / 'ingest_paths.yml').read_text(encoding='utf-8')) or {}
    for s in data.get('sources') or []:
        if s['track'] == 'vcs' and s.get('last_read'):
            n = subprocess.run(['git', 'rev-list', '--count', f"{s['last_read']}..HEAD"],
                               cwd=Path(s['path']).expanduser(), capture_output=True, text=True)
            print(f"source {s['path']}: {n.stdout.strip() or '?'} commit(s) pending")
        else:
            print(f"source {s['path']}: destructive (drain to consume)")
    needs = sum(1 for p in (vault / 'notes').glob('*.md')
                if re.search(r'^labels:.*\bneeds-label\b', p.read_text(encoding='utf-8'), re.M))
    print(f'needs-label: {needs}')
    squat = [p.name for p in (vault / 'journal').iterdir() if p.suffix == '.md' and not DAY.match(p.name)]
    if squat:
        print(f'{len(squat)} non-day-file note(s) in journal/ — relocate to notes/ (manual refactor): '
              + ', '.join(sorted(squat)[:5]) + ('…' if len(squat) > 5 else ''))
    logs = vault / '_machine' / 'logs' / 'ingest'
    flagged = []
    if logs.is_dir():
        for run in logs.iterdir():
            rj = run / 'run.json'
            if not rj.is_file():
                continue
            info = json.loads(rj.read_text(encoding='utf-8'))
            for rel in info.get('marked', []):
                p = vault / rel
                if p.is_file() and p.stat().st_mtime > info.get('ts', 0) + 60:
                    flagged.append(rel)
    if flagged:
        print('modified AFTER ingest (late sync?): ' + ', '.join(sorted(set(flagged)))
              + ' — remove the marker and re-drain (idempotent, duplicate-free)')
    elif not logs.is_dir():
        print('(no run logs yet — modified-after-ingest detection starts with the first drain)')

if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run test — expect ALL PASS.** `chmod +x` both scripts + test. Also re-run Tasks 2–3 tests (regression).

- [ ] **Step 6: Commit**

```bash
cd ~/claude-materia && git add skills/ingest/scripts
git commit -m "feat(ingest): source-delta + ingest-status scripts with fixture tests"
```

---

### Task 5: Cascade + ship (coverage, coherence gate, README, version)

**Files:**
- Modify: `skills/vault/SKILL.md` (two exact replacements)
- Modify: `README.md`, `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: the shipped v0.13.0 plugin.

- [ ] **Step 1: vault/SKILL.md Identity — exact replacement.** Replace:

```markdown
- **Content-dependent → vault-local (NOT here).** Ongoing-ingest *classification* depends on a
  vault's derived vocabulary; it belongs in a vault-local skill.
- **Consumers that read the vocabulary live → their own portable skills.** The synthesizer
  (`claude-materia:synthesizer`) is invariant logic — it blocks on labels, judges relatedness, and
  batch-mints vocabulary by reading `labels.yml`/`INSTRUCTION.md` live at runtime. The
  content-dependence is in the *data*, not the *skill*.
```

with:

```markdown
- **Consumers and processors that read the vocabulary live → their own portable skills.** The
  synthesizer (`claude-materia:synthesizer`) and ongoing ingest (`claude-materia:ingest`) are
  invariant logic — they classify, relate, and mint against `labels.yml`/`INSTRUCTION.md` read
  live at runtime. The content-dependence is in the *data*, not the *skill*. Nothing vault-local
  remains.
```

- [ ] **Step 2: vault/SKILL.md discuss line — exact replacement.** Replace:

```markdown
label-based pool, how the contracts fit together, when a vault-local skill (ongoing-ingest) or a
separate consumer skill (the synthesizer) is warranted vs. an addition here.
```

with:

```markdown
label-based pool, how the contracts fit together, when a separate consumer/processor skill (the
synthesizer, ingest) is warranted vs. an addition here.
```

- [ ] **Step 3: Spec-coverage check** — every spec § maps to shipped text:

```bash
cd ~/claude-materia
echo "§1 identity:";   grep -qi 'split → label → file' skills/ingest/SKILL.md && echo OK
echo "§2 surface:";    grep -q '/ingest status' skills/ingest/SKILL.md && grep -q -- '--today' skills/ingest/SKILL.md && echo OK
echo "§3 journal:";    grep -qi 'three-way' skills/ingest/SKILL.md && grep -q 'ingested: true' skills/ingest/SKILL.md && echo OK
echo "§4 sources:";    grep -qi 'archive-not-delete' skills/ingest/SKILL.md && grep -qi 'filter, not classifier' skills/ingest/SKILL.md && echo OK
echo "§5 gate:";       grep -qi 'batch confirm gate' skills/ingest/SKILL.md && echo OK
echo "§6 idempotent:"; grep -qi 'provenance + verbatim-body' skills/ingest/SKILL.md && echo OK
echo "§7 scripts:";    ls skills/ingest/scripts/journal-candidates skills/ingest/scripts/source-delta skills/ingest/scripts/file-notes skills/ingest/scripts/ingest-status >/dev/null && echo OK
echo "§8 binding:";    grep -q 'ingest.local.md' skills/ingest/SKILL.md && grep -q 'vault.local.md' skills/ingest/SKILL.md && echo OK
echo "§9 cascade:";    grep -q 'claude-materia:ingest' skills/vault/SKILL.md && echo OK
echo "env-agnostic:";  grep -rc '~/.claude/env\|~/Vault\|/Users/' skills/ingest/ | grep -v ':0' | wc -l | grep -x 0 && echo OK
```

Expected: `OK` after every line. If a grep misses, check for a legitimate line-span before treating it as missing content — report, don't reflow.

- [ ] **Step 4: Coherence gate.** Run `/claude-materia:adversarial-review run default:coherence` scoped to the branch diff (skills/ingest/**, skills/vault/SKILL.md). Fix Critical/Important findings, commit as `fix(ingest): coherence-review findings`, re-run until clean.

- [ ] **Step 5: README row** (append after the synthesizer row):

```markdown
| **ingest** | Command | Vault intake pipeline. Drains closed journal day-files (three-way label-driven extraction; `--today` for same-day actionables) and registered `ingest_paths` sources (vcs hunks-delta or destructive archive-not-delete drain, lens-filtered) into labeled atomic notes through one propose-confirm gate. Deterministic shell: shipped scripts own windows, deltas, idempotent verbatim filing (md5-verified), and ordered commit points. Never writes `status`/`handled`; never mints vocabulary. Binds via `~/.claude/ingest.local.md` → `~/.claude/vault.local.md`. |
```

- [ ] **Step 6: Version bump** `.claude-plugin/plugin.json`: `"0.12.0"` → `"0.13.0"`. Validate: `python3 -c "import json; v=json.load(open('.claude-plugin/plugin.json'))['version']; assert v=='0.13.0', v; print('version', v)"`

- [ ] **Step 7: Run ALL script tests one final time** (`for t in skills/ingest/scripts/tests/test-*.sh; do bash "$t" || exit 1; done` → every suite ALL PASS), then commit:

```bash
cd ~/claude-materia && git add README.md .claude-plugin/plugin.json skills/vault/SKILL.md
git commit -m "feat(ingest): ship skill — vault-local claim closed, README entry, version bump"
```

---

## Self-Review

**Spec coverage:** §1 → Task 1 (identity, frozen job). §2 → Task 1 (routing) + Task 4 (`ingest-status`). §3 → Task 1 (journal semantics) + Task 2 (window script) + Task 3 (marker mechanics, `--today` idempotency). §4 → Task 1 (sources semantics) + Task 4 (`source-delta`) + Task 3 (`advance`/`archive_moves`). §5 → Task 1 (gate; headless deferred → BACKLOG.md, already committed). §6 → Task 3 (idempotent filing, ordered commits, abort paths) + Task 4 (modified-after-ingest net). §7 → Tasks 2–4 (all four scripts + tests). §8 → Task 1 (binding). §9 → Task 5 (cascades, README, version). §10 out-of-scope items are in BACKLOG.md, not planned — correct.

**Placeholder scan:** none. All script code is complete and runnable; all SKILL.md content verbatim.

**Name/type consistency:** script names identical across Task 1's SKILL.md references, Tasks 2–4 files, and Task 5's coverage check. Manifest keys (`notes`, `mark_ingested`, `advance`, `archive_moves`) identical between Task 3's docstring/test and SKILL.md's drain step 5. Run-log location `_machine/logs/ingest/` identical in SKILL.md, `file-notes` (archive moves), and `ingest-status` (detection). Binding chain identical in Task 1 and Task 5's README row. Version `0.12.0 → 0.13.0` consistent.

## Execution Handoff

Execute in a **fresh session** (agreed): open a new Claude Code session in `~/claude-materia` and use **superpowers:subagent-driven-development** with this plan. The design conversation is not needed — this plan + the spec are the complete inputs.
