## MODIFIED Requirements

### Requirement: Significant repository alerts carry a concise breakdown

A significant repository alert SHALL include an interpreted breakdown built
only from fields already recorded by the repository tracker (never re-fetched),
rendered as structured single-fact lines rather than a prose paragraph, passing
outbound redaction before rendering, and staying within the configured message
size budget. The breakdown SHALL contain:

- A **verdict line** stating in plain language what the range is, derived
  deterministically from recorded data by a fixed, ordered decision: an
  incomplete or non-fast-forward range is called out as low-confidence first; a
  `spec_version` change leads as a runtime spec bump; an unknown-class directory
  is surfaced as a new/unmapped area; otherwise the core-protocol share of line
  churn decides between a light protocol touch amid a large sync and a core
  protocol change, followed by node/network and a neutral fallback. The
  light-protocol-touch verdict SHALL be emitted only when core-protocol line
  churn is greater than zero, so the verdict never claims a protocol touch that
  did not occur. The share SHALL be computed from line churn (additions plus
  deletions), not file count.
- A **signal-versus-noise area split**: a line for core-protocol directories
  showing, per area, the changed-file count and the summed line churn
  (`+additions / −deletions`) computed from the recorded per-file additions and
  deletions; and a separate line for housekeeping directories showing counts
  only. The split SHALL use the configured area map, which classifies each
  top-level directory as core-protocol, node/network, housekeeping, or
  **unknown**. Housekeeping SHALL be allowlist-only: a top-level directory not
  present in the map SHALL be treated as unknown, not housekeeping, and SHALL be
  surfaced on its own line rather than hidden — mirroring the classifier's
  escalation of never-seen directories. Repo-root files (paths with no
  directory separator) SHALL be grouped under a synthetic housekeeping area so a
  large generated root file cannot present as a protocol area. When the recorded
  file list is truncated, the counts and churn are a lower bound and SHALL be
  rendered as such (e.g. a `≥` marker).
- A **filtered commit list** ranked by commit subject alone (the tracker
  records no commit-to-file mapping, so the list SHALL be presented as the most
  substantive subjects in the range, not as the commits that changed a given
  area). It SHALL exclude merge commits and commits whose subject is prefixed as
  `ci` / `test` / `docs` / `build` / `style`, and `chore` unless the subject
  names a release (`spec_version` / `version` / `release`); and SHALL prioritise
  `feat` / `fix` / `refactor` / `perf` and protocol-keyword subjects. When no
  such commit exists in the recorded range, the breakdown SHALL state plainly
  that the range contains no feature or fix commits rather than showing
  housekeeping commits.
- When `pallets/` files are present, **pallet-level labels** naming the
  pallets touched and, via the configured pallet map, the domain each governs
  (e.g. staking / emissions, governance params, dTAO economics), read from the
  second path segment of recorded file paths.

The breakdown SHALL NOT introduce any new data capture, re-fetch, or network
call, and SHALL degrade honestly (omitting a line rather than guessing) when a
recorded field is absent. Em dashes SHALL NOT appear in rendered output.

#### Scenario: Noise-dominated range is called out, signal is surfaced

- **WHEN** a significant range's changed files are mostly in housekeeping
  directories with only a light core-protocol touch
- **THEN** the verdict line states it is largely housekeeping with a light
  protocol touch, the protocol line shows the core-protocol areas with their
  file counts and line churn, and the housekeeping line lists the noise
  directories separately

#### Scenario: Runtime spec bump leads the verdict

- **WHEN** a range records a `spec_version` change
- **THEN** the verdict line leads with the runtime spec bump and its delta
  against the live chain, rather than presenting the release as generic
  churn

#### Scenario: Commit list filters out merge and housekeeping commits

- **WHEN** the recorded commits are a mix of merge, `ci`, `test`, and
  `feat` / `fix` subjects
- **THEN** the rendered commit list shows the `feat` / `fix` subjects and omits
  the merge and `ci` / `test` subjects; and when no feature or fix commit
  exists, the breakdown states that plainly

#### Scenario: Pallet touch is named and interpreted

- **WHEN** recorded file paths include `pallets/<name>/...` for a mapped pallet
- **THEN** the breakdown names the pallet and the domain it governs from the
  configured pallet map

#### Scenario: Unknown top-level directory is surfaced, not hidden

- **WHEN** a range changes files under a top-level directory absent from the
  configured area map
- **THEN** the directory is shown on its own new/unclassified-area line and the
  verdict marks it as a new or unmapped area, rather than being folded into
  housekeeping

#### Scenario: Truncated or incomplete range is low-confidence

- **WHEN** a delivered range has a truncated file list or a non-fast-forward
  history
- **THEN** the verdict states the range is large or incomplete and the affected
  area counts and churn are marked as lower bounds rather than presented as
  exact

#### Scenario: Breakdown reflects the recorded range

- **WHEN** a significant range is delivered
- **THEN** the message body states the commit count, the core-protocol areas
  with line churn, and the `spec_version` delta drawn from the recorded change
  range
