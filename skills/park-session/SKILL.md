---
name: park-session
description: Use when the user wants to bookmark a Claude Code session for later resumption — phrases like "park this session", "save this for later", "checkpoint before I step away", "remember where I left off", "I want to come back to this", or when they mention tearing down tmux/terminals but worry about losing track of in-flight work. Also triggers on "list parked sessions", "what did I park", "audit parked sessions", "unpark <id>", or any reference to a registry of saved session pointers.
---

# Park Session

Bookmarks a Claude Code session by writing a structured pointer (session ID, when, what, next move) into a destination file the user controls. Lets you tear down ephemeral environments — close tmux windows, kill terminals, restart the machine — without losing the thread of mid-investigation work.

The skill never deletes anything automatically. Every entry leaves the registry only by the user's explicit action.

## Subcommands

| Subcommand | What it does |
|------------|-------------|
| `park` (default) | Bookmark the current session. Drafts the entry from the transcript, classifies the cwd into a sub-section, presents for review, writes on confirm. |
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
# Project slug encoding: cwd with / replaced by - and a leading -
slug=$(pwd | sed 's|/|-|g')
# Find the most recently modified transcript in the project's session dir
ls -t ~/.claude/projects/${slug}/*.jsonl 2>/dev/null | head -1
```

The basename without `.jsonl` is the session ID. **Concurrent-session caveat:** if multiple sessions share this cwd, the mtime trick can be ambiguous. To disambiguate, exploit the fact that Claude Code logs every bash tool invocation (the literal command string, including arguments) into the current session's JSONL transcript. Issue a bash command containing a unique probe string, then grep the project's transcripts for that probe — the only transcript that contains it is this session's:

```bash
probe="park-probe-$(uuidgen)"
echo "$probe" > /dev/null    # output discarded; the bash invocation itself is what gets logged to the JSONL transcript
grep -l "$probe" ~/.claude/projects/${slug}/*.jsonl
```

The file containing the probe is this session's transcript. Use this fallback whenever the project dir contains more than one recently-modified transcript.

### 3. Read the transcript tail and draft entry fields

Read the last ~20 entries of the transcript JSONL. Each line is a self-contained JSON event. Synthesize:

- **Context**: one line describing what the user was working on. Be concrete ("debugging the auto-memory facelift on dotfiles repo"), not vague ("investigating stuff").
- **Next move**: the first concrete action to take when this session is resumed. The most important field — without it, resumption requires re-reading the whole transcript. Example: "re-run `pytest tests/test_memory.py::test_facelift_idempotent` and inspect the diff in `memory/MEMORY.md`."

If the user's `context` field in the local config has guidance about phrasing or what to include, respect it.

### 4. Classify the cwd into a sub-section

If the config has no `sections:` array (flat layout), skip classification — the entry will be appended directly inside the fenced block with no sub-section. Proceed to step 5.

Otherwise, iterate the `sections:` array in declaration order. The first entry whose `cwd_glob` matches the current cwd wins. Match order is **declaration order, first match wins** — no longest-match or specificity heuristics. The user's last entry must have `cwd_glob: "*"` to serve as catch-all (enforced during init for any layout that uses sub-sections).

Glob semantics: standard shell-style globs against the absolute cwd. Tilde-prefixed patterns expand to `$HOME`. `**` matches any number of path segments.

### 5. Render the entry

Format:

```markdown
- **`<session-id>`** — parked YYYY-MM-DD
  - **Context:** <one-line context>
  - **Next move:** <one-line next move>
  - **Origin:** `<absolute cwd>`
```

Use absolute dates (per kernel convention — never "yesterday" or "Thursday").

### 6. Present review pane and write on confirm

Show the user:
- The destination file and the sub-section the entry will land in
- The full rendered entry
- The drafted context and next-move (these are auto-generated; user can edit)

Get explicit confirmation before writing. Allow inline edits to context, next-move, or sub-section assignment.

On confirm, append the entry to the appropriate sub-section inside the marker-fenced block in the destination file (see "Marker-fenced section" below). Most-recent entries go at the **top** of their sub-section (reverse chronological).

### 7. Audit nudge (conditional)

After writing, count entries older than the staleness threshold (default 30 days; configurable via `staleness_days` in config). If the count is at or above the audit nudge threshold (default 5; configurable via `audit_nudge_threshold`), surface a single line:

```
Heads up: <N> parked entries are older than <T> days. Consider running `park-session audit`.
```

Do not nag further; one line, then done.

## Workflow: init

Run on first invocation, when config is missing, or when the user asks to reconfigure.

### 1. Detect existing config

If `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml` exists, ask the user whether to overwrite, edit specific fields, or abort. Never silently overwrite.

### 2. Question 1 — destination

Ask: *"Where should I write parked-session entries?"*

No default. Validate the path's parent directory exists. If the file itself doesn't exist, offer to create it. If it exists, confirm the user is willing to have a managed section appended.

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

For (c): ask the user to provide names and globs directly.

For any layout that uses sub-sections (i.e., (b) and (c)): append a final section `name: Other, cwd_glob: "*"` as the catch-all. This is required for sub-section layouts — without it, sessions in unmatched cwds cannot be classified. Flat layout (a) has no `sections:` array and therefore no catch-all requirement.

### 4. Question 3 — section header

Ask for the section header text. Default `## Parked Sessions`. Configurable in case of name collision in the destination file.

### 5. Free-form context (optional)

Ask: *"Any free-form notes about your system the skill should consider when re-deriving config later? (Optional. Useful for capturing system quirks, transitional moves, or directives like 'treat path X as equivalent to path Y'.)"*

Store as the `context` field in YAML.

### 6. Write config

Create `~/.claude/plugins/data/claude-materia-claude-materia/park-session/` if needed. Write the YAML config (see schema below). Do not include any timestamp, comment, or metadata that doesn't help the user — the config is hand-editable and should stay terse.

### 7. Initialize destination file

If the destination file doesn't have the section header yet, append it followed by a marker-fenced block. If it has the header but no fences, add the fences inside the section. Never delete or rearrange any existing content in the destination file.

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

Argument: session ID (or substring that uniquely matches one entry).

1. Read the destination file's fenced block and parse all entries.
2. Locate the entry by ID (or the unique substring match).
3. Render the entry to the user and ask for confirmation.
4. On confirm, remove the entry from the file, preserving all surrounding content (including other entries' formatting and any sub-section headers).

If the ID doesn't match exactly one entry, surface candidates and ask the user to disambiguate. Never delete on ambiguous match.

## Workflow: list

Read the fenced block. Print all entries in their current order, grouped by sub-section, with a relative-age suffix on each (e.g., `(parked 12d ago)`). Read-only.

## Workflow: audit

Read the fenced block. Sort entries oldest-first across all sub-sections. For each, show the entry and prompt: keep / unpark / skip / quit.

- **keep**: leaves the entry as-is, moves to the next.
- **unpark**: removes the entry directly (audit performs the write itself — do not invoke the `unpark` subcommand path, since audit's per-entry prompt is itself the review step that the standalone `unpark` confirmation provides).
- **skip**: same as keep but signals "I looked at this and explicitly decided not to act." No state change in v1.
- **quit**: stops the audit loop.

After the loop, summarize: N kept, N unparked, N skipped.

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
- For sub-section layouts: the last section's `cwd_glob` must be `"*"` so unmatched cwds always classify. If it isn't, warn the user during init.
- For flat layout: the `sections:` array is omitted entirely. No catch-all is required because no classification is performed.
- `fence_id` becomes the marker string: `<!-- {fence_id}:start -->` / `<!-- {fence_id}:end -->`.

## Marker-fenced section

The skill manages a section inside a user-owned destination file. To find its section reliably without clobbering user content, it uses HTML comment markers:

```markdown
<!-- park-session:start -->
... skill-managed content ...
<!-- park-session:end -->
```

**Rules:**
- The skill reads and writes only between the fences.
- If both fences are present, that's the contract — proceed.
- If both fences are missing, the destination is uninitialized — fail loudly and direct the user to `init`.
- If exactly one fence is present, the file is corrupted — fail loudly and ask the user to fix or re-init. Do not attempt repair.

HTML comments are valid markdown (per CommonMark and GFM) and are stripped from rendered output by all standard renderers. They appear as comments in editors, signaling to the user that the section is tool-managed.

## Edge cases

- **Concurrent sessions in same cwd**: use the probe-and-grep trick from step 2 of park.
- **Transcript missing or unreadable**: fall back to asking the user for context and next-move directly. Do not park with empty fields.
- **Glob matches multiple sections**: declaration order, first match wins. Document this in the config comments.
- **Destination file missing**: init flow offers to create it. During park, if missing, fail and direct the user to init.
- **User edits inside the fenced block by hand**: respected — the skill re-parses the block on every read. Hand-edits to entry formatting or sub-section structure persist.
- **User edits outside the fenced block**: untouched. The skill never reads or writes outside the fences.
- **`uuidgen` not available**: use `python3 -c 'import uuid; print(uuid.uuid4())'` or `cat /proc/sys/kernel/random/uuid` (Linux) as fallback.

## Recovery

The destination file is typically version-controlled (in stowed dotfiles, a notes repo, etc.). Deleted entries are recoverable via `git log -p <destination>`. The skill does not maintain its own archive — version control already serves that role.

If the user has no version control on the destination, recommend they enable it. Do not silently add an archive layer.

---

## Environment

This skill extends with environment context. Unlike workflow skills that read the environment on every invocation, park-session reads the environment only during `init` (or re-init). Subsequent `park`, `unpark`, `list`, and `audit` invocations consume the local config without re-reading the environment — this keeps action-mode fast and predictable.

During `init`:

1. Check if `~/.claude/env/` exists.
   - If `~/.claude/env/` does not exist: bare environment. Skip the auto-derivation steps (2–5) below. Option (b) in question 2 remains available as a user-supplied catalog path. Tell the user no environment was found.
   - If `~/.claude/env/` exists but `index.md` is absent or unreadable: warn the user that the environment appears misconfigured. Skip auto-derivation; option (b) still falls back to a user-supplied catalog path. Do not silently degrade.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: for each entry in the index, state whether it could inform the destination choice or sub-section structure, and a brief rationale. No silent dropping.
4. For relevant entries (typically those describing organizational categories — kinds, areas, taxonomy, container types), read those files and derive **Park Layout**: a list of `name + cwd_glob` pairs suitable for the `sections:` array in config.
5. Present the derived Park Layout to the user as a YAML proposal during question 2(b). The user reviews, edits, and confirms.

When the user re-runs `init` later (e.g., after restructuring their environment), the `context` field from the existing config is read and included in the relevance-map reasoning so the skill can incorporate the user's running narrative about system changes.
