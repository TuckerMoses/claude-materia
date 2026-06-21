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
│   │   ├── agents/          # System agents (triage, fixer, auditor)
│   │   └── defaults/
│   │       └── reviewers/   # Bundled default reviewers (coherence, design, detail)
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
- **Every skill has a `## Per-install binding` section.** This is the only per-install coupling point. On invocation a skill reads `~/.claude/<skill-name>.local.md` (a gitignored, user-owned file that is the documented Claude Code per-install convention; it is NOT in this repo) and follows it: that file may bind the skill to a resource, point to a set of environment heuristics, or override defaults. If the file is absent, the skill proceeds with its built-in defaults (fallback-safe). The public repo names no bespoke environment paths — any forwarding to a local environment lives in the user's `.local.md`, never in a skill body.
- **Skill-local agents live with their skill.** Adversarial-review's system agents (triage, fixer, auditor) are in `skills/adversarial-review/agents/`. Bundled default reviewers are in `skills/adversarial-review/defaults/reviewers/`. Top-level `agents/` is for portable agents that any skill or session can dispatch.
- **Consumer-side contract enforcement.** Adversarial-review accepts user-supplied reviewer agents via configuration or invocation flags. The loop's contract is enforced by a semantic audit (the auditor agent) at session start, not by tags or schema requirements on the agent files. This makes reviewer agents portable across skills.
- **No session data in the repo.** Session artifacts are runtime data created by skills at execution time. They live in user state at `~/.claude/plugins/data/claude-materia-claude-materia/sessions/`, not under the skill install. The `~/.claude/plugins/data/<plugin>-<marketplace>/` path is the Claude Code-canonical user-state location for plugin-managed data — it survives plugin updates and is writable at runtime even when the skill install path is read-only. The audit cache lives in the same directory (`audit-cache.json`).

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with frontmatter (name, description).
2. Add the `## Per-install binding` section using the convention from the README.
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
