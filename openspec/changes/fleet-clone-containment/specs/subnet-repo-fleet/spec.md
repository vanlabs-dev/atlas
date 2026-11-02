## MODIFIED Requirements

### Requirement: Fleet clones are minimal-footprint and are never executed

Fleet clones SHALL be blobless (full commit graph, blobs fetched on demand),
SHALL check out the remote default branch without a third-party API call, SHALL
be created with submodule recursion disabled, and SHALL have their push URL
disabled. Per-repository clone-size and file-count ceilings SHALL be enforced,
quarantining a slot that breaches them. The size ceiling SHALL bound the sum of
the file sizes in the tree being materialized, measured from the tree before
checkout of a new clone and before every advance of an existing one, so an
oversized tree is never written to the working tree. Atlas SHALL NEVER build,
test, execute, install, or run hooks or submodule fetches for any subnet
repository. A configured disk ceiling SHALL be checked before every clone,
before every fetch, and before every checkout or advance; below it, no clone,
fetch or advance starts, the condition is recorded as disk-limited, and every
existing clone keeps its last good state rather than exhausting device storage.

#### Scenario: Untrusted code is cloned but never run

- **WHEN** a subnet repository is cloned or updated
- **THEN** only git fetch/checkout and file reads occur; no build, test,
  install, hook, or submodule fetch is invoked

#### Scenario: Oversized repository is quarantined

- **WHEN** a new repository's HEAD tree exceeds the configured size or
  file-count cap
- **THEN** the clone is aborted before checkout and cleaned up, the slot is
  marked quarantined, and the pass continues

#### Scenario: Oversized update is quarantined at the last good head

- **WHEN** an active slot's fetched head has a tree that exceeds the size cap
- **THEN** the working tree is not advanced, the slot is marked quarantined
  and keeps its last good local SHA and index, and the pass continues

#### Scenario: Low disk headroom stops new clones

- **WHEN** free disk headroom falls below the configured ceiling
- **THEN** no new clone, fetch or advance is started, the condition is
  recorded as disk-limited, and every slot keeps its last good state
