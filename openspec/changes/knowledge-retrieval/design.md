# Design

## Context

See proposal.md (Why) for the motivation.

The current behaviour is in two files:
- `knowledge/atlas_kb.py` splits each corpus file at `#`/`##` into 35 units.
- `knowledge/atlas_kb_server.py` searches them.

The store mixes rows from every ingest run: 679 rows, of which 35 are active. FTS5 is an external-content table (`content=units`), filled at ingest with the default `unicode61` tokenizer. The server opens the store `mode=ro` per request, so it can never migrate or rebuild anything.

The upgrade job and the operator both create runs and activate them:
- `atlas_kb.py ingest` / `activate`;
- `upgrade/atlas_upgrade.py check_kb` and `step_activate`.

The upgrade job tests (`upgrade/tests/test_upgrade.py`) insert unit rows with an explicit column list.

The design rests on a prototype in the WP13 session scratchpad (`retr_proto.py`). It ran 19 queries, each with the text that must rank in the top 3:

| Design | Top-3 hits | Mean result size |
|---|---|---|
| Shipped | 13 / 19 | 4.9 KB |
| Porter + AND/OR, `##` units | 14 / 19 | 7.3 KB |
| Porter + AND/OR, `###` units, heading x5 | 15 / 19 | 2.8 KB |
| Block units, porter, AND then OR, heading x8, question stoplist | 18 / 19 | 0.65 KB |

In the last row, the one miss (`yuma3`) is a corpus gap (A11), not a ranking fault.

## Goals / Non-Goals

**Goals:**
- The right unit is in the top 5 for common user questions, measured by a committed evaluation that fails on regressions.
- One search response stays under about 8 KB for 5 results.
- Old stores keep serving after the code pull, before the next ingest and activation.

**Non-Goals:**
- No vector store or embeddings. The spec permits one only after a benchmark shows full text is insufficient, and the prototype shows it is sufficient.
- No change to evidence states, supersession markers or the activation gate rules.
- The model-graded battery and the pre-activation gate belong to the `kb-battery-honesty` change. This change only provides the retrieval evaluation that change reuses.

## Decisions

**1. Block units, not section units.**
- A unit is one top-level list item (`- `, `* `, `1. `), one bold-led entry (`**Term**:`), or one paragraph, inside its `#`/`##`/`###` section.
- Continuation lines and nested bullets stay with their parent item. A block over 1,500 characters (`BLOCK_CAP`) splits at its nested items, so every unit fits a search result whole (found during apply: four blocks of 1.4 to 5.8 KB hid facts past the payload cap).
- `heading_path` is the full path (`ERRORS > 7o. Coldkey swap ...`). The section's own heading line is not repeated in each block, but the heading column carries it into ranking.
- Unit id: `<file>::<heading path>#<n>`. `n` is the 1-based block index within its section, so it is stable while that section's earlier blocks do not change.

Alternatives considered:
- Splitting at `###` only (15 / 19): the 10 KB `Common Mistakes` unit stays whole.
- Fixed-size windows: these cut facts mid-sentence and break provenance line ranges.

**2. Unit kind from a checked-in map.**
- `knowledge/unit-kinds.json` maps heading paths (exact, or prefix with a trailing ` >`) to `procedure` or `correction`. Everything else is `fact`.
- `procedure` units are stored and served by `knowledge_get_evidence`, but never indexed for search.
- A test asserts that every map entry matches at least one real heading, so a corpus rename cannot silently re-expose procedure text.

Alternative considered: inferring the kind from words such as "publish", "article" or "MUST". Rejected because the result is unpredictable, and correction entries use the same words.

**3. Index of active units only, rebuilt at activation.**
- `activate` deactivates and activates rows as today, then in the same transaction:
  1. `DROP TABLE IF EXISTS units_fts`;
  2. `CREATE VIRTUAL TABLE units_fts USING fts5(heading_path, content, content=units, content_rowid=id, tokenize='porter unicode61')`;
  3. inserts the active non-procedure rows.
- Ingest stops writing FTS rows. Staged runs were never searchable anyway.
- This fixes the IDF skew and changes the tokenizer in one step, with no separate migration command.
- A failed rebuild rolls back the whole activation, so the old run stays active with its old index.

Alternative considered: a standalone `reindex` command. Rejected because it is one more operator step that can be forgotten, and the upgrade job would need it too.

**4. Schema migration in `open_store`.**
- New column `kind TEXT NOT NULL DEFAULT 'fact'`, added by `ALTER TABLE` when missing. (No `section_path` column: the section is the set of active blocks with the same source and heading path, so evidence assembles it from `heading_path`.)
- A new table `kb_meta(key PRIMARY KEY, value)` records `index_version` = 2 after a rebuild.
- `open_store` is only ever called with a writable connection (ingest, activate).

**5. Server tolerates an unmigrated store.**
- Per request, the server reads `PRAGMA table_info(units)` and `kb_meta` read-only.
- If `index_version` is missing, it runs the same query against the old index, without a `kind` filter. Ranking is worse, but results are correct.
- `knowledge_status` reports `index_version` (null for old) so the operator can see that a rebuild is pending.
- This covers the window between the Pi pull and the activation, and any `/restart` inside it.

**6. Query builder.**
- Extract `[A-Za-z0-9_]+` tokens, keeping order.
- Expand `SN<n>` / `sn<n>` / `SN <n>` to the group `("subnet <n>" OR "netuid <n>" OR "sn<n>" OR "<n>")`. The bare number is needed because the corpus also lists netuids plainly ("82 and 103 off").
- Drop stopwords plus question words: `work`, `happen`, `mean`, `explain`, `tell`, `give`, `show`, `please`, `go`, `get`, and their inflections. Keep domain words even when they are common English words (`take`, `stake`, `long`).
- If nothing is left, return the existing `invalid` error.
- Cap the query at 12 terms.
- Run the AND query first. If it returns fewer than k units, run the OR query and append unseen units.
- Rank with `bm25(units_fts, 8.0, 1.0)`.
- Porter stems both the index and the quoted query terms, so `halve` matches `halving` and `staking` matches `stake`.

Alternatives considered:
- Pure OR with bm25: 16 / 19, because stopword-free OR still lets one common term dominate.
- AND only: misses any query with one unseen term.

**7. Payload.**
- Search response: `status`, `query`, `run_id`, `coverage_date`, a `note`, and `results`.
- Each result carries `unit_id`, `kind`, `source_file`, `heading_path`, `lines`, `temporal_scope`, `evidence_state`, `conflict_note` (only when not null) and `content`.
- `content` is capped at 1,500 characters (equal to `BLOCK_CAP`, so in practice nothing from the corpus is cut); a capped result has `truncated: true` and the note says to call `knowledge_get_evidence`.
- Default `max_results` is 5, the maximum stays 10.
- `knowledge_get_evidence` returns the unit, `section` (the full text of its `##`/`###` section, assembled from the run's blocks in line order), and the conflicting units as today.
- FTS `snippet()` is not used: blocks average 325 characters, so a snippet would cut a fact without saving bytes.

**8. Corpus heading renames** (`fact-patterns.md`):
- `ERRORS (must fix before publishing)` becomes `Known wrong claims`;
- `WARNINGS (verify but don't block)` becomes `Claims to verify`;
- `Self-Check Procedure` and `CRITICAL: SOURCE VERIFICATION (before anything else)` keep their names and map to `procedure`;
- `8. Em dashes` maps to `procedure`.

`negative-claim-rules.md` `Verification Process (Required Before...)` maps to `procedure`. "Every article MUST" style lines left in fact or correction units are reworded for an answering agent. The renames are corpus edits; `hashes.json` is regenerated.

**9. Retrieval evaluation.**
- `knowledge/benchmark/retrieval_eval.json` holds about 25 entries: `query`, `marker` (text that must appear in one of the top 5 results), `why`.
- A test ingests the real corpus into a temp store, activates it, and asserts every marker.
- Markers are content text, not headings, so heading renames do not break them.
- The evaluation includes the audit's failing queries: `halve`, `SN82`, "How does staking work?", `yuma3`. The `yuma3` marker lands with the A11 corpus additions, in the same deploy.

## Risks / Trade-offs

- [Block ids shift when a block is inserted before others in a section] → Ids are documented as valid for the active run only, and `knowledge_get_evidence` errors cleanly on an unknown id. Nothing in Atlas persists ids.
- [A block loses context its section heading gave it] → The heading path is part of every result and is weighted in ranking. `knowledge_get_evidence` returns the whole section.
- [The upgrade job edits the corpus and removes a marker fact] → The evaluation test fails in the job's sandboxed test gate, and the job blocks before the push. That is intended: a deleted fact needs an operator decision.
- [A job heading rename orphans a `procedure` map entry] → The kinds test fails before the push. The operator updates the map, which the job cannot edit.
- [The porter stemmer conflates terms such as `stake`/`staking`/`stakes`] → Wanted for this corpus. Exact identifiers (`SubnetEmissionEnabled`, `miner_burn`) are single tokens or quoted phrases and still match.
- [The activation rebuild lengthens activation] → 300 rows. Measured in the prototype at well under a second.

## Migration Plan

Deploy together with the WP13 corpus edits, each step on the operator's yes:
1. Stop `atlas-upgrade.timer`.
2. Push.
3. Pi `git pull --ff-only`.
4. Run the `knowledge/tests` and `upgrade/tests` suites on the Pi.
5. `python3 knowledge/atlas_kb.py ingest`. This migrates the schema; read the report.
6. `python3 knowledge/atlas_kb.py activate --run <id> --actor operator`. This rebuilds the index.
7. Check that `atlas_kb.py status` shows `index_version 2`.
8. Operator `/restart`.
9. Start the timer.

Rollback:
- Activate the previous run id. Activation rebuilds the index from that run's rows with the new tokenizer, which is correct.
- Code rollback (`git revert`) leaves the extra columns and `kb_meta` in place. Old code ignores them and queries `units_fts`, which still exists.

## Open Questions

None.
