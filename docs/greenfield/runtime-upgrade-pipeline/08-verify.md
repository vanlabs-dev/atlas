# runtime-upgrade-pipeline: verify

Session 4, 2026-09-24. Workstation, system `/usr/bin/python3`.

Result: **PASS**. The verify script exits 0. It found no project check it
knows how to run (no npm, root pytest, cargo, or make), so the suite run
below is the real evidence. Every suite the upgrade job's test gate
discovers passes.

## Verify script

```
$ bash ~/.claude/skills/greenfield/scripts/verify.sh runtime-upgrade-pipeline .
=== greenfield verify: runtime-upgrade-pipeline ===
Project root: /home/van/src/github/vanlabs-dev/atlas
Artifact dir: /home/van/src/github/vanlabs-dev/atlas/docs/greenfield/runtime-upgrade-pipeline

Checking greenfield artifacts...
  OK  01-brainstorm.md
  OK  07-review.md
  note  09-ship.md not present yet

Checking OpenSpec change...
  OK  openspec/changes/runtime-upgrade-pipeline

Running project checks (if present)...

RESULT: PASS
exit=0
```

## Every `*/tests` suite (the job's test gate, `atlas_upgrade.test_dirs`)

```
$ python3 -m unittest discover -s .   # in each directory
./fleet/tests: Ran 384 tests in 16.119s OK 
./hardening/tests: Ran 36 tests in 0.058s OK 
./hermes/memory/tests: Ran 59 tests in 0.180s OK 
./hermes/modelval/tests: Ran 61 tests in 0.467s OK 
./hermes/tests: Ran 76 tests in 0.023s OK 
./inventory/tests: Ran 72 tests in 0.045s OK 
./knowledge/tests: Ran 50 tests in 1.407s OK 
./livedata/tests: Ran 235 tests in 26.207s OK 
./repotrack/tests: Ran 38 tests in 2.955s OK 
./subnt/tests: Ran 75 tests in 10.340s OK 
./telegram/tests: Ran 161 tests in 8.627s OK 
./upgrade/tests: Ran 36 tests in 0.064s OK 
```

## OpenSpec

```
$ openspec validate runtime-upgrade-pipeline --strict
Change 'runtime-upgrade-pipeline' is valid
exit=0
```

## Live probe (expected failure)

The probe works against live Finney and finds real drift:
`RootWeightSettingEnabled` and `RootWeightsCap` are absent from the
spec-469 metadata. Atlas still reads both. Recorded in `docs/decisions.md`.

```
$ python3 livedata/atlas_probe.py check
{
  "block": 9133759,
  "block_hash": "0xde650515c6de9814a32ae2a1e0e8a0fb775fae20791811c9329de171dd6ea8fb",
  "failures": [
    {
      "item": "RootWeightSettingEnabled",
      "pallet": "SubtensorModule",
      "reason": "missing from metadata"
    },
    {
      "item": "RootWeightsCap",
      "pallet": "SubtensorModule",
      "reason": "missing from metadata"
    }
  ],
  "ok": false,
  "spec": 469
}
exit=1
```
