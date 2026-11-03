# Spec Delta

## ADDED Requirements

### Requirement: Extra repositories are fetched as commit history only
A repository read only for activity SHALL be fetched as a bare repository holding commits without trees or file contents, with no checkout, submodule fetch, hook or tag fetch, and its push URL disabled. It SHALL NOT be indexed, scanned or read for files. The disk ceiling SHALL be checked before each fetch, and a repository whose stored size passes a configured cap SHALL be dropped from activity and recorded.

#### Scenario: History-only fetch
- **WHEN** an extra repository is fetched
- **THEN** only commit objects are stored, no working tree exists, and no file from it reaches any index

#### Scenario: Low disk
- **WHEN** free disk is below the ceiling before an extra-repository fetch
- **THEN** the fetch does not start, the condition is recorded as disk-limited, and activity uses the last fetched history

#### Scenario: Oversized history
- **WHEN** an extra repository's stored size passes the cap
- **THEN** it is removed from that subnet's counted set and the report names it
