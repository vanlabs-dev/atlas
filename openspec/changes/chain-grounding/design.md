# Design: chain-grounding

## Facts checked on 2026-11-27

- `opentensor/subtensor` redirects (301) to `RaoFoundation/subtensor`, the
  repotrack remote. Both list the same tag SHAs.
- `runtime/src/lib.rs` at v494, v495, v496 and v497 states `spec_version`
  equal to the tag number. v496 never went live: mainnet moved 495 to 497
  on 2026-11-26.
- Tags lead enactment: v494 was tagged 2026-11-21 01:38 UTC and went live
  2026-11-23 17:02 UTC. Hence `newest_tag` and `newest_tag_live`.
- No local node. `https://entrypoint-finney.opentensor.ai` answers
  `state_getRuntimeVersion` with 497.
- A full snapshot takes about 2 minutes from the workstation: 130
  registered subnets, 102 SubtensorModule and 115 AdminUtils extrinsics.
- The Pi's `claude` uses a Claude Max OAuth login with a refresh token. It
  expired once (2026-11-20) and needed an interactive login.

## Decisions

- **Reuse, not a parallel system.** Release anchors, the source export,
  the bubblewrap sandbox and canary, the test-suite gate, the deploy-key
  push and Telegram reporting come from `upgrade/atlas_upgrade.py`. Chain
  reads come from `livedata/atlas_live.py`; `livedata/scale_meta.py`
  gains call decoding.
- **One lock.** The job holds `var/upgrade/lock` for the whole run, so the
  two jobs never run models or push at the same time. The cost is that an
  upgrade run can wait up to one grounding run (under 1 hour).
- **No live-tree pull.** GROUNDING.md is for GitHub readers. Pulling would
  hide code commits from the upgrade job's gateway-restart logic.
- **Per-section workers.** One worker per section with stale claims keeps
  related claims consistent and costs fewer runs than one per claim.
- **Mechanical checks before the critic.** Numbers and backticked names
  must appear in the cited lines; hyperparameter defaults must equal the
  runtime metadata. This makes "never state a constant without a cited
  line" a code rule, not a prompt rule.
- **Dating.** `live_since_spec` is the first release tag that holds the
  newest commit touching the cited lines (`git log -L`). A deprecated
  claim's stop spec comes from the first commit that added its `marker`
  string (`git log -S`), else from its evidence.
- **YAML without a package.** `grounding/yamlsub.py` writes a fixed
  subset (strings as JSON strings) and parses only that.
- **Operator review** edits the ledger through `review accept|reject|
  recheck`, which re-renders GROUNDING.md. The operator commits it.

## Risks

- A strict number check marks more claims UNVERIFIED. That is the safe
  direction; the worker prompt states the rule.
- Main moving often can produce several `pending_on_main` commits a day.
- Claude login expiry stops verification but not snapshots or heartbeats;
  stale claims then show as UNVERIFIED.
