# Design: atlas-phase-0-device-inventory

## Context

Atlas (see [prd.md](../../../prd.md)) will run on an existing 16 GB ARM64 Raspberry Pi with 256 GB NVMe whose current software state is unknown. The PRD's first gate (Phase 0, ATLAS-ENV-001) is a read-only, redacted device inventory that later changes (removal plan, hardening assessment, Hermes install) consume. Nothing exists in this repository yet besides the PRD and OpenSpec structure, so this change also establishes the first code and test conventions.

Constraints that shape the design:

- The target host is Linux aarch64; the exact OS and installed tooling are unknown until the script first runs (PRD §21 Q1–Q2 are unresolved).
- The script must be safe to run on a device we have not inventoried yet — the tool must tolerate the very uncertainty it exists to resolve.
- Architecture must stay proportionate (PRD §5.6): one script, one schema, no services, no daemons.

## Goals / Non-Goals

**Goals:**

- A single read-only inventory script runnable on the Pi with stock tooling.
- A versioned JSON report schema with explicit per-item collection status.
- Redaction applied to all captured output before it is persisted.
- A classification worksheet (preserve / migrate / remove / decision required) generated from the report for human review.
- An audit record per run.
- Tests that run off-device against captured fixtures.

**Non-Goals:**

- Executing any disposition (removal is ATLAS-ENV-002, a separate change).
- The hardening assessment itself (ATLAS-ENV-003 consumes this output).
- Installing Hermes, any Atlas service, database, or MCP tooling.
- Continuous or scheduled monitoring — this is an on-demand script; ongoing health is Phase 6.
- Answering PRD §21 decisions; the report informs them only.

## Decisions

### D1: POSIX shell + Python standard library, no third-party dependencies

The collector is a Bash/POSIX shell script (or a thin shell wrapper around a single Python 3 stdlib program) that shells out to standard Linux tools (`uname`, `lscpu`, `df`, `lsblk`, `ss`, `systemctl`, `dpkg`/`rpm` as available, `docker`/`podman` if present, `crontab -l`, `ufw`/`nft`/`iptables` read subcommands). Rationale: we cannot assume pip, npm, or network access on the un-inventoried Pi, and ATLAS-SEC-005 requires justifying every dependency. Python 3 is near-universal on Raspberry Pi OS/Debian derivatives; if even that is absent, the shell fallback still emits a valid minimal report. Alternative considered: a Go static binary (nice single-artifact story, but adds a build toolchain and cross-compilation for aarch64 before the project has any build infrastructure — disproportionate).

### D1a: Single-file deliverable, transferred by paste over SSH (added during apply)

Confirmed with the operator on 2026-07-11: the script reaches the Pi by SSH-ing
in and pasting the script text into a newly created file (no file copy). The
collector is therefore one self-contained Python file (`atlas_inventory.py`,
stdlib only) rather than a package; the JSON schema is embedded in the script
as the source of truth and the repo's `schema/inventory-report.v1.schema.json`
is generated from it (`dump-schema`), with a unit test asserting they never
diverge. The acceptance procedure requires a `sha256sum` comparison after
pasting to catch transfer corruption.

*Superseded 2026-07-11 (same day, before first Pi run):* the operator formatted
the Pi to a clean OS install and cloned this repo on it, so transfer is now
`git pull` on the Pi; the checksum step is unnecessary (git guarantees
integrity). The single-file design stays — it keeps the tool dependency-free
and the paste method remains a fallback. `var/` is gitignored so device
reports can never be committed from the Pi's checkout.

### D2: Every probe is declared, read-only, and individually wrapped

Each inventory item maps to a declared probe: the exact command line, a parser, and a status. Probes run independently; one failure never aborts the run (spec: collection failure does not trigger remediation). The probe table doubles as the review surface for the "commands must be individually reviewable, no mutating flags" requirement — reviewers audit one table, not scattered call sites. Commands are executed without a shell-interpolation path from collected data (no command built from prior command output), which also addresses prompt-injection-style content in file names.

### D3: JSON report with `schema_version`, per-item status envelope

Output is a single JSON document: run metadata (run id, script version, `schema_version`, start/finish, executing account, hostname) plus one section per ATLAS-ENV-001 category. Every item is wrapped in `{status, data?, error?, command}` where `status ∈ {collected, unsupported-on-device, permission-denied, error}`. The JSON Schema file lives in the repo and is versioned by integer increment. Rationale: JSON + JSON Schema is parseable by the future Atlas service without new dependencies, and the envelope makes unknowns explicit (ATLAS-OPS-004's "unknown is not healthy" principle, applied early). Alternative considered: Markdown-only report (human-friendly but downstream changes would scrape it; instead the worksheet renders human-readable Markdown *from* the JSON).

### D4: Redaction as a mandatory output filter, not per-probe discipline

All captured stdout/stderr passes through one redaction filter before any write. The filter redacts: values of environment variables whose names match secret patterns (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASS*`, etc.), inline `key=value` credentials in process command lines, PEM blocks, bearer/authorization strings, and anything matching common API-key formats. Secret *files* are never read at all — probes record path/owner/mode via `stat` only. Rationale: a single choke point is testable (fixture with planted secrets → assert absence) and survives future probe additions; relying on each probe author to remember redaction is exactly how leaks happen. Trade-off: pattern-based redaction can false-positive (over-redact); acceptable — over-redaction is safe, under-redaction is not.

### D5: Classification worksheet generated as Markdown from the report

A second small program reads the JSON report and emits `classification-worksheet.md`: one table row per discovered software item / service / container / repository / app directory with proposed disposition and evidence pointer. Proposal heuristics are conservative: only well-known-stock OS components may be proposed `preserve`; anything Hermes/Bittensor/Atlas-related or unrecognized defaults to `decision required`. Nothing is ever proposed as `remove` without explicit matching evidence (e.g., duplicate older Hermes version). Rationale: the ATLAS-ENV-001 scenario requires classification without deletion; keeping the generator separate from the collector keeps the collector purely observational.

### D6: Fixture-based tests off-device

The Pi is the production environment; we do not test on it first. Each probe parser is unit-tested against captured/synthetic fixtures (including hostile ones: secrets planted in process lists, missing tools, permission-denied output, non-UTF8 bytes). The redaction filter gets adversarial fixtures. A schema-validation test asserts every generated report validates. An integration test runs the full script inside any available Linux environment (CI container or WSL) and asserts the read-only property by snapshotting relevant state before/after where practical. Live Pi execution happens once, manually, as the acceptance run — its report is the Phase 0 evidence artifact.

## Risks / Trade-offs

- [Unknown OS/tooling on the Pi means probes may all return `unsupported-on-device`] → The envelope makes this visible rather than fatal; the acceptance criterion is "every category reported with explicit status," not "every category collected". First real run may motivate a follow-up probe patch.
- [Pattern-based redaction misses an exotic secret format] → Secret files are never read; only command output is exposed, which sharply limits surface. Redaction list is a single reviewable file; acceptance includes a manual scan of the first real report before it is stored or shared.
- [Script run with sudo could read more than intended] → The script does not require root and must degrade to `permission-denied` statuses; documentation states the recommended invocation (unprivileged first; a privileged re-run is the operator's explicit choice). It never self-elevates.
- [Classification heuristics propose a wrong disposition] → Dispositions are proposals with mandatory human review; ambiguous items default to `decision required`, and this capability contains no execution path for dispositions.
- [Report itself could be sensitive (ports, users, versions)] → Report is written to a local output directory with 0600 permissions and is not transmitted anywhere by this change.

## Migration Plan

Nothing to migrate — first change in an empty repo. Rollback is deleting the script and its outputs; no device state to revert (read-only by construction).

## Open Questions

- PRD §21 Q1–Q5 (Pi model, OS, preservation needs, reinstall permission, access method) remain open and are *outputs* of running this inventory, not blockers to building it.
- Where should inventory reports/worksheets be stored long-term (on-Pi path, and whether they are included in backups)? Proposed default: a `var/inventory/` directory under the Atlas home, revisited in the backup change (ATLAS-BACKUP-001).
- Whether a privileged (sudo) second pass is wanted when the unprivileged run reports many `permission-denied` items — operator decision at run time.
