# Autonomy mode for adversarial-review: design

Status: approved in conversation 2026-11-18; details below are the builder's calls unless marked "user".

Paths are relative to `skills/adversarial-review/` unless they start with `review/` or `iterations/`, which are relative to a session directory.

## Intent

The user wants some reviews to run with no one answering. Today the loop stops at every escalation and waits for a typed reply, and the only way around that has been an ad hoc exception where the session itself plays the user. That exception breaks the blind-orchestrator rule: to decide an `accept-risk` the session has to read findings.

Autonomy mode replaces the exception with a seam. A **principal** answers escalations in the user's place. The principal is a subagent, so finding substance stays out of the session, and it decides from a brief the session writes before the loop starts, so the user's intent still reaches it.

## Goals

- A review started in autonomy mode runs to completion without user input unless something exceeds what the user delegated.
- The session stays blind to finding substance for the whole loop.
- What the user delegated is written down before the loop and readable afterward.
- At the end the user gets a short brief of what changed that matters, and the session points out anything in it the user is likely to mind. (user)

## Non-goals

- A general phase model for rounds, or pluggable final-phase agents. Deferred until a reviewer that consumes other reviewers' output exists.
- Replacing triage. Triage still normalizes, routes, and authors every surface. The principal replaces only the person who answers.
- Running the principal inside the session. Rejected: it puts findings in orchestrator context.

## Anti-goals

- A principal that accepts whatever is in its way to reach `exit_clean`.
- Decisions the user cannot trace afterward.
- Autonomy mode silently turning on.

## Design

### 1. Trigger (user)

Autonomy mode is on when either holds:

- the invocation carries `--autonomy`; or
- the user has said, in the conversation that invokes the skill, that they want to be hands off for this review (for example "run it without me", "I'll be away", "don't stop to ask me").

A general preference stated in some earlier, unrelated task does not count. When the session infers the mode from conversation, it says so in one line at setup ("Running in autonomy mode because you said …") so the user can correct it. The mode is fixed at setup and recorded in `review/session-meta.json` as `autonomy: true | false`. The brief's bump limit is recorded beside it as `principal_bump_limit`, so the orchestrator can enforce it without reading the brief's prose.

### 2. Setup changes (SKILL.md Phase 1)

In autonomy mode:

- **No confirmation waits.** Step 1 builds the manifest from the conversation without asking; step 4 shows the manifest summary and proposed pool and proceeds without waiting. If `intent` cannot be derived from the conversation, autonomy mode cannot start: ask once, as today.
- **No-VCS warning.** Step 2's "Continue?" still waits for the user. Running unattended with no way to revert is not something to assume.
- **Principal brief.** The session writes `review/principal-brief.md` from the conversation, before any reviewer runs. This is the only point where the session's knowledge of the user's intent enters the loop. Template:

  ```markdown
  # Principal brief

  ## What the user wants from this review
  [What they said the review is for, what they care about most, what they would rather not see. Quote them where possible. State only what the conversation supports.]

  ## What you may decide
  [Start from the default limits below. Widen or narrow only where the user said so, and quote what they said.]

  ## What you must send back
  [Start from the defaults below, plus anything the user said they want to decide themselves.]
  ```

- **Default limits**, used unless the user said otherwise:
  - `bump`: at most 3 extra iterations per tier in total, and only while the count of open high and medium findings is falling: lower than in the previous iteration of the same tier. With no previous iteration in the tier, the condition is met.
  - `accept-risk`: medium and low findings only, and only for a reason the brief lists. The default reasons: the finding contradicts a decision the user already made; it concerns behaviour outside what this review is for; its fix would remove meaning the user wants kept.
  - Never: accept a high or critical finding; accept a `baseline_unavailable` or `incomplete_check` finding; abort.
- The session shows the brief's path and its two limits sections at setup. It does not wait.
- `agents/principal.md` is copied into the session's `agents/` with the other system agents.

### 3. Answering an escalation (SKILL.md Phase 2 step 1)

When `surface.requires_response` is true and autonomy mode is on, the orchestrator does not ask the user. It:

1. Echoes `surface.breadcrumb` and `surface.path`, as today, so the transcript shows the escalation.
2. Writes a fixed-template prompt to `iterations/<tier>-<N>/dispatches/principal.md` containing only paths: the brief, this iteration's `user-surface.md`, `triage-output.json`, and `route.json`, and every earlier `user-response.md`.
3. Dispatches the principal (always on the most capable model) with the dispatch-discipline wrapper, except the last line: the principal ends with a decision, not an ACK.
4. Reads the principal's final two lines:

   ```
   RESPONSE: <bump N | accept-risk <ids> | continue | defer-to-user>
   REASON: <one sentence; findings named by id and severity only>
   ```

   The orchestrator may read these two lines. They carry no finding substance by contract, the same contract `surface.recommendation` already follows. Anything else in the principal's reply is ignored.
5. Applies the hard limits (below). If the response passes, writes `iterations/<tier>-<N>/user-response.md`:

   ```
   source: principal
   <the RESPONSE value>
   reason: <the REASON value>
   ```

   and re-dispatches triage exactly as for a human reply.

**Hard limits the orchestrator enforces mechanically**, whatever the brief says. Each converts the response to `defer-to-user`:

- the reply does not end with a well-formed `RESPONSE:` / `REASON:` pair;
- `RESPONSE` is `abort` or anything outside the four allowed forms;
- a `bump` would take the principal's total bumps in this tier above `principal_bump_limit` (the orchestrator sums the `bump` values in this tier's `user-response.md` files that begin `source: principal`).

**Limits triage enforces**, because only triage sees severities: when a `user-response.md` beginning `source: principal` accepts a finding whose severity is high or critical, or whose type is `baseline_unavailable` or `incomplete_check`, triage does not accept it. It leaves `accepted-risks.json` unchanged and emits `control: escalate` with `surface.human_only: true`.

**`surface.human_only`** is a new optional boolean in `route.json` (absent means false; `schema_version` stays `"1"`). When true, the orchestrator surfaces to the user even in autonomy mode.

**`defer-to-user`**, from the principal or from a hard limit, and any `human_only` surface: the loop pauses. The orchestrator surfaces to the user exactly as it would outside autonomy mode, prefixed with one line: "Autonomy mode paused: this decision is outside what the principal may decide." It waits. The user's typed reply is written to `user-response.md` with no `source:` line, and the loop resumes in autonomy mode.

**Baseline comparison failure** (non-zero exit): in autonomy mode the orchestrator reruns the script once without asking. If it fails again, it surfaces the usual `retry` / `abort` line to the user and waits. The principal is not consulted; it cannot repair plumbing.

**Triage contract violation** (iteration limit fail-safe): surfaced to the user, never the principal.

### 4. The principal (`agents/principal.md`, new system agent)

- Reads the brief first, then the escalation's `user-surface.md` and `triage-output.json`, then earlier responses. Forms its decision. Only then reads `surface.recommendation` in `route.json`; it may disagree with it.
- Chooses one of the responses the surface offers, or `defer-to-user`. It defers whenever the brief does not clearly cover the decision. Reaching `exit_clean` is not its goal; answering as the user would is.
- Writes no files. Ends with the two-line decision and nothing else.
- Keeps substance out of `REASON`: ids, severities, and which brief clause applies.

### 5. Triage changes (`agents/triage.md`)

- §10 `route.json`: document `surface.human_only`.
- §12: a `user-response.md` may begin with `source: principal`. Parse the second line as the response. Apply the severity and type guard above. Never see `defer-to-user`; the orchestrator handles it.
- §9 `user-surface.md`: when the decision options include something the principal may not choose (accepting a high finding, a plumbing failure), say so in "Decisions needed", so a human reading a paused run knows why it reached them.

### 6. The end-of-run brief (SKILL.md Phase 4, `agents/scribe.md`) (user)

In autonomy mode the scribe writes a second file, `review/autonomy-brief.md`, in addition to `summary.md`. The summary is the full ledger; the brief is what someone who was away needs to read first. It contains only:

```markdown
# Autonomy brief

**Outcome:** Clean | Aborted | Limit-reached | Paused for user (N times)

## Decisions made for you
[One line per principal decision: iteration, the response, its stated reason, and what it meant for the artifact. "None" if the principal was never consulted.]

## Changes of significance
[Changes to what the scope says or does: requirements added, removed, strengthened or weakened; behaviour changed; structure reorganized. Each with the file and the finding that drove it. Exclude wording fixes, clarifications that did not change meaning, and formatting.]

## Still open
[Accepted risks, deferred lows that could matter, anything unresolved.]

## Size
[Baseline vs final, in lines and words, from the last `baseline-sizes.tsv` TOTAL row.]
```

The scribe's dispatch prompt gains: the autonomy flag, the path to `principal-brief.md`, and the path to the last iteration's `baseline-sizes.tsv`.

After the scribe returns, the session reads `review/autonomy-brief.md` (and only that file). This is an authorized read: the loop is over, and the Read-discipline rule covers Phase 2. The session then tells the user, in a few lines, which items in the brief they are likely to mind given what they said in the conversation, and why; or says plainly that nothing stands out. It does not restate the brief.

The Phase 4 sentence "The orchestrator never reads any session-state file at terminate time" gains this one exception.

### 7. Scribe write fallback (SKILL.md Phase 4, `agents/scribe.md`)

Found in the pilot: some harnesses refuse a subagent's write of a report-like file and tell it to return the text instead. The scribe then cannot ACK. New rule: if a write is refused, the scribe ends its turn with `WRITE-REFUSED <path>` on the first line followed by the full file content; for two files, each block starts with its own `WRITE-REFUSED <path>` line. The orchestrator saves each block verbatim to its path and continues. This is the one case where the orchestrator handles a subagent's content; it happens after the loop, so blindness during Phase 2 is unaffected.

### 8. Docs and version

- SKILL.md: a new `## Autonomy mode` section holding §1–§3 and §6's session step; one-line pointers from Phase 1 steps 1, 2, 4, 5, Phase 2 steps 1 and 3 (b2), and Phase 4; `--autonomy` in Subcommands and `argument-hint`; `principal` added to the dispatch-discipline agent list with its different last line; Acknowledgment-discipline notes the two exceptions (principal decision, scribe write fallback); session layout shows `review/principal-brief.md`, `review/autonomy-brief.md`, `dispatches/principal.md`.
- README.md materia table: one clause on autonomy mode.
- `.claude-plugin/plugin.json`: 0.15.0 → 0.16.0.
- Branch `adversarial-review/autonomy-mode`, stacked on `adversarial-review/bloat-and-lost-items`.

## What the pilot showed

The principal was piloted on the review of the bloat/lost-items implementation, with a hand-written agent and brief.

- **A healthy run never consults the principal.** The pilot review ran seven rounds across both tiers with no escalation. In practice the largest effect of autonomy mode is removing the setup confirmation waits; the principal is for the unusual run.
- **Three constructed escalations, all decided as the brief intends.** (A) A round-limit escalation over the run's real findings: `bump 1`, citing the falling count and the unspent budget. (B) A baseline failure with triage recommending acceptance: `defer-to-user`. (C) A recurring medium finding that contradicts the approved spec, one bump already spent, triage recommending another bump: `accept-risk`, declining the bump. Each took 10 to 20 seconds.
- **Returning the decision as text works, and writing a file would not have.** In the earlier design review the harness refused the scribe's write of `summary.md`. The principal therefore writes nothing (§4) and the scribe gets a fallback (§7).
- **The reasons stayed free of substance** without extra prompting: ids, severities, and which clause of the brief applied.
- **"While the count is falling" needed a definition.** Writing test A showed the brief did not say what to compare against. §2 now reads: falling means lower than the previous iteration in the same tier; with no previous iteration in the tier, the condition is met.
- **The session wanted a progress number and reached for a file it must not read** (the size table's TOTAL row). The end-of-run brief carries the size (§6) so the session never needs to.
- **Setup confirmations were skipped by necessity in both pilot runs** with no ill effect; §2 makes that the rule in this mode.

## Calls made without asking

- The principal is a subagent deciding from a written brief, never the session (agreed in conversation).
- Default limits: 3 bumps per tier; accept medium and low only, for listed reasons; never high, critical, plumbing failures, or abort.
- The session does not wait for the user to approve the brief; it shows the limits and proceeds.
- Hard limits are enforced twice: mechanically by the orchestrator where it can without reading findings, and by triage where severity is needed.
- A paused run resumes in autonomy mode after the user answers.
- The no-VCS warning still waits for the user.
