# Ingest Atomic Commits + Derived CHANGELOG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every ingest run an atomic, individually-revertible jj commit whose description carries the run's changelog entry, with `CHANGELOG.md` as a derived render — per the spec at `docs/superpowers/specs/2026-07-30-ingest-atomic-commits-design.md` (@ 630a2e8, decision-complete).

**Architecture:** A new deterministic script `commit-run` (Python, like its siblings) assembles a path-scoped fileset from `file-notes`' report, commits it with the model-rendered `entry.md` as the commit description body, and regenerates the VCS-ignored `CHANGELOG.md` from `jj log`. `file-notes` gains vault-relative `skipped`/`moved` reporting. The ingest SKILL.md gains drain step 6 and the near-miss contract; the vault skill's assets gain the ignore rules.

**Tech Stack:** Python 3 stdlib (`json`, `re`, `subprocess`, `pathlib`), jj 0.43 (colocated git), bash test harness (`scripts/tests/helpers.sh` pattern).

## Global Constraints

- **Repo:** all paths below are relative to `/Users/johnmoses/claude-materia` unless they start with `~/Vault`.
- **Env-agnostic (spec §3):** every script takes the vault path as an argument; no script knows where any vault lives. `commit-run` must work when invoked from any cwd — it runs `jj` with `cwd=<vault>`.
- **Iron rule (spec §3):** note bodies are never modified. `commit-run` touches only frontmatter markers (rollback) and `CHANGELOG.md` (derived).
- **`CHANGELOG.md` is never in any commit fileset** (spec §2.4/§2.6). It is derived and VCS-ignored.
- **Verified jj 0.43 behaviors** (live-tested 2026-08-14): (a) `jj commit [FILESETS] -m` finalizes only the named paths, rest moves to a fresh working copy; (b) **`jj commit <absent-path>` succeeds with rc=0 and creates an EMPTY commit** — therefore `commit-run` MUST pre-flight that every fileset path exists and MUST verify the created commit is non-empty; (c) `jj log --no-graph -r 'description(glob:"ingest(*")' -T 'description ++ "\0"'` emits full multiline descriptions, newest first, NUL-separated.
- **Tests:** bash, sourcing `scripts/tests/helpers.sh` (`new_vault`, `assert_eq`, `assert_contains`, `finish`). Pin jj identity per-repo in fixtures (`jj config set --repo user.name/user.email`) — never depend on global identity.
- **Exit codes:** `commit-run` exits 0 on success AND on no-op (a no-op is the loop's most common healthy outcome — spec §5); non-zero only on failure, after rolling back markers where applicable.
- **Commit messages in this repo:** conventional prefix (`feat:`, `test:`, `docs:`), and every commit is scoped to the task's files — `plugins/vault/skills/ingest/SKILL.md` and `plugins/vault/skills/synthesizer/SKILL.md` carry **pre-existing uncommitted edits by Tucker** (the 2026-07-25 label-semantics invariant, documented in BACKLOG). See Task 5 Step 1 before touching SKILL.md. Never `git add -A`.

---

### Task 1: `file-notes` reports vault paths for `skipped` and `moved`

The commit fileset (spec §2.4) needs `skipped` as vault-relative paths (failure-recovery sweep) and needs the vault-side destination of archive moves. Today `skipped` holds note *titles* and `moved` holds the *external source* path.

**Files:**
- Modify: `plugins/vault/skills/ingest/scripts/file-notes` (lines 7, 59–61, 95–104)
- Test: `plugins/vault/skills/ingest/scripts/tests/test-file-notes.sh`

**Interfaces:**
- Produces (consumed by Tasks 2–3): `report.json` shape `{"written": [vault-rel...], "skipped": [vault-rel...], "marked": [vault-rel...], "advanced": [source-registry paths — NOT vault paths], "moved": [vault-rel dest under _machine/logs/ingest/<date>/...]}`. `advanced` semantics unchanged (registry keys); the vault file behind an advance is always `_machine/ingest_paths.yml`.

- [ ] **Step 1: Extend the test to expect paths**

In `test-file-notes.sh`, replace line 20:

```bash
assert_contains "re-run skips by source+body" '"skipped"' "$OUT2"
```

with:

```bash
assert_contains "re-run skips by source+body, as vault-relative path" '"notes/test-thought.md"' "$OUT2"
```

and after line 43 (`second archived file uniquified...`), add:

```bash
assert_contains "moved reported as vault-relative dest" '"_machine/logs/ingest/2026-07-05/notes.md"' "$OUT3"
```

which requires capturing output at line 40: change `python3 "$SCRIPT" "$V" "$MF3" >/dev/null` to `OUT3=$(python3 "$SCRIPT" "$V" "$MF3")`.

- [ ] **Step 2: Run to verify the new assertions fail**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-file-notes.sh`
Expected: 2 FAIL lines (skipped still a title; moved still an external path), exit 1.

- [ ] **Step 3: Implement**

In `file-notes`, replace lines 59–61:

```python
        if existing_match(notes_dir, n['source'], body):
            report['skipped'].append(n['title'])
            continue
```

with:

```python
        m = existing_match(notes_dir, n['source'], body)
        if m:
            report['skipped'].append(str(m.relative_to(vault)))
            continue
```

and replace line 104:

```python
        report['moved'].append(str(src))
```

with:

```python
        report['moved'].append(str(dest.relative_to(vault)))
```

Update the docstring line 7 to: `Idempotency: a note is already-filed iff an existing note has identical 'source:' AND identical body; skipped/moved are reported as vault-relative paths (commit-fileset contract).`

- [ ] **Step 4: Run tests to verify they pass**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-file-notes.sh`
Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/scripts/file-notes plugins/vault/skills/ingest/scripts/tests/test-file-notes.sh
git commit -m "feat(vault): file-notes reports skipped/moved as vault-relative paths"
```

---

### Task 2: `commit-run` core — validate, guard, commit, render

**Files:**
- Create: `plugins/vault/skills/ingest/scripts/commit-run` (mode `755`, like siblings)
- Create: `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`

**Interfaces:**
- Consumes: Task 1's `report.json` shape; `run.json` with integer fields `filed`, `day_files`, `parked` (written by drain step 5, Task 5); `entry.md` (model-rendered, starts with `## <run-id> · <mode>`, contains NO `---` separator lines).
- Produces: CLI `commit-run VAULT REPORT_JSON ENTRY_MD RUN_ID MODE` (exit 0 success/no-op, 1 failure) and `commit-run --regen VAULT`; function seams `regen(vault)`, `unmark(vault, rels)` used by Tasks 3–4. Commit description = `ingest(<mode>): <run-id> — <N> notes, <M> days, <P> parked` + blank line + `entry.md` verbatim.

- [ ] **Step 1: Write the test file with core-path tests**

Create `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"; . ./helpers.sh
SCRIPT=$(cd .. && pwd)/commit-run

jj_vault() {  # new_vault + colocated jj repo with pinned identity
  local v; v=$(new_vault)
  (cd "$v" && jj git init --colocate --quiet . >/dev/null 2>&1 \
    && jj config set --repo user.name test >/dev/null 2>&1 \
    && jj config set --repo user.email test@test.invalid >/dev/null 2>&1)
  echo "$v"
}

mk_run() {  # mk_run VAULT RUN_ID MODE — a complete fixture run's on-disk state
  local v=$1 id=$2 mode=$3 rd="$1/_machine/logs/ingest/$2"
  mkdir -p "$rd"
  printf -- '---\ningested: true\n---\nday text\n' > "$v/journal/2026-01-02.md"
  printf -- '---\ntitle: "T"\nlabels: [idea]\n---\na verbatim body\n' > "$v/notes/t.md"
  printf '{"run": "%s", "ts": 1, "filed": 1, "day_files": 1, "parked": 0, "diary_only": 0, "skipped": 0, "marked": ["journal/2026-01-02.md"]}\n' "$id" > "$rd/run.json"
  printf '[]\n' > "$rd/proposals.json"
  printf '## %s · %s\n**1 filed** from 1 day-file\n\n### Filed\n- **T** — `idea`\n' "$id" "$mode" > "$rd/entry.md"
  printf '{"written": ["notes/t.md"], "marked": ["journal/2026-01-02.md"], "advanced": [], "moved": [], "skipped": []}\n' > "$rd/report.json"
  if [ "$mode" = interactive ]; then printf '{}\n' > "$rd/confirmed-manifest.json"; fi
}

# --- happy path (silent), invoked from OUTSIDE the vault (anchoring, spec f-o-1-12) ---
V=$(jj_vault); mk_run "$V" 2026-01-03-1 silent
printf 'unrelated dirt\n' > "$V/journal/2026-01-03.md"   # today's journal — must NOT be committed
OUT=$(cd /tmp && python3 "$SCRIPT" "$V" "$V/_machine/logs/ingest/2026-01-03-1/report.json" \
  "$V/_machine/logs/ingest/2026-01-03-1/entry.md" 2026-01-03-1 silent 2>&1); RC=$?
assert_eq "happy path exits 0" "0" "$RC"
LOG=$(cd "$V" && jj log --no-graph -r 'description(glob:"ingest(*")' -T 'description')
assert_contains "subject line composed from run.json counts" "ingest(silent): 2026-01-03-1 — 1 notes, 1 days, 0 parked" "$LOG"
assert_contains "entry body carried in description" "### Filed" "$LOG"
FILES=$(cd "$V" && jj log --no-graph -r @- -T '' --stat)
assert_contains "note in commit" "notes/t.md" "$FILES"
assert_contains "run-log sublist in commit" "run.json" "$FILES"
case "$FILES" in *"journal/2026-01-03.md"*) echo "FAIL - unrelated dirt swept"; FAILS=$((FAILS+1));; *) echo "ok - unrelated dirt survives";; esac
case "$FILES" in *"CHANGELOG.md"*) echo "FAIL - CHANGELOG in fileset"; FAILS=$((FAILS+1));; *) echo "ok - CHANGELOG not in fileset";; esac
assert_contains "CHANGELOG rendered with header" "# Vault Changelog" "$(cat "$V/CHANGELOG.md")"
assert_contains "CHANGELOG rendered with entry" "## 2026-01-03-1 · silent" "$(cat "$V/CHANGELOG.md")"
assert_contains "renderer owns separators" "---" "$(cat "$V/CHANGELOG.md")"

# --- interactive mode includes the manifest; silent list omits it ---
V2=$(jj_vault); mk_run "$V2" 2026-01-04-1 interactive
python3 "$SCRIPT" "$V2" "$V2/_machine/logs/ingest/2026-01-04-1/report.json" \
  "$V2/_machine/logs/ingest/2026-01-04-1/entry.md" 2026-01-04-1 interactive >/dev/null 2>&1
FILES2=$(cd "$V2" && jj log --no-graph -r @- -T '' --stat)
assert_contains "interactive fileset includes confirmed-manifest" "confirmed-manifest.json" "$FILES2"

# --- mode mismatch: silent claimed but manifest present ---
V3=$(jj_vault); mk_run "$V3" 2026-01-05-1 interactive
if python3 "$SCRIPT" "$V3" "$V3/_machine/logs/ingest/2026-01-05-1/report.json" \
  "$V3/_machine/logs/ingest/2026-01-05-1/entry.md" 2026-01-05-1 silent >/dev/null 2>&1; then
  echo "FAIL - mode mismatch accepted"; FAILS=$((FAILS+1)); else echo "ok - mode mismatch rejected"; fi

# --- no-op: empty touched-path set -> exit 0, no commit, no CHANGELOG ---
V4=$(jj_vault); mk_run "$V4" 2026-01-06-1 silent
printf '{"written": [], "marked": [], "advanced": [], "moved": [], "skipped": ["notes/t.md"]}\n' \
  > "$V4/_machine/logs/ingest/2026-01-06-1/report.json"
OUT4=$(python3 "$SCRIPT" "$V4" "$V4/_machine/logs/ingest/2026-01-06-1/report.json" \
  "$V4/_machine/logs/ingest/2026-01-06-1/entry.md" 2026-01-06-1 silent 2>&1); RC4=$?
assert_eq "no-op exits 0 (skipped alone does not commit)" "0" "$RC4"
assert_eq "no-op creates no ingest commit" "" "$(cd "$V4" && jj log --no-graph -r 'description(glob:"ingest(*")' -T 'description')"
if [ -f "$V4/CHANGELOG.md" ]; then echo "FAIL - no-op regenerated CHANGELOG"; FAILS=$((FAILS+1)); else echo "ok - no regen on no-op"; fi

# --- pre-flight: fileset path missing on disk -> abort BEFORE committing (jj would silently empty-commit) ---
V5=$(jj_vault); mk_run "$V5" 2026-01-07-1 silent
rm "$V5/notes/t.md"
if python3 "$SCRIPT" "$V5" "$V5/_machine/logs/ingest/2026-01-07-1/report.json" \
  "$V5/_machine/logs/ingest/2026-01-07-1/entry.md" 2026-01-07-1 silent >/dev/null 2>&1; then
  echo "FAIL - missing fileset path accepted"; FAILS=$((FAILS+1)); else echo "ok - pre-flight aborts on missing path"; fi
assert_eq "pre-flight abort creates no commit" "" "$(cd "$V5" && jj log --no-graph -r 'description(glob:"ingest(*")' -T 'description')"

finish
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`
Expected: FAILs / errors (`commit-run` does not exist).

- [ ] **Step 3: Implement `commit-run`**

Create `plugins/vault/skills/ingest/scripts/commit-run`:

```python
#!/usr/bin/env python3
"""Atomic per-run commit + derived CHANGELOG render (spec 2026-07-30 SS2.4-SS2.6).

Usage:
  commit-run VAULT REPORT_JSON ENTRY_MD RUN_ID MODE    # drain step 6
  commit-run --regen VAULT                             # re-render CHANGELOG.md only

Contract:
- Fileset = touched-path set (written+marked+moved, plus _machine/ingest_paths.yml when
  `advanced` is non-empty) + skipped paths + run-log sublist (run.json, proposals.json,
  entry.md, report.json, + confirmed-manifest.json iff interactive). CHANGELOG.md never.
- No-op guard: empty touched-path set -> exit 0, no commit, no regen.
- Description = "ingest(<mode>): <run-id> - N notes, M days, P parked" + blank + entry.md
  verbatim; N/M/P read from run.json (filed, day_files, parked) - never parsed from entry.md.
- Mode must agree with confirmed-manifest.json presence in the run dir (exit 1 otherwise).
- jj 0.43 tolerates absent fileset paths and can create an EMPTY commit (verified): every
  fileset path is pre-flighted, and a post-commit empty check abandons + rolls back.
- Failure after commit points -> remove `ingested: true` from report's `marked` files, exit 1.
- Success -> regenerate CHANGELOG.md from jj log (newest first; renderer owns separators).
"""
import json, re, subprocess, sys
from pathlib import Path

HEADER = """# Vault Changelog

Ingest run history, newest first. Each entry is one commit.
To undo a run: `jj log -r 'description(glob:"*<run-id>*")'`, then `jj abandon <change-id>`,
then `commit-run --regen <vault>` to refresh this file (or wait for the next run).
"""

SUBLIST = ['run.json', 'proposals.json', 'entry.md', 'report.json']


def jj(vault, *args):
    return subprocess.run(['jj', *args], cwd=vault, capture_output=True, text=True)


def regen(vault: Path):
    r = jj(vault, 'log', '--no-graph', '-r', 'description(glob:"ingest(*")',
           '-T', 'description ++ "\\0"')
    if r.returncode != 0:
        sys.exit(f'regen failed: jj log error\n{r.stderr}')
    entries = []
    for desc in r.stdout.split('\0'):
        if not desc.strip():
            continue
        body = desc.split('\n', 1)[1].lstrip('\n') if '\n' in desc else desc
        entries.append(body.rstrip('\n'))
    text = HEADER + ''.join(f'\n---\n\n{e}\n' for e in entries)
    (vault / 'CHANGELOG.md').write_text(text, encoding='utf-8')


def unmark(vault: Path, rels):
    """Remove `ingested: true` from each day-file's frontmatter (rollback, spec SS2.5)."""
    for rel in rels:
        p = vault / rel
        if not p.exists():
            continue
        text = p.read_text(encoding='utf-8')
        if not text.startswith('---\n'):
            continue
        end = text.find('\n---\n', 4)
        if end == -1:
            continue
        fm, rest = text[4:end], text[end + 5:]
        fm2 = re.sub(r'^ingested:\s*true\s*$\n?', '', fm + '\n', flags=re.M).rstrip('\n')
        p.write_text(rest if not fm2.strip() else f'---\n{fm2}\n---\n{rest}',
                     encoding='utf-8')


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--regen':
        vault = Path(sys.argv[2]).expanduser().resolve()
        if not (vault / '.jj').is_dir():
            sys.exit(f'not a jj vault: {vault}')
        regen(vault)
        print(f'regenerated {vault / "CHANGELOG.md"}')
        return
    if len(sys.argv) != 6:
        sys.exit('usage: commit-run VAULT REPORT_JSON ENTRY_MD RUN_ID MODE'
                 '  |  commit-run --regen VAULT')
    vault = Path(sys.argv[1]).expanduser().resolve()
    report_path, entry_path = Path(sys.argv[2]), Path(sys.argv[3])
    run_id, mode = sys.argv[4], sys.argv[5]
    if mode not in ('interactive', 'silent'):
        sys.exit(f'mode must be interactive|silent, got: {mode}')
    run_dir = vault / '_machine' / 'logs' / 'ingest' / run_id
    has_manifest = (run_dir / 'confirmed-manifest.json').exists()
    if (mode == 'interactive') != has_manifest:
        sys.exit(f'mode mismatch: --{mode} but confirmed-manifest.json '
                 f'{"present" if has_manifest else "absent"} in {run_dir}')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    touched = [*report.get('written', []), *report.get('marked', []),
               *report.get('moved', [])]
    if report.get('advanced'):
        touched.append('_machine/ingest_paths.yml')
    if not touched:
        print('no-op: nothing touched; no commit, no changelog entry')
        return  # exit 0 - a no-op is the loop's most common healthy outcome
    counts = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
    n, m, p = counts['filed'], counts['day_files'], counts['parked']
    rel_run = run_dir.relative_to(vault)
    sublist = SUBLIST + (['confirmed-manifest.json'] if mode == 'interactive' else [])
    fileset = touched + list(report.get('skipped', [])) \
        + [str(rel_run / name) for name in sublist]
    missing = [f for f in fileset if not (vault / f).exists()]
    if missing:  # jj silently tolerates absent paths -> empty commit; refuse instead
        sys.exit(f'ABORT pre-commit: fileset paths missing on disk: {missing}')
    subject = f'ingest({mode}): {run_id} — {n} notes, {m} days, {p} parked'
    message = subject + '\n\n' + entry_path.read_text(encoding='utf-8')
    r = jj(vault, 'commit', '-m', message, *fileset)
    ok = r.returncode == 0
    if ok:
        e = jj(vault, 'log', '--no-graph', '-r', '@-',
               '-T', 'if(empty, "EMPTY", "NONEMPTY")')
        if 'EMPTY' in e.stdout:
            jj(vault, 'abandon', '@-')
            ok = False
            r.stderr += '\ncommit selected no changes (empty commit abandoned)'
    if not ok:
        marked = report.get('marked', [])
        unmark(vault, marked)
        sys.exit(f'commit-run failed; rolled back ingested markers on '
                 f'{len(marked)} day-file(s)\n{r.stderr}')
    regen(vault)
    print(json.dumps({'committed': True, 'run': run_id, 'files': len(fileset)}))


if __name__ == '__main__':
    main()
```

Then: `chmod 755 plugins/vault/skills/ingest/scripts/commit-run`

- [ ] **Step 4: Run tests to verify they pass**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`
Expected: `ALL PASS`. If the `--stat` template invocation errors, the fallback is `jj diff -r @- --stat` for the FILES assertions — adjust the test, not the script.

- [ ] **Step 5: Commit**

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/scripts/commit-run plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh
git commit -m "feat(vault): commit-run - atomic per-run commit with description-carried entry"
```

---

### Task 3: `commit-run` failure rollback + recovery sweep

**Files:**
- Modify: `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh` (append before `finish`)
- Modify: `plugins/vault/skills/ingest/scripts/commit-run` (only if Step 2 fails — the rollback path shipped in Task 2)

**Interfaces:**
- Consumes: Task 2's `unmark`, CLI, and exit-code contract.
- Produces: verified guarantee for Task 5's SKILL.md invariant text: *failure rolls back markers; recovery run sweeps prior notes via `skipped`.*

- [ ] **Step 1: Append failure + recovery tests**

Append to `test-commit-run.sh` immediately before `finish`:

```bash
# --- failure injection: hide .jj so jj commit fails -> markers rolled back, no CHANGELOG ---
V6=$(jj_vault); mk_run "$V6" 2026-01-08-1 silent
mv "$V6/.jj" "$V6/.jj-hidden"
if python3 "$SCRIPT" "$V6" "$V6/_machine/logs/ingest/2026-01-08-1/report.json" \
  "$V6/_machine/logs/ingest/2026-01-08-1/entry.md" 2026-01-08-1 silent >/dev/null 2>&1; then
  echo "FAIL - commit failure exited 0"; FAILS=$((FAILS+1)); else echo "ok - failure exits non-zero"; fi
assert_eq "marker rolled back on failure" "0" "$(grep -c '^ingested: true$' "$V6/journal/2026-01-02.md" || true)"
assert_contains "day text intact after unmark" "day text" "$(cat "$V6/journal/2026-01-02.md")"
if [ -f "$V6/CHANGELOG.md" ]; then echo "FAIL - CHANGELOG written on failure"; FAILS=$((FAILS+1)); else echo "ok - no CHANGELOG on failure"; fi

# --- recovery sweep: restore repo; re-run marks again and commits prior note via skipped ---
mv "$V6/.jj-hidden" "$V6/.jj"
RD6="$V6/_machine/logs/ingest/2026-01-08-2"; mkdir -p "$RD6"
printf -- '---\ningested: true\n---\nday text\n' > "$V6/journal/2026-01-02.md"   # recovery run re-marks
cp "$V6/_machine/logs/ingest/2026-01-08-1/run.json" "$RD6/run.json"
printf '[]\n' > "$RD6/proposals.json"
printf '## 2026-01-08-2 · silent\n**0 filed** · 1 skipped\n' > "$RD6/entry.md"
printf '{"written": [], "marked": ["journal/2026-01-02.md"], "advanced": [], "moved": [], "skipped": ["notes/t.md"]}\n' > "$RD6/report.json"
OUT6=$(python3 "$SCRIPT" "$V6" "$RD6/report.json" "$RD6/entry.md" 2026-01-08-2 silent 2>&1); RC6=$?
assert_eq "recovery run exits 0" "0" "$RC6"
FILES6=$(cd "$V6" && jj log --no-graph -r @- -T '' --stat)
assert_contains "recovery sweep commits the previously-filed note" "notes/t.md" "$FILES6"
```

- [ ] **Step 2: Run tests**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`
Expected: `ALL PASS` — the Task 2 implementation already contains `unmark` and the sweep. If the unmark assertions fail, fix `unmark()` (frontmatter parsing) in `commit-run` until they pass; do not weaken assertions.

- [ ] **Step 3: Commit**

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh plugins/vault/skills/ingest/scripts/commit-run
git commit -m "test(vault): commit-run failure rollback + recovery sweep"
```

---

### Task 4: `--regen` mode — abandon self-healing, fresh-vault creation

**Files:**
- Modify: `plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh` (append before `finish`)
- Modify: `plugins/vault/skills/ingest/scripts/commit-run` (only if tests expose a defect)

**Interfaces:**
- Consumes: Task 2's `regen` and `--regen` CLI.
- Produces: verified guarantee for Task 6's asset text: *abandoned runs vanish from the render; the file is created from nothing on any vault.*

- [ ] **Step 1: Append regen tests**

Append to `test-commit-run.sh` immediately before `finish`:

```bash
# --- regen: two runs, abandon the first, --regen drops it; file created from nothing ---
V7=$(jj_vault); mk_run "$V7" 2026-01-09-1 silent
python3 "$SCRIPT" "$V7" "$V7/_machine/logs/ingest/2026-01-09-1/report.json" \
  "$V7/_machine/logs/ingest/2026-01-09-1/entry.md" 2026-01-09-1 silent >/dev/null 2>&1
printf -- '---\ntitle: "U"\n---\nsecond body\n' > "$V7/notes/u.md"
RD7="$V7/_machine/logs/ingest/2026-01-09-2"; mkdir -p "$RD7"
printf '{"run": "2026-01-09-2", "ts": 2, "filed": 1, "day_files": 0, "parked": 0, "diary_only": 0, "skipped": 0, "marked": []}\n' > "$RD7/run.json"
printf '[]\n' > "$RD7/proposals.json"
printf '## 2026-01-09-2 · silent\n**1 filed**\n' > "$RD7/entry.md"
printf '{"written": ["notes/u.md"], "marked": [], "advanced": [], "moved": [], "skipped": []}\n' > "$RD7/report.json"
python3 "$SCRIPT" "$V7" "$RD7/report.json" "$RD7/entry.md" 2026-01-09-2 silent >/dev/null 2>&1
assert_contains "both entries rendered, newest first" "2026-01-09-2" "$(head -12 "$V7/CHANGELOG.md")"
CID=$(cd "$V7" && jj log --no-graph -r 'description(glob:"*2026-01-09-1*")' -T 'change_id.short()')
(cd "$V7" && jj abandon "$CID" >/dev/null 2>&1)
rm "$V7/CHANGELOG.md"                       # prove --regen creates from nothing
python3 "$SCRIPT" --regen "$V7" >/dev/null 2>&1
assert_contains "regen recreates file with header" "# Vault Changelog" "$(cat "$V7/CHANGELOG.md")"
assert_contains "surviving run still rendered" "2026-01-09-2" "$(cat "$V7/CHANGELOG.md")"
case "$(cat "$V7/CHANGELOG.md")" in *"2026-01-09-1"*) echo "FAIL - abandoned run still rendered"; FAILS=$((FAILS+1));; *) echo "ok - abandoned run vanished from render";; esac
```

- [ ] **Step 2: Run tests**

Run: `bash plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh`
Expected: `ALL PASS`. If the abandon leaves a divergent/rebased state that breaks the assertion, debug with `(cd $V7 && jj log)` — the assertion targets are correct per spec §2.6; fix `regen` or the fixture, never the assertion.

- [ ] **Step 3: Commit**

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/scripts/tests/test-commit-run.sh plugins/vault/skills/ingest/scripts/commit-run
git commit -m "test(vault): commit-run regen - abandon self-healing, fresh-vault creation"
```

---

### Task 5: ingest SKILL.md — drain step 6, near-miss contract, silent digest, invariants

**Files:**
- Modify: `plugins/vault/skills/ingest/SKILL.md`

No test harness — this is model-facing prose. Verification is the self-check in Step 8.

- [ ] **Step 1: Handle the pre-existing dirty state**

`git diff plugins/vault/skills/ingest/SKILL.md` — the file carries Tucker's uncommitted 2026-07-25 label-semantics edits (see BACKLOG). Commit them **first, separately**, so this task's commit is clean:

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/SKILL.md plugins/vault/skills/synthesizer/SKILL.md
git commit -m "docs(vault): label-semantics invariant in ingest + synthesizer (2026-07-25, pre-existing)"
```

**Gate: show Tucker the diff summary before this commit** — it is his work, not the plan's.

- [ ] **Step 2: Routing — `--silent --today` validation error**

In the "Subcommands and routing" section, after the `/ingest --silent` bullet, add:

```markdown
- **`--silent --today` together is a validation error** — refuse and exit non-zero before
  touching the vault: it would read the mutable open day-file into a gate-free unattended flow,
  the exact duplicate-filing scenario `--today`'s interactive-only restriction exists to prevent.
```

- [ ] **Step 3: Drain step 2 — near-miss emission**

In "The drain" step 2, after "and emit structured proposals with **verbatim bodies**", insert:

```markdown
For every thought disposed to `needs-label`, the subagent additionally emits a `near_miss`
array on that proposal — `{label, reason}` objects for each active label seriously weighed and
why it missed; empty array when nothing was close. This is the changelog's vocabulary-pressure
signal (see step 6); without it the Parked section degrades to a list of titles.
```

- [ ] **Step 4: Drain step 5 — run.json schema**

In step 5, replace the sentence beginning "Then record `run.json`":

```markdown
Then record `run.json` in the run log — `ts` (epoch-seconds, taken after markers land),
`marked` (day-files), `jj_change_id_at_drain_start`, and the run's structured counts:
`filed`, `parked`, `diary_only`, `skipped`, and `day_files` (distinct day-files touched,
including an open day under `--today`, which never enters `marked`). Step 6's `commit-run`
reads `filed`/`day_files`/`parked` for the commit subject line; `status`'s
marked-then-modified net reads `ts` and `marked`. Never record ad-hoc fields
(`labels_registered_this_run` was drift; a label minted by the human at the gate needs no
run-log record — the bank's git history is its record).
```

- [ ] **Step 5: New drain step 6**

After step 5, add:

```markdown
6. **Commit + changelog entry (scripted; every run, silent or interactive).** Render
   `_machine/logs/ingest/<run>/entry.md` from the gate's **final, human-approved** set (silent:
   the proposal set as emitted) per the changelog entry format: `## <run-id> · <mode>` heading,
   bold count line, then Filed / Parked / Diary-only / Skipped subsections (itemize Filed and
   Parked; one-line summaries for the rest; omit empty categories). Parked items render their
   `near_miss` list plus one closing sentence of synthesis on why nothing fit. **Gate-reparked
   items** (a label was proposed; the human parked it instead) have no `near_miss` — render
   from the proposed label plus the gate's stated rejection reason, never the empty-array
   fallback. Emit **no `---` separator lines** — the changelog renderer owns those. Then run
   `scripts/commit-run <vault> <report.json> <entry.md> <run-id> <mode>`: it commits the run's
   own paths plus the run-log directory as one atomic change whose description carries the
   entry, and regenerates the derived vault-root `CHANGELOG.md`. Exit 0 with `no-op` means
   nothing was touched (normal); non-zero means the commit failed and the script already
   rolled the `ingested:` markers back — the next drain retries, so report it and stop; never
   hand-repair. Surface the rendered entry to the user at run end on every path, including
   ones that never reach a commit.
```

- [ ] **Step 6: Silent mode — digest → changelog**

In "Silent mode (`--silent`)", replace the "**Mandatory digest:**" bullet with:

```markdown
- **Mandatory digest = the changelog entry.** Every silent run ends with the run's rendered
  entry (step 6) surfaced to the user AND persisted as the run commit's description, rendered
  into the vault-root `CHANGELOG.md`. Silent shifts review from pre-write to post-write; it is
  never invisible. No separate `digest.md` is written (collapsed 2026-08-10). Whole-run undo:
  `jj log -r 'description(glob:"*<run-id>*")'`, `jj abandon`, then `commit-run --regen`.
```

- [ ] **Step 7: Invariants**

In "Invariants (cross-cutting, hard)", update the digest clause of the propose-confirm bullet from "mandatory digest surfaced + persisted to `_machine/logs/ingest/<run>/digest.md` (review-after)" to "mandatory digest surfaced + persisted as the run commit's description (review-after)", and append two bullets:

```markdown
- **One run, one commit** — every run whose touched-path set is non-empty ends as exactly one
  path-scoped `jj` commit (via `scripts/commit-run`); a no-op run produces none; a failed
  commit produces none and rolls back the run's `ingested:` markers. `CHANGELOG.md` is a
  derived render, never committed, never hand-edited.
- **`--silent --today` is refused** — validation error before any vault read.
```

- [ ] **Step 8: Self-check and commit**

Re-read the modified SKILL.md top to bottom once: no remaining reference to `digest.md` as a written file, step numbering 1–6 contiguous, no contradiction with the frozen-vocabulary invariant. Then:

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/ingest/SKILL.md
git commit -m "docs(vault): ingest drain step 6 - atomic commits, changelog entry, near-miss contract"
```

---

### Task 6: vault plugin surfaces — assets, vault SKILL.md, version, BACKLOG

**Files:**
- Modify: `plugins/vault/skills/vault/assets/gitignore`
- Modify: `plugins/vault/skills/vault/assets/stignore`
- Modify: `plugins/vault/skills/vault/assets/CLAUDE.md`
- Modify: `plugins/vault/skills/vault/SKILL.md`
- Modify: `plugins/vault/.claude-plugin/plugin.json`
- Modify: `BACKLOG.md` (annotate only — do NOT commit, it carries unrelated uncommitted edits)

- [ ] **Step 1: assets/gitignore** — append:

```
# CHANGELOG.md is a derived render of jj log (ingest commit descriptions) — never committed.
CHANGELOG.md
```

- [ ] **Step 2: assets/stignore** — append:

```
// CHANGELOG.md is derived per-machine from local jj history — not synced.
CHANGELOG.md
```

- [ ] **Step 3: assets/CLAUDE.md** — in "Layout (immutable placement)", after the `_archive/` bullet, add:

```markdown
- `CHANGELOG.md` — derived render of ingest run history (each run's commit description,
  newest first). Regenerated by ingest's `commit-run`; VCS-ignored. Read it freely; never
  hand-edit — edits are overwritten on the next render.
```

- [ ] **Step 4: vault SKILL.md** — after the "Stamp ignore files" step in the create flow, add:

```markdown
   (The stamped `.gitignore`/`.stignore` exclude `CHANGELOG.md` — the derived run-history
   render at the vault root. No seed file is stamped; the file first appears when the vault's
   first ingest run commits and renders it.)
```

- [ ] **Step 5: plugin.json** — `"version": "1.1.0"` → `"version": "1.2.0"`.

- [ ] **Step 6: BACKLOG.md** — edit the `[x] ingest: headless/unattended mode` item's last sentence to:

```markdown
  Cron invocation is `/ingest --silent` on a cadence — **but requires vault plugin v1.2.0's
  atomic-commit layer (2026-08 spec) and a one-time manual commit of the vault's uncommitted
  backlog first.**
```

- [ ] **Step 7: Commit (everything except BACKLOG.md)**

```bash
cd /Users/johnmoses/claude-materia
git add plugins/vault/skills/vault/assets/gitignore plugins/vault/skills/vault/assets/stignore \
  plugins/vault/skills/vault/assets/CLAUDE.md plugins/vault/skills/vault/SKILL.md \
  plugins/vault/.claude-plugin/plugin.json
git commit -m "feat(vault): v1.2.0 - derived CHANGELOG ignore rules + layout docs"
```

---

### Task 7: live vault rollout (gated — touches `~/Vault`)

**Files:**
- Modify: `~/Vault/.gitignore`
- Modify: `~/Vault/.stignore`

**Every step in this task requires Tucker's go-ahead at execution time.** Prerequisite he owns (flag, don't automate): the vault's large uncommitted working-copy backlog should be committed manually before the loop is ever scheduled (spec §5).

- [ ] **Step 1: Add ignore lines**

Append to `~/Vault/.gitignore`: the same two lines as Task 6 Step 1. Append to `~/Vault/.stignore`: the same two lines as Task 6 Step 2.

- [ ] **Step 2: Scoped vault commit**

```bash
cd ~/Vault && jj commit .gitignore .stignore -m "vault: ignore derived CHANGELOG.md (ingest atomic-commits rollout)"
```

Verify the commit contains exactly those two files: `jj log --no-graph -r @- -T '' --stat` — and that the untouched backlog survives in the working copy: `jj status | head`.

- [ ] **Step 3: Smoke-test regen against the live vault (read-only for content, writes only CHANGELOG.md)**

```bash
python3 /Users/johnmoses/claude-materia/plugins/vault/skills/ingest/scripts/commit-run --regen ~/Vault
cat ~/Vault/CHANGELOG.md
```

Expected: header only (no `ingest(` commits exist yet) — proving fresh-file creation on the real vault. Confirm `jj status` in the vault does NOT list `CHANGELOG.md` (ignore rule works).

---

## Deferred to implementation follow-up (from adversarial review, backlogged)

Not in this plan: f-o-1-8/-9 (no-op-path entry-rendering order — spec-level, backlogged), f-o-1-14 (spec prose duplication). Already absorbed above: f-o-1-5 (pre-flight + fileset-completeness contract, Tasks 1–2), f-o-1-10 (no-op exits 0, Task 2), f-o-1-12 (cwd anchoring + outside-vault test, Task 2), f-o-1-13 (mode validated against manifest presence, Task 2).
