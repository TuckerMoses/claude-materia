---
name: sidechat
description: Spin off a tangent into a new tmux window with its own Claude Code session, pre-loaded with context from the current conversation. Use whenever the user says "sidechat", "sidenote", "side quest", "tangent", "branch off", "spin up a session for", "open a window for", or expresses wanting to explore an idea without derailing the current thread. Also triggers on "I want to look into X separately", "chase that down in another session", or "let me come back to that" — a sidechat captures the thought immediately in a live, independent Claude session.
---

# Sidechat

Spin off a thought into its own Claude Code session in a new tmux window. The new session gets a context briefing from the current conversation so it can hit the ground running.

## How it works

The user has an idea or tangent mid-conversation that deserves its own thread. Instead of derailing the current session, you launch a new tmux window with Claude Code already primed with the relevant context.

## Steps

### 1. Extract a topic slug

From the user's sidechat prompt, derive a short topic label: 2-3 words, lowercase, hyphenated. Examples: `auth-refactor`, `inventory-state`, `tmux-plugins`. This is used for both the tmux window name and the Claude session name.

### 2. Compose the context briefing

Summarize the conversation context that would help orient the new session. Be selective — include what's load-bearing, skip what's noise. Aim for 10-15 lines max covering:

- **Working directory and project** — what repo/workspace this is, what it's for (use the current working directory unless the user specifies a different one — see step 4)
- **Current work** — what you and the user are actively doing (files, features, bugs, decisions)
- **Relevant constraints** — anything the sidechat session should know (tech choices, deadlines, preferences)
- **Key file paths** — files the sidechat is likely to need

The new session can explore the codebase on its own. Your job is orientation, not transcription.

**Directory override:** If the user mentions a specific directory or project path in their sidechat (e.g., "spin up a session in ~/projects/foo" or "sidechat about the auth service repo"), use that as the working directory instead. Mention the override in the context briefing so the new session understands why it's in a different directory than the parent conversation.

### 3. Compose the initial prompt

Build a single prompt that the new Claude session will receive as its first message:

```
## Context from a parallel session

Working directory: <cwd>

<Your context summary — project state, current work, relevant decisions>

## Task

<The user's sidechat prompt — include their words, expand slightly if needed for clarity to a fresh session>

---
This session was spun off from another conversation to explore a tangent. The context above is a summary to orient you — read the codebase directly for details.
```

### 4. Write the prompt file and launcher, then launch

Write the composed prompt to a tmp file, then create a self-cleaning launcher script that reads from it. This avoids heredoc quoting issues with complex prompts.

**Prompt file:** Write the composed prompt (from step 3) to `/tmp/sidechat-<topic>-<timestamp>.md`. Plain text, no escaping needed.

**Launcher script:** `/tmp/sidechat-<topic>-<timestamp>.sh`

```bash
#!/bin/bash
PROMPT_FILE="/tmp/sidechat-<topic>-<timestamp>.md"
cd "<current working directory>"
PROMPT=$(cat "$PROMPT_FILE")
rm -f "$PROMPT_FILE" "$0"
claude -n "sc-<topic>" "$PROMPT"
```

Make the launcher executable. Now decide **where** to launch it — query the current tmux window's pane count and decide:

```bash
PANE_COUNT=$(tmux display-message -p '#{window_panes}')
if [ "$PANE_COUNT" -ge 2 ]; then
  # Current window is already busy — give the sidechat its own window
  tmux new-window -n "sc-<topic>" "bash /tmp/sidechat-<topic>-<timestamp>.sh"
else
  # Only one pane here — split beside the current work
  tmux split-window -h "bash /tmp/sidechat-<topic>-<timestamp>.sh"
fi
```

**Why the branch:** if the current window only has one pane, splitting keeps the sidechat visually adjacent to the parent conversation — you can watch both at once without switching windows. But once the window has 2+ panes, further splitting crowds the layout, so a fresh window is the cleaner home. The session identity (`sc-<topic>`) is set by `claude -n` and is independent of window vs. pane, so `claude --resume` works the same either way.

### 5. Confirm and move on

Tell the user briefly:
- **Where it landed**: either the new tmux window name (findable via `Ctrl-b w` or by number), or that it was split into a new pane beside the current one (and which direction)
- A one-line summary of what context you forwarded
- That the session is named `sc-<topic>` so they can also find it later with `claude --resume`

Then **continue the current conversation** as if nothing happened. The whole point is to not lose the thread.

## Edge cases

- **Not in tmux**: If `tmux new-window` fails (user isn't in a tmux session), tell them and offer to print the composed prompt so they can paste it into a new terminal manually.
- **Long sidechat prompts**: If the user's sidechat is substantial (multiple paragraphs, specific instructions), include it verbatim rather than summarizing. The context summary is what you compress, not their request.
- **Multiple sidechats**: Each gets its own uniquely-named window and session. No conflicts.

---

## Environment

This skill extends with environment context. Before executing:

1. Check if `~/.claude/env/` exists.
   - If `~/.claude/env/` does not exist: bare environment. Execute with defaults
     and note that no environment was found.
   - If `~/.claude/env/` exists but `index.md` is absent or unreadable: warn the
     user that the environment appears misconfigured. Do not silently degrade.
   - If `~/.claude/env/index.md` exists: proceed to step 2.
2. Read the index to discover available environment heuristics.
3. Produce a **relevance map**: for each entry in the index, state whether
   it applies to this task and a brief rationale. No silent dropping —
   every entry gets an explicit disposition.
4. For relevant entries, read those files and derive
   **Session Context** scoped to the current task. Specifically:
   - **Routing**: if the sidechat involves creating artifacts, the new session
     should know where artifacts land in this environment.
   - **Conventions**: the new session should follow the same naming, commit,
     and workflow conventions as the parent.
   - Other entries: include if the sidechat's topic intersects that concern.
5. Include the derived Session Context in the composed prompt (step 3 above)
   so the new Claude session inherits environment awareness.
