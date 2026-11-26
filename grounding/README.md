# grounding: chain grounding job

`atlas_grounding.py` publishes [`GROUNDING.md`](../GROUNDING.md), a short,
machine-checked summary of how the Bittensor chain works on mainnet. Cloud
sessions with no access to the Pi read it from GitHub:

```
https://raw.githubusercontent.com/vanlabs-dev/atlas/main/GROUNDING.md
```

Change `chain-grounding` (2026-11-27). Spec:
[`openspec/changes/chain-grounding/`](../openspec/changes/chain-grounding/).

## How a run works

`atlas-grounding.timer` runs the job hourly at `:45` on the Pi. It holds the
upgrade job's lock (`var/upgrade/lock`), so the two never run at once.

1. **Detect** (no model). `git ls-remote` on opentensor/subtensor for `v*`
   tags and `main`, and the live `spec_version` through keyless finney
   RPC. When nothing moved, nothing is queued and no heartbeat is due, the
   run records the check and exits.
2. **Snapshot** (no model). On a new live spec, `snapshots/<spec>/`:
   `pallets.json` (extrinsics and storage items with defaults),
   `chain.json` (plain values), `subnets.json` (per-subnet parameters) and
   `DIFF.md` against the previous snapshot.
3. **Stale.** `git diff <old_tag>..<new_tag> --name-only` against every
   claim's `watched_paths` and evidence paths. New extrinsics and storage
   items are queued for the section their name maps to.
4. **Verify**, at most `max_sections_per_run` sections per run:
   - A worker `claude -p` per section reads only the source exported at
     the live tag. It cannot edit files or run commands. It returns JSON.
   - Code checks every citation. The file and line range must exist at the
     tag. Every number and backticked name in the statement must be in the
     cited lines. A hyperparameter default must equal the runtime metadata
     default.
   - A critic `claude -p` with no tools sees each claim and its cited lines
     only. Agree: the claim is updated. Anything else: `UNVERIFIED (pending
     review)`, with the last verified text kept.
5. **Render** `GROUNDING.md` from `claims.yaml` (at most 25,600 bytes).
6. **Push.** Scope, size and render checks, the sandbox canary and every
   test suite, then a vaNlabs commit (the gitleaks hook runs), pushed with
   the Atlas deploy key and read back. The live tree is not pulled.

With no content change, a heartbeat commit refreshes `last_updated` at most
every 3 days.

## Freshness

| Field | Meaning |
|---|---|
| `spec_version` | Live mainnet spec the claims are checked against |
| `subtensor_tag`, `subtensor_commit` | Release tag and commit of that spec |
| `newest_tag`, `newest_tag_live` | Newest `v*` tag; false while mainnet has not enacted it |
| `last_updated` | UTC time of the run that made the last commit |
| `content_changed` | UTC time the content last changed |
| `pending_on_main` | PRs on `main` past the live release |

A reader should treat the file as stale when `last_updated` is more than 7
days old, or when `spec_version` is behind `newest_tag` and
`newest_tag_live` is true. A newer tag that is not live yet is a pending
release, not staleness.

## Commands

On the Pi, from `/home/pi/atlas`:

```bash
python3 grounding/atlas_grounding.py status            # saved state
python3 grounding/atlas_grounding.py run               # one timer run now
systemctl --user start atlas-grounding.service         # same, via systemd
journalctl --user -u atlas-grounding.service -n 100    # logs
python3 grounding/atlas_grounding.py force --from v495 --to v497
```

`force` marks claims stale from that tag diff and re-checks them in this
run, with no section cap.

Model usage per run is appended to `var/grounding/usage.jsonl`.

## Model and usage limits

Every run passes `--model` from `tools/claude-model.json` (Opus 5.5).
`--restricted` ignores the settings files, so a model set in
`~/.claude/settings.json` never applies.

A section costs one worker run (about 2 minutes) and one critic run. All
runs draw on the Claude plan's usage limits, shared with the upgrade job
and the alert rewrite. `max_sections_per_run` (3) keeps an hourly burst
small; a release that touches more sections finishes over the next runs.
When the plan reports a usage limit, the job sends one report with the
reset time, keeps the claims stale (shown as UNVERIFIED), and carries on
with snapshots and the heartbeat.

## Size

Each section has a byte budget in `config.json`; the whole file is capped
at 25,600 bytes. The worker lists new claims most important first. After
the critic, code drops this run's new claims from the end (never-verified
first) until the section fits. Claims that existed before the run are never
dropped for space. The push fails closed if the file is still too large.

## Citation retry

The critic labels every rejection `missing_context` (the claim may be
right, but the cited lines leave out a binding, constant, caller or body)
or `wrong` (the lines show it false or overstated). A backticked name
absent from the cited lines counts as `missing_context` too. Those claims
get one worker run to extend their citations, which may narrow a statement
but never widen it, then a second critic pass. A `wrong` rejection gets no
retry and stays UNVERIFIED.

## Traps, seeds and dating

Section 8 lists mechanisms older docs still describe. A removed mechanism
can leave no `Deprecated` error, so the operator keeps a seed list in
`claims.yaml`; each seed is verified like any other claim:

```bash
python3 grounding/atlas_grounding.py review seed tao-flow \
  --topic "TAO flow emission shares (get_shares_flow), replaced by EMA-price shares." \
  --removed "Self::get_shares_flow("
python3 grounding/atlas_grounding.py recheck --sections traps
```

`--removed` is a literal string the old code had and the live code lacks.
The job finds the last release that still had it, exports those files, and
the worker and the critic may cite them as `spec-<N>`. A seed with no claim
shows as UNVERIFIED, so it never drops out.

Releases are dated from mainline release bumps (the `v<N>` tag, else the
first mainline commit that set `spec_version: N,`), back to spec 100. A
trap's stop release is where its marker string vanished from (or appeared
in) every later release. The tao-flow switch reached main twice (PR #2781
at 421, PR #2769 at 423); the code-tree walk dates it at 421.

A trap shows the release where the code changed and, when Atlas's chain
history covers it, the first live spec that carried it: release 461 never
went live (mainnet moved 459 to 464), so it reads "spec 461, live from spec
464 (2026-09-17)". `redate` re-dates every deprecated claim from its marker
with no model run:

```bash
python3 grounding/atlas_grounding.py redate
```

`recheck [--sections ...]` re-checks every UNVERIFIED claim in those
sections, plus the seeds that have no verified claim, in one run with no
section cap.

## Reviewing UNVERIFIED claims

On the workstation, in this repository:

```bash
python3 grounding/atlas_grounding.py review list
python3 grounding/atlas_grounding.py review accept <id>   # take the proposed text
python3 grounding/atlas_grounding.py review reject <id>   # keep the last verified text
python3 grounding/atlas_grounding.py review recheck <id>  # re-run the checks next hour
python3 grounding/atlas_grounding.py review remove <id>   # delete a claim, verified or not
```

`reject` drops a pending proposal and keeps the last verified text; on a
claim with no pending proposal it changes nothing. Use `remove` to delete a
claim that is verified but wrong for the file. `review list` prints the reason, the last verified text, the proposed text
and the cited lines. Read the cited lines at the tag before you accept.
Each command rewrites `grounding/claims.yaml` and `GROUNDING.md`; commit
and push both. An accepted claim records `verified_by: operator`.

Never edit `GROUNDING.md` by hand: the grounding test suite fails when it
is not the render of `claims.yaml`, and the job will not push.
