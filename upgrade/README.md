# upgrade: runtime upgrade job

`atlas_upgrade.py` runs on the device every 30 minutes. When the live Finney
runtime spec moves past the corpus spec, one headless `claude -p` session edits
the corpus and chain readers in a separate worktree. Code then enforces every
gate (goal, edit scope in `allowed_paths.py`, all test suites, a live
chain-read probe) before it pushes to `main` and activates the corpus.

Full description, gates and failure handling: [docs/runtime-upgrade.md](../docs/runtime-upgrade.md).

```
python3 upgrade/atlas_upgrade.py status
python3 upgrade/atlas_upgrade.py run --dry-run
```
