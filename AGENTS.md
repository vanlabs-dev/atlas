# AGENTS.md

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
| Remote, Pi | `https://github.com/vanlabs-dev/atlas.git` (HTTPS, anonymous, read only) |

**The remote is not the same on both hosts.** The workstation pushes over
SSH. The Pi holds no private SSH key and no credential helper, so it pulls
anonymously over HTTPS and cannot push at all. A commit that is not pushed
from the workstation does not exist as far as the device is concerned, and
`git pull` on the Pi will silently find nothing.

The Pi also has no `~/.gitconfig`, so it has no `user.name` or
`user.email`. Anything that commits there must pass identity per
invocation with `git -c user.name=... -c user.email=...` or the commit
fails outright.

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
