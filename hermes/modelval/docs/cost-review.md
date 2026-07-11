# Operating-cost review — Grok via X OAuth (ATLAS-HERMES-003 / Q8)

Reviewed: 2026-07-12
Signed-off-by: TODO (operator signs at acceptance)

## Cost model

Grok reaches Hermes through **X OAuth subscription auth, not a metered
API key** (decision Q7, 2026-07-11). There is no per-token bill:

- The operating cost is the **X subscription fee** itself, fixed per
  month regardless of Atlas usage, subject to the subscription tier's
  usage allowances (rate/quota limits enforced by the provider).
- The Q8 budget is **~$20/month**. The operator's subscription tier and
  its actual monthly price must be filled in here at sign-off:
  - Tier: TODO (operator)
  - Monthly price: TODO (operator)
  - Within Q8 budget: TODO yes/no (operator)

## What the session store can and cannot evidence

Observed on-device (2026-07-12, read-only): `sessions.input_tokens` /
`output_tokens` are populated and plausible; `estimated_cost_usd` is
`0.0` and `cost_status` is `unknown` for this provider. Token counts are
therefore usable as **consumption evidence** (how much the battery and
normal use consume of the subscription allowance), but no dollar figure
from the store is meaningful — the scorer reports them with that caveat
and the cost validation is this document, not metering.

## Battery consumption

The battery is 35 exchanges (20 tool-calling, 3 context probes up to
~24 k tokens, 6 refusal, 6 latency) — a bounded, one-off consumption
well within a normal day's interactive allowance. No retries are
performed by the runner; re-runs are operator choices.

## Risks

- Subscription terms or allowances may change without notice; the
  monthly fixed cost makes budget overrun unlikely, but allowance
  exhaustion would surface as provider errors (fail-visible in Hermes),
  not silent cost growth.
- If Atlas later needs a metered API key instead of OAuth, this review
  is invalid and must be redone (the threshold sheet and battery remain
  reusable).
