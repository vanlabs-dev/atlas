# Tasks

## 1. Units, kinds and schema

- [ ] 1.1 Replace `split_units` with the block splitter (design 1): `#`/`##`/`###` heading paths, top-level list item, numbered item, bold-led entry or paragraph per unit, nested lines kept, ids `<file>::<path>#<n>`, line ranges exact. Verify with unit tests on a fixture (nested bullets, numbered list, bold entry, preamble, `###` path) and a real-corpus test that unit ids are unique and every line of non-heading text lands in exactly one unit.
- [ ] 1.2 Add `knowledge/unit-kinds.json` and kind assignment (design 2). Verify with tests: a mapped heading gets its kind, an unmapped one is `fact`, and every map entry matches a real corpus heading (fails and names the entry otherwise).
- [ ] 1.3 Migrate the schema in `open_store`: `kind`, `section_path` columns via `ALTER TABLE` when missing, plus the `kb_meta` table. Bump `PARSER_VERSION` to 3. Verify with a test that opens a store built with the old schema, ingests, and keeps the old rows readable; also run `upgrade/tests` unchanged.
- [ ] 1.4 Stop writing FTS rows at ingest. Verify with a test that a staged run adds no index rows.

## 2. Index rebuild at activation

- [ ] 2.1 Rebuild `units_fts` (porter unicode61, active `fact`/`correction` units only) inside the activation transaction and record `index_version` 2 (design 3). Verify with tests: index row count equals the run's searchable units with several runs in the store; procedure units are absent; a forced failure mid-rebuild leaves the prior run active and searchable.
- [ ] 2.2 Report `index_version` in `atlas_kb.py status` and `knowledge_status`. Verify with tests for a rebuilt store (2) and an old store (null).

## 3. Query, ranking and payload

- [ ] 3.1 Query builder (design 6): stopwords and question words, `SN<n>` expansion, 12-term cap, AND pass then OR fill, `bm25(units_fts, 8.0, 1.0)`. Verify with tests for `halve`, `SN82`, "How does staking work?" (first result in `Staking`) and an all-stopword query (`invalid` error).
- [ ] 3.2 Payload (design 7): run-level fields once, per-result fields, 1,200-character cap with `truncated`, conflict note only when set, default 5 and max 10 results, updated tool descriptions. Verify with a test that 5 results from the real corpus serialize under 8 KB and that a long block is cut with the flag.
- [ ] 3.3 `knowledge_get_evidence` returns the unit and its section text assembled in line order, and still lists conflicting units. Verify with a test against the real corpus.
- [ ] 3.4 Old-store fallback (design 5): no `kind` column or no `index_version` means serve from the existing index without a kind filter. Verify with a test against a store built by the pre-change schema.

## 4. Corpus wording and evaluation

- [ ] 4.1 Rename the `fact-patterns.md` headings and reword "Every article MUST" style lines in searchable units (design 8); map the procedure headings; regenerate `knowledge/corpus/hashes.json` and update `SOURCES.md`. Verify that `atlas_kb.py ingest` on a temp store reports zero secret findings and zero duplicate ids, and that the kinds test passes.
- [ ] 4.2 Add `knowledge/benchmark/retrieval_eval.json` (at least 20 queries with content markers, including every audit-failing query) and the test that ingests, activates and asserts each marker in the top 5. Verify that it passes on the new code and fails on the pre-change search (run once against the old `KnowledgeStore.search` in the test, or record the old result in the commit message).
- [ ] 4.3 Update `knowledge/README.md` (units, kinds, index rebuild, payload, evaluation) and run `python3 tools/readme_sync.py`. Verify that the readme sync reports no drift.

## 5. Integration

- [ ] 5.1 Run every Python suite (the README loop), and once inside the upgrade job's bwrap sandbox with no network. Verify that all pass.
- [ ] 5.2 Deploy per design Migration Plan, each step with operator approval. After activation, verify read-only on the Pi: `status` shows `index_version 2`; a `knowledge_search` call through the server for "How does staking work?" returns a `Staking` unit under 8 KB.
