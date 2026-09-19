## 1. Watch the pool-side emission switch

- [x] 1.1 Add a `bool` codec to the netuid-keyed map decode path: `0x01` true,
      `0x00` false, absent entry false with its absence recorded distinctly
      from a failed read.
- [x] 1.2 Register `SubnetEmissionEnabled` in `SUBNET_MAP_ITEMS` with the
      `bool` codec, and confirm `verify_key_derivation` still passes against
      the pinned gate keys with the item added.
- [x] 1.3 Add the item to `chain_params` in `livedata/config.json` with its
      `governs` description naming it a per-subnet root switch over TAO
      injection, explicitly not the emission-gate bar.
- [x] 1.4 Extend the netuid-keyed watch so the first observation seeds every
      subnet silently and a later change records a transition carrying the
      netuid, both values and the reference block.
- [x] 1.5 Fail the item closed on a short or empty batch rather than recording
      transitions to off for every subnet.
- [x] 1.6 Tests in `livedata/tests`: seed-then-transition, a same-block batch
      across many netuids, absent entry decoded as off, short batch fails the
      item closed without affecting the other watched items.
- [x] 1.7 Confirm against live Finney that the derived prefix enumerates the
      expected subnet count and that the two subnets currently off are the
      ones the panel reports off; record the block in the decision entry.

## 2. Collapse a same-block batch into one page

- [x] 2.1 Group unseen chain-parameter events by `(item, reference block)` for
      netuid-keyed items only; leave global items one event per page.
- [x] 2.2 Render a collapsed alert stating the item, the direction, the count
      and the netuid list, with visible truncation when the list exceeds the
      message budget and the count always stated in full.
- [x] 2.3 Ledger each collapsed event individually against its own event id so
      de-duplication and replay-safety are unchanged.
- [x] 2.4 Render the pool-side switch by name, stating that alpha distribution
      continues while TAO injection stops.
- [x] 2.5 Add `SubnetEmissionEnabled` and the switch vocabulary to the
      `chain-parameter-change` `governs` map and the voice gloss map in
      `telegram/config.json`.
- [x] 2.6 Tests in `telegram/tests`: 49 netuids at one block render one page
      and 49 ledger rows; two items at one block render two pages; one item at
      two blocks renders two pages; truncation states the full count; the
      size-shrink path still holds.

## 3. Name the switch on the mining board

- [x] 3.1 Rename the first cut rung and rewrite its reason text to name the
      pool-side emission switch, never the emission gate, and never attribute
      the exclusion to demand or to the bar.
- [x] 3.2 Carry the reference block of the switch state the board was built
      from through to the board output and the `mining_board` tool.
- [x] 3.3 Tests in `fleet/tests` for the rung name, the reason text and the
      reference block on the board.
- [x] 3.4 Confirm the rename passes `shinogi`'s exclusion scan and that the
      public page still composes clean; run the shinogi suite and one
      `compose --dry-run`.

## 4. Corpus: the pool-side switch and the 452 to 455 drift

- [x] 4.1 Verify against the merged subtensor code at tag v455 and one live
      Finney read: the switch's storage item, its root-only writer, and the
      zero-and-redistribute behaviour in the coinbase.
- [x] 4.2 Add the pool-side emission switch to `ground-truth.md` as a distinct
      mechanism from the emission-gate bar, dated, with the redistribution
      behaviour and the fact that alpha distribution continues.
- [x] 4.3 Add a negative-claim rule: positive demand share does not imply the
      subnet earns TAO, because the switch can be off.
- [x] 4.4 Add a fact-pattern entry for the conflation: a question about a
      subnet earning nothing must not be answered with the bar alone.
- [x] 4.5 Re-sync 452 to 455: `claim_root` admission (spec 454), the
      basket-escrow transfer rejection (453), the registration queue (453),
      proxy call filters (453, 454, 455) and the crowdloan pallet.
- [x] 4.6 Regenerate `hashes.json`, update `sync_date` and `coverage_date`,
      and review `supersession-markers.json`.
- [x] 4.7 Correct the `SOURCES.md` sentence stating the watch needs no new
      item, and record why the switch was missed: it predates the gate
      (PR #2657, 2026-05-12) and was never drift from any single release.

## 5. Benchmark

- [x] 5.1 Add a case: a subnet with substantial demand share earning no TAO
      must be explained by the pool-side switch, dated, not by the bar.
- [x] 5.2 Add a case: a `claim_root` question must state the spec-454
      admission rule.
- [ ] 5.3 Run the battery off-device against the new corpus and confirm it
      meets the existing threshold sheet with no fabrications.

## 6. Documentation

- [x] 6.1 Record the 2026-09-09 event in `docs/decisions.md`: block 9029889 at
      12:16:48 UTC, 49 subnets flipped, 18 with nonzero share started
      receiving TAO, the ruled-out causes with their evidence, and the
      measured board effect (56 ranked to 65).
- [x] 6.2 Record the operator decision that the switch routes through the
      instant `chain-parameter-change` class, with the reasoning for why the
      shadow-tier default does not apply to a governance action.
- [x] 6.3 Record the share-universe finding in `docs/emission-metrics.md`: the
      bar is read not computed, the measured reproduction (+0.34%, 32 of 32
      above), and the chain's three emit-to filters against Atlas's universe.
- [x] 6.4 Update `README.md` status, the `live-data` and `telegram-integration`
      capability rows, and the corpus grounding line.

## 7. Deploy and accept

- [x] 7.1 All suites green off-device: `livedata`, `telegram`, `fleet`,
      `knowledge`, `shinogi`.
- [x] 7.2 `git pull` on the Pi; confirm the next gate pass seeds the switch
      across every subnet with no alert and no health event.
- [ ] 7.3 Ingest and activate the new corpus run; run the battery on the
      device and accept it.
- [x] 7.4 Confirm the board's ranked count is unchanged by the rename alone,
      and that it now carries the switch reference block.
- [ ] 7.5 Inspect one synthetic collapsed render on the device before a real
      transition arrives, then record the acceptance entry in
      `docs/decisions.md`.
