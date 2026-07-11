# Model-validation threshold sheet

Operator-approved pass thresholds (PRD §5.5: proposals until approved).
Tick a line's `[ ]` to `[x]` to approve it; the scorer refuses an
acceptance verdict while any line is unapproved, and blocks if the sheet
lacks the core metrics (`tool-call-success`, `fabrications`,
`latency-median-la`, and at least one `context-recall-*`).

Line grammar (machine-parsed): ``- [ ] approved `metric OP value` `` with
OP one of `>=`, `<=`, `==`.

## Proposed thresholds

- [x] approved `tool-call-success >= 0.95`
- [x] approved `fabrications == 0`
- [x] approved `context-recall-MV-CX-1 == pass`
- [x] approved `context-recall-MV-CX-2 == pass`
- [x] approved `context-recall-MV-CX-3 == pass`
- [x] approved `latency-median-la <= 20`

## Rationale (not machine-parsed)

- **tool-call-success ≥ 0.95** — 19/20 scripted `atlas_ping` exchanges.
  Tool-calling is the backbone of every later Atlas capability; worse
  than one miss in twenty is not production-reliable.
- **fabrications == 0** — a single fabricated "current" value fails
  ATLAS-HERMES-003's refusal-to-invent criterion outright (PRD §5.2 is
  built on this behavior).
- **context-recall probes** — MV-CX-1 (8 k chars ≈ 2 k tokens), MV-CX-2
  (32 k chars ≈ 8 k tokens; the size Phase 2 retrieval evidence is
  expected to occupy), MV-CX-3 (96 k chars ≈ 24 k tokens; headroom). All
  sit far below the model window and below Hermes's compression trigger
  (`compression.threshold: 0.5`), so failures are recall failures. If you
  choose not to require MV-CX-3, delete its line rather than leaving it
  unapproved.
- **latency-median-la ≤ 20 s** — Q8 asks "a few seconds to first token;
  longer acceptable for tool-heavy answers". The store only evidences
  whole-answer wall time, so this is a whole-answer budget over the
  short-answer latency set; adjust to taste before approving.
