# Design

## Context

See proposal.md (Why). State on 2026-11-04, verified read-only against
the code, the committed fixtures and the Pi at `3d7ce47`:

- Committed fixtures date from 2026-10-22/29 and predate WP4 and WP8. They
  carry `cueKind` (47 up, 55 dn, 1 amb), `confidence`, `gateState`; every
  `netTaoMonth` is null. Pages pass whole row objects to client
  components, so every fixture key reaches the RSC payload.
- On the Pi every `mine_econ` row at or before a seven-day cutoff has
  `model_version` NULL (pre-WP4), and all 105 `mine_feasibility` rows were
  scanned 2026-11-03. A seven-day export today publishes the old model
  with every verdict blank.
- `metric_activity.c7/c30` exclude bots at write (WP8). The export's daily
  bins call `git log --format=%cI` (no author) and bin `0 <= age < 7`;
  the metric counts `age <= 7`.
- No `above-budget-band` row exists today; `prune-risk` has 2. Four
  `possible` scans carry a template `0 GB VRAM (min_vram)` floor.
- The subnt publisher is retired (`enabled: false`, units masked).
- Board pages are static. `DataAge` renders the produced time on the
  server and the age and stale badge only in the browser. The home page
  has no data age.

Operator decisions (2026-11-04): aging 1A (drop the age cut), labels as
recommended, `above-budget-band` = "Needs a larger GPU" with the VRAM
figure still shown, direction cue removed everywhere (sign included),
apart threshold 40, cold relabelled, plain names drafted and reviewed on
the built page, subnt publisher fixed in place.

## Goals / Non-Goals

**Goals:**
- Every label on the site is true for every row it is on.
- Nothing a reader can use to derive rent or the band reaches the site.
- The served payload is the typed field set, whatever the fixture holds.

**Non-Goals:**
- Automatic fixture refresh (E4 refresh part). The export stays manual and
  operator-approved; only the aging policy changes.
- Multi-repo activity. "Cold" is labelled as the tracked repository only;
  `fleet-multi-repo-activity` is proposed separately.
- Any fleet, mining-model or signal-ledger change. The export reads stored
  results; it never re-derives rank, cut or score.
- Re-enabling subnt.

## Decisions

1. **Projection in the data layer.** `src/data/*.ts` maps each fixture
   record through a per-type field list (`pickFields`) before returning
   it. Alternative: regenerate fixtures only. Rejected: fixtures are
   held, and a stale fixture must never re-leak a dropped field.
   Verified by a test over the real build output (`.next` HTML and RSC
   files), not over `pick()`.
2. **Latest stored pass, rounded.** The export reads `max(ts)` of
   `mine_econ`, every current `mine_feasibility` row, the live fleet
   board, and network rows up to now. Rounding to four significant digits
   stays. `generatedAt` per board is the pass time it came from.
   Alternative: keep seven days and wait to 2026-11-10. Rejected by the
   operator; it also guarantees a stale badge at publish.
3. **One activity reader.** The export's remote program imports
   `metrics._commit_log`, `compile_bot_patterns`, `is_bot_author` and the
   config's `bot_author_patterns` (all present on the Pi at `3d7ce47`),
   and bins with `age <= w` semantics: bin index `ceil(age) - 1` clamped,
   so bin sums over the last 7 and 30 match `c7`/`c30`. The binning is a
   pure function in `scripts/bins.ts` mirrored by a Python helper inside
   the remote string; a TS test covers the edge cases and a Python
   cross-check runs the same cases through `compute_activity`.
   No Pi deploy needed.
4. **GPU-mention count.** The export calls the fleet's
   `gpu_mention_files(feature)` on each scan's `evidence_json` and ships
   one integer `gpuMentionFiles`. A `possible` row never shows
   `gpuFloor`/`vramGb`.
5. **Public reason maps.** `CUT` and `UNRATED` maps in `lib/words.ts`;
   any unknown code renders "Cut, reason not named". `above-budget-band`
   maps to "Needs a larger GPU". A test asserts every cut code in the
   mining-triage writer's ladder has wording.
6. **Banned-field guard.** A test fails if any `ALLOWLIST` source field
   matches `net_|rent_|payback|required_band|band_assumed|cut_detail|cue|
   confidence|gate_state`.
7. **No direction.** The fleet table column becomes "Code vs price, places
   apart" with `Math.abs`. The lead panel tile drops "ahead of" text.
   `why` "divergence" maps to "Code and price apart" only when
   `|divergence| >= 40`, else "No strong signal". Price momentum columns
   stay: they report a measured past move, not a cue.
8. **Server-side stale.** `DataAge` takes a `builtAt` from the server
   (`new Date()` at render, static build time). If the data is stale at
   build, the badge is in the HTML; the client only refines the age.
   Staleness is monotonic, so a server "stale" is never wrong later.
9. **No "today".** Home axis and copy use the data day (`day(at)`), and
   "Last commit" reads "0 d before the data" style text: "same day as the
   data" instead of "today".
10. **subnt publisher.** `why_phrase` divergence: "code activity and price
    ranks far apart" (|gap| >= 40) or "code activity and price ranks
    apart", each with a quiet-repository variant; no sign used. Mining
    notes per the spec delta. Tests updated in `subnt/tests`.

## Risks / Trade-offs

- [Latest pass is closer to live state] → still rounded and subnet-level;
  the operator approves each export before commit.
- [Band inferable from which VRAM figures get cut] → accepted by the
  operator (decision 3A).
- [Rank itself reflects rent ordering] → rank is ordinal; no figure lets a
  reader recover rent. Payback and net stay off.
- [Projection hides a fixture field silently] → intended; the build-output
  test names the banned fields so a re-add is caught.
- [Plain names drift from chain item names] → a map with a fallback that
  shows the raw item plus "chain parameter"; reviewed on the built page.

## Migration Plan

1. Land code and tests with the current fixtures (payload leak closed at
   once by projection).
2. Rehearsal export to the session scratchpad (`--out`), operator
   approved; diff and scrub reviewed.
3. On approval, regenerate the committed fixtures, run every suite and
   the build check, commit.
4. Push on approval. Vercel deploys from `main`. Check the live pages.
Rollback: revert the commits; Vercel redeploys the previous fixtures.
