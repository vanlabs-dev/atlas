## ADDED Requirements

### Requirement: Mining triage is queryable through the fleet MCP server

The read-only fleet MCP server SHALL expose the mining triage screen as
tools alongside the existing code-search tools, so the ranking can be
questioned conversationally rather than only read from a rendered page. No
additional MCP server SHALL be introduced for this purpose.

The server SHALL provide a ranked board view with a bounded result size, a
per-subnet detail view carrying every recorded economics field with its
reference block and every feasibility finding with its evidence path and
scanned commit, and a per-subnet history view over recorded observations.

Every response SHALL carry both the economics observation time and the
feasibility scan time. Every tool SHALL be read-only; no tool SHALL write to
the store, alter the ranking, or trigger a screen run.

#### Scenario: Board view returns ranked subnets with cut reasons

- **WHEN** the board tool is called
- **THEN** it returns the ranked subnets within the requested bound, each
  carrying its figures, and excluded subnets carry the reason they were cut

#### Scenario: Detail view carries provenance

- **WHEN** the per-subnet tool is called for a scanned subnet
- **THEN** every economics field carries its reference block and every
  feasibility finding carries its evidence path and scanned commit

#### Scenario: No tool mutates state

- **WHEN** any mining tool is called
- **THEN** the store is opened read-only and no write, ranking change, or
  screen run occurs

### Requirement: Mining tools fail closed and report insufficient history honestly

A mining tool SHALL fail closed with a structured, named error when the
mining store is absent, unreadable, or has never been populated, rather than
returning an empty result that reads as an answer.

A history query SHALL report insufficient history explicitly until at least
two observations exist for the subnet, rather than presenting a single
observation as a trend or inferring change that was not observed.

A subnet with no feasibility scan SHALL be reported as unscanned rather than
as infeasible, and a subnet excluded by the cut ladder SHALL be reported
with its cut reason rather than omitted from results.

#### Scenario: Absent store returns a named error

- **WHEN** the mining store does not exist and a mining tool is called
- **THEN** a structured unavailable error is returned rather than an empty
  successful result

#### Scenario: Single observation is not a trend

- **WHEN** a history query runs against a subnet with one recorded
  observation
- **THEN** insufficient history is reported explicitly and no change is
  inferred

#### Scenario: Unscanned is distinct from infeasible

- **WHEN** a subnet has economics recorded but no feasibility scan
- **THEN** it is reported as unscanned, never as infeasible or feasible
