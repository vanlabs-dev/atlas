# Tasks

## 1. Tier guard and config (C1)

- [x] 1.1 `load_config` refuses a `briefing` tier while `briefing.enabled` is false. Move `knowledge-ingestion` and `gate-crossing-no-effect` to `shadow` in the same commit. Verify: a test loads the committed config; a test with a briefing-tier class and the briefing off raises.

## 2. Class splits (C1, C2)

- [x] 2.1 `_build_econ_event` emits `econ-code` only for `high`; else `econ-code-minor`. Register both at `shadow`. Verify: tests show the shipped config sends no econ alert, and with `econ-code` at `instant` only a high verdict pages.
- [x] 2.2 The registry adapter emits renames as `subnet-rename`. Register `subnet-registry` at `instant` and `subnet-rename` at `shadow`. Verify: tests show a deregistration pages and a rename does not.

## 3. Digest lines (C10)

- [x] 3.1 Resolve each digest line's source class from its dedup-key prefix and keep only lines that resolve to `instant`. Register `signal-digest`. Verify: tests show a cluster-follow line and an econ-digest line are not kept, and an instant-source line is.

## 4. Close out

- [x] 4.1 Decision record in `docs/decisions.md`; `python3 tools/readme_sync.py`; full test loop.
