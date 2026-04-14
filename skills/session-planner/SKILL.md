---
name: session-planner
description: "Turn a list of todos into a live tmux workspace with intelligent layout. Analyzes tasks, decides which need a Claude Code session vs a raw terminal, proposes a tmux layout (windows, panes, dimensions), and launches everything with context-aware prompts injected into Claude panes. Use this skill whenever the user wants to parallelize work across multiple terminals, spin up sessions for a task list, dispatch todos to tmux, create a working session layout, or says things like 'let's spin these up', 'launch sessions for these', 'set up a workspace for these tasks', or 'let me work on all of these at once'. Also triggers when the user has been discussing multiple action items and wants to execute on them in parallel."
user-invocable: true
argument-hint: "[todos or 'these' to use items from conversation context]"
---

# Session Planner

Turn a todo list into a live tmux workspace. Each todo becomes a pane — some with Claude Code sessions already working, others as raw terminals ready for manual commands.

## How It Works

1. **Collect todos** — from the user's argument, or from conversation context if they say something like "these" or "spin these up"
2. **Classify each todo** — decide whether it needs a Claude session or a raw terminal
3. **Propose a layout** — design a tmux session with windows and panes sized to the actual screen
4. **Get user sign-off** — present the plan, let the user override classifications or layout
5. **Launch** — create the tmux session and inject prompts into Claude panes

## Phase 1: Collect and Classify Todos

### Collecting

If the user passed todos explicitly, use those. If they referenced conversation context ("these items", "the action items we discussed", or just invoked the skill mid-conversation), extract the relevant todos from the conversation history.

Each todo should be a short, actionable description. If the source material is vague, sharpen it — "fix the auth thing" becomes "Fix JWT token refresh logic in auth middleware."

### Classifying: Claude vs Raw

For each todo, decide whether it should get a **Claude session** or a **raw terminal**. The heuristic:

**Claude session** — the todo involves thinking, code changes, investigation, writing, or anything where Claude Code would be useful:
- "Refactor the database connection pooling"
- "Write tests for the payment module"
- "Investigate why the build is slow"
- "Draft the API design doc"

**Raw terminal** — the todo is a manual process, a long-running command, or something that needs human interaction:
- "Run the dev server"
- "Watch the test suite"
- "Monitor logs"
- "SSH into staging"
- "Run database migrations"

When in doubt, lean toward Claude — the user can always drop into the shell from a Claude session, but can't easily summon Claude into a raw terminal.

Present the classification to the user in a table:

```
 #  Todo                                    Type     Window
 1  Refactor auth middleware                 claude   1: auth
 2  Write API integration tests             claude   1: auth
 3  Run dev server                          raw      2: servers
 4  Fix dashboard chart rendering           claude   3: dashboard
```

The user can override any classification by saying things like "make #3 a claude session" or "2 should be raw."

## Phase 2: Design the Layout

### Screen Awareness

Before proposing a layout, get the actual terminal dimensions. If already inside tmux:

```bash
tmux display-message -p '#{window_width} #{window_height}'
```

If not inside tmux, fall back to:

```bash
tput cols && tput lines
```

Use these dimensions to make sensible layout decisions. A 200-column terminal can comfortably hold 2-3 side-by-side panes; an 80-column terminal probably shouldn't split horizontally at all.

### Layout Strategy

The goal is a layout that makes sense for the work, not a mechanical "one pane per todo." Think about:

- **Grouping related todos** into the same window. Todos that touch the same part of the codebase, or that have a natural relationship (e.g., "run dev server" + "test the UI"), belong together.
- **Window naming** should reflect the theme of the work in that window, not just "window-1."
- **Pane sizing** should reflect the nature of the work. A Claude session benefits from vertical space (lots of output). A log tail or dev server might be fine as a smaller pane.
- **Don't over-split.** More than 3-4 panes per window gets cramped. If there are many todos, use multiple windows rather than cramming everything into splits.

### Layout Rules of Thumb

| Screen width | Max horizontal splits | Notes |
|---|---|---|
| < 120 cols | 1 (no h-split) | Stack vertically or use separate windows |
| 120–200 cols | 2 side-by-side | Each pane gets ~60-100 cols |
| 200+ cols | 3 side-by-side | Ultrawide territory |

| Pane purpose | Minimum comfortable size |
|---|---|
| Claude session | 80 cols x 24 rows |
| Raw terminal (interactive) | 80 cols x 20 rows |
| Raw terminal (log tail/watch) | 60 cols x 10 rows |

### Present the Layout

Show the user a visual representation of the proposed layout. Use ASCII art or a simple diagram:

```
Session: project-work

Window 1: "auth" [focused]
┌─────────────────────┬─────────────────────┐
│ [claude] Refactor   │ [claude] Write API  │
│ auth middleware      │ integration tests   │
│                     │                     │
└─────────────────────┴─────────────────────┘

Window 2: "servers"
┌─────────────────────────────────────────────┐
│ [raw] Run dev server                        │
│                                             │
└─────────────────────────────────────────────┘

Window 3: "dashboard"
┌─────────────────────────────────────────────┐
│ [claude] Fix dashboard chart rendering      │
│                                             │
└─────────────────────────────────────────────┘
```

Wait for the user to approve or request changes before launching.

## Phase 3: Launch

The launch phase uses two bash scripts executed in sequence with a pause between them. The first script creates the tmux structure (session, windows, panes, layout). The second script injects commands into the now-ready panes. A 5-second sleep between them ensures all shells have fully initialized — this eliminates the race condition where `send-keys` fires before a shell is ready and the command gets swallowed silently.

### Script 1: Structure (`/tmp/session-planner-structure.sh`)

Creates the session, windows, panes, and layout. No commands are sent to panes yet.

```bash
#!/bin/bash
set -e

# Create the session with the first window
tmux new-session -d -s SESSION_NAME -n WINDOW_1_NAME -x WIDTH -y HEIGHT

# Additional windows
tmux new-window -t SESSION_NAME -n WINDOW_N_NAME

# Pane splits within a window
tmux split-window -t SESSION_NAME:WINDOW -h   # horizontal split (side by side)
tmux split-window -t SESSION_NAME:WINDOW -v   # vertical split (stacked)

# Apply an even layout after splitting (recommended before fine-tuning)
tmux select-layout -t SESSION_NAME:WINDOW even-horizontal  # or even-vertical, tiled

# Resize panes if needed
tmux resize-pane -t SESSION_NAME:WINDOW.PANE -x COLS
tmux resize-pane -t SESSION_NAME:WINDOW.PANE -y ROWS
```

### Wait for shells to initialize

After running the structure script, sleep 5 seconds before running the inject script:

```bash
sleep 5
```

This is deliberately generous — shell initialization (loading `.zshrc`, plugins, etc.) can take several seconds on configured machines. The cost of waiting an extra few seconds is negligible compared to a silently dropped command.

### Script 2: Inject (`/tmp/session-planner-inject.sh`)

Sends commands into the now-ready panes.

```bash
#!/bin/bash
set -e

# cd + claude for panes that need a working directory
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'cd /path/to/repo' Enter
sleep 0.5
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'claude "PROMPT_HERE"' Enter

# Direct claude for panes already in the right directory
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'claude "PROMPT_HERE"' Enter

# Raw terminal commands
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'npm run dev' Enter

# Focus the first window
tmux select-window -t SESSION_NAME:WINDOW_1_NAME
```

Use a 0.5-second sleep between sequential commands to the **same pane** (e.g., `cd` then `claude`). No sleep needed between commands to different panes — each has its own shell.

### Pane Indexing

After creating panes, tmux assigns indices starting from 1 (not 0). Always use `WINDOW_NAME.1`, `.2`, `.3` etc. in the script. If in doubt, query first:

```bash
tmux list-panes -t SESSION_NAME:WINDOW -F '#{pane_index}'
```

### Session Naming

Pick a descriptive session name based on the work theme. If ambiguous, use a timestamp-based name like `work-20260414`. Before creating, check for collisions:

```bash
tmux has-session -t SESSION_NAME 2>/dev/null && echo "EXISTS" || echo "CLEAR"
```

If it exists, append a number suffix rather than clobbering.

### Prompt Construction

**Working directory:** If a todo references or implies a specific repo or directory (from conversation context, file paths mentioned, or the todo text itself), `cd` to that directory before launching Claude. The current session's working directory is a strong default — if the user invokes the skill from within a repo and says "these todos," assume the todos live in that repo unless context says otherwise.

**Claude pane prompts:**
- Start with the todo itself as the core task
- If the conversation contained relevant context (file paths discussed, decisions made, constraints mentioned), weave that into the prompt
- If the todo is part of a broader effort discussed in conversation, mention that framing
- Keep it focused — the spawned Claude session should know what to do without needing the full conversation history
- Escape single quotes in the prompt (replace `'` with `'\''`)

Example prompt for a todo "Refactor auth middleware":
```
Refactor the JWT auth middleware in src/middleware/auth.ts. The current implementation refreshes tokens synchronously which blocks the request. Convert to async refresh with a token cache. The rest of the team is working on the API integration tests in parallel, so don't change the public interface.
```

**Raw pane commands:** If the todo implies a specific command (like "run the dev server"), include it. If ambiguous, just `cd` to the directory and leave the pane at a shell prompt — don't guess.

### Execute and Attach

Write both scripts, make them executable, and run them in sequence with a 5-second gap:

```bash
chmod +x /tmp/session-planner-structure.sh /tmp/session-planner-inject.sh

# 1. Create the tmux structure
/tmp/session-planner-structure.sh

# 2. Wait for all shells to initialize
sleep 5

# 3. Inject commands into panes
/tmp/session-planner-inject.sh

# If inside tmux, switch to the new session
tmux switch-client -t SESSION_NAME

# If not inside tmux, attach
tmux attach-session -t SESSION_NAME
```

After running the attach/switch command, tell the user the session is ready and which windows are available. The skill's job is done at this point — the user takes over from the tmux session.

## Context Injection

When the skill is invoked mid-conversation, the current conversation is a rich source of context. Mine it for:

- **File paths** that were discussed or edited
- **Technical decisions** that were made ("we decided to use Redis for caching")
- **Constraints** that were established ("don't touch the public API")
- **Related work** happening in parallel ("the frontend team is redesigning the dashboard")
- **Error messages or symptoms** if the todo is about fixing something

Distill this into concise, actionable context for each Claude prompt. Don't dump the whole conversation — extract what's relevant to each specific todo.

## Edge Cases

- **Single todo**: Don't create an elaborate multi-window layout. One window, one pane, done.
- **All raw todos**: Still create the tmux session with the layout, just no Claude sessions.
- **Existing tmux session with same name**: Append a number suffix rather than clobbering.
- **Very many todos (8+)**: Group aggressively into themed windows. Warn the user that this many parallel sessions might be hard to manage and suggest prioritizing.
- **User is not in tmux and tmux is not installed**: Error clearly. This skill requires tmux.
