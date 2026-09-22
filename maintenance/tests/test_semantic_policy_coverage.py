"""Regression for a real unmapped migration-test source in the bootstrap diff."""
import json
from pathlib import Path


def test_bootstrap_migration_tests_have_source_bound_obligations():
    policy=json.loads((Path(__file__).resolve().parents[1]/'policies/runtime468.json').read_text())
    path='pallets/subtensor/src/tests/migration.rs'
    sources={row['path']:row for row in policy['sources']}
    assert path in sources
    assert sources[path]['ranges'] == [[7614, 7654]]
    mapped={row['id'] for row in policy['requirements'] if path in row['paths']}
    assert mapped == {'migrationMarkers','historicalBasketEnabled'}
