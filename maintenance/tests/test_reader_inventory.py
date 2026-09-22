from pathlib import Path


def test_production_reader_allowlist_names_real_repository_servers():
    from maintenance.readers import SERVERS
    root=Path(__file__).resolve().parents[2]
    for path in SERVERS.values():
        assert (root/Path(path).relative_to('/home/pi/atlas')).is_file(), path
    assert set(SERVERS)=={'kb','repo','fleet','live'}
