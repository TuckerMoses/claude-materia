# claude-materia

Portable skills and agents for Claude Code — slottable materia that extend any environment with reusable abilities. Equip them once, carry them anywhere.

## What is materia?

In Final Fantasy VII, materia are crystallized orbs of knowledge. You slot them into your equipment and gain new abilities — magic, summons, support techniques. Swap them between characters, combine them for new effects, carry them across the entire game.

This plugin works the same way. Each skill is a self-contained orb of capability. Slot it into any Claude Code environment and it just works. If you give a skill a [per-install binding](https://github.com/TuckerMoses/claude-materia#per-install-binding), the materia adapts to your local conventions. If you don't, it runs with sensible defaults. No configuration required either way.

## Install

```bash
claude plugin marketplace add TuckerMoses/claude-materia
claude plugin install claude-materia@claude-materia
```

## Equipped materia

### Skills

| Materia | Type | What it does |
|---------|------|-------------|
| **adversarial-review** | Command | Multi-agent review loop for a scope (one file, many files, or a YAML manifest declaring intent + locations). Ships with three default reviewers (coherence, design, detail) and accepts user-supplied reviewers via per-install config or `--reviewers <ref>`. Dispatches reviewers, triage to synthesize and route, fixer to apply changes, scribe to author the final summary. Loops until clean, then promotes to opus for final verification. |
| **sidechat** | Support | Spins off a tangent into a new tmux window with its own Claude Code session. The new session gets a context briefing so it hits the ground running. Your current conversation continues uninterrupted. |
| **session-planner** | Support | Turns todos into a live tmux workspace OR reorganizes an existing one. Five modes: `create` (todos → fresh session), `reorganize` (existing session → restructured), `extend` (existing session + todos), `audit` (analysis only), `reannotate` (migration). Confidence-weighted pane-type inference, sentinel-titled panes, an approval gate before any destructive op, and a non-transactional failure path with checkpoint logs and an incident breadcrumb. |
| **park-session** | Command | Bookmarks a Claude Code session by writing a structured pointer (session ID, when, what, next move) into a destination file you control. Lets you tear down ephemeral environments without losing the thread of mid-investigation work. Subcommands: `park` (default), `init`, `unpark`, `list`, `audit`. |
| **vault** | Command | Portable knowledge-vault skill. `create` scaffolds a born-correct vault (flat `notes/` + `journal/`, parseable `_machine/labels.yml`, `INSTRUCTION.md` with local path filled, `.obsidian/` config) with a four-phase workflow (Analyze → Structure-lock → Scaffold → File). `add-source` registers an external source in the vault's ingest pull registry (`_machine/ingest_paths.yml`). `discuss` routes vault strategy questions to the right advisor (kind-bootstrapper or inline). Binds to `~/.claude/vault.local.md`. |

### Agents

_No portable agents migrated yet. Coming soon: researcher, architect, debugger, house-wrecker, house-cleaner, teacher, expert._

## Per-install binding

Materia skills are designed to work anywhere, but they get smarter when you bind them to your setup. Each skill reads a single per-install file on invocation — `~/.claude/<skill-name>.local.md` (for example `~/.claude/adversarial-review.local.md`). This is a gitignored, user-owned file and the documented Claude Code per-install convention. It is **not** part of this repo, and the repo references no specific local-environment layout — the only coupling lives in your `.local.md`.

A skill's `.local.md` may:
- **bind the skill to a resource** (e.g. a knowledge vault it should query),
- **point to your environment heuristics** (a set of conventions, kind definitions, routing rules — whatever layout you keep them in), or
- **override the skill's built-in defaults.**

This means:
- **With a binding:** adversarial-review can validate artifacts against your structural constraints and discover extra reviewers; sidechat forwards your conventions to the new session; session-planner can pull work from a bound resource.
- **Without a binding:** everything still works, just without the local context. The skill proceeds with its built-in defaults — fallback-safe, identical to a bare install.

### The per-install-binding convention

Every portable skill includes a `## Per-install binding` section that follows this protocol:

1. Check if `~/.claude/<skill-name>.local.md` exists.
2. If absent, proceed with built-in defaults (fallback-safe).
3. If present, read it and follow its per-install instructions before proceeding — bind to the named resource, follow any pointer to environment heuristics, and apply any overrides.

The `.local.md` is yours to author. It is the one and only per-install coupling point; what it points to (a resource, an environment, an override) is entirely up to you.

## Writing a custom reviewer for adversarial-review

The adversarial-review skill accepts user-supplied reviewer agents. Drop a `*.md` agent file anywhere accessible and reference it via `--reviewers <ref>` or per-install config (`~/.claude/adversarial-review.local.md`).

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
For each finding, emit: finding_type, severity, files (list), location, description, suggestion.
```

**Where to put it**:
- `~/.claude/agents/<name>.md` — referenced by bare name (`run my-reviewer`)
- Anywhere else — referenced by path (`run /abs/path/to/my-reviewer.md` or `run ./relative/path.md`)
- Declared in `~/.claude/adversarial-review.local.md` under `reviewers_dir` (which may itself point to an environment) for always-on inclusion

## License

MIT
