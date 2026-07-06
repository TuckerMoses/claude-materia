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
