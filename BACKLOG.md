# claude-materia — BACKLOG

Top of file = next. Items are concrete and clearly actionable near-term; may be vague far-term.
Mark complete with `[x]`.

- [ ] **Vault: relocate the 35 journal squatters.** Migrated topical notes sitting in
  `~/Vault/journal/` belong in `notes/` — where they sit they're invisible to the synthesizer.
  One-time confirmed refactor in a vault session (the `sc-vault-scan` sidechat is a natural home);
  `/ingest status` flags the anomaly until done. *(Cross-container: vault-side op, parked here
  until the vault's own todo path is live.)*
- [ ] **ingest: headless/unattended mode** (`--yes` / cron drain, skipping the gate).
  **Trigger:** gate correction rate ≈ 0 after the vocabulary stabilizes. (ingest spec 2026-07-05 §5)
- [ ] **synthesizer: label-bank hygiene** — merge/retire near-duplicate labels already in the
  bank; the mint-time near-dup guard only prevents new occurrences. (synthesizer spec 2026-07-03 §9)
- [ ] **ingest: interactive mint-at-ingest** — optionally offer a new label on the spot when the
  user is present; the `needs-label` → synthesizer path remains the durable floor. (both specs)
- [ ] **synthesizer: embedding/semantic-index shortlisting.** **Trigger:** label-blocking + title
  sweep demonstrably missing related pairs. (synthesizer spec 2026-07-03 §9)
- [ ] **synthesizer/ingest: scheduled operation** (cron / `/loop` cadences) — a user decision;
  requires no skill changes. (synthesizer spec 2026-07-03 §9)
- [ ] **ingest: stable per-source-item ids** for edited-in-place thoughts (the
  two-notes-per-evolving-thought limitation). (ingest spec 2026-07-05 §10)

> Phase 3 (sync: Syncthing/Möbius) and Phase 5 (capture surfaces) are tracked in the vault design
> plan's phase map (`~/.claude/plans/vault-design.md`), not duplicated here.
