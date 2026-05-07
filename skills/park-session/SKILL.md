---
name: park-session
description: Use when the user wants to bookmark a Claude Code session for later resumption — phrases like "park this session", "save this for later", "checkpoint before I step away", "remember where I left off", "I want to come back to this", or when they mention tearing down tmux/terminals but worry about losing track of in-flight work. Also triggers on "list parked sessions", "what did I park", "audit parked sessions", "unpark <session-id>", or any reference to a registry of saved session pointers.
---

# Park Session

Bookmarks a Claude Code session by writing a structured pointer (session ID, when, what, next move) into a destination file the user controls. Lets you tear down ephemeral environments — close tmux windows, kill terminals, restart the machine — without losing the thread of mid-investigation work.

The skill never deletes anything automatically. Every entry leaves the registry only by the user's explicit action.

## Subcommands

| Subcommand | What it does |
|------------|-------------|
| `park` (default) | Bookmark the current session. Drafts the entry from the transcript, classifies the cwd into a sub-section if the layout has one, presents for review, writes on confirm. |
| `init` | Configure the destination, layout, and section structure. Run once before first park (or to reconfigure). |
| `unpark <session-id>` | Remove an entry. Confirmation prompt before deletion. |
| `list` | Show all parked entries with ages and sections. Read-only. |
| `audit` | Walk entries oldest-first, prompting keep/unpark/skip/quit on each. |

If the user's intent is ambiguous, default to `park`.

## Workflow: park (default)

### 1. Load config or fall through to init

Read the local config at `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`. If it doesn't exist, tell the user "no config found, running init first" and do the init workflow before continuing. Do not proceed with park silently if config is missing — the destination is unknown.

### 2. Derive the current session ID

Claude Code does not expose the session ID via environment variable. Derive it from the active transcript file.

**Canonical cwd derivation (deterministic, single mechanism):** Claude Code's bash tool runs in the session's invocation cwd. **The contract is: the user has not run `cd` since the session started.** Provided that holds, `pwd` returns the invocation cwd (the directory Claude Code itself was launched from), which is what indexes the transcript directory. The slug is derived directly from `pwd` via a documented encoding (both `/` and `.` → `-`, leading `-`); the project transcript dir is then `~/.claude/projects/<slug>/`. Within that dir, the active transcript is the most recently modified `*.jsonl`. The session-start system reminder is **not** used as the primary source because (i) it can be compacted away on long sessions, and (ii) it is plain text whose format is undocumented and subject to change.

If the user has issued `cd` mid-session, `pwd` no longer reflects the invocation cwd; the derived slug will not match any transcript dir, and step 2b below fails loudly with the no-transcripts-found message. See the Edge case for the workaround.

Run the entire transcript-handling surface (slug derivation + project-dir validation + disambiguation + tail-read) as a **single bash invocation**. The Claude Code Bash tool does not share shell state across calls, so variables (`$slug`, `$proj_dir`, `$active_transcript`) defined in one block are undefined in the next. The consolidated block below derives the slug, validates the project dir, picks the correct transcript across the three disambiguation cases, and emits its last 40 lines (the tail consumed by step 3) — all in one shot, no cross-call handoff.

**Slug encoding rule:** both `/` and `.` are replaced with `-`. Examples:
- `/Users/u/projects/foo` → `-Users-u-projects-foo`
- `/Users/u/.claude/foo` → `-Users-u--claude-foo` (note the double hyphen: `/` before `.claude` becomes `-`, and the leading `.` of `.claude` also becomes `-`)
- `/Users/u/projects/foo.bar` → `-Users-u-projects-foo-bar`

The basename without `.jsonl` is the session ID. The slug derivation requires that the user has not issued `cd` since the session started; if they have, the project-dir check inside the consolidated block (step 2b below) will fail loudly because the constructed `proj_dir` will not exist (see Edge cases).

**Concurrent-session disambiguation (probe-and-grep fallback):** count the transcripts in the project dir, then compute the time delta between the most-recently-modified transcript and the second-most-recently-modified transcript. The disambiguation logic:

- **Exactly one transcript**: that transcript is this session's by definition. Skip both the delta check and the probe-and-grep — there is nothing to disambiguate against. This is the common case on the first park in a fresh project dir.
- **Two or more transcripts, top-two delta ≥ 60 seconds**: the most recent transcript is unambiguously this session's (a 60-second gap is large enough that two sessions could not have started within it). Use it.
- **Two or more transcripts, top-two delta < 60 seconds**: the mtime trick is ambiguous (the top two are nearly tied). Fall through to the probe-and-grep below.

(60 seconds reflects the worst-case interval over which two sequential session starts could plausibly overlap; shorter thresholds risk false negatives — probe-and-grep skipped when sessions are actually concurrent — and longer ones impose probe latency on sequential parks. With three or more transcripts, only the top-two delta matters — older transcripts cannot be the current session.)

Mtimes are computed portably using Python (`os.path.getmtime`) — `stat` flags differ between macOS BSD (`stat -f %m`) and GNU Linux (`stat -c %Y`); the Python form works on both with no flag selection.

The probe-and-grep fallback exploits the fact that Claude Code logs every bash tool invocation (the literal command string, including arguments) into the current session's JSONL transcript. Issue a bash command containing a unique probe string, then grep the project's transcripts for that probe — the only transcript that contains it is this session's.

The consolidated block below performs all of step 2 — slug derivation (2a), project-dir validation (2b), disambiguation across the three cases (2c), and the tail-read that step 3 consumes (2d) — in one bash invocation. The single-transcript, unambiguous-mtime, and probe-and-grep paths converge on a shared `$active_transcript` variable, which step 2d tails. No cross-Bash-call handoff: the disambiguation outcome is consumed in the same shell.

```bash
# Step 2a: derive the slug from the current cwd.
# Claude Code stores transcripts under ~/.claude/projects/<slug>/<session-id>.jsonl
# where <slug> is the invocation cwd with BOTH `/` and `.` replaced by `-`,
# and with a leading `-`. The double substitution matters for paths that contain
# dotfiles or dotted segments — e.g. /Users/u/.claude/foo encodes to
# -Users-u--claude-foo (the slash before .claude becomes `-`, AND the leading
# `.` of `.claude` also becomes `-`, producing the double hyphen).
session_cwd=$(pwd)
slug=$(printf '%s' "$session_cwd" | sed -e 's|/|-|g' -e 's|\.|-|g')
slug="-${slug#-}"  # ensure leading dash, strip duplicate if cwd already started with /
proj_dir="$HOME/.claude/projects/${slug}"

# Step 2b: fail loudly if the project dir doesn't exist.
# This is the diagnostic for "wrong cwd", "user has cd'd since session start",
# or "not an active Claude Code session."
if [ ! -d "$proj_dir" ]; then
  echo "no transcripts found for cwd ${session_cwd} at ${proj_dir}; is this an active Claude Code session, or have you cd'd since session start?" >&2
  exit 1
fi

# Step 2c: pick the active transcript across the three disambiguation cases.
# The single, unambiguous-mtime, and probe-and-grep paths all converge on a
# single $active_transcript variable that step 2d then tails.

# Single-transcript guard: with exactly one transcript, that file is this session's
# by definition. Skip the delta check and the probe-and-grep entirely. With zero
# transcripts the project dir exists but is empty — fail loudly with the canonical
# no-transcripts message rather than falling into `tail ""` on an empty path.
transcript_count=$(ls -t "${proj_dir}"/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
if [ "$transcript_count" -eq 0 ]; then
  echo "no transcripts found for cwd ${session_cwd} at ${proj_dir}; is this an active Claude Code session, or have you cd'd since session start?" >&2
  exit 1
elif [ "$transcript_count" -eq 1 ]; then
  active_transcript=$(ls -t "${proj_dir}"/*.jsonl 2>/dev/null | head -1)
else
  # Two-or-more transcripts: compute the top-two mtime delta portably.
  mtime() { python3 -c 'import os, sys; print(int(os.path.getmtime(sys.argv[1])))' "$1"; }
  top_two=$(ls -t "${proj_dir}"/*.jsonl 2>/dev/null | head -2)
  t1=$(mtime "$(echo "$top_two" | sed -n 1p)")
  t2=$(mtime "$(echo "$top_two" | sed -n 2p)")
  delta=$((t1 - t2))

  if [ "$delta" -ge 60 ]; then
    # Unambiguous: top two are >= 60s apart, the most recent is this session's.
    active_transcript=$(echo "$top_two" | sed -n 1p)
  else
    # Ambiguous (delta < 60): probe-and-grep. The bash invocation itself gets logged
    # to the JSONL transcript, so grepping for the probe string identifies the
    # current session's transcript.
    #
    # UUID fallback cascade — try uuidgen, then python3 -c uuid, then
    # /proc/sys/kernel/random/uuid. Fail loudly if none is available rather
    # than falling back to a weaker source ($RANDOM, $$, timestamps): this is
    # a destructive ID-resolution path and collision risk is unacceptable.
    if uuid=$(uuidgen 2>/dev/null); then
      :
    elif uuid=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null); then
      :
    elif uuid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null); then
      :
    else
      echo "no UUID source available (tried uuidgen, python3 -c uuid, /proc/sys/kernel/random/uuid). Refusing to use a weaker probe on a destructive ID-resolution path. Please supply the session ID directly." >&2
      exit 1
    fi
    probe="park-probe-${uuid}"
    echo "$probe" > /dev/null    # output discarded; the bash invocation itself is what gets logged
    sleep 1                       # initial flush wait; succeeds in the common case
    matches=$(grep -l "$probe" "${proj_dir}"/*.jsonl 2>/dev/null)
    if [ -z "$matches" ]; then
      sleep 2                     # 2s retry handles transient flush delays beyond the 1s common case
      matches=$(grep -l "$probe" "${proj_dir}"/*.jsonl 2>/dev/null)
    fi
    match_count=$(printf '%s\n' "$matches" | grep -c .)
    if [ "$match_count" -eq 0 ]; then
      echo "unable to derive session ID via probe-and-grep — possible causes: (a) the bash invocation has not yet been flushed to disk after 3 total seconds (delayed-write filesystem or harness-buffered logging), or (b) Claude Code transcript schema may have changed. Please supply the session ID directly" >&2
      exit 1
    elif [ "$match_count" -gt 1 ]; then
      echo "probe-and-grep matched multiple transcripts; refusing to guess. Please supply the session ID directly" >&2
      exit 1
    fi
    active_transcript="$matches"
  fi
fi

# Step 2d: emit the last 40 lines of the chosen transcript on stdout, AND
# capture $active_transcript to a sentinel file so step 3(d)'s extension path
# can re-tail without re-running the full disambiguation cascade. The sentinel
# is overwritten on every park (single-user, single-machine workflow); a stale
# sentinel from a prior park is harmless because every park re-derives and
# rewrites it before the extension path is reachable.
mkdir -p "$HOME/.claude/plugins/data/claude-materia-claude-materia/park-session"
printf '%s\n' "$active_transcript" > "$HOME/.claude/plugins/data/claude-materia-claude-materia/park-session/.active-transcript"
tail -40 "$active_transcript"
```

Failure-mode notes for the probe-and-grep path inside the consolidated block:
- **Zero matches after the 2s retry** (3 seconds total wait): the block exits non-zero with the canonical message above; ask the user for the session ID directly.
- **Exactly one match**: that file is this session's transcript. Captured into `$active_transcript` and tailed by step 2d.
- **More than one match**: a real probe collision is implausible because every supported UUID source produces a strong UUID (see Edge cases — `uuidgen` not available; if none of `uuidgen`, `python3 -c uuid`, or `/proc/sys/kernel/random/uuid` is available, the skill fails loudly rather than inventing a weaker probe — collision risk is unacceptable on a destructive ID-resolution path). Multiple matches therefore indicate cross-contamination of project transcripts; the block exits non-zero with the canonical multi-match message above.

**Known fragility:** the probe-and-grep fallback depends on Claude Code logging bash tool invocations verbatim into the per-session JSONL transcript. This is undocumented internal harness behavior and may break across Claude Code versions. The fail-loud guards above are the defense.

### 3. Process the transcript tail and draft entry fields

Step 2's consolidated block emitted the chosen transcript's last 40 lines on stdout. Step 3 is **prose-only — no bash invocation** — it processes that captured tail to synthesize the entry fields. (Folding the tail-read into step 2 excises the cross-Bash-call handoff that previously discarded the disambiguation result on the probe-and-grep path.)

Process the captured tail in this order: (a) take the 40 lines emitted by step 2d as the working set; (b) filter out tool-result events larger than 4 KB (typically large file reads or command output) — they bloat the read budget without adding signal; (c) within the filtered set, count **substantive events** as the union of (i) `tool_use` events and (ii) assistant events whose text content exceeds 200 chars — each JSONL line counts at most once; (d) if the count is below 3, **re-tail only — do not re-run the full disambiguation cascade**. Read the sentinel file written at the end of step 2d and tail it directly: `tail -120 "$(cat ~/.claude/plugins/data/claude-materia-claude-materia/park-session/.active-transcript)"`. Re-filter the 120-line working set, stopping after at most 120 lines total. **If the post-extension count is still below 3, apply the low-confidence prefix per Edge cases.** The prefix fires only after the extension fails to recover; a 120-line tail that finds ≥3 substantive events is treated as a confident draft and no prefix is applied.

Synthesize from the filtered set:

- **Context**: one line describing what the user was working on. Be concrete ("debugging the auto-memory facelift on dotfiles repo"), not vague ("investigating stuff").
- **Next move**: the first concrete action to take when this session is resumed. The most important field — without it, resumption requires re-reading the whole transcript. Example: "re-run `pytest tests/test_memory.py::test_facelift_idempotent` and inspect the diff in `memory/MEMORY.md`."

Read the `context` field from the local config on every park. Treat the entire field as guidance the agent considers — interpret it as a system prompt for drafting and apply anything in it that could affect the current drafting decision (phrasing rules, content to include or exclude, path-equivalence aliases, terminology preferences, descriptive background that resolves an otherwise-ambiguous classification). There is no formal "directive vs descriptive note" distinction; err on the side of "yes, apply this" when in doubt, since `context` is user-authored and intentional. If the field is empty, draft normally.

(The 40-line tail is a deliberate tradeoff: enough to capture recent investigation state for typical sessions, small enough to read quickly. A long debugging session may have hundreds of relevant events further back; a quick park may happen before any meaningful events exist. The review pane in step 6 is the safety net — and the low-confidence draft prefix in Edge cases warns the user when the tail is sparse.)

### 4. Classify the cwd into a sub-section

If the config has no `sections:` array (flat layout), skip classification — the entry will be appended directly inside the fenced block with no sub-section. Proceed to step 5.

Otherwise, iterate the `sections:` array in declaration order. The first entry whose `cwd_glob` matches the current cwd wins. Match order is **declaration order, first match wins** — no longest-match or specificity heuristics. The last entry is guaranteed to be `cwd_glob: "*"` (the catch-all) because init normalizes the array on write — it appends `name: Other, cwd_glob: "*"` itself if the user-supplied or derived array does not already end with one. The runtime `park` workflow may rely on the catch-all being present.

**Glob semantics (matcher contract):**

Matcher: Python stdlib `fnmatch.fnmatch` against the tilde-expanded glob. Available on any Python 3 (no version pin). Tilde-expand the **glob** before matching; never un-expand or re-expand the cwd (the cwd is always passed as its absolute, tilde-free form).

```python
import fnmatch
import os

def matches(cwd: str, glob: str) -> bool:
    expanded = os.path.expanduser(glob)  # tilde-expand the glob, never the cwd
    return fnmatch.fnmatch(cwd, expanded)
```

Inline shell equivalent (used by the agent at park step 4): `python3 -c 'import fnmatch, os, sys; sys.exit(0 if fnmatch.fnmatch(sys.argv[1], os.path.expanduser(sys.argv[2])) else 1)' "$cwd" "$glob"` — exit 0 on match, 1 on no-match.

**Semantics (per Python stdlib `fnmatch`):**

- `*` matches any number of characters **including `/`**. There is no way to constrain `*` to a single path segment under `fnmatch` — this is the load-bearing limitation. Authors who need single-segment constraints must enumerate multiple `cwd_globs` at different prefix depths.
- `?` matches a single character including `/`.
- `[abc]` and `[a-z]` character classes work as in POSIX shell.
- `[!abc]` negation works as in POSIX shell.
- **`**` is redundant** — since `*` already crosses `/`, `~/workspaces/*` matches everything `~/workspaces/*/**` would have matched. Authors should write `*`, not `**`. **Authoritative behavior:** init normalizes `**` → `*` on write (with a one-line warning, see Local config schema validation rules) so that on-disk configs are always free of `**`. **Defense-in-depth:** the runtime classifier treats `**` and `*` as equivalent if encountered, so a hand-edited config that introduces `**` after init still classifies correctly. The runtime path is a fallback for hand-edited configs; init normalization is the canonical source.
- Tilde forms: only bare `~` (your `$HOME`) is supported, expanded via `os.path.expanduser`. `~user/...` (tilde-with-username) patterns are rejected at init validation with a clear message: `unsupported tilde form: only ~/ is supported, not ~user`. Embedded `~` not at the start of the glob is treated literally.
- The catch-all entry's `cwd_glob: "*"` works directly: `*` matches everything (including paths containing `/`). No special-case handling needed.
- Case sensitivity: `fnmatch.fnmatch` is case-sensitive on POSIX (macOS, Linux); the skill documents POSIX behavior as the contract. macOS HFS+/APFS default filesystems are case-insensitive at the storage layer, but the skill matches against the literal `pwd` string returned by the shell and does not attempt to mirror filesystem case-sensitivity. v1 does not expose a per-glob case-insensitive override.

Examples (with `$HOME=/Users/u`):
- `~/workspaces/*` expands to `/Users/u/workspaces/*` and matches `/Users/u/workspaces/foo`, `/Users/u/workspaces/foo/bar`, `/Users/u/workspaces/foo/bar/baz`. Does not match `/Users/u/workspaces` (no trailing chars after `workspaces/`).
- `~/projects/*` matches `/Users/u/projects/foo` AND `/Users/u/projects/foo/bar` (since `*` crosses `/`).
- `*` matches any cwd (catch-all).

### 5. Render the entry

Format:

```markdown
- **`<session-id>`** — parked YYYY-MM-DD
  - **Context:** <one-line context>
  - **Next move:** <one-line next move>
  - **Origin:** `<absolute cwd>`
```

Date source: today's local date at the moment of park (Claude's `currentDate` from the system reminder). Use absolute dates (per kernel convention — never "yesterday" or "Thursday").

### 6. Present review pane and write on confirm

Show the user:
- The destination file and (for sub-section layouts) the sub-section the entry will land in. For flat layout, omit the sub-section line — the entry lands directly inside the fenced block.
- The full rendered entry
- The drafted context and next-move (these are auto-generated; user can edit)

Prompt: `Confirm, edit, or cancel?` On `edit`, allow modifications to **context**, **next-move**, and (for sub-section layouts) **sub-section assignment** only. Date, origin, and session-ID are derived and cannot be edited inline. Remediation differs by field: **date** is derived from the system-reminder `currentDate` and re-running park on a different day will produce a different date. **Session-ID** is derived deterministically per session — re-running park always lands on the same answer (or fails the same way); if it is wrong, the slug or probe-and-grep step misfired, so supply the session ID directly per the failure-mode handling in step 2. **Origin** is descriptive metadata derived from the invocation cwd — if it is wrong, edit the entry in the destination file by hand after writing. For flat layout, sub-section assignment is not offered.

On confirm, apply the **Fence-block mutation procedure** (see Marker-fenced section) to insert the entry. For sub-section layouts, insert into the appropriate sub-section. For flat layout, insert directly inside the fences (treat the entire fenced block as the implicit single section). Most-recent entries go at the **top** of their (sub-)section (reverse chronological).

### 7. Audit nudge (conditional)

After writing, count entries older than the staleness threshold (default 30 days — chosen on the assumption that a session not revisited within a month is unlikely to be revisited at all; tune downward via `staleness_days` if you park aggressively, upward if your investigations span months).

**Age computation procedure:**
1. For each entry in the fenced block, parse the date from its header line (the `parked YYYY-MM-DD` suffix).
2. Compute `age_days = (today's local date) − (parsed date)` using `date.toordinal()`-style integer day-number subtraction (both dates as calendar dates, not timestamps). Reference is today's local date at park time (Claude's `currentDate` from the system reminder). Off-by-one errors near timezone changes or DST boundaries are accepted as low-impact (±1 day age skew on a multi-day staleness threshold).
3. Entries with missing or unparseable date suffixes (e.g., user hand-edited the header) are treated as `age_days = staleness_days` — i.e., they contribute to the nudge count. After the count, log a one-line warning listing the affected entry IDs so the user can repair them. (This biases toward over-nudging on hand-edited entries rather than silently ignoring them; the warning log lets the user repair headers and restore accurate counts. The opposite policy — treat unparseable as `age=0` — would underweight hand-edited entries and let the nudge mechanism go silent over time, which we judged worse since the audit nudge is the artifact's only built-in pressure-relief valve.)
4. An entry is "stale" if `age_days >= staleness_days`.

If the stale count is at or above the audit nudge threshold (default 5 — chosen as a soft signal that the registry is accumulating entries faster than the user is processing them; tune via `audit_nudge_threshold`), surface a single line:

```
Heads up: <N> parked entries are older than <T> days. Consider running `park-session audit`.
```

Do not nag further within a single park invocation; one line, then done. The nudge fires on **every** park while the stale count is at or above threshold — it is not rate-limited within a day. A user who parks 10 sessions while 5 stale entries exist will see the nudge 10 times. Suppress further nudges by running `audit` and reducing the stale count below threshold. The nudge fires only on `park` (not `list`) by design — `list` is a quick read-only inspection, and nagging on a passive surface erodes the signal. If you want a nudge without parking, run `audit` directly. (A v2 cool-down — e.g., once-per-day per destination — is a candidate refinement if the per-park firing proves too noisy in practice.)

## Workflow: init

Run on first invocation, when config is missing, or when the user asks to reconfigure.

### 1. Detect existing config

If `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml` exists, ask the user whether to overwrite, edit specific fields, or abort. Never silently overwrite.

### 2. Question 1 — destination

Ask: *"Where should I write parked-session entries?"*

No default. Validate the path with these rules:

- **Relative path**: reject with `absolute paths only — please re-supply a path beginning with / or ~`. Do not silently expand against any base.
- **Tilde-prefixed path**: only bare `~/` (followed by `/`) is supported; expand to `$HOME` via `os.path.expanduser` and proceed (e.g., `~/notes.md` → `$HOME/notes.md`). Reject `~user/...` (tilde-with-username) forms with `unsupported tilde form in destination '<path>': only ~/ is supported, not ~user`. This mirrors the `cwd_glob` tilde-form rule (see Local config schema validation rules) so the two config fields share one tilde contract.
- **Path is an existing directory**: reject with `<path> is a directory; please supply a file path`.
- **Parent directory does not exist** (one or more missing levels): prompt `parent directory <parent> does not exist. OK to create it? (y/n)`. On `y`, `mkdir -p <parent>` and proceed. On `n`, restart this question. (Skill-owned data directories under `~/.claude/plugins/data/` are created freely by step 7 because they are part of the skill's own footprint; user-owned content paths require explicit consent because they shape the user's filesystem.)
- **File does not exist** (parent exists): offer to create it. If declined, restart this question.
- **File exists**: confirm `OK to append a managed section to <path>?`. If declined, restart this question.

After the destination is confirmed, perform the **VCS-coverage check** described in the Recovery section: run `git -C <parent> rev-parse --show-toplevel`. If it fails (parent is not in a git working tree), surface the one-time warning from Recovery. Do not block init on the result.

### 3. Question 2 — layout

Ask: *"How should entries be grouped within the section?"*

Options:
- **(a) Flat list** — most recent on top, no sub-sections. Suitable for few sessions or no clear categories.
- **(b) Sub-sections derived from a catalog** — point at a markdown file describing your organizational structure (kinds index, GTD areas, project taxonomy) and the skill proposes sub-sections from it.
- **(c) Sub-sections you define directly** — list the sub-section names, and for each one a cwd glob pattern.

For (b), follow this precedence:

1. **Auto-derived path (preferred).** Trigger the Environment section's discovery (see Environment, below) and, if it produces a Park Layout proposal from `~/.claude/env/`, present that proposal first as a YAML draft for the user to review, edit, or reject.
2. **User-supplied path (fallback).** If no auto-derived proposal exists (bare environment, environment misconfigured, or the user rejected the auto-derived proposal), ask the user for a catalog path. Read it. Derive sub-section names and cwd glob patterns by inspecting the catalog's structure.

Either way, derivation is interpreted by the agent (Claude), not by regex — read the catalog like a human would, identify organizational categories, and propose `name + cwd_glob` for each. Present the proposal as YAML for the user to review and edit.

**Inference back-stop:** if the catalog does not contain explicit path patterns (it describes abstract categories, types, or topics rather than disk locations), the agent must invent `cwd_glob` patterns by inferring "where on disk does this category live." If the agent cannot infer a glob with high confidence for a given category, ask the user explicitly (`for category <X>, what cwd_glob should match it?`) rather than guessing. Listing the proposal as YAML with `cwd_glob: "?"` placeholders for low-confidence rows is fine — the user resolves them during review.

For (c): ask the user to provide names and globs directly.

For any layout that uses sub-sections (i.e., (b) and (c)): init normalizes the `sections:` array on write by appending `name: Other, cwd_glob: "*"` if it does not already end with that catch-all. After normalization the rule is always satisfied; the runtime `park` workflow may assume the catch-all is present. Flat layout (a) has no `sections:` array and therefore no catch-all requirement.

### 4. Question 3 — section header

Ask for the section header text. Default `## Parked Sessions`. Configurable in case of name collision in the destination file.

### 5. Free-form context (optional)

Ask: *"Any free-form notes about your system the skill should consider when re-deriving config later? (Optional. Useful for capturing system quirks, transitional moves, or directives like 'treat path X as equivalent to path Y'.)"*

Store as the `context` field in YAML.

### 6. Pre-write fence scan

Scan the destination file for **any** `<!-- *:start -->` or `<!-- *:end -->` park-session-style markers (regex `<!-- [a-z0-9-]+:(start|end) -->`), not just markers under the new config's `fence_id`. This catches the silent dual-fence case where a user runs init with one `fence_id`, then re-runs init with a different `fence_id` — a fence_id-scoped scan would miss the old fences and create a second parallel fenced block.

This scan runs **before** writing `config.yaml` (step 7) so that a scan failure leaves the on-disk state — both the config file and the destination file — completely unchanged. Re-running init after a scan failure produces the same diagnostic, not a half-applied config that the next invocation can no longer recover from.

The scan regex `[a-z0-9-]+` matches the schema's `fence_id` character set exactly (see Local config schema validation rules — `fence_id` must match `[a-z0-9-]+`, validated at init). Any `fence_id` that conforms to the schema is therefore guaranteed to be detected by this scan.

Classify the scan result:

- **Zero fences** (clean destination): proceed to step 7 (write config), then step 8 (initialize destination file).
- **Exactly one start-fence and exactly one end-fence in order, both under the new config's `fence_id`** (legitimate single fence pair): this is the re-init happy path. Init step 1 has already obtained the user's consent to overwrite via the existing-config prompt. **Leave the existing fence pair (and any user-authored content between them) in place**; step 8 will return without modifying the destination — the layout structure inside the fences is preserved across re-init. (The user's reason for re-running init is typically to change `section_header` or layout config; structural changes to the fenced block are out of scope for v1 re-init. To restructure entries inside an existing fence pair, edit by hand or remove the fences and re-run init.) **Layout-mode change guard**: if the new config flips between flat layout and sub-section layout, or the new config's `sections:` array names do not match (set equality, case-sensitive, no whitespace tolerance) the sub-section headers present inside the existing fenced block, fail loudly with `destination's existing fenced block has layout structure that does not match the new config (existing sub-sections: <list>; new config: <list or "flat">). Layout migration is manual: remove the existing fence pair from <path> by hand, then re-run init for a fresh start.` This prevents the next park from inserting into a sub-section header that does not exist in the on-disk block.
- **Exactly one start-fence and exactly one end-fence in order, but under a `fence_id` that does not match the new config's `fence_id`**: fail loudly with `destination contains fence pair with id <existing>; new config specifies <new>. Migration is manual: remove the old fences from <path> by hand, then re-run init.` Do not attempt automatic rename or migration in v1.
- **Singleton fence** (one start, no end, or vice versa, regardless of `fence_id`): fail loudly with the canonical singleton-fence error message (see Marker-fenced section).
- **Multiple start-fences or multiple end-fences anywhere in the file** (any combination of `fence_id`s): fail loudly with the canonical multi-fence error message (see Marker-fenced section), with guidance to remove the extras before re-running init.

On any failure outcome above, exit without writing config or modifying the destination. This guards against init creating an inconsistent multi-fence file that every subsequent invocation would then refuse to mutate, and against silent layout-drift between the on-disk fenced block and the new config — and ensures the on-disk config never gets ahead of the destination.

### 7. Write config

The pre-write fence scan in step 6 has passed. Create `~/.claude/plugins/data/claude-materia-claude-materia/park-session/` if needed. Write the YAML config (see schema below). Do not include any timestamp, comment, or metadata that doesn't help the user — the config is hand-editable and should stay terse.

### 8. Initialize destination file

If step 6's scan found a legitimate single fence pair under the new config's `fence_id` (the re-init happy path), return without modifying the destination — the existing fenced block is preserved.

Otherwise (step 6 found zero fences):

- If the destination file doesn't have the section header yet, append it (and a blank line, then the marker-fenced block) at the end of the file.
- If it has the header but no fences, insert the fence pair **at the end of the section**. The section is everything from the matched header up to the next heading at the same depth (e.g., the next `##` if the section header is `## Parked Sessions`) or shallower (`#`), or end-of-file. Fences go at the very end of that span. User-authored deeper subsections (e.g., `###`) inside the section remain inside the section, above the fences, untouched. Existing user content stays in its original position, outside the fences. After initialization, the skill never reads or writes outside the fences. Never delete or rearrange any existing content in the destination file.

The initial fenced block contains the empty sub-sections derived from layout config:

```markdown
## Parked Sessions

<!-- park-session:start -->
### Workspace sessions

### Project sessions

### Other

<!-- park-session:end -->
```

For flat layout, the block is empty (entries get appended directly inside the fences).

**Partial-completion recovery:** if step 8 fails after step 7 has succeeded (config written, destination not initialized — disk full mid-write, permissions race, etc.), the on-disk state has config present but destination uninitialized. The next `park` invocation will hit the "no fence pair found" failure (per the Marker-fenced section rules) and direct the user back to init. Re-running init detects the existing config at step 1 and offers to overwrite; choosing overwrite re-runs step 8 idempotently — step 6's pre-write fence scan will correctly find zero fences and proceed.

## Workflow: unpark

Argument: `<session-id>` (or a **prefix** of an entry's session ID that uniquely matches one entry).

1. Read the destination file's fenced block and parse all entries.
2. Locate the entry by matching `<session-id>` against the **session ID field only** (the `<session-id>` in each entry's header). Match rules:
   - **Case-sensitive.**
   - **Prefix match only**: the argument must equal the first N characters of an entry's session ID. Substring-anywhere matching is **not** used — typing the middle or end of a UUID returns zero matches even if the substring appears within an entry. This mirrors the convention used by `git`, Docker, and other UUID-keyed systems and keeps the false-multi-match rate predictable.
   - **Prefix length**: must be at least 8 characters. Reject shorter arguments with `unpark argument must be at least 8 characters to avoid accidental wrong-entry matches`.
   - **Field scope**: match against session IDs only — never against context, next-move, or origin fields.
   - **Result handling:**
     - **Exactly one match** → proceed to step 3.
     - **More than one match** → surface all candidate entries (full headers) and ask the user to disambiguate by re-running with a longer prefix or the full ID. Never delete on ambiguous match.
     - **Zero matches** → report `no entry matches <arg>` and exit without modification. Do not prompt for a new argument; the user can re-invoke.
3. Render the entry to the user and prompt: `Confirm unpark, or cancel?` Edit is not offered — re-run park if the entry contents are wrong; unpark only removes.
4. On confirm, apply the **Fence-block mutation procedure** (see Marker-fenced section) to remove the entry's lines from the fenced block.

## Workflow: list

Read the fenced block. For sub-section layouts, print all entries in their current file-encountered order, grouped by sub-section (most recent first per the park-time reverse-chronological insert rule). For flat layout (no sub-sections), treat the entire fenced block as the implicit single section and print entries in file order (also most recent first per the same rule). Render each entry's header line as `**<session-id>** — parked YYYY-MM-DD (Nd ago)` (with the relative-age suffix appended after the absolute date), followed by the entry body fields indented exactly as they appear in the destination file. Suffix format: **always days**, e.g. `(parked 0d ago)`, `(parked 1d ago)`, `(parked 365d ago)`. No other units (no hours, no weeks, no years) — uniform units make the output sortable and predictable. **Unparseable date headers** (e.g., user hand-edited the header into a non-`YYYY-MM-DD` form) render the suffix as `(parked ?d ago)`. Read-only — the destination file is unchanged.

## Workflow: audit

Read the fenced block once at audit start and operate on that in-memory snapshot for sorting and per-entry display. See Known limitations for the concurrent-park-during-audit race.

For sub-section layouts, sort the in-memory snapshot oldest-first across all sub-sections. For flat layout (no sub-sections), treat the entire fenced block as the implicit single section and sort the whole snapshot oldest-first. **Unparseable date headers** (e.g., user hand-edited the header into a non-`YYYY-MM-DD` form) sort as `age = +infinity` so they surface first — the user encounters them early and can repair the date. For each entry, show one entry, prompt the user, wait for the reply, then proceed to the next:

- **keep**: leaves the entry as-is, moves to the next.
- **unpark**: applies the **Fence-block mutation procedure** (see Marker-fenced section) to remove the entry directly. The mutation procedure re-reads the file fresh per its existing contract and removes the target entry by session ID match. If the target entry no longer exists in the on-disk file (typically because audit's own previous unpark already removed it, or — rare — a hand-edit removed it before audit started), warn-and-skip with one line: `entry <session-id> no longer present in destination; skipping.` Audit performs the write itself — do not invoke the `unpark` subcommand path, since audit's per-entry prompt is itself the review step that the standalone `unpark` confirmation provides.
- **skip**: same as keep but signals "I looked at this and explicitly decided not to act." No state change in v1.
- **quit**: stops the audit loop.

Per-entry interaction is the design: do not batch-render entries with numbered prompts — the per-entry pause forces the user to consider each entry, which is the audit's purpose. For large registries (>20 entries) the user is expected to use `quit` mid-loop and re-run audit later.

After the loop (whether via `quit` or end-of-list), summarize: `N kept, N unparked, N skipped`. Counts cover only entries reviewed up to the point the loop ended. If the user used `quit`, also report `M unreviewed` where M is the remaining entry count.

## Local config schema

Path: `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`

```yaml
destination: ~/.claude/backlog.md
section_header: "## Parked Sessions"
fence_id: park-session
staleness_days: 30
audit_nudge_threshold: 5

context: |
  Free-form guidance about the user's system. Read by the skill during init,
  re-init, every park (for drafting), and any catalog-interpretation step.
  Treated as a system prompt for the agent — anything in this field that
  could affect drafting or classification is applied. No formal distinction
  between "directives" and "descriptive notes"; write it as you would
  brief a colleague.

sections:
  - name: Workspace sessions
    cwd_glob: "~/workspaces/*"
  - name: Project sessions
    cwd_glob: "~/projects/*"
  - name: Other
    cwd_glob: "*"
```

**Validation rules:**
- For sub-section layouts: every section must have `cwd_glob`. No exceptions. Init rejects user-supplied arrays missing `cwd_glob` on any entry.
- For sub-section layouts: the last section's `cwd_glob` must be `"*"` so unmatched cwds always classify. Init **normalizes on write** by appending `name: Other, cwd_glob: "*"` if the user-supplied or auto-derived array does not already end with the catch-all. After normalization the rule is always satisfied; the runtime `park` workflow may assume the catch-all is present.
- For flat layout: the `sections:` array is omitted entirely. No catch-all is required because no classification is performed.
- **Tilde form in `cwd_glob`**: only bare `~/` (your `$HOME`, expanded via `os.path.expanduser`) is supported. Init rejects `~user/...` (tilde-with-username) globs with `unsupported tilde form in cwd_glob '<glob>': only ~/ is supported, not ~user`. Embedded `~` not at the start of the glob is treated as a literal character.
- **`**` in `cwd_glob`**: treated as equivalent to `*` under `fnmatch` semantics (since `*` already crosses `/`). Init normalizes `**` to `*` on write and emits a one-line warning: `cwd_glob '<glob>' uses ** which is redundant under fnmatch; rewriting to *`. Authors should write `*`.
- `fence_id` becomes the marker string: `<!-- {fence_id}:start -->` / `<!-- {fence_id}:end -->`. Must match the regex `[a-z0-9-]+` (lowercase ASCII letters, digits, and hyphens; non-empty). Init validates this **before** the pre-write fence scan (step 6) — i.e., as soon as a non-default `fence_id` is supplied (or, for the default `park-session`, the validation is trivially satisfied) — and rejects out-of-class characters with `fence_id '<value>' contains invalid characters; must match [a-z0-9-]+ (lowercase letters, digits, hyphens)`. The narrow character class keeps the pre-write fence scan regex simple and prevents dual-fence orphans where a permissive `fence_id` slips past the scan. **Set-once**: re-running init with a different `fence_id` against an already-initialized destination is rejected by the pre-write fence scan (see Workflow: init step 6). Migration is manual: remove the old fences from the destination by hand, then re-run init. v1 does not auto-migrate.

## Marker-fenced section

The skill manages a section inside a user-owned destination file. To find its section reliably without clobbering user content, it uses HTML comment markers. The marker name is the configured `fence_id` (default `park-session`). All `{fence_id}` placeholders below are substituted with the configured value at message-emit time; the example block uses the default for readability:

```markdown
<!-- park-session:start -->
... skill-managed content ...
<!-- park-session:end -->
```

**Rules:**
- After initialization, the skill reads and writes only between the fences (init itself writes the fence markers and, if needed, the section header).
- **Exactly one start-fence and exactly one end-fence present**, in that order: that's the contract — proceed.
- **Both fences missing** (destination uninitialized): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> is not initialized: no `<!-- {fence_id}:start -->` / `<!-- {fence_id}:end -->` fence pair found. Run `park-session init` to initialize.
  ```
- **Exactly one fence present** (singleton — file corrupted): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> is in an inconsistent state: found `<!-- {fence_id}:start -->` but no matching end fence (or vice versa). The skill will not modify it. To fix: either remove the orphan fence and re-run `park-session init`, or restore the matching fence by hand.
  ```
- **More than one start-fence OR more than one end-fence** present anywhere in the file (e.g., a markdown code block in the file contains the literal fence strings): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> contains multiple `<!-- {fence_id}:start -->` or `<!-- {fence_id}:end -->` markers; the skill cannot determine which is authoritative. Please remove the extras manually (or move them inside indented/escaped code blocks) and re-run.
  ```

  Do not attempt automatic disambiguation.

HTML comments are valid markdown (per CommonMark and GFM) and are stripped from rendered output by all standard renderers. They appear as comments in editors, signaling to the user that the section is tool-managed.

### Fence-block mutation procedure

All write paths (`park` step 6 append, `unpark` step 4 remove, `audit` unpark action) share this single contract:

1. Read the destination file in full.
2. Validate the fence pair per the Rules above. Fail loudly on any violation; do not attempt to repair.
3. Mutate only the entry being inserted or removed; do not reflow existing entries' whitespace, blank lines, or indentation. Match the existing inter-entry separator (typically one blank line between entries) when inserting; if the (sub-)section is empty, insert directly after the (sub-)section header with one blank line before the entry. Sub-section headers live **inside** the fences (they are skill-managed; init step 8 — Initialize destination file — writes them as part of the initial fenced block) and are not touched by per-entry mutation: only entry insert/remove changes the block. Content **outside** the fences — including the user's section header, surrounding prose, and any other content elsewhere in the destination file — is never touched and remains byte-for-byte.
4. Write the modified file back atomically: write to a sibling temp file in the same directory, then `mv` over the original (POSIX same-directory `mv` is atomic on every filesystem the skill targets — ext4, APFS, HFS+, ZFS, and native Linux filesystems on WSL2; note that NTFS accessed via `/mnt/c/...` from WSL2 does **not** provide guaranteed POSIX rename atomicity and is out of scope for the v1 atomicity claim). If the temp-file write fails, surface the underlying error and leave the destination untouched. If the `mv` fails, attempt to remove the temp file (best-effort cleanup); surface the original `mv` error to the user and leave the destination untouched.

This procedure is referenced by name from each write path. Any future change to the contract (e.g., adding a `flock` advisory lock around steps 1–4 to address the concurrent-write limitation between park and unpark, or switching to a different atomic-write strategy) is made here once.

## Edge cases

- **User has `cd`'d during the session**: derivation will fail with the no-transcripts-found message in step 2b — `pwd` no longer reflects the invocation cwd that indexes the transcript directory. The user must either re-park before `cd`-ing (return to the invocation cwd via `cd -` or `cd <original>`, then re-run park) or supply the session ID directly via a future flag (deferred for v2).
- **Multiple recently-modified transcripts in same cwd** (typically caused by concurrent sessions): use the probe-and-grep fallback from step 2 of park.
- **Transcript missing or unreadable**: fall back to asking the user for context and next-move directly. Do not park with empty fields.
- **Glob matches multiple sections**: declaration order, first match wins. Add a one-line comment above the `sections:` array in the config noting this: `# first match wins; last entry must be "*" catch-all`. No other comments in the config — keep it terse. Duplicate `cwd_glob` entries are accepted at write-time without warning; only the first by declaration order will ever match. Users editing their own config can resolve duplicates by hand.
- **Destination file missing**: init flow offers to create it. During park, if missing, fail and direct the user to init.
- **User edits inside the fenced block by hand**: respected — the skill re-parses the block on every read. Hand-edits to entry formatting or sub-section structure persist.
- **User edits outside the fenced block**: untouched. The skill never reads or writes outside the fences.
- **`uuidgen` not available**: use `python3 -c 'import uuid; print(uuid.uuid4())'` or `cat /proc/sys/kernel/random/uuid` (Linux) as fallback. If none of the three is available, fail loudly — do not invent a weaker probe (`$RANDOM`, `$$`, timestamps): collision risk is unacceptable for the destructive ID-resolution path in `park` step 2.
- **Cwd contains a backtick**: wrap the cwd in a backtick-run one longer than the longest backtick run that appears inside the cwd (CommonMark inline-code-span delimiter rule — backslashes inside `` `...` `` are literal characters, so escape sequences do not work). Example: cwd `/tmp/a` followed by a backtick followed by `b` renders as `` ``/tmp/a`b`` ``. (Backticks in cwds are rare but legal on POSIX; without this, the inline-code span breaks and corrupts the surrounding entry.)
- **Drafted context or next-move contains triple-backtick fences or newlines**: both fields must render as **single-line strings**. If the auto-draft contains triple-backtick sequences or newlines, collapse newlines to spaces and replace each triple-backtick with single-quoted code spans (e.g., rewrite ` ```pytest tests/foo.py``` ` as `` `pytest tests/foo.py` ``). If the field cannot be reduced to a clean single line, prefix the rendered draft with `(needs manual edit — see review pane)` and rely on the user to rewrite during step 6.
- **Low-confidence draft**: if the post-extension filtered transcript-tail set from park step 3 (after the 4 KB filter, and after the 120-line extension if step 3(d) triggered it) contains fewer than 3 substantive events — defined as the union of `tool_use` events and assistant events whose text content exceeds 200 chars, each JSONL line counted at most once — prefix the draft in the review pane with `(low-confidence draft — please review carefully)`. The prefix fires only after the 120-line extension has been tried and still failed to recover signal; a 40-line tail with <3 events is not low-confidence on its own. The user is more likely to rubber-stamp a confident-looking bad draft than to rewrite from scratch; the prefix is the friction.

## Recovery

The destination file is typically version-controlled (in stowed dotfiles, a notes repo, etc.). Deleted entries are recoverable via `git log -p <destination>`. The skill does not maintain its own archive — version control already serves that role.

If the user has no version control on the destination, recommend they enable it. **During init, after the destination is set (see Workflow: init step 2), check whether the destination's parent directory is inside a git working tree (`git -C <parent> rev-parse --show-toplevel`). If not, surface a one-time warning: `<destination> is not under version control; unpark and audit-unpark are destructive with no recovery. Consider `git init` in the directory.`** Do not block init on this; do not silently add an archive layer.

The check is best-effort: it succeeds inside ordinary working trees, submodules, and worktrees, but the meaning differs (a submodule's toplevel is the submodule, not the parent repo; bare repos have no working tree and the command fails; worktrees of unrelated repos pass the check without offering useful recovery for the destination). The warning is a heuristic, not a guarantee — users with heavy worktree usage may still want to manually verify their recovery story.

**Scale assumption:** designed for tens to low-hundreds of concurrent entries. The destination is a single markdown file read in full on every invocation. If you accumulate more (rare for the target persona), `list` and `audit` will become slow and the rendered file unwieldy — recommend periodic manual archival (move audit-skipped entries older than ~6 months into a separate file by hand). The skill does not auto-archive in v1.

## Known limitations

- **Concurrent destination writes between `park` and `unpark` are not protected.** The write paths (`park` append, `unpark` remove, `audit` unpark action) read the destination file, mutate the fenced block in memory, then write it back via the shared Fence-block mutation procedure (see Marker-fenced section). There is no inter-process file lock for these paths. If two `park` invocations from different sessions race against the same destination, the second writer can silently clobber the first writer's entry. This is acceptable for the v1 target persona because concurrent **parks** against the same destination are rare — parking is a deliberate teardown-time action, not steady-state work. Users tearing down many sessions in rapid succession against the same destination should serialize parks by hand.
- **Concurrent park during audit:** audit's display of pending entries is computed once at the start of the audit loop (the T0 snapshot). If a `park` invocation appends a new entry mid-audit, that entry won't appear in audit's prompts — it'll be visible on the next audit run. No data loss: audit's per-entry unpark routes through the Fence-block mutation procedure, which re-reads the destination fresh and surgically removes only the targeted entry by session-ID match, so concurrently parked entries are preserved on disk. The effect is purely a stale-display one. Users running concurrent park and audit (e.g., across multiple tmux sessions) should sequence them manually if seeing the freshest entry list mid-audit matters.
- **Probe-and-grep depends on undocumented Claude Code behavior.** Specifically, the disambiguator depends on Claude Code's bash tool logging the resolved command (post-shell-substitution, with `${uuid}` already substituted) into the session's JSONL transcript. If this behavior changes in a future Claude Code release (e.g., the harness logs the pre-substitution command parameter instead), the disambiguator will fail closed: no probe match, fall back to the manual session-ID supply path, never silently misidentifies. See "Concurrent-session disambiguation" in `park` step 2 for the failure modes and guards.
- **Session-invocation cwd derivation depends on the user not having `cd`'d during the session.** Claude Code's bash tool persists working-directory state across invocations, so any user `cd` shifts `pwd` away from the invocation cwd that indexes the transcript directory under `~/.claude/projects/<slug>/`. When that happens, slug derivation returns a non-existent path and step 2b's no-transcripts-found message fires. This is a present-tense failure mode, not a future-contract concern: any session where the user has issued `cd` mid-session and then invokes `park` will hit this. Workaround: `cd` back to the invocation cwd before parking, or supply the session ID directly via a future flag (deferred for v2). See the corresponding Edge case for the user-facing remediation.
- **Mechanical pieces are described in prose, not extracted as helper scripts.** Session ID derivation, fence-block I/O, and glob classification are re-derived from this document on every invocation. This is a deliberate v1 choice to keep the skill self-contained; a v2 refactor could extract `helpers/session_id.sh` and `helpers/fence_io.py` for stability and testability.
- **The init workflow is sprawling.** Init currently handles ~14 distinct responsibilities across ~95 lines: destination validation, layout selection, env-relevance-map construction, env-derived layout proposal, user-supplied catalog interpretation with inference back-stop, user-direct sub-section definition, catch-all normalization, section header configuration, free-form context capture, config schema write, destination file initialization with pre-write fence scan and re-init happy-path handling, fence placement, and the VCS coverage check. This is v1-acceptable but a v2 refactor candidate: factor into named sub-procedures (`validate-destination`, `propose-layout`, `write-config`, `initialize-destination-file`, `vcs-check`) with explicit handoffs. **Promotion criterion**: refactor when init grows by another ~20 lines or one more distinct responsibility, whichever comes first — at that point the documentation cost of holding all responsibilities in one workflow exceeds the cost of the structural split.

## Dependencies

- **Python 3** (any version) for `park` glob classification and the probe-and-grep mtime computation. The skill matches globs via stdlib `fnmatch.fnmatch` after tilde-expanding the glob with `os.path.expanduser` (see `park` step 4 — Glob semantics), and reads file mtimes via `os.path.getmtime` (portable across macOS BSD and GNU Linux without flag selection). Both modules ship with every Python 3 install; no version constraint applies. Stdlib `uuid` is also used as a fallback UUID source. Only `park` uses Python; `unpark`, `list`, and `audit` do not need it.
- **A UUID source** for the `park` step 2 probe-and-grep fallback path. Any of the following suffices, tried in order: `uuidgen`, `python3 -c 'import uuid; print(uuid.uuid4())'` (uses stdlib `uuid`, works on any Python 3), or `cat /proc/sys/kernel/random/uuid` (Linux only). If none is available, the probe-and-grep fallback fails loudly — a weaker probe (`$RANDOM`, `$$`, timestamps) is not acceptable on a destructive ID-resolution path. The fallback is only invoked when the mtime-trick disambiguator is ambiguous (concurrent sessions in the same cwd within 60 seconds); the common-case `park` path never triggers it.
- **`jq`** for parsing transcript JSONL events. Only `park` uses `jq`; `unpark`, `list`, and `audit` operate on the destination markdown file and do not need it.
- **`grep`** with standard `-l` (list-files-with-matches) line-formatting behavior — one path per line, no trailing whitespace. Used by `park` step 2's probe-and-grep disambiguator (the `match_count` math depends on this format). True on macOS BSD `grep` and GNU/Linux `grep`; documented explicitly because it is a portable assumption rather than a documented contract.
- **`git`** is optional and only used by init's VCS-coverage check (a one-time best-effort warning). The skill operates without it — the warning is informational only.

---

## Environment

This skill extends with environment context. Unlike workflow skills that read the environment on every invocation, park-session reads the environment only during `init` (or re-init). Subsequent `park`, `unpark`, `list`, and `audit` invocations consume the local config without re-reading the environment — this keeps action-mode fast and predictable.

**When environment discovery runs:** lazily, as a sub-step of init question 2(b), only when the user picks option (b). Steps 1–5 below are gated on that choice. The relevance map is shown to the user at that point. This avoids running discovery for users who pick flat layout (a) or who define sub-sections directly (c) — neither path consumes the derived Park Layout.

During `init` (within question 2(b)):

1. Check if `~/.claude/env/` exists.
   - If `~/.claude/env/` does not exist: bare environment. Skip the auto-derivation steps (2–5) below. Option (b) in question 2 remains available as a user-supplied catalog path. Tell the user no environment was found.
   - If `~/.claude/env/` exists but `index.md` is absent or unreadable: warn the user that the environment appears misconfigured. Skip auto-derivation; option (b) still falls back to a user-supplied catalog path. Do not silently degrade.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: print to the user as a brief table (`entry | relevant? | rationale`) listing every entry in the index. The user sees which entries were considered and why each was kept or excluded. "No silent dropping" means no entry is omitted from the printed table — exclude by marking `relevant?: no`, never by leaving a row out.
4. For relevant entries (typically those describing organizational categories — kinds, areas, taxonomy, container types), read those files and derive **Park Layout**: a list of `name + cwd_glob` pairs suitable for the `sections:` array in config.
5. Present the derived Park Layout to the user as a YAML proposal during question 2(b). The user reviews, edits, and confirms.

When the user re-runs `init` later (e.g., after restructuring their environment), the `context` field from the existing config is read and included in the relevance-map reasoning so the skill can incorporate the user's running narrative about system changes.
