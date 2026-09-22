# Mainnet upgrade maintenance

## Approved scope

The operator approved this change and its implementation on 2026-09-22.
Track finalized Finney runtime deployments, review every intervening source
change, maintain affected Atlas code and current documentation, then validate,
commit, push and activate the accepted result. Preserve historical records.

The approval includes resource-capped isolated Pi tests, repository-scoped
write credentials, normal fast-forward main publication, and validated local
code/knowledge activation. It excludes security-policy weakening, wallet
operations, unrelated repos, uncommitted user work and credential disclosure.

## Why

The previous system records runtime observations and alerts the operator,
but does not produce a complete deployment audit or maintain Atlas consumers.
An hourly observation can skip intervening runtime deployments.

## Success criteria

- Scan finalized history without gaps; identify deployments by chain,
  activation hash and runtime code hash rather than spec number alone.
- Match the deployed artifact to source before auditing its full diff.
- Use isolated model proposals and a separate review; deterministic gates
  decide whether a candidate is publishable.
- Validate all affected consumers and all mandatory subsystem suites.
- Verify remote commit and local activation independently.
- Persist blocked states and send deduplicated notifications.

The build is not accepted merely because unit tests pass. A real upgrade
must exercise the full path, with a verified source mapping and safe rollout.
