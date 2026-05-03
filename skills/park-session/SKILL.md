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
| `audit` | Walk entries oldest-first, prompting keep/unpark/skip on each. |

If the user's intent is ambiguous, default to `park`.

## Workflow: park (default)

### 1. Load config or fall through to init

Read the local config at `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`. If it doesn't exist, tell the user "no config found, running init first" and do the init workflow before continuing. Do not proceed with park silently if config is missing — the destination is unknown.

### 2. Derive the current session ID

Claude Code does not expose the session ID via environment variable. Derive it from the active transcript file:

```bash
# Canonical cwd: the cwd Claude Code was invoked from for this session
# (NOT the bash tool's current cwd — the Claude Code Bash tool resets cwd between
# calls, so `pwd` in a fresh bash invocation is unreliable. Read the cwd from the
# system reminder at session start, or from a transcript event's `cwd` field).
# Mid-session `cd` does not change the slug.
# Project slug encoding: cwd with / replaced by - and a leading -
session_cwd="<cwd Claude Code was invoked from>"
slug=$(printf '%s' "$session_cwd" | sed 's|/|-|g')
# Find the most recently modified transcript in the project's session dir
ls -t ~/.claude/projects/${slug}/*.jsonl 2>/dev/null | head -1
```

The basename without `.jsonl` is the session ID.

**Concurrent-session disambiguation (probe-and-grep fallback):** if the project dir contains two or more transcripts whose mtimes differ by less than 60 seconds, the mtime trick is ambiguous. Use this fallback. It exploits the fact that Claude Code logs every bash tool invocation (the literal command string, including arguments) into the current session's JSONL transcript. Issue a bash command containing a unique probe string, then grep the project's transcripts for that probe — the only transcript that contains it is this session's:

```bash
probe="park-probe-$(uuidgen)"
echo "$probe" > /dev/null    # output discarded; the bash invocation itself is what gets logged to the JSONL transcript
sleep 1                       # allow the harness to flush the bash event into the JSONL transcript
grep -l "$probe" ~/.claude/projects/${slug}/*.jsonl
```

Failure-mode handling for the probe-and-grep:
- **Zero matches** (transcript not yet flushed, or harness schema changed): wait 2 seconds and retry the grep once. If still zero, fail loudly with `unable to derive session ID via probe-and-grep — Claude Code transcript schema may have changed; please supply the session ID directly` and ask the user for the session ID.
- **Exactly one match**: that file is this session's transcript. Proceed.
- **More than one match** (probe collision — implausible if `uuidgen` succeeded, possible if a weaker fallback was used): fail loudly with `probe-and-grep matched multiple transcripts; refusing to guess. Please supply the session ID directly`.

**Known fragility:** this fallback depends on Claude Code logging bash tool invocations verbatim into the per-session JSONL transcript. This is undocumented internal harness behavior and may break across Claude Code versions. The fail-loud guards above are the defense.

### 3. Read the transcript tail and draft entry fields

Read the **last 40 lines** of the transcript JSONL file (`tail -40`). Each line is a self-contained JSON event of varying type (user message, assistant message, tool use, tool result, system, meta). Skip tool-result events larger than 4 KB (typically large file reads or command output) when synthesizing — they bloat the read budget without adding signal. Synthesize:

- **Context**: one line describing what the user was working on. Be concrete ("debugging the auto-memory facelift on dotfiles repo"), not vague ("investigating stuff").
- **Next move**: the first concrete action to take when this session is resumed. The most important field — without it, resumption requires re-reading the whole transcript. Example: "re-run `pytest tests/test_memory.py::test_facelift_idempotent` and inspect the diff in `memory/MEMORY.md`."

Read the `context` field from the local config on every park. If it contains directives that affect drafting (phrasing rules, content to include or exclude, path-equivalence aliases, terminology preferences, anything the agent would otherwise have to guess), apply them to the draft. If the field is empty or contains only descriptive notes (not directives), draft normally.

(The 40-line tail is a deliberate tradeoff: enough to capture recent investigation state for typical sessions, small enough to read quickly. A long debugging session may have hundreds of relevant events further back; a quick park may happen before any meaningful events exist. The review pane in step 6 is the safety net — and the low-confidence draft prefix in Edge cases warns the user when the tail is sparse.)

### 4. Classify the cwd into a sub-section

If the config has no `sections:` array (flat layout), skip classification — the entry will be appended directly inside the fenced block with no sub-section. Proceed to step 5.

Otherwise, iterate the `sections:` array in declaration order. The first entry whose `cwd_glob` matches the current cwd wins. Match order is **declaration order, first match wins** — no longest-match or specificity heuristics. The user's last entry must have `cwd_glob: "*"` to serve as catch-all (init refuses to write a sub-section config that lacks it; see Validation rules).

**Glob semantics (pinned for stability across invocations):**
- Matcher: Python `pathlib.PurePosixPath(cwd).match(glob)`. If Python is unavailable, fall back to `fnmatch.fnmatch` semantics (a literal `**` is treated as `*` under fnmatch — accept this degradation and warn).
- Tilde expansion: expand the **glob** to `$HOME` before matching (do not un-expand the cwd). The cwd is always passed as its absolute, tilde-free form.
- `**` semantics: matches **zero or more** path segments. Examples (with `$HOME=/Users/u`):
  - `~/workspaces/*/**` matches `/Users/u/workspaces/foo`, `/Users/u/workspaces/foo/bar`, `/Users/u/workspaces/foo/bar/baz`. Does not match `/Users/u/workspaces`.
  - `~/projects/*` matches `/Users/u/projects/foo` only (single segment).
  - `*` matches any cwd (catch-all).
- Case sensitivity: matches the underlying filesystem (case-sensitive on Linux, case-insensitive on macOS HFS+/APFS-default).

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

Prompt: `Confirm, edit, or cancel?` On `edit`, allow modifications to **context**, **next-move**, and (for sub-section layouts) **sub-section assignment** only. Date, origin, and session-ID are derived and cannot be edited inline — re-run park if they are wrong. For flat layout, sub-section assignment is not offered.

On confirm, append the entry inside the marker-fenced block in the destination file (see "Marker-fenced section" below). For sub-section layouts, append into the appropriate sub-section. For flat layout, append directly inside the fences (treat the entire fenced block as the implicit sub-section). Most-recent entries go at the **top** of their (sub-)section (reverse chronological).

### 7. Audit nudge (conditional)

After writing, count entries older than the staleness threshold (default 30 days — chosen on the assumption that a session not revisited within a month is unlikely to be revisited at all; tune downward via `staleness_days` if you park aggressively, upward if your investigations span months).

**Age computation procedure:**
1. For each entry in the fenced block, parse the date from its header line (the `parked YYYY-MM-DD` suffix).
2. Compute `age_days = (today's local date) − (parsed date)` — both as calendar dates, not timestamps. Reference is today's local date at park time (Claude's `currentDate` from the system reminder).
3. Entries with missing or unparseable date suffixes (e.g., user hand-edited the header) are treated as `age_days = staleness_days` — i.e., they contribute to the nudge count. After the count, log a one-line warning listing the affected entry IDs so the user can repair them.
4. An entry is "stale" if `age_days >= staleness_days`.

If the stale count is at or above the audit nudge threshold (default 5 — chosen as a soft signal that the registry is accumulating entries faster than the user is processing them; tune via `audit_nudge_threshold`), surface a single line:

```
Heads up: <N> parked entries are older than <T> days. Consider running `park-session audit`.
```

Do not nag further; one line, then done. The nudge fires only on `park` (not `list`) by design — `list` is a quick read-only inspection, and nagging on a passive surface erodes the signal. If you want a nudge without parking, run `audit` directly.

## Workflow: init

Run on first invocation, when config is missing, or when the user asks to reconfigure.

### 1. Detect existing config

If `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml` exists, ask the user whether to overwrite, edit specific fields, or abort. Never silently overwrite.

### 2. Question 1 — destination

Ask: *"Where should I write parked-session entries?"*

No default. Validate the path with these rules:

- **Relative path**: reject with `absolute paths only — please re-supply a path beginning with / or ~`. Do not silently expand against any base.
- **Tilde-prefixed path** (e.g., `~/notes.md`): expand to `$HOME` and proceed.
- **Path is an existing directory**: reject with `<path> is a directory; please supply a file path`.
- **Parent directory does not exist** (one or more missing levels): reject with `parent directory <parent> does not exist; please create it first or supply a different path`. Do **not** `mkdir -p` silently — creating directory trees in user space without explicit consent is out of scope.
- **File does not exist** (parent exists): offer to create it. If declined, restart this question.
- **File exists**: confirm `OK to append a managed section to <path>?`. If declined, restart this question.

### 3. Question 2 — layout

Ask: *"How should entries be grouped within the section?"*

Options:
- **(a) Flat list** — most recent on top, no sub-sections. Suitable for few sessions or no clear categories.
- **(b) Sub-sections derived from a catalog** — point at a markdown file describing your organizational structure (kinds index, GTD areas, project taxonomy) and the skill proposes sub-sections from it.
- **(c) Sub-sections you define directly** — list the sub-section names, and for each one a cwd glob pattern.

For (b), follow this precedence:

1. **Auto-derived path (preferred).** If the Environment section's discovery has already produced a Park Layout proposal from `~/.claude/env/`, present that proposal first as a YAML draft for the user to review, edit, or reject.
2. **User-supplied path (fallback).** If no auto-derived proposal exists (bare environment, environment misconfigured, or the user rejected the auto-derived proposal), ask the user for a catalog path. Read it. Derive sub-section names and cwd glob patterns by inspecting the catalog's structure.

Either way, derivation is interpreted by the agent (Claude), not by regex — read the catalog like a human would, identify organizational categories, and propose `name + cwd_glob` for each. Present the proposal as YAML for the user to review and edit.

**Inference back-stop:** if the catalog does not contain explicit path patterns (it describes abstract categories, types, or topics rather than disk locations), the agent must invent `cwd_glob` patterns by inferring "where on disk does this category live." If the agent cannot infer a glob with high confidence for a given category, ask the user explicitly (`for category <X>, what cwd_glob should match it?`) rather than guessing. Listing the proposal as YAML with `cwd_glob: "?"` placeholders for low-confidence rows is fine — the user resolves them during review.

For (c): ask the user to provide names and globs directly.

For any layout that uses sub-sections (i.e., (b) and (c)): the final section **must** be `name: Other, cwd_glob: "*"` as the catch-all. Init appends this catch-all itself if the user-supplied or derived `sections:` array does not already end with one. Init refuses to write a sub-section config that lacks a `*` catch-all — without it, sessions in unmatched cwds cannot be classified. Flat layout (a) has no `sections:` array and therefore no catch-all requirement.

### 4. Question 3 — section header

Ask for the section header text. Default `## Parked Sessions`. Configurable in case of name collision in the destination file.

### 5. Free-form context (optional)

Ask: *"Any free-form notes about your system the skill should consider when re-deriving config later? (Optional. Useful for capturing system quirks, transitional moves, or directives like 'treat path X as equivalent to path Y'.)"*

Store as the `context` field in YAML.

### 6. Write config

Create `~/.claude/plugins/data/claude-materia-claude-materia/park-session/` if needed. Write the YAML config (see schema below). Do not include any timestamp, comment, or metadata that doesn't help the user — the config is hand-editable and should stay terse.

### 7. Initialize destination file

If the destination file doesn't have the section header yet, append it (and a blank line, then the marker-fenced block) at the end of the file. If it has the header but no fences, insert the fence pair **at the end of the section** — after all existing user content under that header but before the next sibling heading (or end-of-file). Existing user content stays in its original position, outside the fences. The skill never reads or writes outside the fences. Never delete or rearrange any existing content in the destination file.

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

## Workflow: unpark

Argument: `<session-id>` (or substring that uniquely matches one entry's session ID).

1. Read the destination file's fenced block and parse all entries.
2. Locate the entry by matching `<session-id>` against the **session ID field only** (the `<session-id>` in each entry's header). Match rules:
   - **Case-sensitive.**
   - **Substring length**: must be at least 8 characters. Reject shorter arguments with `unpark argument must be at least 8 characters to avoid accidental wrong-entry matches`.
   - **Field scope**: match against session IDs only — never against context, next-move, or origin fields.
   - **Result handling:**
     - **Exactly one match** → proceed to step 3.
     - **More than one match** → surface all candidate entries (full headers) and ask the user to disambiguate by re-running with a longer substring or the full ID. Never delete on ambiguous match.
     - **Zero matches** → report `no entry matches <arg>` and exit without modification. Do not prompt for a new argument; the user can re-invoke.
3. Render the entry to the user and ask for confirmation.
4. On confirm, remove the entry from the file, preserving all surrounding content (including other entries' formatting and any sub-section headers).

## Workflow: list

Read the fenced block. Print all entries in their current order, grouped by sub-section, with a relative-age suffix on each. Suffix format: **always days**, e.g. `(parked 0d ago)`, `(parked 1d ago)`, `(parked 365d ago)`. No other units (no hours, no weeks, no years) — uniform units make the output sortable and predictable. Read-only.

## Workflow: audit

Read the fenced block. Sort entries oldest-first across all sub-sections. For each, show the entry and prompt: keep / unpark / skip / quit.

- **keep**: leaves the entry as-is, moves to the next.
- **unpark**: removes the entry directly (audit performs the write itself — do not invoke the `unpark` subcommand path, since audit's per-entry prompt is itself the review step that the standalone `unpark` confirmation provides).
- **skip**: same as keep but signals "I looked at this and explicitly decided not to act." No state change in v1.
- **quit**: stops the audit loop.

After the loop, summarize: `N kept, N unparked, N skipped`. Counts cover only entries reviewed up to the point the loop ended. If the user used `quit`, also report `M unreviewed` where M is the remaining entry count.

## Local config schema

Path: `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`

```yaml
destination: ~/.claude/backlog.md
section_header: "## Parked Sessions"
fence_id: park-session
staleness_days: 30
audit_nudge_threshold: 5

context: |
  Free-form notes about the user's system. Read by the skill during init,
  re-init, and any catalog-interpretation step. Use for system quirks,
  transitional states, or directives the catalog doesn't capture.

sections:
  - name: Workspace sessions
    cwd_glob: "~/workspaces/*/**"
  - name: Project sessions
    cwd_glob: "~/projects/*/**"
  - name: Other
    cwd_glob: "*"
```

**Validation rules:**
- For sub-section layouts: every section must have `cwd_glob`. No exceptions.
- For sub-section layouts: the last section's `cwd_glob` must be `"*"` so unmatched cwds always classify. Init **refuses to write** a config violating this rule (and appends the catch-all itself if missing from a user-supplied or auto-derived array). The runtime `park` workflow may assume the catch-all is present.
- For flat layout: the `sections:` array is omitted entirely. No catch-all is required because no classification is performed.
- `fence_id` becomes the marker string: `<!-- {fence_id}:start -->` / `<!-- {fence_id}:end -->`. **Set-once**: changing `fence_id` after the destination file has been initialized leaves the old fences in place and the skill will fail to find its block. Migration is manual (rename the fences in the destination file by hand). v1 does not auto-migrate.

## Marker-fenced section

The skill manages a section inside a user-owned destination file. To find its section reliably without clobbering user content, it uses HTML comment markers:

```markdown
<!-- park-session:start -->
... skill-managed content ...
<!-- park-session:end -->
```

**Rules:**
- The skill reads and writes only between the fences.
- **Exactly one start-fence and exactly one end-fence present**, in that order: that's the contract — proceed.
- **Both fences missing** (destination uninitialized): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> is not initialized: no `<!-- park-session:start -->` / `<!-- park-session:end -->` fence pair found. Run `park-session init` to initialize.
  ```
- **Exactly one fence present** (singleton — file corrupted): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> is in an inconsistent state: found `<!-- park-session:start -->` but no matching end fence (or vice versa). The skill will not modify it. To fix: either remove the orphan fence and re-run `park-session init`, or restore the matching fence by hand.
  ```
- **More than one start-fence OR more than one end-fence** present anywhere in the file (e.g., a markdown code block in the file contains the literal fence strings): fail loudly with this exact message and exit without modifying the file:

  ```
  Destination file <path> contains multiple `<!-- park-session:start -->` or `<!-- park-session:end -->` markers; the skill cannot determine which is authoritative. Please remove the extras manually (or move them inside indented/escaped code blocks) and re-run.
  ```

  Do not attempt automatic disambiguation.

HTML comments are valid markdown (per CommonMark and GFM) and are stripped from rendered output by all standard renderers. They appear as comments in editors, signaling to the user that the section is tool-managed.

## Edge cases

- **Multiple recently-modified transcripts in same cwd** (typically caused by concurrent sessions): use the probe-and-grep fallback from step 2 of park.
- **Transcript missing or unreadable**: fall back to asking the user for context and next-move directly. Do not park with empty fields.
- **Glob matches multiple sections**: declaration order, first match wins. Add a one-line comment above the `sections:` array in the config noting this: `# first match wins; last entry must be "*" catch-all`. No other comments in the config — keep it terse.
- **Destination file missing**: init flow offers to create it. During park, if missing, fail and direct the user to init.
- **User edits inside the fenced block by hand**: respected — the skill re-parses the block on every read. Hand-edits to entry formatting or sub-section structure persist.
- **User edits outside the fenced block**: untouched. The skill never reads or writes outside the fences.
- **`uuidgen` not available**: use `python3 -c 'import uuid; print(uuid.uuid4())'` or `cat /proc/sys/kernel/random/uuid` (Linux) as fallback.
- **Cwd contains a backtick**: replace each backtick with the escape sequence `` \` `` before wrapping in inline-code in the rendered entry. (Backticks in cwds are rare but legal on POSIX; unescaped, they break the inline-code span and corrupt the surrounding entry.)
- **Drafted context or next-move contains triple-backtick fences or newlines**: both fields must render as **single-line strings**. If the auto-draft contains triple-backtick sequences or newlines, collapse newlines to spaces and replace each triple-backtick with single-quoted code spans (e.g., rewrite ` ```pytest tests/foo.py``` ` as `` `pytest tests/foo.py` ``). If the field cannot be reduced to a clean single line, prefix the rendered draft with `(needs manual edit — see review pane)` and rely on the user to rewrite during step 6.
- **Low-confidence draft**: if the transcript tail contains fewer than 3 substantive events (tool calls, file edits, or assistant messages over 200 chars), prefix the draft in the review pane with `(low-confidence draft — please review carefully)`. The user is more likely to rubber-stamp a confident-looking bad draft than to rewrite from scratch; the prefix is the friction.

## Recovery

The destination file is typically version-controlled (in stowed dotfiles, a notes repo, etc.). Deleted entries are recoverable via `git log -p <destination>`. The skill does not maintain its own archive — version control already serves that role.

If the user has no version control on the destination, recommend they enable it. **During init, after the destination is set, check whether the destination's parent directory is inside a git working tree (`git -C <parent> rev-parse --show-toplevel`). If not, surface a one-time warning: `<destination> is not under version control; unpark and audit-unpark are destructive with no recovery. Consider `git init` in the directory.`** Do not block init on this; do not silently add an archive layer.

**Scale assumption:** designed for tens to low-hundreds of concurrent entries. The destination is a single markdown file read in full on every invocation. If you accumulate more (rare for the target persona), `list` and `audit` will become slow and the rendered file unwieldy — recommend periodic manual archival (move audit-skipped entries older than ~6 months into a separate file by hand). The skill does not auto-archive in v1.

## Known limitations

- **Concurrent destination writes are not protected.** All three write paths (`park` append, `unpark` remove, `audit` unpark) read the destination file, mutate the fenced block in memory, then write it back. There is no file lock or atomic-rename procedure. If two `park` invocations from different sessions race against the same destination, the second writer can silently clobber the first writer's entry. This is acceptable for the v1 target persona (single user, personal markdown file, realistically zero concurrent-write contention) but the user should serialize parks if tearing down many sessions in rapid succession against the same destination.
- **Probe-and-grep depends on undocumented Claude Code behavior** (bash invocations logged verbatim into per-session JSONL transcripts). See "Concurrent-session disambiguation" in `park` step 2 for the failure modes and guards.
- **Mechanical pieces are described in prose, not extracted as helper scripts.** Session ID derivation, fence-block I/O, and glob classification are re-derived from this document on every invocation. This is a deliberate v1 choice to keep the skill self-contained; a v2 refactor could extract `helpers/session_id.sh` and `helpers/fence_io.py` for stability and testability.

---

## Environment

This skill extends with environment context. Unlike workflow skills that read the environment on every invocation, park-session reads the environment only during `init` (or re-init). Subsequent `park`, `unpark`, `list`, and `audit` invocations consume the local config without re-reading the environment — this keeps action-mode fast and predictable.

During `init`:

1. Check if `~/.claude/env/` exists.
   - If `~/.claude/env/` does not exist: bare environment. Skip the auto-derivation steps (2–5) below. Option (b) in question 2 remains available as a user-supplied catalog path. Tell the user no environment was found.
   - If `~/.claude/env/` exists but `index.md` is absent or unreadable: warn the user that the environment appears misconfigured. Skip auto-derivation; option (b) still falls back to a user-supplied catalog path. Do not silently degrade.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: print to the user as a brief table (`entry | relevant? | rationale`) listing every entry in the index. The user sees which entries were considered and why each was kept or excluded. "No silent dropping" means no entry is omitted from the printed table — exclude by marking `relevant?: no`, never by leaving a row out.
4. For relevant entries (typically those describing organizational categories — kinds, areas, taxonomy, container types), read those files and derive **Park Layout**: a list of `name + cwd_glob` pairs suitable for the `sections:` array in config.
5. Present the derived Park Layout to the user as a YAML proposal during question 2(b). The user reviews, edits, and confirms.

When the user re-runs `init` later (e.g., after restructuring their environment), the `context` field from the existing config is read and included in the relevance-map reasoning so the skill can incorporate the user's running narrative about system changes.
