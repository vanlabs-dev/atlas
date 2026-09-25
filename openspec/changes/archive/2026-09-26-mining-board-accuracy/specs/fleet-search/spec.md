## MODIFIED Requirements

### Requirement: Mining triage is queryable through the fleet MCP server

The read-only fleet MCP server SHALL expose the mining triage screen as
tools alongside the existing code-search tools, so the ranking can be
questioned conversationally rather than only read from a rendered page. No
additional MCP server SHALL be introduced for this purpose.

The server SHALL provide:
- a ranked board view with a bounded result size
- a per-subnet detail view carrying every recorded economics field with its
  reference block, the per-mechanism figures, and every feasibility finding
  with its evidence path and scanned commit
- a per-subnet history view over recorded observations

Every view SHALL return the ranking and cut state the pass stored. No view
SHALL recompute them. The detail and history views SHALL carry each
observation's cut rung and detail, or its rank and the mechanism the rank
is based on. A list of excluded subnets returned by the board view SHALL be
bounded, with a count of those omitted.

Every response that presents the entrant income figure SHALL state the
parity assumption behind it, identified as a model. Every response SHALL
carry the economics observation time of the rows it returns, its reference
block, and the feasibility scan time of the verdicts it joins. Every tool
SHALL be read-only. No tool SHALL write to the store, alter the ranking, or
trigger a screen run.

#### Scenario: Board view returns ranked subnets with cut reasons

- **WHEN** the board tool is called with excluded subnets requested
- **THEN** it returns the ranked subnets within the requested bound, each
  carrying its figures and ranking mechanism, and a bounded list of
  excluded subnets each carrying its stored cut rung and detail

#### Scenario: Detail view carries provenance

- **WHEN** the per-subnet tool is called for a scanned subnet
- **THEN** every economics field carries its reference block, every
  mechanism's figures are present, and every feasibility finding carries
  its evidence path and scanned commit

#### Scenario: Detail view carries the stored cut

- **WHEN** the per-subnet tool is called for a subnet the last pass cut
- **THEN** the response carries that pass's cut rung and detail, identical
  to the board's

#### Scenario: An old row is stamped with its own time

- **WHEN** the per-subnet tool returns a subnet whose latest observation
  predates the latest pass
- **THEN** the response carries that observation's own time, not the latest
  pass time

#### Scenario: The parity model travels with the figure

- **WHEN** any mining tool returns an entrant income figure
- **THEN** the same response states the parity assumption as a model

#### Scenario: No tool mutates state

- **WHEN** any mining tool is called
- **THEN** the store is opened read-only and no write, ranking change, or
  screen run occurs
