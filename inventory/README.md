# Atlas Device Inventory (Phase 0)

Read-only inventory collector for the Atlas target device (Raspberry Pi, Linux aarch64).
Implements PRD requirement **ATLAS-ENV-001** via OpenSpec change `atlas-phase-0-device-inventory`.

## Read-only guarantee

This tool observes; it never changes the device:

- It does **not** install, remove, upgrade, stop, start, restart, enable, disable,
  reconfigure, or delete anything.
- Every command it runs is declared in one reviewable probe table
  (`PROBES` in `atlas_inventory.py`; reviewed in `docs/probe-review.md`) and uses
  read-only invocations only.
- It never executes discovered binaries (including a found Hermes install) and never
  builds a command line from collected data.
- Secret-bearing files are **never read** — only their path, owner, and permissions
  are recorded (`stat`). All captured command output passes a redaction filter before
  it is written anywhere.
- It never self-elevates. Run it unprivileged; items needing more privilege are
  reported as `permission-denied`, not silently skipped.
- The only files it creates are its outputs (report, classification worksheet,
  audit record) in the output directory you choose.

## Layout

```
inventory/
  atlas_inventory.py    # single-file, stdlib-only collector (paste-friendly deliverable)
  schema/               # versioned JSON report schema (generated from the script)
  tests/                # unit tests + fixtures (run off-device)
    fixtures/
    integration/        # full-run test for a Linux environment (WSL/container)
  docs/
    probe-review.md           # read-only review of every probe command
    acceptance-procedure.md   # how to run the first real inventory on the Pi
```

## Requirements

Python 3.9+ (standard library only — no pip installs on the target device).

## Usage

```sh
# Full inventory run (report + classification worksheet + audit record)
python3 atlas_inventory.py run --output-dir var/inventory

# Regenerate the worksheet from an existing report
python3 atlas_inventory.py worksheet var/inventory/report-<run-id>.json

# Print the report JSON schema
python3 atlas_inventory.py dump-schema
```

Exit codes for `run`: `0` complete collection, `3` partial (some items
`permission-denied`/`error` — see the report), `1` fatal.

**Recommended invocation is unprivileged.** If the unprivileged report shows many
`permission-denied` items, a privileged re-run is the operator's explicit choice —
the script itself never asks for or acquires elevation.

## Transferring to the Pi

The deliverable is the single file `atlas_inventory.py`. The agreed low-impact
transfer method is: SSH into the Pi, create a new file, and paste the script text
into it. Then verify integrity before running:

```sh
sha256sum atlas_inventory.py   # compare against the checksum recorded from the repo copy
```

See `docs/acceptance-procedure.md` for the full first-run procedure.

## Tests

```sh
python -m unittest discover -s inventory/tests -v
```

Tests run off-device against fixtures; no probe touches the real system except the
opt-in integration script in `tests/integration/` (intended for WSL or a container).
