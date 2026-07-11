# Tasks: atlas-phase-0-device-inventory

## 1. Project scaffolding

- [x] 1.1 Create the inventory module layout (`inventory/` with collector entry point, probe table, redaction filter, worksheet generator, `schema/` directory, `tests/fixtures/` directory) and a README stating the read-only guarantee and recommended unprivileged invocation
- [x] 1.2 Define the JSON report schema v1 (`schema/inventory-report.v1.schema.json`): run metadata block (run id, script version, schema_version, start/finish times, executing account, hostname) plus one section per ATLAS-ENV-001 category, each item wrapped in the `{status, data?, error?, command}` envelope with status enum `collected | unsupported-on-device | permission-denied | error`

## 2. Redaction filter (build first — all output flows through it)

- [x] 2.1 Implement the redaction filter: secret-named env var values, `key=value` credentials in command lines, PEM blocks, bearer/authorization strings, common API-key formats → replaced with a redaction marker
- [x] 2.2 Write adversarial redaction tests with planted secrets in fixtures (process lists, env dumps, mixed/non-UTF8 output) asserting no planted value survives into any output

## 3. Probe table and collector

- [x] 3.1 Implement the declared probe table: one entry per ATLAS-ENV-001 item with exact read-only command line and parser (hardware/arch, CPU/RAM/NVMe/partitions/filesystem, OS/kernel, users and service accounts, Atlas-relevant packages, containers/images, systemd services, listening ports, cron/timers, existing Hermes files+version, repositories and app directories, env/secret file locations via `stat` only, backup config, firewall status, remote access config, temperature/NVMe health)
- [x] 3.2 Implement the collector runner: executes each probe independently, wraps results in the status envelope, never aborts on single-probe failure, never self-elevates, maps missing tools to `unsupported-on-device` and EPERM to `permission-denied`, builds no command from collected data
- [x] 3.3 Emit the JSON report (0600 permissions, output directory parameter) and validate it against schema v1 before writing; exit code distinguishes complete vs partial collection
- [x] 3.4 Write per-probe parser unit tests against captured/synthetic fixtures, including missing-tool, permission-denied, and malformed-output cases asserting correct status mapping

## 4. Classification worksheet

- [x] 4.1 Implement the worksheet generator: reads a valid report, emits `classification-worksheet.md` with one row per discovered software item/service/container/repository/app directory, proposed disposition (`preserve`/`migrate`/`remove`/`decision required`) and evidence pointer; conservative heuristics — unrecognized or Hermes/Bittensor/Atlas-related items default to `decision required`, `remove` only with explicit matching evidence
- [x] 4.2 Write worksheet tests: stale-Hermes fixture produces classifications with nothing executed; ambiguous items land as `decision required` with the open question stated

## 5. Audit record

- [x] 5.1 Implement the per-run audit record (run id, start/finish, script+schema versions, executing account, per-item status summary, errors) written alongside the report, passing through the redaction filter
- [x] 5.2 Test that failed and partial runs still produce a complete audit record containing no planted secrets

## 6. Integration verification and acceptance evidence

- [x] 6.1 Full-run integration test in a Linux environment (container or WSL): report validates against schema, every ATLAS-ENV-001 category present with explicit status, before/after state snapshot confirms the read-only property for observable state (packages, services, cron, files outside the output dir)
- [x] 6.2 Review pass on the probe table confirming every command is read-only with no mutating flags; record the review in the change
- [x] 6.3 Document the acceptance procedure for the first real Pi run: unprivileged invocation, manual scan of the report for anything sensitive before storage, worksheet review by the operator, storage location note (`var/inventory/` default pending the backup change) — execution on the Pi itself is the operator's acceptance step, not part of this implementation
