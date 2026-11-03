# upgrade: runtime upgrade job

`atlas_upgrade.py` runs on the device every 30 minutes. When the live Finney
runtime spec moves past the corpus spec, one headless `claude -p` session edits
the corpus in a separate worktree, reading the subtensor source as exported at
the live release. It may not edit code. Code then enforces every gate (goal,
edit scope in `allowed_paths.py`, citations, all test suites and a live
chain-read probe inside a bubblewrap sandbox checked by `sandbox_canary.py`)
before it pushes to `main` and activates the corpus.
Each run first recovers a failed pull or activation and keeps the active
knowledge run equal to the live corpus. After a pull that brings in code,
it restarts `hermes-gateway` when the gateway is idle.

Full description, gates and failure handling: [docs/runtime-upgrade.md](../docs/runtime-upgrade.md).

```
python3 upgrade/atlas_upgrade.py status
python3 upgrade/atlas_upgrade.py run --dry-run
```
