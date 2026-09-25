## 1. Live-data chain reads

- [x] 1.1 Declare the new reads in `CHAIN_READS` with pallet, hashers and
      value type exactly as in design D9. Confirm each against live metadata
      with `livedata/atlas_probe.py` before writing any decoder.
- [x] 1.2 Teach `read_subnet_maps` the `Twox64Concat` netuid tail
      (`MechanismCountCurrent`, `MechanismEmissionSplit`) and mechanism-index
      keys. Return `Incentive` keyed by (netuid, mecid), and stop dropping
      keys at or above 4096.
- [x] 1.3 Add decoders: `AlphaBalance`/`TaoBalance` u64, `MechId` u8,
      `Vec<u16>` split, `AccountId` 32 bytes, `Vec<AccountId>`, and
      `Perquintill` u64 over 1e18. Each fails closed on a length mismatch.
- [x] 1.4 Add the batched point-read helper for `OwnedHotkeys(coldkey)` and
      `Uids(netuid, hotkey)`. Keys come from the declared hashers, reads use
      the snapshot's block hash, and a per-coldkey cap (256) makes that
      subnet's owner set unread when exceeded.
- [x] 1.5 Write a `chain_storage` audit row per chain read (items, key
      counts, block number and hash, times, result, error category; no
      values), including failed reads. Catch `verify_key_derivation` failures
      inside the read and return them as a failed, audited read.
- [x] 1.6 Tests in `livedata/tests`:
      - mechanism keys at or above 4096 map to (netuid, 1)
      - `Twox64Concat` tails decode correctly
      - point-read key derivation matches a pinned `Uids` key taken from
        live Finney
      - the cap fails closed
      - an audit row is written on success and on failure
      - an undeclared read fails the table test

## 2. Economics stage (Stage A)

- [x] 2.1 Replace `collect_inputs` with one chain snapshot: the maps from
      1.2, the owner resolution from 1.4, the global `SubnetOwnerCut`, and
      `SwapBalancer`, all at one block. Remove the TaoSwap panel call from
      the screen.
- [x] 2.2 Compute `miner_share = 0.5 × (1 − owner_cut × enabled)` per
      subnet. Store the 0.5 citation (`run_coinbase.rs:326-329`, spec 471)
      in `mine_state`. Remove `miner_share` and `miner_share_source` from
      `fleet/config.json` and ignore leftovers with a note.
- [x] 2.3 Per mechanism:
      - take the split (or even split when unset)
      - remove the owner UIDs
      - compute the independent earner count, top-1, top-10, owner share,
        pools, entrant and incumbent median
      - leave the entrant figure undefined at zero independent earners
- [x] 2.4 Reconcile Σ split × owner share against `MinerBurned`, with
      `owner_reconcile_tolerance` in config (default 0.01). A mismatch sets a
      reconciliation-failed confidence and no figure.
- [x] 2.5 Compute price and haircut with the balancer formulas (design D6).
      An unknown haircut blocks the figure.
- [x] 2.6 Record context: `Burn` in TAO, `ImmunityPeriod`, `uids_full`
      (`SubnetworkN == MaxAllowedUids`), and `alpha_issuance`. A zero
      `SubnetAlphaOutEmission` marks the subnet not emitting (unrated).
- [x] 2.7 Drive the switch from chain `SubnetEmissionEnabled` at the
      snapshot block. Treat a per-netuid identity decode failure as unread.
- [x] 2.8 Add the schema: `mine_mechanism` and the new `mine_econ` columns
      (design D3) through the additive `ensure_schema` path. Insert all rows
      of a pass in one transaction. A per-subnet malformed value marks that
      subnet only. A chain read failure writes nothing.
- [x] 2.9 Remove the fabricated zeros: `baseline_tao_month` when rent is
      unknown, and `collateral_lock_pct` defaulting to 0.0 without a read.

## 3. Feasibility stage (Stage B)

- [x] 3.1 Replace the entrypoint tokens with the pattern set and excluded
      components in design D7. Count only source files toward any
      file-count evidence.
- [x] 3.2 Make no-entrypoint yield `unknown`. Stop producing `closed` and
      `stub` without a positive cited rule. Update the test that locks in
      the old behaviour (`fleet/tests/test_mining.py:747-756`).
- [x] 3.3 Build the template `min_compute.yml` fingerprint from the SN60 and
      SN33 clones, check it against the upstream subnet template, and record
      a matching file as `template` evidence with no VRAM or GPU.
- [x] 3.4 Search the VRAM evidence line within the miner section only, and
      make `vram_basis` follow the value actually kept.
- [x] 3.5 Key and gate scans on `index_state.indexed_sha`. Skip slots whose
      index is behind. Join verdicts only on current (netuid, epoch, indexed
      sha, active). Delete superseded rows at insert. Bump `SCAN_VERSION`
      to 3.
- [x] 3.6 Make `mining_status` count only current verdicts.

## 4. Classify stage and ranking (Stage C)

- [x] 4.1 Add a classify stage after feasibility that runs the ladder once
      over the latest complete pass. The rung order is switch, identity,
      owner-capture, no-independent-earner, winner-take-all (per mechanism,
      independent field), feasibility (positive evidence only), hardware. It
      writes `cut_reason`, `cut_detail`, `rank`, `rank_mecid`,
      `unrated_reason` and the per-mechanism rung in one transaction. It
      runs only if econ committed this pass.
- [x] 4.2 Rank on the best surviving mechanism's entrant figure (design D5).
      Unrated subnets are listed apart and are never ranked last.
- [x] 4.3 Make `report()` read the stored result, not recompute it. Report
      unrated counts. Bound the excluded list and give an omitted count.
- [x] 4.4 Record `model_version = 2` in `mine_state`.

## 5. Surfaces

- [x] 5.1 Board page:
      - name the ranking mechanism
      - show independent earners and top-1, owner share, and the
        full-subnet and immunity context
      - show an unverified marker for `unknown` feasibility
      - list the unrated subnets
      - show a per-subnet cut table with its stored reasons
      - state the econ age and block, with a staleness warning over
        `stale_after_hours` (default 18)
      - keep the parity statement
- [x] 5.2 Link `mining.html` from the dashboard `index.html`.
- [x] 5.3 MCP tools:
      - `mining_board`, `mining_subnet` and `mining_history` return the
        stored cut and rank and the per-mechanism figures
      - `mining_subnet` stamps the row's own ts
      - every response with an entrant figure carries the parity statement
      - `include_cut` is bounded, with an omitted count
- [x] 5.4 Pulse briefing: read the stored rank and counts. Report unrated
      subnets. Suppress top-ten deltas across a `model_version` change and
      say so once.
- [x] 5.5 subnt: same as 5.4, keeping rent and band off the page.

## 6. Tests

- [x] 6.1 Fixtures from the measured chain snapshot (block 9142678/9142723
      values for SN9, SN80, SN93, SN44, SN120, SN4) prove:
      - SN93 mechanism 0 gets 2%
      - SN44 mechanism 0 gets 0
      - SN9 is cut winner-take-all on the independent field
      - SN80's divisor is 3 earners + 1
      - reconciliation passes for all six
- [x] 6.2 Cases:
      - a zero-earner field and an owner-only field are cut at
        no-independent-earner
      - a halved subnet (0.5 alpha per block) is priced at 0.5
      - `OwnerCutEnabled` false gives a share of 0.5
      - balancer weight other than 0.5 changes price and haircut
      - an unknown haircut blocks the figure
- [x] 6.3 Failure cases:
      - a chain read failure writes nothing and the board is unchanged, with
        its age
      - one malformed subnet is isolated
      - a mid-econ exception commits nothing
      - classify does not run after a failed econ
- [x] 6.4 Feasibility cases:
      - Go `cmd/miner/main.go`, a `miner/` package and a Rust bin are
        recognised
      - validator, API, migration and register-script files are rejected
      - a template `min_compute.yml` is ignored
      - a re-pointed or inactive slot is unscanned
      - index-behind is skipped
      - superseded rows are pruned
- [x] 6.5 Store and surface agreement: every row carries exactly one of a
      cut, a rank or an unrated marker. The board, MCP, briefing and subnt
      report identical counts and head. Consumer fixtures are produced by
      the real writer.
- [x] 6.6 Test isolation: fleet tests use a temp `dashboard.www_dir`, and a
      guard fails if a run writes under the repo `var/`.
- [x] 6.7 Run every suite (fleet, livedata, telegram, subnt) green with no
      network.

## 7. Docs and deploy

- [x] 7.1 Update the `fleet/README.md` mining section:
      - chain snapshot
      - per-mechanism owner-removed model and reconciliation
      - new rung
      - unknown feasibility
      - current counts
- [x] 7.2 Correct `docs/emission-metrics.md:56` and add a `docs/decisions.md`
      entry that supersedes the "1 alpha/block constant" claim at `:334`,
      citing `run_coinbase.rs:226-238` and the 6.62M/10.5M measurement.
- [x] 7.3 Flag to the operator that `knowledge/corpus/ground-truth.md` lacks
      per-subnet alpha halving and mechanism splits. Do not edit the corpus
      in this change.
- [x] 7.4 Propose the push and the Pi `git pull` to the operator. After the
      first pass, run the read-only verification in design Migration step 4
      and record the results and the block in `docs/decisions.md`.
