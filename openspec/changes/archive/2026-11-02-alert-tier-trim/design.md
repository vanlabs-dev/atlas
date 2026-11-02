# Design

## Split by sibling class, not by a per-event tier key

The repo already splits one adapter's output into a delivery-only sibling
class (`gate-crossing-no-effect`). Econ and registry use the same pattern:
the builder picks the class, the tier registry decides delivery, and every
tier stays a single config value. The ledger shows `econ-code-minor` and
`subnet-rename` rows under their own names, so a later promotion is one
config edit and does not replay old rows.

The fleet effectiveness ledger keys on the fleet store's class, which stays
`econ-code` for every verdict, so its history is continuous and the report
keeps reading `econ-code` at its registered tier.

## Guard against a dead tier

`load_config` raises `FatalTelegramError` when the briefing is disabled and
any class is registered at `briefing`. The guard and the config move ship
in one commit, and a test loads the committed `config.json` through
`load_config`, so a deploy cannot refuse its own config.

## Digest lines

Fleet digest rows carry only `{"line"}`. The origin is in the dedup-key
prefix:

| Prefix | Source class |
|---|---|
| `cluster-follow`, `term-overflow`, `range-capped` | `narrative-cluster` |
| `econ-digest`, `econ-cooldown` | `econ-code-minor` |

An unknown prefix resolves to no class and the line is dropped, matching the
fail-closed rule for unregistered classes. The filter runs before the line
enters `pending_signal`. The Pi's `pending_signal` was empty on 2026-11-02,
so no purge is needed.
