# claude-materia — BACKLOG

Top of file = next. Items are concrete and clearly actionable near-term; may be vague far-term.
Mark complete with `[x]`.

- [ ] **weekly-planner: vault-query wiring** (approved 2026-07-07, queued behind the kind-vault
  bridge build in `sc-kind-vault-bridge`). The deferred #4 edge: query `todo AND status:open` as a
  lifecycle consumer into weekly planning. Kernel skill — respect its `improvements.md`
  discipline; the seam + label declaration already exist.
- [ ] **research-prompt consumer** (approved 2026-07-07, queued). A puller surfacing the
  `research-prompt` / `question` queue and dispatching chosen items to `/research` /
  deep-research; one-shot archetype. Design from scratch — no prior spec.
- [ ] **Vault: relocate the 35 journal squatters.** Migrated topical notes sitting in
  `~/Vault/journal/` belong in `notes/` — where they sit they're invisible to the synthesizer.
  One-time confirmed refactor in a vault session (the `sc-vault-scan` sidechat is a natural home);
  `/ingest status` flags the anomaly until done. *(Cross-container: vault-side op, parked here
  until the vault's own todo path is live.)*
- [x] **ingest: headless/unattended mode** — built as `--silent` (2026-07-06, vault v1.1.0):
  gate skipped, mandatory digest, vocabulary frozen, synthesizer excluded. Trigger met on the
  first real gate run (clean). Cron invocation is now just `/ingest --silent` on a cadence.
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
- [ ] **ingest: "no watermark yet" wording consistency.** `ingest-status` prints "destructive
  (drain to consume)" for a vcs source lacking `last_read`, while `source-delta` quietly treats it
  as empty-delta — both should say "no watermark yet" instead (asymmetric handling, cosmetic).
  (final-review finding, 2026-07-05)
- [ ] **ingest: tolerate unreadable journal files in `journal-candidates`.** A non-UTF-8 or
  otherwise unreadable journal file currently aborts the whole drain window (loud + pre-write, so
  low risk, but unnecessarily broad) — add per-file tolerance so one bad file doesn't block the
  rest. (final-review finding, 2026-07-05)
- [ ] **ingest: idempotency boundary test coverage** — same source + different body; different
  source + same body. Behavior verified correct live; tests absent. (final-review finding,
  2026-07-05)
- [ ] **ingest: test fixture for `ingest-status`'s marked-then-modified detection path.**
  (final-review finding, 2026-07-05)
- [ ] **ingest: vcs branch pinning.** The registry has no branch field; drain reads whatever's
  currently checked out. Revisit if branch pinning ever matters. (final-review finding, 2026-07-05)
- [ ] **ingest: pin git identity in test suites' throwaway `git commit` calls** (`-c
  user.email=... -c user.name=...`) — currently depend on global git identity, which breaks
  portability. (final-review finding, 2026-07-05)

> Phase 3 (sync: Syncthing/Möbius) and Phase 5 (capture surfaces) are tracked in the vault design
> plan's phase map (`~/.claude/plans/vault-design.md`), not duplicated here.
