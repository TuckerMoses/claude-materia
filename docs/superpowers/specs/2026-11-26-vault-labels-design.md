# Vault labels: vault-owned vocabulary, label proposals, surgeon, routing adapters

Status: reviewed with the author 2026-11-26; decisions D1 to D14 settled. Nothing here is built.
Plugin: `plugins/vault` (currently 1.3.0). This is a breaking change; target version 2.0.0.

**Superseded by implementation (2026-11-26).** Where these points and sections 3, 5.1, 7 and 9 differ, the
implementation stands: `label-bank` also has `merge --from --into` (one commit moving every note, routing
rule and source lens from the absorbed label to the survivor, then removing it; refused when the absorbed
label is imported or protected) and a read-only `show`; the surgeon's `merge A into B` is that one call.
`label-proposals accept` writes `labels.yml` itself, adding the entry and removing the proposal in one
commit, rather than calling `label-bank add`, so the bank has two writers. A protected label's text
(including `needs-label`'s, section 9) is changed with `label-bank update` directly, outside the surgeon,
which still refuses every operation on protected labels. No writer creates `origin: imported` entries yet;
the migration seed (section 10, step 2) or a future import adapter would.

## 1. Why

Four problems, one design:

1. **Asking for a label is not possible at capture time.** A thought that deserves a new label can only
   wait for the synthesizer to notice it. The author wants to write the request in the journal.
2. **Labels cannot be changed once minted.** No rename, merge or retire exists. Vocabulary quality depends
   on iteration, and iteration needs safe edits.
3. **The vocabulary lives outside the vault.** The label bank and routing sit in an external standard
   library that is being redesigned. The vault should own its vocabulary and run with nothing else present.
4. **Routing is hard-wired to that library.** Delivery of actionable notes to external backlogs is coded
   against its files and functions.

## 2. Decisions already taken

| # | Decision |
|---|---|
| D1 | The vocabulary (subject, type and action labels) moves into the vault. The vault is its only writer. |
| D2 | The vault takes no dependency on any external library. No calls into it, no reads of its registry or routing files. |
| D3 | Delivery to external targets is switched off until the external system's API settles. The current library-backed delivery code is deleted, not kept as a disabled adapter. Version history holds it. |
| D4 | Routing stays as a subsystem: label match to one or more targets, each target an adapter. It ships with the notes target only. |
| D5 | Ingest writes label *proposals*, never active labels. One exception: at the interactive gate the human may accept an explicit proposal on the spot. |
| D6 | Open actionables are shown by a live view over the notes. No stored list, no vault-local backlog target. |
| D7 | Existing container labels (`workspace:*`, `project:*`) stay in the bank as a frozen, read-only snapshot so ingest keeps applying them. |
| D8 | `todo`, `session-seed` and `delegated` keep their names and meanings. They are protected from rename. |
| D9 | Growing the vocabulary and changing it are two skills. The synthesizer owns growth (`scan` opens proposals, `resolve` reviews them). The surgeon owns changes to what exists. They share scripts, not a skill. |
| D10 | The synthesizer's `scan` no longer mints labels. A theme it finds becomes a proposal with evidence, like any other. Acceptance in `resolve` is the only path into the bank. |
| D11 | A rename is one atomic operation: the bank entry's name and every note carrying it change in a single commit. No old entry is left behind, retired or otherwise. |
| D12 | Proposals never expire and are never auto-rejected. A proposal may sit for months until a cluster forms around it. |
| D13 | Rejected proposals are remembered in a short list so ingest does not reopen them. An explicit `label::` overrides it. |
| D14 | Bank entries carry no subject/type/action field. Whether a subject label fits a thought is the classifier's judgement. |

## 3. The label bank

**File:** `<vault>/_machine/labels.yml`, validated by a schema the plugin ships.

```yaml
labels:
  roadmap:
    when_to_apply: "…"
    status: active          # active | retired
  todo:
    when_to_apply: "…"
    status: active
    protected: true         # optional; surgeon refuses rename, merge, retire
  workspace:learning:
    when_to_apply: "…"
    status: active
    origin: imported        # optional, default local; read-only to every vault writer
```

- `protected: true` on `todo`, `session-seed`, `delegated`, `needs-label`.
- `origin: imported` marks labels the vault does not own. Today that is the frozen snapshot of container
  labels (D7). Later an adapter may refresh them. With none present the vault still works.

**Sole writer:** one script, `label-bank`, with subcommands:

| Subcommand | Effect | Refuses when |
|---|---|---|
| `add --name --when-to-apply` | new active local label | name exists; name fails the schema pattern |
| `update --name --when-to-apply` | rewrite the text | label is imported |
| `retire --name` | status to retired | label is imported or protected |
| `rename --from --to` | change the entry's name, keeping its text and status | target name exists; imported or protected |
| `remove --name` | delete the entry | any note still carries it; imported or protected |

Every mutation validates against the schema, refuses if the bank file has uncommitted changes, and ends as
one path-scoped commit (reusing `commit-run`'s mechanism). The bank is never hand-edited.

`rename` is the one mutation that also touches notes: it takes the relabel primitive's path (section 4) so
the bank entry, every note carrying the old name, and any routing rule or source lens naming it change in
the same commit, or not at all (D11).

## 4. The shared relabel primitive

**Script:** `relabel-notes <vault> <manifest.json>`. The manifest maps note slug to `{add: [...], remove: [...]}`.

- Edits frontmatter `labels` only. Body md5 is taken before and after; any mismatch aborts the whole run.
- Every added label must be active in the bank. Removed labels need not be.
- All-or-nothing: either every note in the manifest is rewritten, or none is.
- One commit per run, with the manifest's stated reason as the description.

Used by proposal acceptance (section 6) and by the surgeon (section 7). Nothing else rewrites `labels`
in bulk.

## 5. Label proposals

### 5.1 The proposal bank

**File:** `<vault>/_machine/label-proposals.yml`, schema shipped by the plugin.

```yaml
proposals:
  roadmap:
    when_to_apply: "draft text, written by ingest or the human"
    origin: explicit        # explicit | implicit
    opened: 2026-11-26
    evidence:
      - source: journal/2026-11-21
        quote: "Sketch the bed layout before ordering seeds."
        note: sketch-the-bed-layout      # optional; a slug can go stale after a merge
        added: 2026-11-26
rejected:
  - name: nix-stuff
    reason: "too broad; covered by an existing label"
    date: 2026-12-03
```

- Evidence stores the verbatim trigger text and its source day, so it survives note merges and renames.
- This file is the one sanctioned exception to "no stored label-to-notes index". It is transient: an
  entry is deleted when its proposal is accepted or rejected.
- `rejected` is a short memory so ingest does not reopen the same implicit proposal every night. An
  explicit request from the human overrides it and reopens the proposal.

**Sole writer:** `label-proposals` with `open`, `attach`, `revise`, `rename`, `merge`, `accept`, `reject`.
`accept` calls `label-bank add` and deletes the proposal. Same validation and commit discipline as the bank.

### 5.2 The explicit request: `label:: <name>`

A line starting with `label:: ` inside a journal thought. Double colon is Dataview's inline-field syntax,
so Obsidian renders it and prose containing "label:" cannot trigger it. It attaches to the thought block
it sits in. A thought may carry several. The line stays in the note body (bodies are verbatim).

| `<name>` is… | Ingest does |
|---|---|
| an active label (local or imported) | applies it. All modes, including `--silent`. |
| an open proposal | attaches the thought as evidence; adds `needs-label` |
| unknown | opens an explicit proposal with a drafted `when_to_apply` from context; adds `needs-label` |
| previously rejected | reopens it as explicit, carrying the old rejection reason; adds `needs-label` |
| retired | adds `needs-label`; reports it in the digest. Never revives a label on its own. |
| not a valid label name | proposes the normalised name; reports the change in the digest |

At the interactive gate an explicit proposal can be accepted immediately (D5). `--silent` never accepts.

### 5.3 Implicit proposals

- **Attach:** any thought, whatever its other labels, may be attached to an existing open proposal when
  it fits the draft `when_to_apply`. This is how evidence accumulates.
- **Open:** ingest opens a new implicit proposal only when no label describing the thought's *subject*
  fits. Type labels (`idea`, `question`, …) and action labels do not count as fitting.
- Themes across already well-labelled notes remain the synthesizer `scan` pass's job. `scan` records a
  theme by opening a proposal with its member notes as evidence; it does not mint (D10).
- The ingest subagents read the proposal bank alongside the label bank, as data.

### 5.4 `needs-label`, redefined

Old meaning: nothing fits. New meaning: **this note is waiting on vocabulary**, either because nothing
fits or because it is evidence for an open proposal. It now coexists with real labels. The proposed
label's name is never written to the note before acceptance.

The ingest invariant "label semantics come from the bank, never from note content" is narrowed, not
dropped: prose in a note is still data, and only a `label::` line is a request.

## 6. Review and acceptance: `/synthesizer resolve`

`resolve` stops being stateless clustering and starts from the proposal bank.

1. **List** open proposals ranked by evidence count, then age. By default the sitting presents explicit
   proposals and any proposal with two or more evidence records. Implicit proposals with a single record
   are counted in the header and shown on request; they wait, without expiring, for more evidence (D12).
   The header also shows the running accept and reject counts, so a falling acceptance rate is visible.
2. **Iterate** per proposal with the human: revise wording, rename, merge into another proposal or into
   an existing label, accept, reject, or leave open. The human may add proposals by hand here.
3. **Residue:** `needs-label` notes tied to no proposal get the existing recheck-and-cluster treatment,
   and any cluster becomes a proposal in the same sitting.
4. **Apply accepted labels**, in one confirmed manifest through `relabel-notes`:
   - **Sweep A, pending notes:** every `needs-label` note is classified against the newly accepted labels
     and the rest of the active bank. `needs-label` is cleared from a note once it is evidence for no
     remaining open proposal.
   - **Sweep B, backfill:** for each accepted label, search the whole pool for candidates (ripgrep on
     terms from the definition and evidence), classify them, and show the proposed additions. Without
     this, earlier notes that already carried a generic label would never receive the new one.
5. **Effect check:** accepted labels sit in the bank; their proposals are gone; swept notes carry them.

## 7. Surgeon: `vault:surgeon`

A new skill for changing vocabulary that already exists. Every operation is propose-confirm, shows a dry
run first (how many notes, which rules and lenses), and refuses imported and protected labels.

| Operation | Steps |
|---|---|
| `rename A B` | `label-bank rename`: bank entry, every note, routing rules and source lenses in one commit |
| `merge A into B` | relabel every note A→B → rewrite references → `label-bank remove A` |
| `retire A` | `label-bank retire A`; notes keep it for history |
| `split A` | human defines the new labels; each note carrying A is classified among them at a gate → relabel → retire or remove A |
| `redefine A` | `label-bank update`; then offer a re-check of A's current notes against the new text |

After a rename there is no old entry (D11). After a merge the absorbed label is removed: no note carries
it, and history is in version control. Only an explicit `retire` leaves a retired entry.

## 8. Routing behind adapters

- **File:** `<vault>/_machine/routing.yml`, owned by the vault. Rules keep today's match semantics
  (`any`, `none`, wildcard, multicast). Each rule lists target names.
- **Adapter interface:** an executable that takes one labelled thought as JSON and returns
  `{status: delivered, landed: …}` or `{status: failed, reason: …}`. Targets are declared in the routing
  file with the adapter they use and its parameters.
- **Ships with:** the `notes` adapter only (today's `file-notes`).
- **Deleted:** every call into the external library in `dispatch-targets` and `ingest-status`, the
  `backlog` row in the dispatch table, and all reads of `AGENT_LIB`.
- **`ingest status` gains:** a count of undelivered actionables, meaning notes with an action label, no
  `outcome`, and no non-notes target in `routed_to`. It loses the backlog reconciliation checks.
- **`note-outcome` stays** as the direct way to mark a note done or dropped.
- **Planned, not built now:** when a new adapter is enabled, one interactive pass offers it every
  undelivered actionable.

## 9. Contract text that changes

- `INSTRUCTION.md` template and the live vault's copy: bank path; "Register a missing label" section
  (now `label-bank` and proposals); field ownership (surgeon and acceptance write `labels`); the
  proposal-bank exception to the no-index rule; the `label::` request.
- Vault `CLAUDE.md` template and live copy: "Vocabulary growth lives in the synthesizer, never ingest"
  becomes "ingest proposes, review accepts".
- `ingest` SKILL.md: silent mode writes proposals; invariant narrowed as in 5.4; routing section.
- `synthesizer` SKILL.md: `resolve` is no longer stateless.
- Bank entry for `needs-label`: new `when_to_apply` text.

## 10. Migrating the live environment

Done once, supervised, after the plugin work merges. The nightly ingest job is live, so the switch is
atomic from its point of view.

1. Pause the nightly job.
2. Seed `<vault>/_machine/labels.yml` from the current bank: local labels as they are, container labels
   as `origin: imported`, the four protected flags set.
3. Create `_machine/routing.yml` (notes target only) and an empty `_machine/label-proposals.yml`.
4. Update the live `INSTRUCTION.md`, `CLAUDE.md` and the vault binding file.
5. Update the nightly wrapper: drop the library paths from its allowlist and prompt; name the bank at
   its vault path.
6. Update and reload the plugin. Run one supervised ingest, then re-enable the job.
7. Leave the external library's own bank untouched; it is that system's concern. Log the change as a
   request against its frozen spec rather than editing the spec.

## 11. Work packages

| WP | Content | Depends on |
|---|---|---|
| WP0 | Bank schema, `label-bank`, `relabel-notes`, tests | none |
| WP1 | Routing adapters, removal of library coupling, `ingest status` changes, tests | WP0 |
| WP2 | Proposal bank, `label-proposals`, ingest and resolve skill text, tests | WP1 (same files) |
| WP3 | `vault:surgeon` skill | WP0 |
| WP4 | Live migration (section 10) | all merged |

WP1 and WP2 both edit `ingest/SKILL.md` and `dispatch-targets`, so they run in sequence on one branch.
WP3 touches neither and runs in parallel in a second worktree branched from WP0.

## 12. Open questions

None. The four raised in the first draft are settled as D11 to D14.
