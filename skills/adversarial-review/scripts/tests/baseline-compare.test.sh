#!/bin/bash
# Tests for baseline-compare.sh. Run: bash skills/adversarial-review/scripts/tests/baseline-compare.test.sh
set -u
here="$(cd "$(dirname "$0")" && pwd)"
script="$here/../baseline-compare.sh"
root="$(mktemp -d "${TMPDIR:-/tmp}/baseline-compare-test.XXXXXX")"
root="$(cd "$root" && pwd -P)"
trap 'rm -rf "$root"' EXIT
pass=0; fail=0
ok()  { pass=$((pass + 1)); echo "ok   - $1"; }
bad() { fail=$((fail + 1)); echo "FAIL - $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

session="$root/session"; iter="$session/review/iterations/c-2"; src="$root/src"
base="$session/review/baseline$src"
mkdir -p "$iter" "$base" "$src"

# kept.md: unchanged. edited.md: one line rewritten longer (same line count, more words).
# deleted.md: baseline only. created.md: current only. blob.bin: binary, changed.
# ghost.md: listed in scope.txt, on neither side.
printf 'alpha\nbeta\n' > "$base/kept.md";    printf 'alpha\nbeta\n' > "$src/kept.md"
printf 'one two\nthree\n' > "$base/edited.md"; printf 'one two and four five six\nthree\n' > "$src/edited.md"
printf 'gone one\ngone two\n' > "$base/deleted.md"
printf 'new\nfile here' > "$src/created.md"   # no trailing newline: still 2 lines
printf 'a\000b\n' > "$base/blob.bin";         printf 'a\000c\n' > "$src/blob.bin"
printf '%s\n' "$src/kept.md" "$src/edited.md" "$src/created.md" "$src/blob.bin" "$src/ghost.md" > "$iter/scope.txt"

out="$(bash "$script" "$session" "$iter" 2>&1)"; status=$?
check "exits 0 when files differ" '[ "$status" -eq 0 ]'
check "prints nothing" '[ -z "$out" ]'
check "writes baseline.diff" '[ -f "$iter/baseline.diff" ]'
check "writes baseline-sizes.tsv" '[ -f "$iter/baseline-sizes.tsv" ]'

d="$iter/baseline.diff"; t="$iter/baseline-sizes.tsv"
check "header has line and word columns" 'head -1 "$t" | grep -q "^path	baseline_lines	current_lines	delta	baseline_words	current_words	word_delta$"'
check "labels use baseline/current + absolute path" 'grep -q "^--- baseline$src/edited.md" "$d" && grep -q "^+++ current$src/edited.md" "$d"'
check "unchanged file has no diff section" '! grep -q "kept.md" "$d"'
check "unchanged file still has a size row" 'grep -q "^$src/kept.md	2	2	0	2	2	0$" "$t"'
check "in-place rewrite: zero line delta, positive word delta" 'grep -q "^$src/edited.md	2	2	0	3	7	4$" "$t"'
check "deleted file diffs against /dev/null" 'grep -q "^+++ /dev/null" "$d" && grep -q "^-gone one" "$d"'
check "deleted file counts 0 current" 'grep -q "^$src/deleted.md	2	0	-2	4	0	-4$" "$t"'
check "created file diffs from /dev/null" 'grep -q "^--- /dev/null" "$d" && grep -q "^+new" "$d"'
check "unterminated final line is counted" 'grep -q "^$src/created.md	0	2	2	0	3	3$" "$t"'
check "binary file gets one diff line" '[ "$(grep -c "^Binary files baseline$src/blob.bin and current$src/blob.bin differ$" "$d")" -eq 1 ]'
check "binary file row says binary in six columns" 'grep -q "^$src/blob.bin	binary	binary	binary	binary	binary	binary$" "$t"'
check "path absent from both sides is skipped" '! grep -q "ghost.md" "$d" && ! grep -q "ghost.md" "$t"'
check "TOTAL excludes binary and sums the rest" 'tail -1 "$t" | grep -q "^TOTAL	6	6	0	9	12	3$"'
check "rows sorted by path with TOTAL last" '[ "$(sed 1d "$t" | sed "\$d" | cut -f1)" = "$(sed 1d "$t" | sed "\$d" | cut -f1 | LC_ALL=C sort)" ]'

# No differences at all: empty diff, still exit 0.
iter2="$session/review/iterations/c-1"; mkdir -p "$iter2"
printf '%s\n' "$src/kept.md" > "$iter2/scope.txt"
s2="$root/s2"; mkdir -p "$s2/review/baseline$src" "$s2/review/iterations/c-1"
cp "$base/kept.md" "$s2/review/baseline$src/kept.md"; cp "$iter2/scope.txt" "$s2/review/iterations/c-1/scope.txt"
bash "$script" "$s2" "$s2/review/iterations/c-1"; status=$?
check "no differences: exit 0" '[ "$status" -eq 0 ]'
check "no differences: empty diff" '[ -f "$s2/review/iterations/c-1/baseline.diff" ] && [ ! -s "$s2/review/iterations/c-1/baseline.diff" ]'

# Failure modes: non-zero and no partial output.
iter3="$session/review/iterations/c-3"; mkdir -p "$iter3"
bash "$script" "$session" "$iter3"; status=$?
check "missing scope.txt: non-zero" '[ "$status" -ne 0 ]'
check "missing scope.txt: no output files" '[ ! -e "$iter3/baseline.diff" ] && [ ! -e "$iter3/baseline-sizes.tsv" ]'
mkdir -p "$root/nobase/review/iterations/c-1"; printf '%s\n' "$src/kept.md" > "$root/nobase/review/iterations/c-1/scope.txt"
bash "$script" "$root/nobase" "$root/nobase/review/iterations/c-1"; status=$?
check "missing baseline dir: non-zero" '[ "$status" -ne 0 ]'
bash "$script"; status=$?
check "missing arguments: non-zero" '[ "$status" -ne 0 ]'

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
