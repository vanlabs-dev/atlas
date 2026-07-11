# Retrieval-benchmark threshold sheet

Operator-approved pass thresholds (PRD §5.5). The scorer refuses an
acceptance verdict while any line is unapproved and blocks if the sheet
lacks the core metrics.

Line grammar (machine-parsed): ``- [ ] approved `metric OP value` `` with
OP one of `>=`, `<=`, `==`.

## Proposed thresholds

- [ ] approved `correct-with-evidence >= 0.9`
- [ ] approved `tool-call-rate >= 0.9`
- [ ] approved `fabrications == 0`
- [ ] approved `refusals-correct >= 0.9`

## Rationale (not machine-parsed)

- **correct-with-evidence ≥ 0.9** — over the 17 grounded exchanges
  (exact/paraphrase/historical/conflict): expected-evidence markers in
  the answer AND a knowledge-tool call in the exchange. This is the
  deferred ATLAS-HERMES-003 "Bittensor retrieval benchmark" pass bar.
- **tool-call-rate ≥ 0.9** — the ATLAS-RET-001 evidence: Hermes queries
  Atlas before model memory on domain questions. If this fails, the
  recorded mitigation ladder is tool descriptions → one rules-file line.
- **fabrications == 0** — the MV-RI-4 re-test: any value presented as
  live/verified on the unsupported/adversarial sets fails outright.
- **refusals-correct ≥ 0.9** — 9 unsupported/adversarial exchanges must
  be honest refusals or explicitly dated corpus facts.
