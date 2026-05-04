---
name: session-planner
description: "Turn a list of todos into a live tmux workspace, OR reorganize/extend/audit an existing session. Five modes: create (todos → fresh session), reorganize (existing session → restructured), extend (existing session + todos), audit (analysis only), reannotate (migration path for legacy sessions). Uses sentinel-titled panes, confidence-weighted inference, and an approval gate with status annotations. Use whenever the user wants to spin up parallel terminals, dispatch todos to tmux, restructure existing windows/panes, or just survey a session — phrases like 'spin these up', 'set up a workspace', 'reorganize my session', 'audit this layout', 'add these todos to', 'what would change if'."
user-invocable: true
argument-hint: "[subcommand] [args] — create [todos], reorganize [session], extend [session] [todos], audit [session] [todos], reannotate [session]"
---

# Session Planner

Turn todos into a live tmux workspace, or restructure an existing one. Each todo becomes a pane — some with Claude Code sessions already working, others as raw terminals ready for manual commands.

The skill operates as a **tmux-state diff engine**: it reads existing state, computes a transformation against intent, presents a unified plan, and only executes after approval.

## Modes

| Mode | Input | Output | Touches existing state? |
|---|---|---|---|
| `create` | todos | new tmux session | no |
| `reorganize` | existing session, optional rename ops | restructured session | yes — moves, kills, renames |
| `extend` | existing session + todos | session with new panes, possibly restructured | yes |
| `audit` | existing session, optional todos | analysis + suggested restructure, no execution | no |
| `reannotate` | existing session | sentinel-titled panes; layout unchanged | yes — only `select-pane -T` and `set-option` writes |

`audit` is `(reorganize ∪ extend) --dry-run` — accepts the same `[<session-name>] [todos]` arg shape as extend; absent todos behaves as `reorganize --dry-run`.

## Subcommands and routing

- `/session-planner` — infer mode from arguments and conversation context.
- `/session-planner create [todos]` — current behavior.
- `/session-planner reorganize [<session-name>]` — defaults to current session if invoked from inside tmux.
- `/session-planner extend [<session-name>] [todos]` — defaults likewise.
- `/session-planner audit [<session-name>] [todos]` — analysis only.
- `/session-planner reannotate [<session-name>]` — runs inspection, prompts for confirmation, then writes `sp:`-prefixed titles and populates the `@session-planner-titles` accumulator. Migration path for legacy sessions.
- `--dry-run` flag — accepted by `reorganize`/`extend`; generates scripts only (no `report.md`, no `plan.json`). `audit` is the report-producing variant.

### Inference rules (no subcommand)

Deterministic decision tree over `(args, inside_tmux, current_session)`. First match wins:

1. Args contain a recognized subcommand keyword → route to that subcommand.
2. Args reference a tmux session AND contain todo-shaped phrases → `extend`.
3. Args reference a tmux session AND no new todos → `reorganize`.
4. Args contain todo-shaped phrases AND no session reference → `create`.
5. Args explicitly request analysis without execution → `audit` on current session if inside tmux, else ask.
6. No args, inside tmux → `audit` of the current session (read-only default).
7. No args, outside tmux → `create`.
8. Multiple rules could fire (genuine ambiguity) → ask once, quoting the args back with candidate routings.

"Recognized as a tmux session" = exact match against `tmux list-sessions -F '#{session_name}'`. "Todo-shaped" = imperative task description (verb-led, present tense, action-object).

## Inspection protocol (reorganize / extend / audit / reannotate)

The skill reads existing tmux state up-front and presents a proposed restructure. **No separate "what is each pane?" quiz** — corrections happen at the approval gate. When inference confidence is too low, the bulk-correction pre-step kicks in (see "Approval gate").

### Read pass

```bash
# Sessions
tmux list-sessions -F '#{session_name} #{session_windows} #{session_attached}'

# Windows — capture window IDs (@n)
tmux list-windows -t <session> \
  -F '#{window_id} #{window_index} #{window_name} #{window_active} #{window_last_flag} #{window_layout} #{window_panes}'

# Panes — capture pane IDs (%n)
tmux list-panes -t <session>:<window_id> \
  -F '#{pane_id} #{pane_index} #{pane_active} #{pane_pid} #{pane_current_command} #{pane_current_path} #{pane_title} #{pane_width}x#{pane_height}'

# Captured pane content for type inference
tmux capture-pane -t <pane_id> -p -S -200

# Session-level title accumulator (for sentinel verification — see "Pane titles")
tmux show-options -t <session> -v '@session-planner-titles'

# Incident breadcrumb check (see "Failure handling")
tmux show-options -t <session> -v '@session-planner-incident'
```

For each window, capture the **anchor pane ID** — the active pane at inspection time. This is the destination reference for `move-pane`/`join-pane`.

If `@session-planner-incident` is set, the session is in a post-failure state from a prior `restructure.sh`. Surface this as a top-of-prompt notice under "Environment notes" at the approval gate; do NOT auto-clear (only successful `restructure.sh` clears it).

### Pane-type inference

Each pane classifies as one of: `claude`, `claude-exited`, `raw` (sub-types `dev-server`, `log-tail`, `idle-shell`, `other`), or `remote-or-nested` (opaque tier covering `ssh`, nested `tmux`, `mosh`, `docker exec`).

#### Confidence-weighted scoring (normative)

Signal weights — values fixed by design; AI implementers MUST NOT change them:

| Signal | Weight |
|---|---|
| `pane_title` with `sp:` prefix AND verified by `@session-planner-titles` accumulator | +5 |
| `pane_current_command` matches a strong pattern (`claude`, `node` running claude, `vite`, `nodemon`, etc.) | +4 |
| Process-tree walk (≤3 levels) finds a recognized command | +3 |
| Captured-content pattern match | +2 |
| `pane_title` with `sp:` BUT not in the accumulator (forged / accidental / legacy) | +1 (advisory) |
| `pane_title` set without `sp:` | +1 (advisory) |
| Process is `ssh`/`mosh`/nested `tmux`/`docker exec` | classifies as `remote-or-nested` (short-circuit) |
| Shell + Claude exit banner in capture | classifies as `claude-exited` (short-circuit) |

The classification with the highest summed weight wins. Cardinal scoring is the rule; the priority order above is a tie-breaker only (verified-sentinel > strong-process > process-tree > captured-content > unverified/unsentineled title).

When `pane_title` (sentinel) and `pane_current_command` disagree, surface as `[claude (title) / shell (process)]` rather than silently picking one.

#### Concrete inference patterns

**Canonical shell-prompt regex** (used everywhere shell-prompt detection is invoked):

```
[$%#>❯λ»►] *$
```

Patterns:
- **Claude UI** — last 50 lines contain box-drawing `╭` or `╰` followed by a `>` prompt, AND a model identifier matching `claude-(sonnet|opus|haiku)-[0-9]` earlier in the capture.
- **Claude exit banner** — capture contains `Goodbye` or `Session ended`, AND most recent line matches the prompt regex.
- **Watch-shaped argv** — `(npm|pnpm|yarn) (run )?(dev|start|watch|test:watch)`, `vite( |$)`, `next (dev|start)`, `nodemon( |$)`, `tail -[fF]`, `webpack (--watch|serve)`, `tsc --watch`.
- **Idle shell** — most recent line matches the prompt regex AND no foreground child via `pgrep -P <pane_pid>`.
- **Long persistent output (watcher)** — no line in last 30 captured lines matches the prompt regex.

#### `[unknown]` trigger

A pane is annotated `[unknown]` when:
- (a) No signal returns a positive classification, OR
- (b) Two classifications tie on cumulative weight AND the priority order does not resolve.

### Tmux command targets (universal rule)

`move-pane` and `join-pane` take **pane targets**, not window targets. Passing `-t '<session>:<window>'` resolves to that window's currently-active pane at execution time — non-deterministic.

Every `-t` in generated scripts uses captured pane IDs (`%n`) or window IDs (`@n`) — never names or indices after structural ops. Window names are display-only; scripts always reference `@n`.

Names containing `:`, `.`, or `*` are **rejected at inference time** (conflict with tmux target syntax). Skill asks the user to choose a different name; does not auto-rename. Other interpolated names use `printf %q` for shell-escaping.

## Unified display format

Two views — tree (hierarchy + status) and spatial diagram (proportions + arrangement). Both render in reorganize/extend/audit; only the spatial diagram in create. The spatial diagram shows the **after-state only**.

### Tree view (annotation grammar)

Order: **pane type first, status second.**

```
Session: project-work [renamed: work → project-work]
├── Window 1 (@1): "auth" [existing + NEW]
│   ├── Pane 1.1 (%23) [claude]    [existing]    Refactor auth middleware
│   ├── Pane 1.2 (%24) [claude]    [reposition]  API integration tests
│   └── Pane 1.3 (NEW) [raw]       [NEW]         Tail auth-service logs
├── Window 2 (@2): "infra" [renamed: servers → infra]
│   ├── Pane 2.1 (%30) [raw]       [existing]    (none)
│   └── Pane 2.2 (%26) [claude]    [← w3.p1]     Investigate log spike
└── Window 3 (@4): "scratch" [killed]
    └── Pane 3.1 (%29) [claude-exited] [killed]
```

| Annotation | Meaning |
|---|---|
| `[claude]` / `[claude-exited]` / `[raw]` / `[remote-or-nested]` | Pane type — always present, always first. |
| `[existing]` | Unchanged spatially. May still receive `set-title` or be a destination anchor. |
| `[NEW]` | Pane will be created. |
| `[reposition]` | Within-window `move-pane`. Sibling order encodes new position. |
| `[← w<n>.p<m>]` | Cross-window move. Source window/pane named (pre-state). |
| `[renamed: old → new]` | Window or session rename. Both names visible. |
| `[killed]` | Pane or window will be destroyed. Flagged as destructive. |
| `[existing + NEW]` | Window-level rollup. |
| `[unknown]` | Type could not be inferred. Surfaced explicitly during approval. |
| `[claude (title) / shell (process)]` | Conflicting signals; user resolves at approval. |

Precedence (multi-op composition): each pane gets exactly one status; `[NEW]` > `[killed]` > `[← w<n>.p<m>]` > `[reposition]` > `[existing]`. `set-title` does NOT contribute a status — it's reflected only in the title column.

A pane is a "target" of an op only as the **source** of `move-pane` or `kill-pane`. Destination anchors and `resize-pane` targets remain `[existing]`.

### Spatial diagram

ASCII-box diagram showing post-restructure layout. Same shape as the existing create-mode diagram.

## Approval gate (safety property)

No destructive tmux command runs until the user has seen the full plan and approved.

### Standard flow

1. Skill presents detected state, proposed restructure (tree + after-state diagram), and generated scripts. Environment notes appear at the top under heading "Environment notes."
2. User can:
   - Correct any detection inference ("pane 2.1 is actually a log tail").
   - Reject moves, request different groupings, change names.
   - Designate a **post-restructure landing pane** (defaults to pre-state active pane).
   - Approve and execute.
3. On corrections, regenerate and re-present. Loop until approved.
4. `--dry-run` / `audit` short-circuits after step 1, writing scripts (and for `audit` only, also `report.md` + `plan.json`) to `/tmp/session-planner-audit-<timestamp>/`.

### Bulk-correction pre-step (low-confidence inference)

When inference is too uncertain, switch to a two-stage flow before the standard approval. Trigger thresholds (fixed constants — not user-configurable):

| Constant | Value | Branch |
|---|---|---|
| `unknown_pct` | 30 | Triggers when ≥30% of qualifying panes are `[unknown]`. |
| `floor_pct` | 50 | Triggers when ≥50% of qualifying panes score below `confidence_floor`. |
| `confidence_floor` | 4 | Cumulative-weight threshold. A single +5 verified-sentinel or +4 strong-process clears the floor; weaker signals alone do not. |

**Qualifying population**: panes whose winning classification is `claude`, `raw` (any sub-type), or `[unknown]`. Short-circuit classifications (`[claude-exited]`, `[remote-or-nested]`) are excluded from both numerator and denominator — they are confidently classified, just non-trivial states. If qualifying population is empty, neither branch fires.

When triggered:
- **Stage 1** — present a compact list of every below-floor and `[unknown]` pane with its current best guess and alternatives. User accepts batch corrections in one pass.
- **Stage 2** — with corrected classifications, generate the proposal and proceed to standard approval.

### Edit-proposal mode

User can invoke "edit proposal" at the gate. Skill writes the tree view to a temp file, opens in `$EDITOR`, re-derives the script from edits.

**Honored operations:**
- Delete a pane line → `[killed]`.
- Delete a window subtree → `kill-window`.
- Reorder pane lines within a window → within-window `[reposition]` ops; sibling order encodes split direction.
- Rename a window heading → `rename-window` for that `@n`.
- Cross-window move → requires explicit `[← w<n>.p<m>]` annotation.

**Rejected operations** (cause re-derivation to fail; re-open with `#`-prefixed error block):
- Adding brand-new pane lines (use `extend` instead).
- Changing a pane's type annotation.
- Modifying `[← src]` source annotations.
- Modifying `[unknown]` / conflict annotations.
- Changing within-window split orientation.

On parser failure, re-open the file with prepended error block listing each problem with line number and rejection reason. User fixes and saves; skill re-parses. Closing without saving aborts back to standard approval.

### Active-pane contract (safety invariant)

The active pane is the pane carrying `pane_active=1` for the target session.

**Detached-session resolution** (no client attached): tmux records `pane_active=1` per window, not per session. Two-step resolution:
1. **Binding window** — the window where `window_active=1` from `tmux list-windows`. If none carries that flag (some tmux versions clear on detach), fall back to the highest-`window_index` window with `window_last_flag=1`; else lowest `window_index`. Do NOT use `window_activity` — a watcher producing log output would otherwise outrank the user's actual focus.
2. **Binding pane** — within the binding window, the pane with `pane_active=1`.

**Multi-client / cross-session invocation**: if target has ≥1 attached client, use the focused pane of the most-recently-active client (highest `client_activity` from `tmux list-clients -t <session>`); ties fall through to detached resolution. Surface the resolved client at the approval gate.

**Nested-tmux invocation**: detect with:

```bash
inner_socket=$(tmux display-message -p '#{socket_path}')
outer_socket="${TMUX%%,*}"
if [[ -n "$TMUX" && "$inner_socket" != "$outer_socket" ]]; then
  # nested
fi
```

For "no args, inside tmux," default to innermost tmux's current session. If user invokes against a session not in innermost's `tmux list-sessions`, surface a confirmation prompt.

**Clauses:**
- (a) **Active pane is never killed.** If the proposal would kill it, refuse and ask the user to deselect or move focus.
- (b) **Active pane is moved only if explicitly marked.** Implicit moves require explicit confirmation.
- (c) **If `restructure.sh` would run in the active pane, dispatch to a sidecar.** The script generator detects this and emits a wrapper that creates a sidecar pane, dispatches `restructure.sh` to it, and exits the originating pane cleanly. Sidecar self-cleans on completion. Does not apply when invoked against a detached session from outside.
- (d) **Post-restructure focus.** Final step (`step 7`) re-selects the pre-state active pane by ID, or the user-designated landing pane.

## Launch script architecture (mode-aware)

Two-script structure (`structure.sh` + sleep + `inject.sh`) preserved for create. New modes use `restructure.sh` as the single structural-script name; sleep tax is mode-conditional.

### Order of operations

1. **Renames** (windows and session) — names referenced downstream by humans only; scripts use IDs.
2. **Breaks and joins** — `break-pane` to extract, `join-pane` to merge, before bulk moves.
3. **Moves and swaps** — `move-pane`, `swap-pane`. Preserve running processes.
4. **Kills** — `kill-pane`, `kill-window`. Destructive; require explicit user approval.
5a. **New-pane creation** (extend mode only) — capture pane IDs via `-P -F '#{pane_id}'`.
5b. **Layout adjustments** — `select-layout` first (resets sizing), `resize-pane` second (applies overrides). The destructive relationship is per-window; emit each window's `select-layout` before its `resize-pane` calls.
6. **Pane titles** — set on new panes; update on changed-intent panes; **defensively re-set on moved panes** (the design does not rely on tmux preserving titles across `move-pane`).
7. **Restore focus** — `select-pane -t <landing_pane_id>`.

### Kill-before-move dependencies

The default ordering (moves before kills) fails when a move's destination slot is occupied by a pane scheduled for kill. The script generator runs a **dependency-resolution pass**:

- For each move with destination `D`, check whether `D` is in the kill set.
- If yes: emit `swap-pane -s <source> -t <D>` in step 3 (places source in slot, displaces kill target out), then `kill-pane -t <D>` in step 4. Pane IDs are stable across `swap-pane` (only positions exchange).
- If the dependency graph contains cycles: **refuse to emit**. Surface the cycle at the approval gate ("panes %25 ↔ %26 form an unresolvable swap-cycle in window @2"). User must split across two invocations or accept a different layout.

### Move-pane source-window auto-destruction

Tmux auto-destroys a source window when `move-pane` extracts its last pane (last-pane semantics, identical to `kill-pane` on the last pane). The planner emits `kill-window` ops for emptied windows (preserves byte-identical reports invariant), but the script generator filters out `kill-window` ops whose source window auto-destructs via a prior `move-pane` (marks them `emit_to_script: false` in the plan object). The kill-window stays in the plan object for `report.md` rendering and tree-view `[killed]` annotation; only the script omits it.

### Failure handling

The script does **not** use `set -e`. Tmux is non-transactional — there is no clean rollback. Instead, every command is wrapped in a checked helper:

```bash
#!/bin/bash
# No set -e. Every command checked explicitly.

CHECKPOINT=/tmp/session-planner-checkpoint-$$.log

on_failure() {
  local step=$1 cmd=$2 stderr=$3
  cat <<EOF >&2
session-planner: $step failed.
  Command: $cmd
  Stderr:  $stderr
  Checkpoint log: $CHECKPOINT

The session is in an intermediate state. Run \`/session-planner audit\`
to see the post-failure layout. The skill does NOT attempt automatic
rollback (tmux operations are not transactional).

A breadcrumb (\`@session-planner-incident\` session option) was set
before step 1 emitted; it persists across invocations until a future
\`restructure.sh\` completes successfully.
EOF
  exit 1
}

run_step() {
  local label=$1; shift
  local stderr_file
  stderr_file=$(mktemp)
  if "$@" 2>"$stderr_file"; then
    echo "OK: $label — $*" >> "$CHECKPOINT"
  else
    on_failure "$label" "$*" "$(cat "$stderr_file")"
  fi
  rm -f "$stderr_file"
}

# capture_step — variant for commands whose stdout must be captured
# (e.g., -P -F '#{pane_id}'). Cannot use $(run_step …) — that runs run_step
# in a subshell, and on_failure's `exit 1` only terminates the subshell,
# leaving the captured variable empty and the parent oblivious.
# capture_step writes captured stdout to a caller-supplied tempfile and
# signals the parent with SIGTERM on failure.
capture_step() {
  local label=$1 outfile=$2; shift 2
  local stderr_file
  stderr_file=$(mktemp)
  if "$@" >"$outfile" 2>"$stderr_file"; then
    echo "OK: $label — $*" >> "$CHECKPOINT"
    rm -f "$stderr_file"
  else
    cat <<EOF >&2
session-planner: $label failed.
  Command: $*
  Stderr:  $(cat "$stderr_file")
  Checkpoint log: $CHECKPOINT
EOF
    rm -f "$stderr_file"
    kill -TERM $$
    exit 1
  fi
}
```

**Use `capture_step` (not `$(run_step …)`)** for any tmux command whose stdout must be captured — typically `split-window`/`new-window` calls in step 5a that emit a new pane ID via `-P -F '#{pane_id}'`. Bare `run_step` is correct for every other call.

### Incident breadcrumb

Set BEFORE step 1 emits (so the breadcrumb exists if any subsequent step fails); cleared at the end on successful completion. Step 0 (set) and step 8 (clear) deliberately do NOT use `run_step` — failures of the breadcrumb writes themselves should warn-and-continue, not abort:

```bash
# Step 0: set breadcrumb
tmux set-option -t "$OLD_SESSION" \
    '@session-planner-incident' "planner-time:$OLD_SESSION,checkpoint:$CHECKPOINT" \
  || echo "warning: could not set incident breadcrumb; partial-failure protection is degraded for this run." >&2

# ... steps 1-7 ...

# Step 8: clear breadcrumb (only on successful completion)
tmux set-option -u -t "$NEW_SESSION" '@session-planner-incident' \
  || echo "warning: could not clear breadcrumb; clear manually with: tmux set-option -u -t \"\$NEW_SESSION\" @session-planner-incident" >&2
```

### Skeleton (reorganize, no extend)

```bash
#!/bin/bash
# (run_step / capture_step / on_failure helpers from above)

# Window map (human-readable comment):
# @1 → "auth"
# @2 → "infra" (renamed from "servers")

# Anchor pane IDs captured at inspection
ANCHOR_W1='%23'
ANCHOR_W2='%30'
# Invariant: source pane ID ≠ destination anchor pane ID for any move-pane.
# If a candidate anchor coincides with a move source, rebind the anchor to a
# different pane in the same window before emitting step 3 (or use swap-pane).

OLD_SESSION='work'
NEW_SESSION='project-work'
LANDING_PANE="$ANCHOR_W1"  # default; user-designated landing overrides

# Step 0: incident breadcrumb (warn-and-continue on failure)
tmux set-option -t "$OLD_SESSION" '@session-planner-incident' \
    "planner-time:$OLD_SESSION,checkpoint:$CHECKPOINT" \
  || echo "warning: could not set incident breadcrumb." >&2

# Step 1: renames
run_step "rename session"  tmux rename-session -t "$OLD_SESSION" "$NEW_SESSION"
run_step "rename window @2" tmux rename-window -t '@2' 'infra'

# Step 2: breaks / joins (omitted if none)

# Step 3: moves and swaps
run_step "move %24 next to anchor of @1" tmux move-pane -s '%24' -t "$ANCHOR_W1" -v
run_step "move %25 next to anchor of @2" tmux move-pane -s '%25' -t "$ANCHOR_W2" -h

# Step 4: kills (kill-window for auto-destructed windows is OMITTED — emit_to_script: false)
run_step "kill-pane %29"  tmux kill-pane -t '%29'
run_step "kill-window @4" tmux kill-window -t '@4'

# Step 5a: new-pane creation (extend only — use capture_step)
# PANE_TMP=/tmp/sp-pane-$$-1.tmp
# capture_step "split-window in @1" "$PANE_TMP" tmux split-window -t '@1' -h -P -F '#{pane_id}'
# NEW_PANE_1=$(< "$PANE_TMP"); rm -f "$PANE_TMP"

# Step 5b: layout (select-layout first, resize-pane second)
run_step "select-layout @1" tmux select-layout -t '@1' tiled
run_step "resize-pane width" tmux resize-pane -t '%30' -x 80

# Step 6: pane titles (defensive re-set on moved panes; sentineled)
run_step "title %23"           tmux select-pane -t '%23' -T 'sp:Refactor auth middleware'
run_step "title %24 (moved)"   tmux select-pane -t '%24' -T 'sp:API integration tests'
# Update accumulator for any title changes
run_step "accumulator update"  tmux set-option -t "$NEW_SESSION" '@session-planner-titles' \
  "%23:Refactor auth middleware;%24:API integration tests;%30:..."

# Step 7: restore focus
run_step "select landing pane" tmux select-pane -t "$LANDING_PANE"

# Step 8: clear breadcrumb (warn-and-continue on failure)
tmux set-option -u -t "$NEW_SESSION" '@session-planner-incident' \
  || echo "warning: could not clear breadcrumb." >&2
```

## Mode-specific behavior

### Create

Unchanged from prior version. `structure.sh` creates session/windows/panes; active wait per new pane; `inject.sh` sends commands. **Addition**: every new pane gets a sentinel-prefixed `sp:` title set at creation, and the pane is appended to `@session-planner-titles`.

### Reorganize

Single `restructure.sh`. No inject phase. No sleep — no new shells.

### Extend

Reuses reorganize's `restructure.sh` generator with new-pane creation enabled in step 5a. `inject.sh` follows, sending commands only to new panes. Active wait between scripts (only because new panes exist).

#### Truth table

| New panes? | Restructure ops? | `restructure.sh`? | `inject.sh`? | Wait between? |
|---|---|---|---|---|
| yes | yes | yes (with step 5a) | yes (NEW panes only) | yes |
| yes | no | yes (steps 5a + 6 + 7 only) | yes | yes |
| no | yes | yes (no step 5a) | no | n/a |
| no | no | none generated | none | n/a — exit "no changes proposed" |

#### Placement algorithm (new panes)

1. **Smallest existing window with room and matching pane type.** "Room" = <4 panes AND ≥30 cols × 15 rows after split. "Matching" = window already contains a pane of the same type (`claude-exited` counts as claude-leaning; `remote-or-nested` counts as raw-leaning). Tie-break: smaller window first; then lower window index.
2. **New window grouped by topic affinity.** If no existing window matches, create a new window. Two todos share affinity if they share ≥3 non-stopword tokens of length ≥4 (case-insensitive; stopwords: `the`, `and`, `for`, `with`, `from`, `into`, `this`, `that`, `then`, `but`, `not`, `you`, `are`, `was`, `were`). Surface matched tokens at the gate as `[placed: rule 2 — shared keywords: auth, middleware, tests]`. Overlapping pairs: place the disputed todo in the pair with the greater number of shared keywords; ties broken by todo-list order.
3. **New window per pane** if no affinity exists.

Annotate each new pane in the tree with `[placed: rule 1/2/3]`.

### Audit

Runs the full inspection-and-propose pipeline, stops short of execution. Writes scripts + `report.md` + `plan.json` to `/tmp/session-planner-audit-<timestamp>/`. Prints the path at end. Cannot fail destructively.

### Reannotate

Migration path for legacy sessions whose panes pre-date the `sp:` sentinel convention. Runs inspection, prompts for confirmation/correction, then writes sentineled `sp:` titles for every pane and populates `@session-planner-titles`. Does NOT change layout, kill, or move panes — only `select-pane -T` and `set-option` writes.

## Pane titles (sentinel + accumulator)

The `sp:` prefix is the skill's signature; the `@session-planner-titles` session option is the integrity check. Sentinel alone is not authoritative — any process can call `tmux select-pane -T 'sp:foo'`. Pairing the sentinel with an accumulator entry detects spoofing.

### Trust model

- `sp:` title AND pane in `@session-planner-titles` → +5 (authoritative).
- `sp:` title BUT pane NOT in accumulator → +1 (advisory; surface as forged/accidental at gate).
- `@session-planner-titles` absent (legacy) → all `sp:` titles weigh +1; recommend `reannotate`.
- Title without `sp:` → +1 (advisory).

### Accumulator format

Each entry: `<pane_id>:<title-text>;` (semicolon-terminated; `;` forbidden in title text — planner rejects todos whose condensed title would contain literal `;`).

Lifecycle:
- **`set-title`** (step 6) — rewrite the accumulator with the updated title.
- **`kill-pane`** — script emits a follow-up `set-option` write that rewrites the accumulator without the killed pane's entry.
- **`move-pane`** — entry persists unchanged (pane IDs are stable across `move-pane`).

## Pane indexing and ID stability

`tmux move-pane`, `kill-pane`, and `break-pane` all renumber pane indices within affected windows. Generated scripts must NOT reference panes by index after a structural op has touched their window.

Universal rules:
1. **Existing panes**: use captured `%n` from inspection.
2. **New panes**: capture at creation via `-P -F '#{pane_id}'`.
3. **Windows**: always `@n`, never index or name.

## Mode-aware sleep tax (active wait)

Fixed-duration sleep replaced by **active wait** wherever possible — poll for the canonical shell-prompt regex in the spawned pane:

```bash
wait_for_pane_ready() {
  local pane_id=$1
  local timeout_s=30  # calibrated against typical shell-init time
  local timeout_ms=$(( timeout_s * 1000 ))
  local elapsed_ms=0
  local prompt_re='[$%#>❯λ»►] *$'
  while (( elapsed_ms < timeout_ms )); do
    if tmux capture-pane -t "$pane_id" -p | tail -1 | grep -qE "$prompt_re"; then
      return 0
    fi
    sleep 0.25
    (( elapsed_ms += 250 ))
  done
  echo "warning: pane $pane_id did not signal ready within ${timeout_s}s; proceeding anyway" >&2
  return 1
}
```

Per-mode:

| Scenario | Wait? |
|---|---|
| Create — only new shells | yes — active wait per new pane |
| Reorganize — only existing panes | no |
| Extend — new + existing | yes — active wait per new pane between `restructure.sh` and `inject.sh` |
| Audit — no execution | n/a |

If active wait is infeasible (spawned process is not a shell), fall back to fixed 5s sleep.

## Detached-session viewport

For sessions without an attached client, `select-layout` and `resize-pane -x/-y` need a viewport. Resolution order:

1. **Attached session** — `#{client_width}x#{client_height}` of the attached client.
2. **Detached** — `#{window_width}x#{window_height}` of the active window in target session.
3. **Both unavailable** — default `200x50`; surface assumption under "Environment notes."

Recorded in audit report and approval prompt.

## Session collision and defaults

- `reorganize` / `extend` / `audit` invoked without session name: default to current session if inside tmux; else ask.
- Target session does not exist: error and suggest `create`.
- `create` with colliding session name: append numeric suffix.

## Multi-session scope

Out of scope for v1. All four modes operate on a single session at a time.

## Environment integration matrix

How env-derived session context flows into each mode:

| Concern | create | reorganize | extend | audit |
|---|---|---|---|---|
| Working directory | applies (per-pane default cwd) | n/a (existing panes keep cwd) | applies (new panes only) | advisory (report cwd anomalies) |
| Naming conventions | applies (new names) | advisory (suggest renames; never auto-rename) | advisory (new windows) | advisory (report violations) |
| Classification override | applies (new todos) | advisory (suggest at gate; never auto-override) | applies (new panes); advisory (existing) | advisory (report mismatches) |
| Prompt framing | applies (new claude panes) | n/a | applies (new claude panes) | n/a |

`applies` = drives the decision automatically. `advisory` = surfaces a recommendation at the approval gate; user accepts or overrides. `n/a` = doesn't arise.

## Environment

This skill extends with environment context. Before launching:

1. Check if `~/.claude/env/` exists.
   - If not: bare environment. Proceed with built-in heuristics.
   - If `~/.claude/env/index.md` is absent or unreadable: warn and proceed. Surface the warning as a bullet under "Environment notes" at the top of the approval prompt. For audit mode, print before the audit summary.
   - Otherwise: read the index.
2. Produce a relevance map. An entry is **relevant** iff it defines or constrains one of:
   - Working-directory defaults / workspace-relative path conventions.
   - Session/window naming conventions.
   - Pane-type classification overrides (e.g., "research → claude").
   - Prompt-construction framing for new claude panes.

   Entries that do not address any of these four concerns are **not relevant** — skip silently. If an entry's name is unclear, read its first heading to decide. Do not load full bodies of clearly off-topic entries.
3. For relevant entries, derive **session context**:
   - Default working directory for each pane (workspace-relative paths).
   - Naming conventions for sessions and windows.
   - Prompt-construction heuristics (env-aware framing, conventions to forward).
   - Classification overrides.
4. Apply derived session context per the per-mode integration matrix above — not just at launch.

If the environment is bare or no entries are relevant, proceed with built-in heuristics and note this once.

## Edge cases per mode

### Create
- Single todo: one window, one pane. No elaborate layout.
- Existing session with same name: append numeric suffix.
- All todos classify as raw: still create the session, just no Claude prompts.
- User not in tmux and tmux not installed: error.

### Reorganize
- **Empty session (no panes):** reject. Nothing to reorganize.
- **Single-pane session:** permitted iff at least one rename is proposed.
- **Detached session:** operate; viewport per "Detached-session viewport" rules.
- **Pane running an editor** (`vim`/`nvim`/`emacs`/`nano`/`hx`/`helix`/`micro`/`kak`): warn at gate ("kills will discard unsaved buffer; cannot be detected"). Do not block; user decides.
- **Skill invoked from inside the session being reorganized:** active-pane contract governs (clauses a–d).
- **`[unknown]` panes:** surface during approval; do not move/kill without explicit confirmation. If proportion exceeds bulk-correction threshold, switch to two-stage flow.
- **Mid-run failure:** no automatic rollback. Structured incident report + checkpoint log path + persistent `@session-planner-incident` breadcrumb.

### Extend
- **Target session does not exist:** error; suggest `create`.
- **Detached target:** proceed; user attaches when ready.
- **All-additive (no moves/kills/renames):** truth-table row {new: yes, restructure: no} applies.

### Audit
- No execution path; cannot fail destructively. Output written to `/tmp/session-planner-audit-<timestamp>/`.
- Audit running on a partial-failure state: valid use case; flags the unexpected layout.

### All non-create modes
- **tmux not installed or not running:** error.
- **Inferring pane type fails:** annotate `[unknown]`; surface during approval.
- **Generated `restructure.sh` would be empty:** report "no changes proposed" and exit cleanly.
- **Names containing `:`, `.`, or `*`:** rejected at inference.

## Migration / backward compatibility

- The current `create` flow is unchanged for users who invoke `/session-planner [todos]` without a subcommand (inference rule 4 routes to `create`).
- The display-format change (tree + after-state diagram) applies in all modes; create's tree degenerates to a one-level "all NEW" view — informative, not noisy.
- The Environment section is additive — bare environments see no behavior change.
- Legacy sessions (no `sp:` titles, no `@session-planner-titles`): inference falls through to lower-weight signals; the skill recommends `reannotate` to promote to the verified path.
