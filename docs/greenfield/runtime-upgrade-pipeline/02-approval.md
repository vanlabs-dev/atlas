# runtime-upgrade-pipeline: approval

Approved: 2026-09-24, operator.

Change: `openspec/changes/runtime-upgrade-pipeline/` (validates `--strict`).

Facts gathered after propose:

- Pi `claude` binary: `/home/pi/.local/bin/claude`. Use it for
  `ATLAS_CLAUDE_BIN` (design decision 3, task 5.10).
- Task 1.1 done 2026-09-24: `claude -p "reply ok"` as `pi` under
  `env -i` (non-login, minimal `PATH`) returned `ok`.

Session 3 review done 2026-09-24 (`07-review.md`). Next: Session 4 (apply).
