# Park Session

Bookmark a Claude Code session so you can come back to it later. Writes a structured pointer (session ID, when, what you were doing, what to do next, where you were) into a markdown file you control. Lets you tear down tmux windows, kill terminals, or restart the machine without losing the thread of mid-investigation work.

The skill never deletes anything automatically. Every entry leaves the registry only by your explicit action.

## How to invoke it

Talk to Claude in natural language. The skill triggers on phrases like:

- "park this session"
- "save this for later"
- "checkpoint before I step away"
- "remember where I left off"
- "I want to come back to this"
- "list parked sessions" / "what did I park"
- "audit parked sessions"
- "unpark `<session-id>`"

There are no slash commands; Claude reads the skill and runs the right workflow.

## First-time setup

The first time you trigger `park`, the skill notices there's no config and walks you through `init` before parking. You'll answer four questions:

1. **Destination file** — where parked-session entries should land. No default; supply an absolute path or `~/...` path. The skill will offer to create the file (and its parent directory, with consent) if missing. Most users point this at a personal backlog or notes file (e.g. `~/notes/sessions.md` or a stowed `~/.claude/backlog.md`).

2. **Layout** — how entries should be grouped within the section:
   - **(a) Flat list** — most recent on top, no sub-sections.
   - **(b) Sub-sections derived from a catalog** — point at a markdown file describing your organizational structure; the skill proposes sub-sections from it. If you have a `~/.claude/env/index.md` set up, the skill discovers it automatically.
   - **(c) Sub-sections you define directly** — list sub-section names and a `cwd_glob` pattern for each.

3. **Section header** — defaults to `## Parked Sessions`. Configurable in case of name collision in your destination.

4. **Free-form context (optional)** — any notes about your system the skill should consider when drafting entries. Treated as guidance for the agent on every park. Examples:
   - "treat `~/work/` as equivalent to `~/projects/`"
   - "prefer terse next-move phrasing"
   - "always mention the active git branch in context"

The skill then writes your config (`~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`) and initializes a marker-fenced block in your destination file. Your existing content in the destination is never touched outside the fences.

## Subcommand reference

| Subcommand | What it does |
|------------|-------------|
| `park` (default) | Bookmark the current session. The skill drafts the entry from the transcript, classifies your cwd into a sub-section if you have one, presents a review pane, writes on confirm. |
| `init` | Configure the destination, layout, and section structure. Run once before first park (or to reconfigure). |
| `unpark <session-id>` | Remove an entry. Confirmation prompt before deletion. |
| `list` | Show all parked entries with ages and sections. Read-only. |
| `audit` | Walk entries oldest-first, prompting `keep / unpark / skip / quit` on each. |

If your intent is ambiguous, the skill defaults to `park`.

### `park` — what to expect

When you say "park this session," the skill:

1. Derives your session ID from the active transcript (more on this in *How it works*).
2. Reads the last 40 transcript events and synthesizes drafts for two fields:
   - **Context** — one line on what you were doing.
   - **Next move** — the first concrete action to take when you resume.
3. Classifies your cwd into the right sub-section (if your layout uses them).
4. Shows a review pane with the destination, the sub-section, and the rendered entry.
5. Lets you edit `context`, `next-move`, and (for sub-section layouts) the sub-section assignment inline. The session ID, date, and origin cwd are derived and can't be edited inline — fix them by editing the destination file directly if needed.
6. On confirm, inserts the entry at the top of its sub-section.

Entries render as:

```markdown
- **`d8763b24-9a00-4878-855d-bcb46f447cfd`** — parked 2026-05-20
  - **Context:** debugging the auto-memory facelift on dotfiles repo
  - **Next move:** re-run `pytest tests/test_memory.py::test_facelift_idempotent` and inspect the diff in `memory/MEMORY.md`
  - **Origin:** `/Users/u/claude-config`
```

If the auto-draft has low confidence (the recent transcript is sparse — fewer than 3 substantive events after extending the tail to 120 lines), the draft is prefixed with `(low-confidence draft — please review carefully)`. The point is friction against rubber-stamping bad drafts when there isn't much to work with.

### `unpark <session-id>` — removal

You can supply the full session ID or a **prefix** (minimum 8 chars). Match is case-sensitive, prefix-only — typing the middle or end of a UUID returns zero matches. This mirrors `git`'s short-SHA convention and keeps false-multi-match rates predictable.

- Exactly one match → confirmation prompt, then removal.
- Multiple matches → candidates listed, re-run with a longer prefix.
- Zero matches → reports `no entry matches <arg>`.

### `list` — read-only

Prints all entries grouped by sub-section (or flat, depending on your layout). Each entry's header shows the absolute date plus a relative-age suffix: `(parked 0d ago)`, `(parked 12d ago)`, `(parked 365d ago)`. Always days, never hours or weeks.

### `audit` — bulk review

Walks the registry oldest-first, one entry at a time, with four options:

- `keep` — leave as-is, next entry.
- `unpark` — remove this entry (no separate confirmation — audit is itself the review).
- `skip` — leave but signal "I looked and decided not to act."
- `quit` — stop.

After the loop, summarizes counts: `N kept, N unparked, N skipped`, plus `M unreviewed` if you quit mid-loop.

Per-entry pacing is intentional — batched prompts encourage rubber-stamping; one-at-a-time forces consideration.

## Audit nudge

After a successful park, the skill counts entries older than `staleness_days` (default 30). If the count is at or above `audit_nudge_threshold` (default 5), you'll see one extra line:

```
Heads up: 7 parked entries are older than 30 days. Consider running `park-session audit`.
```

The nudge fires on every park while the threshold is exceeded — it's not rate-limited within a day. Run `audit` to reduce the count below threshold and suppress further nudges. The nudge fires only on `park`, not on `list` (nagging on a passive surface erodes the signal).

## Your config file

Lives at `~/.claude/plugins/data/claude-materia-claude-materia/park-session/config.yaml`. Hand-editable. Example:

```yaml
destination: ~/notes/sessions.md
section_header: "## Parked Sessions"
fence_id: park-session
staleness_days: 30
audit_nudge_threshold: 5

context: |
  Treat ~/work/ as equivalent to ~/projects/ — they're symlinked.
  Prefer terse next-move phrasing.

sections:
  - name: Workspace sessions
    cwd_glob: "~/workspaces/*"
  - name: Project sessions
    cwd_glob: "~/projects/*"
  - name: Other
    cwd_glob: "*"
```

Field reference:

- `destination` — file the skill writes entries into. Tilde-expanded; only bare `~/` supported (not `~user/`).
- `section_header` — the markdown header above the skill's fenced block. Configurable in case of collision.
- `fence_id` — name used in the HTML comment markers (`<!-- park-session:start -->` / `<!-- park-session:end -->`). Must be lowercase letters, digits, and hyphens. Set once at init — changing it requires manually removing old fences first.
- `staleness_days` — age threshold for the audit nudge. Default 30.
- `audit_nudge_threshold` — stale-entry count at which the nudge fires. Default 5.
- `context` — free-form guidance the skill reads on every park. Anything that could affect drafting or classification gets applied. Write it like you'd brief a colleague.
- `sections` — array of `{name, cwd_glob}` pairs for sub-section classification. First match wins, declaration order. Last entry must be `cwd_glob: "*"` (catch-all) — init normalizes the array to ensure this. Omit the array entirely for flat layout.

### Glob semantics for `cwd_glob`

Uses Python's stdlib `fnmatch.fnmatch` against the tilde-expanded glob. One important limitation: `*` crosses `/`. There's no way to constrain `*` to a single path segment. So `~/workspaces/*` matches `~/workspaces/foo` AND `~/workspaces/foo/bar/baz` — which is usually what you want for prefix-style classification, but if you need single-segment constraints, you'll have to list multiple globs at different depths.

`**` is redundant (since `*` already crosses `/`); init normalizes `**` → `*` on write with a warning.

## Your destination file

The skill writes only between marker comments. Your file ends up looking like:

```markdown
# My notes

(... whatever you already had here, untouched ...)

## Parked Sessions

<!-- park-session:start -->
### Workspace sessions

- **`<session-id>`** — parked 2026-05-20
  - **Context:** ...
  - **Next move:** ...
  - **Origin:** `...`

### Project sessions

### Other

<!-- park-session:end -->

(... more of your content, also untouched ...)
```

The HTML comments are valid markdown — they're stripped from rendered output by GitHub, Hugo, Jekyll, etc., but visible in editors so you can see what's tool-managed.

Hand-edits **inside** the fences (e.g., manually fixing a typo in an entry, moving an entry between sub-sections) are respected — the skill re-parses on every read. Hand-edits **outside** the fences are never touched, byte-for-byte.

## Resuming a parked session

Once you've parked a session, you can resume it any time with:

```bash
claude --resume <session-id>
```

The session ID is the first field in each parked entry. Drop into your terminal, run that command, you're back in the transcript exactly where you left off. Then run `unpark <session-id>` (full ID or 8+ char prefix) to remove it from the registry once you're done with it.

## Recovery

The skill maintains no archive. If you `unpark` an entry by mistake (or wholesale delete the destination file), recovery is via version control — `git log -p <destination>`. The skill recommends putting your destination in a git-tracked directory. At init, it does a one-time `git rev-parse` check on the destination's parent and surfaces a warning if it's not in a git working tree.

## Limitations to know

- **`*` in `cwd_glob` crosses `/`.** No way to express "exactly one path level." Most session-classification use cases don't need this.
- **Concurrent parks against the same destination can clobber.** No file lock. Single-machine workflow rarely hits this — parking is teardown-time, not steady-state. Serialize manually if you're tearing down many sessions in rapid succession.
- **Concurrent park during audit creates a stale-display effect (not data loss).** Audit's display is computed once at the start; entries parked mid-audit appear on the next audit run. No on-disk overwrite — the mutation procedure re-reads the file fresh per entry.
- **`cd` mid-session breaks session ID derivation.** Claude Code's bash tool persists working-directory state across invocations, so `cd` shifts `pwd` away from the invocation cwd that indexes the transcript directory. Workaround: `cd -` (or `cd <original>`) back to the invocation directory before parking.
- **Concurrent-session disambiguation depends on Claude Code's bash-tool logging behavior.** Specifically, the disambiguator relies on the harness logging post-substitution bash commands into the JSONL transcript. If that changes in a future Claude Code release, the disambiguator falls back to asking you for the session ID directly — it fails closed, never silently misidentifies.
- **Probe-and-grep sentinel race on the unhappy-path 120-line extension.** If two parks run truly concurrently in the same project dir, the sentinel file used to skip re-disambiguation can be overwritten. The agent will usually notice the tail content doesn't match the active session's recent activity and surface to you in the review pane. Mitigation: serialize parks across concurrent sessions if you're regularly hitting low-confidence drafts.
- **Init has ~14 distinct responsibilities** and is a v2 refactor candidate. No user-facing impact, just acknowledged design debt.

## How it works (one-paragraph pointer)

Claude Code doesn't expose the session ID via environment variable, so the skill derives it from disk: encode your `pwd` into a slug (`/` and `.` both become `-`), look up `~/.claude/projects/<slug>/`, find the most recently modified transcript JSONL there. For concurrent sessions in the same cwd, the skill falls back to a "probe-and-grep" trick — write a UUID via bash (Claude Code logs every bash invocation into the JSONL transcript), then grep for that UUID across all transcripts in the project dir; the unique match is yours.

For full implementation details (the consolidated bash block, edge cases, validation rules, mutation procedure), see [`SKILL.md`](./SKILL.md). That file is what the agent reads to execute — this README is the human-facing version.
