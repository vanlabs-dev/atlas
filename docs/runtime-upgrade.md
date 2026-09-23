# Runtime upgrades

Atlas updates itself when the live chain moves to a new runtime spec.

## How it works

- **Watch.** Hermes cron job "Atlas runtime upgrade" runs every 30 minutes.
  Its monitor, `~/.hermes/scripts/atlas_live_spec.py`, prints the live spec
  that `livedata` records (`meta.last_live_spec` in
  `var/livedata/livedata.db`). Unchanged output starts no agent.
- **Update.** On a change, an agent in `~/atlas`:
  1. pulls `main` and runs `knowledge/atlas_spec_sync.py`
     (`corpus=<n> live=<n> repo=<n>`); stops silently if corpus equals live;
     updates the subtensor clone if it lags;
  2. reads the spec-bump diff in `var/repotrack/subtensor`;
  3. re-reads touched live knobs at one finalized block;
  4. follows the re-sync rules in `knowledge/corpus/SOURCES.md`: edits the
     corpus, `hashes.json`, and the live-chain entry in `decisions.md`;
  5. fixes Atlas code that uses changed names;
  6. runs the knowledge, livedata and telegram tests (plus any edited module)
     with `python3 -m unittest discover -s .` from each tests dir;
  7. ingests and activates the corpus;
  8. commits as vaNlabs and pushes to `main` with the Atlas deploy key.
- **Report.** The agent posts a short summary to Telegram. If tests fail,
  ingest rejects units, or the push fails, it does not push and reports the
  error instead.

## Rules

Only the live spec drives an update. The repo spec moves ahead when a release
merges before enactment. Never force-push.
