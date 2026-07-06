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
