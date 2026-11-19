#!/bin/bash
# baseline-compare.sh <session-dir> <iteration-dir>
#
# Compares the pre-review baseline against the current scope files and writes,
# into <iteration-dir>:
#   baseline.diff        unified diff, baseline -> current, one section per changed file
#   baseline-sizes.tsv   per-file line and word counts, baseline vs current, plus TOTAL
#
# Inputs (both arguments absolute):
#   <session-dir>/review/baseline/   baseline copies, mirroring absolute paths
#   <iteration-dir>/scope.txt        current scope, one absolute path per line
#
# Prints nothing. Exit 0 iff both output files were written. Non-zero on a diff
# error (status >= 2) or an I/O error. Differences between files are not errors.

exec >/dev/null 2>&1
set -u

session_dir="${1:-}"
iter_dir="${2:-}"
[ -n "$session_dir" ] && [ -n "$iter_dir" ] || exit 2

baseline_dir="$session_dir/review/baseline"
scope_list="$iter_dir/scope.txt"
[ -d "$baseline_dir" ] && [ -r "$baseline_dir" ] || exit 3
[ -f "$scope_list" ] && [ -r "$scope_list" ] || exit 3
[ -d "$iter_dir" ] && [ -w "$iter_dir" ] || exit 3

work="$(mktemp -d "${TMPDIR:-/tmp}/baseline-compare.XXXXXX")" || exit 3
trap 'rm -rf "$work"' EXIT

# Union of baseline files (as absolute paths) and scope.txt, sorted, unique.
{
  (cd "$baseline_dir" && find . -type f -print) | sed 's|^\.||'
  grep -v '^[[:space:]]*$' "$scope_list"
} | LC_ALL=C sort -u > "$work/paths" || exit 3

count_lines() { if [ -f "$1" ]; then awk 'END { print NR }' "$1"; else echo 0; fi; }
count_words() { if [ -f "$1" ]; then wc -w < "$1" | tr -d '[:space:]'; else echo 0; fi; }

diff_out="$work/baseline.diff"
sizes_out="$work/baseline-sizes.tsv"
: > "$diff_out" || exit 3
printf 'path\tbaseline_lines\tcurrent_lines\tdelta\tbaseline_words\tcurrent_words\tword_delta\n' > "$sizes_out" || exit 3

tot_bl=0; tot_cl=0; tot_bw=0; tot_cw=0

while IFS= read -r path; do
  base="$baseline_dir$path"
  [ -f "$base" ] || base=""
  cur="$path"
  [ -f "$cur" ] || cur=""
  # Absent from both sides: no diff, no size row.
  [ -n "$base" ] || [ -n "$cur" ] || continue

  left="${base:-/dev/null}";  left_label="baseline$path"; [ -n "$base" ] || left_label="/dev/null"
  right="${cur:-/dev/null}";  right_label="current$path"; [ -n "$cur" ] || right_label="/dev/null"

  diff -u --label "$left_label" --label "$right_label" "$left" "$right" > "$work/one.diff"
  status=$?
  [ "$status" -lt 2 ] || exit 4

  if grep -q '^Binary files ' "$work/one.diff"; then
    printf 'Binary files %s and %s differ\n' "$left_label" "$right_label" >> "$diff_out" || exit 3
    printf '%s\tbinary\tbinary\tbinary\tbinary\tbinary\tbinary\n' "$path" >> "$sizes_out" || exit 3
    continue
  fi
  cat "$work/one.diff" >> "$diff_out" || exit 3

  bl=$(count_lines "$base"); cl=$(count_lines "$cur")
  bw=$(count_words "$base"); cw=$(count_words "$cur")
  printf '%s\t%d\t%d\t%d\t%d\t%d\t%d\n' "$path" "$bl" "$cl" $((cl - bl)) "$bw" "$cw" $((cw - bw)) >> "$sizes_out" || exit 3
  tot_bl=$((tot_bl + bl)); tot_cl=$((tot_cl + cl)); tot_bw=$((tot_bw + bw)); tot_cw=$((tot_cw + cw))
done < "$work/paths"

printf 'TOTAL\t%d\t%d\t%d\t%d\t%d\t%d\n' "$tot_bl" "$tot_cl" $((tot_cl - tot_bl)) "$tot_bw" "$tot_cw" $((tot_cw - tot_bw)) >> "$sizes_out" || exit 3

mv "$diff_out" "$iter_dir/baseline.diff" || exit 3
mv "$sizes_out" "$iter_dir/baseline-sizes.tsv" || exit 3
exit 0
