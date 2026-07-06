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
assert_eq "no status field (strict)" "0" "$(grep -c '^status:' "$V/notes/test-thought.md" || true)"
assert_contains "marker written" "ingested: true" "$(cat "$V/journal/2026-01-02.md")"
assert_contains "raw text preserved under marker" "raw day text" "$(cat "$V/journal/2026-01-02.md")"
# Idempotent re-run: same manifest → skipped, not duplicated
OUT2=$(python3 "$SCRIPT" "$V" "$MF")
assert_contains "re-run skips by source+body" '"skipped"' "$OUT2"
assert_eq "no duplicate file" "1" "$(ls "$V/notes" | grep -c 'test-thought')"
assert_eq "marker written once after re-run" "1" "$(grep -c '^ingested: true$' "$V/journal/2026-01-02.md")"
# Empty-body rejection (iron rule)
MF2=$(mktemp)
cat > "$MF2" <<EOF
{"notes": [{"title": "Empty", "labels": ["idea"], "created": "2026-07-05",
  "captured": "2026-01-02", "source": "journal/2026-01-02", "related": [], "body": ""}],
 "mark_ingested": [], "advance": [], "archive_moves": []}
EOF
if python3 "$SCRIPT" "$V" "$MF2" >/dev/null 2>&1; then echo "FAIL - empty body accepted"; FAILS=$((FAILS+1)); else echo "ok - empty body aborts"; fi
# Archive-move basename collision: two staged files share a basename from different dirs
D1=$(mktemp -d); D2=$(mktemp -d)
printf 'content-one\n' > "$D1/notes.md"
printf 'content-two\n' > "$D2/notes.md"
MF3=$(mktemp)
cat > "$MF3" <<EOF
{"notes": [], "mark_ingested": [], "advance": [],
 "archive_moves": [{"from": "$D1/notes.md", "date": "2026-07-05"}, {"from": "$D2/notes.md", "date": "2026-07-05"}]}
EOF
python3 "$SCRIPT" "$V" "$MF3" >/dev/null
assert_eq "archive collision preserved" "2" "$(ls "$V/_machine/logs/ingest/2026-07-05" | grep -c 'notes')"
assert_contains "first archived file content intact" "content-one" "$(cat "$V/_machine/logs/ingest/2026-07-05/notes.md")"
assert_contains "second archived file uniquified + content intact" "content-two" "$(cat "$V/_machine/logs/ingest/2026-07-05/notes-2.md")"
finish
