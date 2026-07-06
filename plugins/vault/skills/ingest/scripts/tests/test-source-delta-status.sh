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
