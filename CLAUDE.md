# claude-materia

Claude Code plugin providing portable skills and agents.

## Repository Structure

```
claude-materia/
├── .claude-plugin/
│   ├── plugin.json          # Plugin manifest (name, version, metadata)
│   └── marketplace.json     # Marketplace definition for plugin distribution
├── skills/
│   ├── adversarial-review/  # Multi-agent artifact review loop
│   │   ├── SKILL.md
│   │   └── agents/          # Skill-local agents (coherence, design, detail, triage, fixer)
│   ├── sidechat/            # Tmux-based session spawner
│   │   └── SKILL.md
│   └── session-planner/     # Todo-to-tmux workspace launcher
│       └── SKILL.md
├── agents/                  # Portable agents (empty — migrations pending)
├── CLAUDE.md                # This file
└── README.md                # FF7-themed user-facing docs
```

## Design Conventions

- **Every skill is portable.** No references to specific environment paths, user-specific heuristics, or config management tools. Skills work in bare environments with sensible defaults.
- **Every skill has an `## Environment` section.** This is the extension point — if `~/.claude/env/index.md` exists, the skill reads it and adapts. If not, it proceeds without.
- **Skill-local agents live with their skill.** Adversarial-review's reviewer/triage/fixer agents are in `skills/adversarial-review/agents/`, not in the top-level `agents/` directory. Top-level `agents/` is for portable agents that any skill or session can dispatch.
- **No session data in the repo.** Session artifacts are runtime data created by skills at execution time. They live on the user's filesystem, not here.

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with frontmatter (name, description).
2. Add the `## Environment` section using the convention from the README.
3. Name the derived artifact type appropriate to the skill (Review Criteria, Session Context, Planning Context, etc.).
4. If the skill has its own agents, put them in `skills/<skill-name>/agents/`.
5. Update `README.md` with an entry in the materia table.
6. Bump the version in `.claude-plugin/plugin.json`.

## Adding a Portable Agent

1. Create `agents/<agent-name>.md` with frontmatter.
2. Verify it's self-contained — no environment-specific paths or heuristics.
3. Update `README.md`.
4. Bump the version in `.claude-plugin/plugin.json`.

## Version Bumping

Bump the version in `.claude-plugin/plugin.json` for any content change. Users update via:

```bash
claude plugin marketplace update claude-materia
claude plugin update claude-materia@claude-materia
```
