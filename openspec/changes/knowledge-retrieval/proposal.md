# Proposal

## Why

`knowledge_search` often misses the right unit and returns too much text. Audit items A7 and G6, re-verified 2026-11-05:
- `halve`, `yuma3` and `SN82` return nothing.
- "How does staking work?" misses the `Staking` section.
- The default 3 results are 7 to 37 KB of JSON.
- The 21 KB `ERRORS (must fix before publishing)` unit lands in the top 3 for many queries.

On a 19-query evaluation over the current corpus, the shipped search puts the right unit in the top 3 for 13 queries. The cause is in how search is built:
- there is no stemming;
- every query word, including "how", "does" and "work", is OR'd;
- whole `##` sections are the units;
- the IDF counts 644 inactive rows from old ingest runs.

A phone-facing agent also receives article-pipeline text: "Every article MUST..." and "before publishing".

## What Changes

- **Units.** Ingest splits each `#`/`##`/`###` section into block units: one top-level bullet, numbered item, bold-led entry or paragraph per unit. Each unit keeps the full heading path and the source line range. Unit ids become `<file>::<heading path>#<n>`. **BREAKING** for any caller that stored a section-level `unit_id`. No Atlas code stores one.
- **Unit kind.** Each unit has a `kind`:
  - `fact` for ground truth;
  - `correction` for known wrong claims and their fixes;
  - `procedure` for writing or publishing workflow.

  `procedure` units are never searchable. They stay in the store for evidence lookup. A checked-in map assigns `procedure` by heading. A test fails when a mapped heading no longer exists in the corpus.
- **Index.** The FTS5 index uses the `porter unicode61` tokenizer and holds active units only. Activation rebuilds it, inside the activation transaction. Ingest no longer writes FTS rows.
- **Query.** The query is built by code:
  - question words and stopwords are dropped;
  - `SN<n>` expands to `subnet <n>`, `netuid <n>` or `sn<n>`;
  - all remaining terms are AND'd, and an OR pass fills any remaining slots;
  - ranking is bm25 with the heading weighted 8 to 1 over the body.
- **Payload.**
  - Search returns compact results: `unit_id`, `kind`, heading path, source and lines, temporal scope, evidence state, and the block text capped at 1,200 characters with a `truncated` flag.
  - Run-level fields (coverage date, run id) appear once per response.
  - The default result count rises from 3 to 5.
  - `knowledge_get_evidence` returns the unit plus its whole section as context.
- **Corpus wording.** The `fact-patterns.md` headings written for the article pipeline are renamed for an agent reader. For example, `ERRORS (must fix before publishing)` becomes `Known wrong claims`. The same goes for the "Every article MUST" lines in units that stay searchable.
- **Regression set.** A committed retrieval evaluation over the real corpus runs as a test. Each query names a text marker that must appear in its top 5. The new `kb-battery-honesty` change reuses it as the pre-activation gate.
- **Compatibility.**
  - The server reads an older store, without the `kind` column or with an old-tokenizer index, and keeps serving it.
  - `PARSER_VERSION` becomes 3.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `knowledge-base`:
  - Units become heading-scoped blocks with a kind.
  - The index holds active units only and is rebuilt at activation.
  - Search gets a defined query and ranking contract.
  - Search payloads are bounded.
  - Evidence lookup returns section context.

## Impact

- Code:
  - `knowledge/atlas_kb.py`: splitter, kinds, schema migration, FTS rebuild at activation.
  - `knowledge/atlas_kb_server.py`: query builder, ranking, payload, evidence context, old-store fallback.
  - New `knowledge/unit-kinds.json`.
  - New retrieval evaluation under `knowledge/benchmark/`.
- Corpus: heading renames in `fact-patterns.md` and `negative-claim-rules.md`, then `hashes.json`. Corpus edits need a new ingest and an activation on the Pi.
- Tests: `knowledge/tests`. The upgrade job tests insert units directly; the new columns have defaults, so those tests keep working.
- Upgrade job:
  - The job runs every suite. The retrieval evaluation now fails when a corpus edit removes a marked fact, so a job edit that deletes such a fact blocks before the push.
  - The job may not edit `knowledge/unit-kinds.json`: it may modify only corpus files, supersession markers and `docs/decisions.md`. So a heading rename by the job that orphans a `procedure` mapping fails the kinds test before the push, and the operator fixes the map.
- Pi:
  - one ingest and one activation (the rebuild);
  - an operator `/restart`, so `atlas-kb` loads the new server.
- Hermes: SOUL.md and tool descriptions mention `knowledge_search` only by name, so no change is needed there. The tool description text in the server is updated.
