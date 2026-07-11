# Hardening assessment on the Pi — acceptance procedure

**Change:** `atlas-phase-0-hardening-assessment`, task 5.3
**Who:** the operator, on the Pi (user `pi`, via SSH)

## 1. Get the code and evidence

```sh
cd ~/atlas && git pull
```

The assessor needs a recent inventory report. If `var/inventory/` has none, or
the newest is older than ~3 days (the assessor warns), re-run the inventory
first:

```sh
python3 inventory/atlas_inventory.py run --output-dir var/inventory
```

## 2. Run the assessment (unprivileged)

```sh
python3 hardening/atlas_hardening.py assess
```

- Exit `0` = complete; `3` = some areas lacked evidence (the plan lists them);
  `1` = fatal (e.g. invalid inventory report).
- Outputs (0600, gitignored) in `var/hardening/`:
  - `assessment-<run-id>.json` — machine-readable verdicts
  - `hardening-plan-<run-id>.md` — **the document you review**
  - `audit-<run-id>.json`

## 3. Review the plan

Open `hardening-plan-<run-id>.md`:

1. **Verdict summary table** — sanity-check it matches what you know about
   the device.
2. **Proposed changes** — for each numbered item, read the why, impact, and
   rollback, then either tick `- [x] approved` or strike it / annotate why
   not. Pay particular attention to the SSH item: **confirm key login works
   in a second session before ever approving password-auth disable.**
3. **Decisions required** — answer these in [docs/decisions.md](../../docs/decisions.md)
   (expected: backup destination Q10, disk thresholds).
4. Nothing executes as part of this review. The approved plan is the input
   for the follow-up change (`atlas-phase-1-apply-hardening`), which is where
   commands actually run — one approved item at a time, with verification.

## 4. Preserve the reviewed plan

Keep the annotated plan file in `var/hardening/` (it is the approval record
the apply-change will reference). If you want it versioned, copy it into the
follow-up change's directory when that change is proposed — never commit the
raw assessment JSON (it embeds device detail).

## 5. Acceptance checklist

- [ ] Assessment ran against a fresh inventory report (exit 0 or 3)
- [ ] All 11 areas present with sensible verdicts
- [ ] Every proposed item explicitly approved or struck
- [ ] `decision-required` answers recorded in docs/decisions.md
- [ ] No secrets in any output (spot-check the JSON)
- [ ] Annotated plan retained as the approval record

When ticked, this change can be archived and the apply-hardening change can
be proposed from the approved plan.
