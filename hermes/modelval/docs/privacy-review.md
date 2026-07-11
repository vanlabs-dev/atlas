# Privacy review — Grok via X OAuth (ATLAS-HERMES-003 / PRD §15.7)

Reviewed: 2026-07-12
Signed-off-by: TODO (operator signs at acceptance, after completing the
account checks below)

## Boundary being reviewed

Decision Q9 (2026-07-11) already allows conversations to leave the Pi to
a hosted model: prompts, retrieved evidence, and Hermes tool results are
sent to xAI's Grok service, authenticated by the operator's X account
via OAuth. Secrets and wallet material are excluded from conversations
by design (ATLAS-MEM-005, ATLAS-API-008), and the memory verifier
enforces secret-free memory. This review covers what the provider may do
with what it receives, per PRD §15.7 (retention, training use,
telemetry).

## Provider posture (evidence states per PRD §2)

Sources retrieved 2026-07-12. Everything below is **web-lead grade until
the operator confirms it against the authoritative policy** at
[x.ai/legal/privacy-policy](https://x.ai/legal/privacy-policy) during
sign-off — third-party summaries conflict on the key point.

1. **Training on conversations — CONFLICTING (unresolved):** one
   third-party source states xAI defaults to *not* training on
   conversations with an explicit opt-in ("Improve the Model" setting);
   others state conversations are used by default with an opt-out
   toggle, and that the toggle only affects future use. Per PRD §2 this
   stays **Conflicting** until the operator reads the current policy and
   inspects the actual account setting. The resolution action is the
   account check below, not a guess.
2. **Retention — Unverified:** deleted conversations/accounts are
   reported to be removed from xAI systems within ~30 days, with
   legal/safety carve-outs. A "Private Chat" mode reportedly keeps
   conversations out of history and deletes them within 30 days (not
   applicable to API/OAuth agent traffic as far as reported).
3. **Public X posts — Unverified:** public posts are reportedly used for
   training by default for non-EU users. Not an Atlas data path (Atlas
   sends prompts, not posts), noted for completeness because the same
   account is involved.
4. **Telemetry:** Hermes-side telemetry is already disabled and verified
   (Q11, baseline check `telemetry-disabled`). Provider-side collection
   is inherent to using a hosted model and is governed by the policy
   above.

## Operator actions required before sign-off

1. Read the current [xAI privacy policy](https://x.ai/legal/privacy-policy)
   and note its date here: TODO.
2. On the X account used for the OAuth login, locate the data/training
   setting (reported as Settings → Data → "Improve the Model" or a
   Grok-training toggle) and record its state here — and set it to the
   most restrictive available option: TODO.
3. Decide whether the resolved posture is acceptable for Atlas prompts
   and retrieved Bittensor evidence (personal secrets are excluded by
   design either way): TODO accept/reject.

## Standing consequences

- Anything sent to the provider must be assumed retained for up to the
  policy's stated window regardless of settings; Atlas therefore keeps
  excluding secrets from every conversation path (enforced, not hoped).
- If xAI's policy or the account's training setting changes, this review
  is stale and must be redone before the next acceptance-grade decision
  relying on it.

Sources (retrieved 2026-07-12, all web-lead grade):
[x.ai privacy policy](https://x.ai/legal/privacy-policy) ·
[Anonyome on Grok privacy](https://anonyome.com/knowledge-center/ai-privacy/grok-privacy/) ·
[TrustScan opt-out guide](https://trustscan.dev/blog/how-to-opt-out-grok-xai-data-training-2026) ·
[LLMnesia on Grok retention](https://www.llmnesia.com/blog/grok-conversation-history-limits)
