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
assert_eq "pre-flight abort rolls back marker" "0" "$(grep -c '^ingested: true$' "$V5/journal/2026-01-02.md" || true)"

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
FILES6=$(cd "$V6" && jj diff -r @- --stat)
assert_contains "recovery sweep commits the previously-filed note" "notes/t.md" "$FILES6"

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

finish
