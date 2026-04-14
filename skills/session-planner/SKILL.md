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

### Session Creation

Pick a descriptive session name based on the work theme. If ambiguous, use a timestamp-based name like `work-20260414`.

Build the tmux session step by step:

```bash
# Create the session with the first window
tmux new-session -d -s SESSION_NAME -n WINDOW_1_NAME -x WIDTH -y HEIGHT

# For additional windows
tmux new-window -t SESSION_NAME -n WINDOW_N_NAME

# For pane splits within a window
tmux split-window -t SESSION_NAME:WINDOW -h   # horizontal split (side by side)
tmux split-window -t SESSION_NAME:WINDOW -v   # vertical split (stacked)

# Resize panes if needed
tmux resize-pane -t SESSION_NAME:WINDOW.PANE -x COLS
tmux resize-pane -t SESSION_NAME:WINDOW.PANE -y ROWS
```

### Injecting Claude Sessions

For panes classified as "claude," send an interactive Claude command with the todo as a prompt. The prompt should be contextual — not just the raw todo text, but enriched with relevant context from the conversation.

```bash
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'claude "PROMPT_HERE"' Enter
```

**Prompt construction for Claude panes:**
- Start with the todo itself as the core task
- If the conversation contained relevant context (file paths discussed, decisions made, constraints mentioned), weave that into the prompt
- If the todo is part of a broader effort discussed in conversation, mention that framing
- Keep it focused — the spawned Claude session should know what to do without needing the full conversation history
- Escape single quotes in the prompt (replace `'` with `'\''`)

Example prompt for a todo "Refactor auth middleware":
```
Refactor the JWT auth middleware in src/middleware/auth.ts. The current implementation refreshes tokens synchronously which blocks the request. Convert to async refresh with a token cache. The rest of the team is working on the API integration tests in parallel, so don't change the public interface.
```

### Injecting Raw Terminal Commands

For raw panes, if the todo implies a specific command (like "run the dev server"), send that command:

```bash
tmux send-keys -t SESSION_NAME:WINDOW.PANE 'npm run dev' Enter
```

If the todo is ambiguous, just leave the pane at a shell prompt — don't guess.

### Attach

After everything is set up, attach to the session:

```bash
tmux attach-session -t SESSION_NAME
```

If already inside tmux, switch instead:

```bash
tmux switch-client -t SESSION_NAME
```

**Important:** After running the attach/switch command, tell the user the session is ready and which windows are available. The skill's job is done at this point — the user takes over from the tmux session.

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
