# claude-materia

Marketplace repo hosting two Claude Code plugins: **claude-materia** (portable session/review skills, repo root) and **vault** (the knowledge-vault system, `plugins/vault/`).

## Repository Structure

```
claude-materia/
├── .claude-plugin/
│   ├── plugin.json          # claude-materia plugin manifest
│   └── marketplace.json     # Marketplace definition — lists BOTH plugins
├── skills/                  # claude-materia plugin skills
│   ├── adversarial-review/  # Multi-agent artifact review loop (agents/, defaults/reviewers/)
│   ├── sidechat/            # Tmux-based session spawner
│   ├── session-planner/     # Todo-to-tmux workspace launcher
│   └── park-session/        # Session bookmarking
├── plugins/
│   └── vault/               # The vault plugin (own manifest, own version)
│       ├── .claude-plugin/plugin.json
│       ├── README.md        # Vault-system docs (architecture + workflow SVGs in docs/)
│       └── skills/
│           ├── vault/       # create / add-source / discuss (+ assets/ templates-as-spec)
│           ├── ingest/      # intake pipeline (+ scripts/ deterministic shell + tests)
│           └── synthesizer/ # pool coherence + vocabulary growth
├── agents/                  # Portable agents (empty — migrations pending)
├── docs/superpowers/        # Design history: specs, decision SVGs, implementation plans
├── BACKLOG.md               # Deferred work (container convention: top = next)
├── CLAUDE.md                # This file
└── README.md                # FF7-themed user-facing docs
```

**Two plugins, one repo.** Skills in `skills/` belong to the claude-materia plugin; skills in `plugins/vault/skills/` belong to the vault plugin (fully-qualified names `vault:vault`, `vault:ingest`, `vault:synthesizer`). Each plugin versions independently in its own `plugin.json`; bump the one whose content changed.

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
