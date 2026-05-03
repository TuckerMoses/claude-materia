# claude-materia

Portable skills and agents for Claude Code — slottable materia that extend any environment with reusable abilities. Equip them once, carry them anywhere.

## What is materia?

In Final Fantasy VII, materia are crystallized orbs of knowledge. You slot them into your equipment and gain new abilities — magic, summons, support techniques. Swap them between characters, combine them for new effects, carry them across the entire game.

This plugin works the same way. Each skill is a self-contained orb of capability. Slot it into any Claude Code environment and it just works. If you have an [environment](https://github.com/TuckerMoses/claude-materia#environment-extension) set up, the materia adapts to your local conventions. If you don't, it runs with sensible defaults. No configuration required either way.

## Install

```bash
claude plugin marketplace add TuckerMoses/claude-materia
claude plugin install claude-materia@claude-materia
```

## Equipped materia

### Skills

| Materia | Type | What it does |
|---------|------|-------------|
| **adversarial-review** | Command | Multi-agent review loop for artifacts. Ships with three default reviewers (coherence, design, detail) and accepts user-supplied reviewers via env config or `--reviewers <ref>`. Dispatches reviewers, triage to synthesize and assign severity, and a fixer to apply changes. Loops until clean, then promotes to opus for final verification. |
| **sidechat** | Support | Spins off a tangent into a new tmux window with its own Claude Code session. The new session gets a context briefing so it hits the ground running. Your current conversation continues uninterrupted. |
| **session-planner** | Support | Turns a list of todos into a live tmux workspace. Analyzes tasks, decides which need Claude Code vs raw terminal, proposes a layout, and launches everything with context-aware prompts. |

### Agents

_No portable agents migrated yet. Coming soon: researcher, architect, debugger, house-wrecker, house-cleaner, teacher, expert._

## Environment extension

Materia skills are designed to work anywhere, but they get smarter when they find an environment. If `~/.claude/env/index.md` exists, each skill reads it on invocation, builds a relevance map of available heuristics, and derives task-specific criteria from the relevant entries.

This means:
- **With an environment:** adversarial-review knows your kind definitions and can validate artifacts against their spec checklists. Sidechat forwards your conventions to the new session.
- **Without an environment:** everything still works, just without the local context. The skill tells you no environment was found so you know the extension point exists.

To create an environment, add `~/.claude/env/index.md` pointing to your heuristic files. See the [environment convention](#the-environment-convention) below.

### The environment convention

Every portable skill includes an `## Environment` section that follows this protocol:

1. Check if `~/.claude/env/` exists
2. Read `index.md` to discover available heuristics
3. Produce a relevance map (every entry gets an explicit disposition — no silent dropping)
4. For relevant entries, derive task-specific criteria
5. Include derived criteria in agent dispatches as appropriate

The environment is yours to design. The index is the only hardcoded path — everything else is discovered dynamically.

## Writing a custom reviewer for adversarial-review

The adversarial-review skill accepts user-supplied reviewer agents. Drop a `*.md` agent file anywhere accessible and reference it via `--reviewers <ref>` or env config.

**Minimum contract**: an agent file needs only two things:
- `name` (frontmatter field)
- A non-empty prompt body describing what the agent does

Everything else is optional. The skill audits each candidate semantically — it evaluates whether your agent's described purpose will produce review-shaped output. Agents shaped like reviewers (find/identify/detect issues, emit findings with locations and severities) will pass; agents shaped like generators or orchestrators will be rejected with explanation.

**Recommended shape** (used by the bundled defaults):
```yaml
---
name: my-reviewer
description: "What this reviewer checks for"
required: true               # or false with a trigger
trigger: null                # required if required: false
precondition: "..."          # describes when this agent should run
severity_guidance:           # hint to triage; optional
  - finding_type: my_issue
    typical_severity: high
---

# My Reviewer

You are reviewing an artifact for X. Your job is...

## What you check
- ...

## How to report findings
For each finding, emit: finding_type, severity, location, description, suggestion.
```

**Where to put it**:
- `~/.claude/agents/<name>.md` — referenced by bare name (`run my-reviewer`)
- Anywhere else — referenced by path (`run /abs/path/to/my-reviewer.md` or `run ./relative/path.md`)
- Configured in `~/.claude/env/index.md` under `adversarial-review.reviewers_dir` for always-on inclusion

## License

MIT
