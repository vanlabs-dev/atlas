# root-weight-drift: verify

Session 4, 2026-09-24. Run from the project root on the workstation.

## Verify script

`bash ~/.claude/skills/greenfield/scripts/verify.sh root-weight-drift .`

The script runs no project suite here (no top-level `tests/`,
`pyproject.toml`, or `Makefile`). The suites are run separately below.

```
=== greenfield verify: root-weight-drift ===
Project root: /home/van/src/github/vanlabs-dev/atlas
Artifact dir: /home/van/src/github/vanlabs-dev/atlas/docs/greenfield/root-weight-drift

Checking greenfield artifacts...
  OK  01-brainstorm.md
  OK  07-review.md
  note  09-ship.md not present yet

Checking OpenSpec change...
  OK  openspec/changes/root-weight-drift

Running project checks (if present)...

RESULT: PASS
verify exit=0
```

## Test suites

Every suite the upgrade job runs:
`python3 -m unittest discover -s .` in each `*/tests` directory.

```
fleet/tests: Ran 384 tests in 15.118s OK 
hardening/tests: Ran 36 tests in 0.055s OK 
hermes/tests: Ran 76 tests in 0.025s OK 
inventory/tests: Ran 72 tests in 0.042s OK 
knowledge/tests: Ran 50 tests in 1.334s OK 
livedata/tests: Ran 220 tests in 21.579s OK 
repotrack/tests: Ran 38 tests in 2.823s OK 
subnt/tests: Ran 75 tests in 9.018s OK 
telegram/tests: Ran 155 tests in 8.585s OK 
upgrade/tests: Ran 36 tests in 0.063s OK 
```

## Live checks against Finney

`python3 livedata/atlas_probe.py check` (exit 0):

```
{"block": 9133932, "failures": [], "ok": true, "spec": 469}
```

`python3 livedata/atlas_live.py read-knobs` (exit 0, spec 469, block
9133918): `BasketConcentrationCap` raw `0x0010`, `explicit`, value 4096.
`BasketTradingEnabled` explicit true.

## Grep check (task 6.4)

`grep -rn "RootWeightSettingEnabled\|RootWeightsCap\|root_rotation" livedata telegram fleet knowledge/corpus`
returns only history notes (config `_comment`, READMEs), retirement
tests, and corpus supersession text. No live read.

## Result

PASS. Task 6.5 (re-ingest and activate on the Pi) is an operator step and
stays open until the change is pulled on the Pi.
