# AGENTS.md

## Quality fixes, not quick fixes

Fix the cause, completely and verifiably. A fix that only hides a
symptom, narrows the test, or defers the real work is not a fix.

When you offer options, you may list a quicker fix, but never mark a
quick fix as the recommended option. Recommend the fix that holds up:
the one with sourced facts, tests that can fail, and no known gap left
open. Name what the quicker option leaves undone.

## This repo is personal

It is not work, and it is not shared. Nothing in it is written for or on
behalf of an employer.

If the machine you are on also holds work repos, keep them out of this one.
Do not read work org context, do not apply work conventions here, and do not
cite work docs in anything this repo produces. A global instruction to load
org context applies to those repos, not this one.

### Identity

Every commit and every push uses the personal identity:

| | |
|---|---|
| Git author | `vaNlabs <vanlabs@pm.me>` |
| GitHub account | `vanlabs-dev` |
| Remote, workstation | `git@github.com:vanlabs-dev/atlas.git` (SSH, read and write) |
| Remote, Pi reads | `https://github.com/vanlabs-dev/atlas.git` (anonymous HTTPS) |
| Remote, Pi upgrade pushes | `git@github.com:vanlabs-dev/atlas.git` (Atlas-only deploy key) |

The runtime upgrade job (`upgrade/atlas_upgrade.py`, change
`runtime-upgrade-pipeline`, 2026-09-24) runs on the Pi every 30 minutes.
When the live runtime spec moves past the corpus spec, one headless
`claude -p` session edits the corpus in the `~/atlas-upgrade` worktree.
Code then checks the goal, the edit scope (`upgrade/allowed_paths.py`),
citations, and runs every test suite and a live chain-read probe in a
bubblewrap sandbox with no secrets. Only then does the job push to `main`
with the Atlas deploy key, activate the corpus, and report on Telegram. It never force-pushes. See
`docs/runtime-upgrade.md`. The job may edit only the corpus,
`knowledge/supersession-markers.json` and `docs/decisions.md`, and may not
add files. Since 2026-11-03 (change `upgrade-sandbox-scope`) that excludes
the chain readers in `livedata/`: a reader fix is the operator's.
It replaced Hermes cron job `fb98152a3fa1`, removed 2026-09-24.

Supply the personal identity explicitly for automated commits, even when
repo-local Git identity is configured. Do not rely on global configuration.

Verify the author before any commit lands. If `git var GIT_AUTHOR_IDENT`
shows anything else, stop and fix it rather than committing.

Never commit or push under a work identity. If the only credentials available
on the machine belong to a work account, do not push. Ask instead.

Commits before 2026-08-06 were authored as `1vaNtastiq <vantastiq@pm.me>`, a
stale personal identity. Leave that history alone. New commits use `vaNlabs`.

### Before using gh

The `gh` CLI authenticates separately from `git`, so a correct commit author
does not mean gh is the right account. Check `gh auth status` and confirm
`vanlabs-dev` is active before any gh command that writes. If it is not,
use plain `git` over the SSH remote, which does not touch the gh token.

## Device access

The Pi 5 is at `192.168.0.150`, user `pi`, on the LAN only. Key auth only,
password auth disabled, nftables default-deny inbound. Reaching it from
outside the LAN is not supported and not planned.

Code reaches the device by `git pull` in `~/atlas` on the Pi. No file
transfers.

Host aliases and key paths differ per machine. Check the local `ssh` config
rather than assuming a name.

## Conventions

Conventional Commits, imperative mood, subject 50 characters or less. Body
only when the change needs explaining, wrapped at 72.

No AI attribution anywhere: no `Co-Authored-By` tags, no "Generated with"
lines, in commits or PR bodies.

Never push, force-push, or open a PR unprompted. Propose the command.

After changing a component directory, a spec or a systemd timer, run
`python3 tools/readme_sync.py`. It rewrites the generated tables in
`README.md`. `tools/tests` and CI fail when they are stale.
