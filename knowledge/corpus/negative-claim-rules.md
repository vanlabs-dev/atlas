# Negative Claim Rules

This file governs all claims that characterize a subnet negatively.
These rules are enforced in Step 4 of the pipeline before any article
can be published.

---

## What Counts as a Negative Claim

Any of the following requires the full verification process below:

- Development is inactive, stalled, paused, or absent
- No commits since [date]
- Team is absent, unresponsive, or has departed
- Project appears abandoned or dormant
- No public activity
- GitHub shows no recent work
- Codebase has not been updated
- Development gap of [N] months
- No releases, no changelog, no PRs

---

## Verification Process (Required Before Writing)

### Step A: Check GitHub directly

GitHub API (Source 2 in data-sources.md) must be called before any
inactivity claim. The Supabase snapshot alone is never sufficient.

If `pushed_at` from the GitHub API is within 45 days of today:
- Development is NOT inactive. Do not write inactivity claims.
- Use the live GitHub data in the article.

If `pushed_at` is more than 45 days ago, proceed to Step B.

### Step B: Check Desearch for counter-evidence

Scan the Desearch completion text and tweets for any of the following
signals from the past 30 days:

- Product releases, changelog entries, or version announcements
- Partnership or customer announcements
- Team posts about development, features, or roadmap progress
- Community posts referencing new functionality
- Any evidence the team is actively working

If ANY counter-evidence is found in Desearch:
- Do NOT write inactivity claims
- Instead use: "Public GitHub activity has slowed since [date], though
  the team [has announced / is actively engaged with / recently
  shipped] [specific evidence from Desearch]."
- Save as draft and flag in Telegram so vaN can review

If Desearch also shows no signals of active development:
- Proceed to Step C

### Step C: Write with hedged language and correct attribution

If both GitHub and Desearch confirm low activity, write with:
1. The exact data point and its date: "The public GitHub repository
   shows the last commit on [date from GitHub API]"
2. The source type: "via live GitHub API check" or "via cached snapshot
   from [snapshot_date] — direct API call unavailable"
3. Appropriate hedging: "This may reflect a transition to private
   development, an internal build phase, or reduced public activity"

Never write: "development has been inactive" as a bare assertion.
Always write: "public GitHub commits have slowed since [specific date],
though this may not reflect the full picture of internal development."

---

## Single-Repo Limitation

The github_snapshots cron and the GitHub identity field track ONE repo
per subnet. Before asserting inactivity:

1. Check if `identity.github` from TaoSwap matches what is in
   Supabase subnet_data. If they differ, use the TaoSwap URL.
2. Consider that development may have moved to a private repo or a
   different organization. Desearch is the cross-reference for this.
3. If the GitHub URL returns 404, this means the repo was deleted,
   made private, or moved — NOT that the team is inactive.
   Flag as draft and send a conflict Telegram.

---

## Market Size Claims

Claims like "the market is projected to reach $X billion by [year]"
sourced from Desearch web summaries require either:
- A clearly cited source URL
- Or mandatory hedged language: "reportedly", "according to analysts",
  "industry estimates suggest"

Never present web-sourced market projections as bare facts.

---

## Auto-Publish Restriction

Any article containing a negative claim — even one written with correct
hedging — must save as draft. The `NEGATIVE_CLAIM_PRESENT` flag must
be set to true in the publish logic.

See `references/publish-logic.md` for how this interacts with the
publish decision.

---

## Stale-Identity Stub Exemption

A stale-identity stub (Step 2 **Parked** classification) states only the
verifiable on-chain identity status. Because it makes NO characterization of
the team, development, or activity, it is NOT a negative claim and the
`NEGATIVE_CLAIM_PRESENT` gate does not apply. It publishes normally.

The exemption holds ONLY while the stub stays factual. It must not use
abandonment or inactivity language ("abandoned", "dormant", "inactive",
"for sale", "team has left") or infer WHY the identity is unset. State the
on-chain identity field and nothing more. The moment the article
characterizes the project rather than reporting the chain fact, the normal
negative-claim gate applies again.
