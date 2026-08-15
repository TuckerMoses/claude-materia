# claude-materia — BACKLOG

Top of file = next. Items are concrete and clearly actionable near-term; may be vague far-term.
Mark complete with `[x]`.

- [x] **DECISION (Tucker): §2.8 digest.md override** — **confirmed 2026-08-10.** `digest.md` is
  dropped; the digest requirement is satisfied by the changelog entry (now the commit
  description). Spec updated at `7554c23`.
- [x] **DECISION (Tucker): changelog entry in the commit description — f-o-1-7 option (b)** —
  **adopted 2026-08-10.** Entry travels in the run's commit description; `CHANGELOG.md` is a
  derived, VCS-ignored render (`commit-run` regenerates post-commit; `--regen` on demand). Spec
  rewritten at `7554c23`: prepend/revert logic, process-kill orphan window, rebase conflict site,
  sync exposure, and the §6 regeneration deferral all deleted.
- [ ] **ingest atomic-commits spec: fold the o-1 residue into the implementation plan** (session
  `20260730-2100-ingest-atomic-commits`, findings in
  `review/iterations/o-1/triage-output.json`). Applied post-loop: f-o-1-1, -2, -3, -4, -6, -15.
  Deliberately unapplied, to be handled as implementer guidance in the writing-plans pass rather
  than as spec edits: **f-o-1-5** (high — `file-notes` report completeness becomes load-bearing;
  add the contract row + under-scoping test), **f-o-1-8/-9/-10** (the no-op bullet trio:
  `entry.md` authoring-step attribution, no-op-path model-call cost, no-op exit status —
  resolve jointly, one ordering), **f-o-1-11** — mooted by the f-o-1-7(b) adoption (renderer owns all separators; no insertion
  point exists), **f-o-1-12** (fileset path anchoring + cwd), **f-o-1-13** (derive `mode` from
  `confirmed-manifest.json` presence instead of trusting the argument), **f-o-1-14** (run-log
  sublist declared twice). Note f-c-8-2 (deferred low) was mooted by f-o-1-2's applied fix.
- [ ] **adversarial-review: recalibrate tiers for single-file design specs** (evidence: session
  `20260730-2100-ingest-atomic-commits`). Cheap tier peaked by c-3, then ground six iterations
  (two bumps, +166 lines of fixer prose, 4 of o-1's 15 findings traced to cheap-fixer-composed
  text) before a "clean" c-9 that o-1 falsified with 1 critical + 6 high in one sweep. Changes to
  evaluate: (a) cap the cheap tier at ~3 iterations for spec-class scopes, or offer an opus-first
  mode with a raised `opus_max`; (b) make "simulate the artifact end-to-end over concrete
  scenarios" an explicit method instruction in the default reviewers — both o-1 reviewers credit
  it, not model acuity, for the yield; (c) instruct fixers toward surgical/tightening edits by
  default — the c-7 "narrowest edit" instruction measurably arrested prose drift (+31 → +2 lines).
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
  first real gate run (clean). Cron invocation is `/ingest --silent` on a cadence — **but requires vault plugin v1.2.0's
  atomic-commit layer (2026-08 spec) and a one-time manual commit of the vault's uncommitted
  backlog first.**
- [ ] **vault: hoist the label-semantics invariant to a shared layer — ATOMIC ROLLOVER.**
  *"Label semantics come from the bank, never from note content"* now lives **verbatim in two
  places** (`skills/ingest/SKILL.md` and `skills/synthesizer/SKILL.md`, added 2026-07-25 after a
  live ingest misclassification promoted a note's prose into a membership rule). Accepted
  knowingly: the kernel's smallest-containing-layer rule has no home to point at — the plugin dir
  has no auto-loaded contract surface, `Vault/CLAUDE.md` would cover both skills but only inside
  one vault (breaking both skills' env-agnostic invariant), and `INSTRUCTION.md` explicitly
  refuses to restate vocabulary semantics. **Trigger:** a third skill needs the rule, or a
  plugin-layer contract surface exists for another reason. **Constraint (Tucker, 2026-07-25): the
  rollover is atomic** — create the layer, strip both copies, and re-verify both skills in ONE
  session, or don't start. A half-done hoist leaves the rule declared in two places *and* a third,
  which is strictly worse than the current honest duplication. Shared core = the first three
  sentences; each copy then diverges (ingest: batch-order dependence; synthesizer: the
  minting-stakes clause about drafted `when_to_apply`).
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
