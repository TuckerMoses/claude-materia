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
# --- F11: no child waits on stdin. Shims read stdin to EOF before the real tool, and the scripts run with stdin
# held open by a pipe that never closes: with stdin=DEVNULL they finish, without it they hang until timeout. ---
SHIM=$(mktemp -d)
for t in git jj; do printf '#!/bin/sh\ncat >/dev/null\nexec "%s" "$@"\n' "$(command -v $t)" > "$SHIM/$t"; chmod +x "$SHIM/$t"; done
open_stdin() { PATH="$SHIM:$PATH" timeout 15 "$@" < <(sleep 30); }  # nothing waits on the sleeper
open_stdin python3 ../source-delta "$V" >/dev/null 2>&1; assert_eq "source-delta: git gets no stdin" "0" "$?"
open_stdin python3 ../ingest-status "$V" >/dev/null 2>&1; assert_eq "ingest-status: git gets no stdin" "0" "$?"
JV=$(new_vault); (cd "$JV" && jj git init --colocate --quiet . >/dev/null 2>&1)
mkdir -p "$JV/_machine/logs/ingest/2026-01-01-1"; printf '{"written": [], "completed": true}\n' > "$JV/_machine/logs/ingest/2026-01-01-1/report.json"
open_stdin python3 ../commit-run --landed "$JV" 2026-01-01-1 >/dev/null 2>&1; assert_eq "commit-run: jj gets no stdin (a no-op run -> 0)" "0" "$?"
finish
