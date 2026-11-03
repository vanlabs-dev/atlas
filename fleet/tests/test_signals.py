"""fleet-signals: schema, scan-surface predicates, manifest/model-id
parsers, per-range fail-closed extraction, novelty/cluster/watchlist/econ
detection, epoch seeding, backfill/seed-modelids/calibrate, and the
price/outcome effectiveness ledger."""

import datetime
import json
import os
import sqlite3
import sys
import tempfile
import shutil
import unittest
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLEET_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _FLEET_DIR)

import _helpers as h  # noqa: E402
from _helpers import fleet  # noqa: E402
import atlas_fleet_signals as sig  # noqa: E402
import atlas_fleet_index as idx  # noqa: E402


def _iso(days_ago=0, hours_ago=0):
    return (datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.timedelta(days=days_ago, hours=hours_ago)).isoformat()


CFG = dict(sig.DEFAULT_SIGNALS_CFG)


def snap(prices, registered=None, block=None):
    """A price snapshot as the fetcher returns it (change:
    signal-statistics-ties): every priced netuid carries a registration
    block, block 1 unless given."""
    reg = {n: 1 for n in prices}
    reg.update(registered or {})
    return {"prices": dict(prices), "registered": reg, "block_number": block}


def _insert_range(conn, netuid, epoch, prev, new, files, commits=1,
                  files_truncated=False, commits_truncated=False,
                  non_ff=False):
    commit_rows = [{"sha": "c%040d"[:40] % i, "subject": "feat: x"}
                   for i in range(commits)]
    file_rows = [{"path": p, "additions": 1, "deletions": 0} for p in files]
    cursor = conn.execute(
        "INSERT INTO change_ranges (netuid, epoch, prev_sha, new_sha, "
        "retrieved_at, non_fast_forward, commits_json, files_json, "
        "tags_json, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (netuid, epoch, prev, new, _iso(), 1 if non_ff else 0,
         json.dumps({"commits": commit_rows,
                     "truncated": commits_truncated}),
         json.dumps({"files": file_rows, "truncated": files_truncated}),
         json.dumps([]), None))
    conn.commit()
    return cursor.lastrowid


class SignalsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "fleet.db")
        self.conn = fleet.open_store(self.db)
        self.addCleanup(self.conn.close)
        sig.ensure_schema(self.conn)
        self.clone_root = os.path.join(self.tmp, "clones")
        self.config = {"db": self.db, "clone_root": self.clone_root,
                       "signals": {},
                       "dashboard": {"www_dir": os.path.join(self.tmp,
                                                             "www")}}

    def make_slot(self, netuid, files, epoch=1, opened_at=None,
                  status="active"):
        origin = h.make_origin(self.tmp, name="origin_%d_%d"
                               % (netuid, epoch), files=files)
        clone_dir = os.path.join(self.clone_root, str(netuid))
        state = fleet.setup_clone(clone_dir, origin)
        self.assertEqual(state["status"], "active", state)
        fleet.upsert_slot(self.conn, {
            "netuid": netuid, "github_repo": "https://github.com/o/r%d"
            % netuid, "epoch": epoch, "status": status,
            "default_branch": state["default_branch"],
            "local_sha": state["local_sha"]})
        self.conn.execute(
            "INSERT OR IGNORE INTO epochs (netuid, epoch, opened_at) "
            "VALUES (?, ?, ?)", (netuid, epoch, opened_at or _iso()))
        self.conn.commit()
        return origin, clone_dir, state

    def advance(self, netuid, origin, clone_dir, rel_path, content,
                prev_sha, **range_kwargs):
        h.add_commit(origin, rel_path, content)
        slot = fleet.get_slot(self.conn, netuid)
        result = fleet.update_clone(clone_dir, slot["default_branch"],
                                    prev_sha)
        self.assertEqual(result["status"], "ok", result)
        rng = result["range"]
        return _insert_range(
            self.conn, netuid, slot["epoch"], result["prev_sha"],
            result["new_sha"],
            [f["path"] for f in rng["files"]],
            commits=max(1, len(rng["commits"])), **range_kwargs
        ), result["new_sha"]


# ---------------------------------------------------------------------------
# Schema / store
# ---------------------------------------------------------------------------

class TestSchema(SignalsBase):
    def test_schema_additive_and_idempotent(self):
        before = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        sig.ensure_schema(self.conn)  # second run: no error, no change
        after = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(before, after)
        self.assertIn("slots", after)          # reconcile schema untouched
        self.assertIn("signal_adoptions", after)

    def test_wal_and_busy_timeout_active(self):
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")
        timeout = self.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertGreaterEqual(int(timeout), 10000)

    def test_concurrent_reader_during_write(self):
        self.conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) VALUES "
            "('econ-code', 'instant', 1, NULL, 'k1', '{}', ?)", (_iso(),))
        # writer holds an open transaction; a read-only URI connection
        # must still see the last committed state without erroring.
        self.conn.commit()
        self.conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) VALUES "
            "('econ-code', 'instant', 2, NULL, 'k2', '{}', ?)", (_iso(),))
        uri = "file:%s?mode=ro" % urllib.request.pathname2url(self.db)
        reader = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            rows = reader.execute(
                "SELECT COUNT(*) FROM signal_events").fetchone()[0]
            self.assertEqual(rows, 1)  # only committed data is visible
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute("INSERT INTO signal_state VALUES ('a','b')")
        finally:
            reader.close()
            self.conn.rollback()

    def test_status_on_empty_store(self):
        status = sig.signals_status(self.conn)
        self.assertEqual(status["adoptions"]["rows"], 0)
        self.assertEqual(status["events"], {})


# ---------------------------------------------------------------------------
# Scan surface + parsers (pure)
# ---------------------------------------------------------------------------

class TestSurface(unittest.TestCase):
    def test_manifest_predicate(self):
        self.assertTrue(sig.is_manifest("requirements.txt", CFG))
        self.assertTrue(sig.is_manifest("requirements-dev.txt", CFG))
        self.assertTrue(sig.is_manifest("api/pyproject.toml", CFG))
        self.assertFalse(sig.is_manifest("poetry.lock", CFG))
        self.assertFalse(sig.is_manifest("package-lock.json", CFG))
        self.assertFalse(sig.is_manifest("vendor/pkg/requirements.txt", CFG))
        self.assertFalse(sig.is_manifest("tests/requirements.txt", CFG))
        self.assertFalse(sig.is_manifest("src/main.py", CFG))

    def test_model_and_econ_predicates(self):
        self.assertTrue(sig.is_model_id_file("neuron/config.py", CFG))
        self.assertTrue(sig.is_model_id_file(".env.example", CFG))
        self.assertFalse(sig.is_model_id_file("node_modules/a/b.py", CFG))
        self.assertFalse(sig.is_model_id_file("README.md", CFG))
        self.assertTrue(sig.is_econ_path("validator/reward.py", CFG))
        self.assertTrue(sig.is_econ_path("neurons/scoring/model.rs", CFG))
        self.assertFalse(sig.is_econ_path("tests/reward_test.py", CFG))
        self.assertFalse(sig.is_econ_path("src/main.py", CFG))

    def test_requirements_parser(self):
        terms = sig.dep_terms_for("requirements.txt", [
            "vllm==0.5.1", "Torch>=2.0  # gpu", "# comment", "",
            "-r base.txt", "git+https://x/y.git",
            "package[extra1]~=1.0", "https://files/x.whl"], CFG)
        self.assertEqual(terms, ["vllm", "torch", "package"])

    def test_pyproject_parser(self):
        terms = sig.dep_terms_for("pyproject.toml", [
            'dependencies = ["sglang>=0.4", "numpy==1.26"]',
            'verl = "^1.0"', 'version = "3.1"', 'python = ">=3.10"'], CFG)
        self.assertEqual(terms, ["sglang", "numpy", "verl"])

    def test_package_json_and_cargo_parsers(self):
        terms = sig.dep_terms_for("package.json", [
            '"left-pad": "^1.3.0",', '"start": "node index.js",',
            '"@scope/pkg": ">=2.0.0"'], CFG)
        self.assertEqual(terms, ["left-pad", "@scope/pkg"])
        terms = sig.dep_terms_for("Cargo.toml", [
            'serde = "1.0"', 'tokio = { version = "1", features = ["full"] }',
            'edition = "2021"', '[dependencies]'], CFG)
        self.assertEqual(terms, ["serde", "tokio"])

    def test_environment_markers_never_become_terms(self):
        # PEP 508 markers after ';' inside a quoted spec (the deployed
        # 'python_version' ledger-noise case), standalone poetry marker
        # values, and marker-shaped TOML keys must all yield nothing.
        terms = sig.dep_terms_for("pyproject.toml", [
            "dependencies = [\"numpy>=1.0; python_version >= '3.8'\"]",
            "markers = \"python_version >= '3.9'\"",
            "python_version = \"3.10\"",
            "requires = [\"tomli>=1.1; sys_platform == 'win32'\"]"], CFG)
        self.assertEqual(terms, ["numpy", "tomli"])
        terms = sig.dep_terms_for("setup.py", [
            "install_requires=[\"pandas>=2.0; platform_machine!='arm'\"],"],
            CFG)
        self.assertEqual(terms, ["pandas"])
        terms = sig.dep_terms_for("requirements.txt", [
            "numpy>=1.0; python_version < '3.11'"], CFG)
        self.assertEqual(terms, ["numpy"])
        for marker in ("python_version", "sys_platform", "extra"):
            self.assertIsNone(sig.normalize_dep(marker, 120))

    def test_normalization_bounds(self):
        self.assertIsNone(sig.normalize_dep("x", 120))
        self.assertIsNone(sig.normalize_dep("123", 120))
        self.assertIsNone(sig.normalize_dep("https://x/y", 120))
        self.assertIsNone(sig.normalize_dep("a" * 200, 120))
        self.assertEqual(sig.normalize_dep(' "Verl" ', 120), "verl")

    def test_model_id_extraction(self):
        regexes = sig._model_regexes(CFG)
        terms = sig.model_terms_for([
            'MODEL = "deepseek-ai/DeepSeek-V3-Base"',
            "default='gpt-4o-mini'", "x = llama-3.1-70b",
            "nothing here"], regexes, 120)
        self.assertIn("gpt-4o-mini", terms)
        self.assertTrue(any("deepseek" in t for t in terms))
        self.assertTrue(any(t.startswith("llama-3") for t in terms))

    def test_watchlist_compile_and_match(self):
        cfg = dict(CFG)
        cfg["watchlist"] = ["re:^vllm", "chutes", "re:[invalid"]
        matchers, invalid = sig.compile_watchlist(cfg)
        self.assertEqual(invalid, ["re:[invalid"])
        self.assertTrue(sig.watchlist_hit("vllm-flash", matchers))
        self.assertTrue(sig.watchlist_hit("chutes-sdk", matchers))
        self.assertFalse(sig.watchlist_hit("torch", matchers))


# ---------------------------------------------------------------------------
# Extraction over real fixture clones
# ---------------------------------------------------------------------------

class TestExtraction(SignalsBase):
    def test_manifest_adoption_recorded(self):
        origin, clone_dir, state = self.make_slot(
            5, {"requirements.txt": "torch==2.0\n"})
        self.advance(5, origin, clone_dir, "requirements.txt",
                     "torch==2.0\nvllm==0.5\n", state["local_sha"])
        summary = sig.run_extract(self.conn, self.config)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["adoptions"], 1)  # torch line unchanged
        row = self.conn.execute(
            "SELECT term, kind, netuid, epoch, seeded FROM signal_adoptions"
        ).fetchone()
        self.assertEqual(tuple(row), ("vllm", "dependency", 5, 1, 0))

    def test_duplicate_adoption_ignored(self):
        origin, clone_dir, state = self.make_slot(
            6, {"requirements.txt": "torch\n"})
        _rid, sha = self.advance(6, origin, clone_dir, "requirements.txt",
                                 "torch\nvllm\n", state["local_sha"])
        sig.run_extract(self.conn, self.config)
        # vllm reappears in a later range (removed + re-added)
        self.advance(6, origin, clone_dir, "requirements.txt",
                     "torch\nvllm\nvllm-extra\n", sha)
        sig.run_extract(self.conn, self.config)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM signal_adoptions WHERE term='vllm'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_free_path_runs_no_git(self):
        origin, clone_dir, state = self.make_slot(7, {"README.md": "x\n"})
        self.advance(7, origin, clone_dir, "README.md", "y\n",
                     state["local_sha"])
        calls = []

        def counting_git(cwd, args, **kwargs):
            calls.append(args)
            return fleet._run_git(cwd, args, **kwargs)

        summary = sig.run_extract(self.conn, self.config, git=counting_git)
        self.assertEqual(summary["no-surface"], 1)
        self.assertEqual(calls, [])

    def test_truncated_record_never_takes_free_path(self):
        origin, clone_dir, state = self.make_slot(
            8, {"requirements.txt": "torch\n"})
        h.add_commit(origin, "requirements.txt", "torch\nsglang\n")
        slot = fleet.get_slot(self.conn, 8)
        result = fleet.update_clone(clone_dir, slot["default_branch"],
                                    state["local_sha"])
        # record the range with an EMPTY, truncated file list — the
        # manifest change is invisible in the recorded metadata
        _insert_range(self.conn, 8, 1, result["prev_sha"], result["new_sha"],
                      [], files_truncated=True)
        summary = sig.run_extract(self.conn, self.config)
        self.assertEqual(summary["adoptions"], 1)
        term = self.conn.execute(
            "SELECT term FROM signal_adoptions").fetchone()[0]
        self.assertEqual(term, "sglang")
        detail = self.conn.execute(
            "SELECT detail FROM signal_range_log").fetchone()[0]
        self.assertIn("rebuilt", detail)

    def test_giant_range_degrades_to_manifests_only(self):
        self.config["signals"] = {"range_caps": {"max_files": 2,
                                                 "max_commits": 100}}
        origin, clone_dir, state = self.make_slot(
            9, {"requirements.txt": "torch\n", "a.py": "x\n", "b.py": "x\n"})
        h.add_commit(origin, "a.py", 'M = "gpt-4o"\n')
        h.add_commit(origin, "b.py", "y\n")
        h.add_commit(origin, "requirements.txt", "torch\nverl\n")
        slot = fleet.get_slot(self.conn, 9)
        result = fleet.update_clone(clone_dir, slot["default_branch"],
                                    state["local_sha"])
        rng = result["range"]
        _insert_range(self.conn, 9, 1, result["prev_sha"], result["new_sha"],
                      [f["path"] for f in rng["files"]], commits=3)
        summary = sig.run_extract(self.conn, self.config)
        self.assertEqual(summary["degraded"], 1)
        kinds = {row[0] for row in self.conn.execute(
            "SELECT kind FROM signal_adoptions")}
        self.assertEqual(kinds, {"dependency"})  # model-id pass skipped
        capped = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE dedup_key LIKE "
            "'range-capped:%'").fetchone()[0]
        self.assertEqual(capped, 1)

    def test_term_overflow_capped_with_note(self):
        self.config["signals"] = {"max_terms_per_range": 2}
        origin, clone_dir, state = self.make_slot(
            10, {"requirements.txt": "torch\n"})
        self.advance(10, origin, clone_dir, "requirements.txt",
                     "torch\naaa\nbbb\nccc\nddd\n", state["local_sha"])
        sig.run_extract(self.conn, self.config)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM signal_adoptions").fetchone()[0]
        self.assertEqual(count, 2)
        note = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE dedup_key LIKE "
            "'term-overflow:%'").fetchone()[0]
        self.assertEqual(note, 1)

    def test_failed_range_never_blocks_pass(self):
        origin, clone_dir, state = self.make_slot(
            11, {"requirements.txt": "torch\n"})
        # a range for a slot whose clone directory does not exist
        _insert_range(self.conn, 99, 1, "a" * 40, "b" * 40,
                      ["requirements.txt"])
        _rid, _sha = self.advance(11, origin, clone_dir, "requirements.txt",
                                  "torch\nvllm\n", state["local_sha"])
        summary = sig.run_extract(self.conn, self.config)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["adoptions"], 1)  # the good range still ran
        outcome = self.conn.execute(
            "SELECT outcome FROM signal_range_log WHERE netuid=99"
        ).fetchone()[0]
        self.assertEqual(outcome, "extract-failed")
        wm = int(sig.state_get(self.conn, "range_watermark"))
        self.assertEqual(wm, self.conn.execute(
            "SELECT MAX(id) FROM change_ranges").fetchone()[0])


# ---------------------------------------------------------------------------
# Detection: watchlist, novelty/cluster, econ
# ---------------------------------------------------------------------------

class TestDetection(SignalsBase):
    def _adopt(self, netuid, term, at=None, kind="dependency", seeded=False):
        sig.record_adoption(self.conn, term, kind, netuid, 1, at or _iso(),
                            "f" * 40, "requirements.txt", seeded=seeded)

    def _evaluate(self, netuid, term, at=None, cfg_over=None):
        cfg = sig.signals_cfg({"signals": cfg_over or {}})
        matchers, _ = sig.compile_watchlist(cfg)
        return sig.evaluate_adoption(self.conn, cfg, matchers, term,
                                     "dependency", netuid, 1, at or _iso(),
                                     "f" * 40, "requirements.txt", _iso())

    def test_cluster_fires_at_kth_and_never_refires(self):
        self._adopt(1, "newlib", at=_iso(days_ago=5))
        self._adopt(2, "newlib", at=_iso(days_ago=3))
        self._adopt(3, "newlib")
        emitted = self._evaluate(3, "newlib")
        self.assertEqual(emitted["cluster"], 1)
        payload = json.loads(self.conn.execute(
            "SELECT payload_json FROM signal_events WHERE class="
            "'narrative-cluster'").fetchone()[0])
        self.assertEqual([m["netuid"] for m in payload["members"]], [1, 2, 3])
        self.assertEqual(payload["first_mover"]["netuid"], 1)
        # fourth adopter: digest reference, no second instant event
        self._adopt(4, "newlib")
        emitted = self._evaluate(4, "newlib")
        self.assertEqual(emitted["cluster"], 0)
        self.assertEqual(emitted["digest"], 1)
        clusters = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE class="
            "'narrative-cluster'").fetchone()[0]
        self.assertEqual(clusters, 1)

    def test_window_excludes_old_adoptions(self):
        self._adopt(1, "slowlib", at=_iso(days_ago=40))
        self._adopt(2, "slowlib", at=_iso(days_ago=30))
        self._adopt(3, "slowlib")
        emitted = self._evaluate(3, "slowlib")
        self.assertEqual(emitted["cluster"], 0)

    def test_common_term_never_clusters(self):
        for netuid in range(1, 13):
            self._adopt(netuid, "torch")
        emitted = self._evaluate(12, "torch")
        self.assertEqual(emitted["cluster"], 0)

    def test_seeded_rows_raise_novelty_but_not_windows(self):
        # 11 seeded prevalence rows push the term over the novelty
        # ceiling: three fresh adoptions must NOT cluster.
        for netuid in range(20, 31):
            self._adopt(netuid, "gpt-4o", kind="dependency", seeded=True)
        self._adopt(1, "gpt-4o")
        self._adopt(2, "gpt-4o")
        self._adopt(3, "gpt-4o")
        emitted = self._evaluate(3, "gpt-4o")
        self.assertEqual(emitted["cluster"], 0)

    def test_watchlist_hit_once_per_netuid_epoch(self):
        self._adopt(5, "vllm-core")
        emitted = self._evaluate(5, "vllm-core")
        self.assertEqual(emitted["watchlist"], 1)
        emitted = self._evaluate(5, "vllm-core")  # replay: dedup key holds
        self.assertEqual(emitted["watchlist"], 0)

    def test_econ_instant_then_cooldown_digest(self):
        origin, clone_dir, state = self.make_slot(
            13, {"validator/reward.py": "def reward(): pass\n"})
        _rid, sha = self.advance(13, origin, clone_dir,
                                 "validator/reward.py",
                                 "def reward(): return 1\n",
                                 state["local_sha"])
        sig.run_extract(self.conn, self.config)
        instants = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE class='econ-code' AND "
            "tier='instant'").fetchone()[0]
        self.assertEqual(instants, 1)
        # second reward touch within the cooldown window → digest only
        self.advance(13, origin, clone_dir, "validator/reward.py",
                     "def reward(): return 2\n", sha)
        sig.run_extract(self.conn, self.config)
        instants = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE class='econ-code' AND "
            "tier='instant'").fetchone()[0]
        self.assertEqual(instants, 1)
        digests = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE dedup_key LIKE "
            "'econ-cooldown:%'").fetchone()[0]
        self.assertEqual(digests, 1)


# ---------------------------------------------------------------------------
# Epoch seeding + install gating
# ---------------------------------------------------------------------------

class TestEpochSeeding(SignalsBase):
    def test_pre_install_epochs_seed_silently(self):
        self.make_slot(21, {"requirements.txt": "torch\nvllm\n"},
                       opened_at=_iso(days_ago=10))
        sig.state_set(self.conn, "installed_at", _iso())
        summary = sig.seed_epochs(self.conn, self.config)
        self.assertEqual(summary["seeded"], 1)
        rows = self.conn.execute(
            "SELECT term, seeded FROM signal_adoptions ORDER BY term"
        ).fetchall()
        self.assertEqual([tuple(r) for r in rows],
                         [("torch", 1), ("vllm", 1)])
        events = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events").fetchone()[0]
        self.assertEqual(events, 0)

    def test_post_install_epoch_runs_detection(self):
        sig.state_set(self.conn, "installed_at", _iso(days_ago=30))
        self.make_slot(22, {"requirements.txt": "vllm-core\n"},
                       opened_at=_iso(days_ago=1))
        summary = sig.seed_epochs(self.conn, self.config)
        self.assertEqual(summary["seeded"], 1)
        seeded_flag = self.conn.execute(
            "SELECT seeded FROM signal_adoptions").fetchone()[0]
        self.assertEqual(seeded_flag, 0)
        hits = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE class='watchlist'"
        ).fetchone()[0]
        self.assertEqual(hits, 1)  # vllm-core matches the starter watchlist

    def test_epoch_isolation_on_repoint(self):
        self.make_slot(23, {"requirements.txt": "vllm\n"}, epoch=1,
                       opened_at=_iso(days_ago=10))
        sig.state_set(self.conn, "installed_at", _iso(days_ago=30))
        sig.seed_epochs(self.conn, self.config)
        # re-point: new epoch, new project, same netuid
        shutil.rmtree(os.path.join(self.clone_root, "23"),
                      ignore_errors=True)
        fleet._rmtree(os.path.join(self.clone_root, "23"))
        self.make_slot(23, {"requirements.txt": "vllm\n"}, epoch=2,
                       opened_at=_iso(days_ago=1))
        sig.seed_epochs(self.conn, self.config)
        rows = self.conn.execute(
            "SELECT epoch, COUNT(*) FROM signal_adoptions WHERE term='vllm' "
            "AND netuid=23 GROUP BY epoch ORDER BY epoch").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(1, 1), (2, 1)])

    def test_seed_runs_once_per_epoch(self):
        self.make_slot(24, {"requirements.txt": "torch\n"})
        sig.state_set(self.conn, "installed_at", _iso())
        self.assertEqual(sig.seed_epochs(self.conn, self.config)["seeded"], 1)
        self.assertEqual(sig.seed_epochs(self.conn, self.config)["seeded"], 0)


# ---------------------------------------------------------------------------
# Backfill / seed-modelids / calibrate
# ---------------------------------------------------------------------------

class TestBackfill(SignalsBase):
    def test_backfill_seeds_history_and_emits_nothing(self):
        origin, clone_dir, state = self.make_slot(
            31, {"requirements.txt": "torch\n"})
        h.add_commit(origin, "requirements.txt", "torch\nvllm\n")
        h.add_commit(origin, "requirements.txt", "torch\nvllm\nsglang\n")
        slot = fleet.get_slot(self.conn, 31)
        result = fleet.update_clone(clone_dir, slot["default_branch"],
                                    state["local_sha"])
        self.assertEqual(result["status"], "ok")
        _insert_range(self.conn, 31, 1, result["prev_sha"],
                      result["new_sha"],
                      [f["path"] for f in result["range"]["files"]])
        summary = sig.backfill(self.conn, self.config)
        self.assertEqual(summary["failed"], 0)
        terms = sorted(row[0] for row in self.conn.execute(
            "SELECT term FROM signal_adoptions"))
        self.assertEqual(terms, ["sglang", "torch", "vllm"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_events").fetchone()[0], 0)
        # watermark pinned to the newest range: extract replays nothing
        wm = int(sig.state_get(self.conn, "range_watermark"))
        self.assertEqual(wm, self.conn.execute(
            "SELECT MAX(id) FROM change_ranges").fetchone()[0])

    def test_backfill_upgrades_seeded_rows_with_real_dates(self):
        origin, clone_dir, state = self.make_slot(
            32, {"requirements.txt": "vllm\n"})
        sig.record_adoption(self.conn, "vllm", "dependency", 32, 1,
                            _iso(), None, "requirements.txt", seeded=True)
        sig.backfill(self.conn, self.config)
        seeded, sha = self.conn.execute(
            "SELECT seeded, commit_sha FROM signal_adoptions WHERE "
            "term='vllm'").fetchone()
        self.assertEqual(seeded, 0)
        self.assertTrue(sha)

    def test_seed_modelids_from_index_blocks_cold_start(self):
        cfg_low = {"novelty_max_adopters": 2}
        self.config["signals"] = cfg_low
        idx.ensure_schema(self.conn)
        for netuid in (41, 42, 43):
            _origin, clone_dir, state = self.make_slot(
                netuid, {"miner/config.py": 'MODEL = "gpt-4o-mini"\n'})
            idx.index_slot(self.conn, netuid, 1, clone_dir,
                           {"extensions": [".py"], "max_file_bytes": 65536},
                           local_sha=state["local_sha"])
        summary = sig.seed_modelids(self.conn, self.config)
        self.assertEqual(summary["adoptions"], 3)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_adoptions WHERE seeded=1"
        ).fetchone()[0], 3)
        # forward adoptions can no longer fake a "novel" cluster
        cfg = sig.signals_cfg({"signals": cfg_low})
        matchers, _ = sig.compile_watchlist(cfg)
        for netuid in (1, 2, 3):
            sig.record_adoption(self.conn, "gpt-4o-mini", "model-id",
                                netuid, 1, _iso(), None, "x.py")
            emitted = sig.evaluate_adoption(
                self.conn, cfg, matchers, "gpt-4o-mini", "model-id", netuid,
                1, _iso(), None, "x.py", _iso())
        self.assertEqual(emitted["cluster"], 0)

    def test_seed_modelids_without_index_reports(self):
        conn = sqlite3.connect(":memory:")
        sig.ensure_schema(conn)
        result = sig.seed_modelids(conn, self.config)
        self.assertIn("error", result)
        conn.close()

    def test_calibrate_read_only_and_stable(self):
        for netuid, days in ((1, 9), (2, 6), (3, 2)):
            sig.record_adoption(self.conn, "newlib", "dependency", netuid, 1,
                                _iso(days_ago=days), None, "r.txt")
        before = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events").fetchone()[0]
        report = sig.calibrate(self.conn, self.config, k_values=[3],
                               window_values=[14], novelty_values=[10])
        self.assertEqual(report["grid"][0]["clusters"], 1)
        self.assertEqual(report["grid"][0]["examples"][0]["term"], "newlib")
        report2 = sig.calibrate(self.conn, self.config, k_values=[3],
                                window_values=[14], novelty_values=[10])
        self.assertEqual(report["grid"], report2["grid"])
        after = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events").fetchone()[0]
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Price snapshots + outcomes (effectiveness ledger)
# ---------------------------------------------------------------------------

class TestMeasurement(SignalsBase):
    def _instant_event(self, netuid=50, created_at=None, dedup="econ:1"):
        cursor = self.conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) VALUES (?, ?, ?, ?, ?, "
            "?, ?)",
            ("econ-code", "instant", netuid, None, dedup, "{}",
             created_at or _iso()))
        self.conn.commit()
        return cursor.lastrowid

    def test_no_events_no_fetch(self):
        calls = []
        summary = sig.run_measurement(self.conn, self.config,
                                      price_fetcher=lambda: calls.append(1)
                                      or {})
        self.assertFalse(summary["fetched"])
        self.assertEqual(calls, [])

    def test_entry_fill_and_one_fetch_per_pass(self):
        self._instant_event(netuid=50)
        self._instant_event(netuid=51, dedup="econ:2")
        calls = []

        def fetcher():
            calls.append(1)
            return snap({50: 0.01, 51: 0.002, 52: 0.5})

        summary = sig.run_measurement(self.conn, self.config,
                                      price_fetcher=fetcher)
        self.assertEqual(calls, [1])
        self.assertEqual(summary["entries_filled"], 2)
        status, price = self.conn.execute(
            "SELECT status, price_tao FROM signal_entries WHERE netuid=50"
        ).fetchone()
        self.assertEqual(status, "recorded")
        self.assertEqual(price, 0.01)
        horizons = [row[0] for row in self.conn.execute(
            "SELECT horizon_days FROM signal_outcomes WHERE netuid=50 "
            "ORDER BY horizon_days")]
        self.assertEqual(horizons, [1, 7, 30])
        # full fleet vector stored for baseline computation
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_prices").fetchone()[0], 3)

    def test_failed_fetch_leaves_pending_never_blocks(self):
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        self._instant_event(created_at=t0.isoformat())
        summary = sig.run_measurement(self.conn, self.config,
                                      now=t0.isoformat(),
                                      price_fetcher=lambda: None)
        self.assertTrue(summary.get("fetch_failed"))
        status = self.conn.execute(
            "SELECT status FROM signal_entries").fetchone()[0]
        self.assertEqual(status, "pending")
        # A retry inside the late grace fills from that vector.
        later = (t0 + datetime.timedelta(hours=5)).isoformat()
        sig.run_measurement(self.conn, self.config, now=later,
                            price_fetcher=lambda: snap({50: 0.01}))
        status, as_of = self.conn.execute(
            "SELECT status, as_of FROM signal_entries").fetchone()
        self.assertEqual((status, as_of), ("recorded", later))

    def test_entry_past_the_grace_is_unavailable(self):
        # Regression (audit C13): an entry filled 12 h late used to be
        # `late` and still measured, so its horizons ran short.
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        self._instant_event(created_at=t0.isoformat())
        sig.run_measurement(self.conn, self.config,
                            now=(t0 + datetime.timedelta(hours=12)).isoformat(),
                            price_fetcher=lambda: snap({50: 0.01}))
        status, reason = self.conn.execute(
            "SELECT status, reason FROM signal_entries").fetchone()
        self.assertEqual((status, reason), ("unavailable", "no-vector"))

    def _pass(self, when, prices, registered=None):
        return sig.run_measurement(
            self.conn, self.config, now=when.isoformat(),
            price_fetcher=lambda: snap(prices, registered))

    def _outcome_row(self, event_id, horizon):
        return self.conn.execute(
            "SELECT return_pct, baseline_return_pct, status, v2_status, "
            "v2_reason, v2_excess_pct FROM signal_outcomes WHERE "
            "event_id = ? AND horizon_days = ?",
            (event_id, horizon)).fetchone()

    def test_outcome_fill_with_baseline_window_alignment(self):
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=50, created_at=t0.isoformat())
        self._pass(t0, {50: 0.01, 51: 1.0, 52: 2.0})
        self._pass(t0 + datetime.timedelta(days=1, hours=2),
                   {50: 0.02, 51: 1.5, 52: 2.0})
        ret, base, status, v2, _reason, excess = self._outcome_row(event_id, 1)
        self.assertAlmostEqual(ret, 100.0, places=3)
        # fleet median over {50: +100%, 51: +50%, 52: 0%} = +50%
        self.assertAlmostEqual(base, 50.0, places=3)
        self.assertEqual((status, v2), ("recorded", "recorded"))
        self.assertAlmostEqual(excess, 50.0, places=3)

    def test_late_exit_is_unavailable_not_stretched(self):
        # Regression (audit C13): a horizon filled at the first pass after
        # it fell due, however late, so "7 days" could span 5 or 9.
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=50, created_at=t0.isoformat())
        self._pass(t0, {50: 0.01})
        self._pass(t0 + datetime.timedelta(days=1, hours=9), {50: 0.02})
        _ret, _base, status, v2, reason, _excess = self._outcome_row(event_id, 1)
        self.assertEqual((status, v2, reason),
                         ("unavailable", "unavailable", "no-vector"))

    def test_exit_in_a_jittered_timer_gap_is_recorded(self):
        # 6 h timer, 6.5 h gap: inside the 7 h grace (operator decision
        # 2026-11-04).
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=50, created_at=t0.isoformat())
        self._pass(t0, {50: 0.01})
        self._pass(t0 + datetime.timedelta(days=1, hours=6, minutes=30),
                   {50: 0.02})
        self.assertEqual(self._outcome_row(event_id, 1)[3], "recorded")

    def test_reregistered_netuid_is_not_one_subnet(self):
        # Regression (audit C13): SN82 read +2533% over 30 days because a
        # new subnet took the netuid inside the window.
        t0 = datetime.datetime(2026, 9, 17, 12, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=82, created_at=t0.isoformat())
        self._pass(t0, {82: 0.001, 51: 1.0, 52: 2.0},
                   {82: 8000000, 51: 5, 52: 6})
        self._pass(t0 + datetime.timedelta(days=1, hours=1),
                   {82: 0.0263, 51: 1.0, 52: 2.0},
                   {82: 9155260, 51: 5, 52: 6})
        ret, _base, status, v2, reason, _excess = self._outcome_row(event_id, 1)
        self.assertIsNone(ret)
        self.assertEqual((status, v2, reason),
                         ("unavailable", "unavailable", "re-registered"))

    def test_baseline_excludes_a_reregistered_netuid(self):
        t0 = datetime.datetime(2026, 11, 3, 0, 0, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=50, created_at=t0.isoformat())
        self._pass(t0, {50: 1.0, 51: 1.0, 52: 1.0, 53: 0.001},
                   {53: 100})
        self._pass(t0 + datetime.timedelta(days=1, hours=1),
                   {50: 1.1, 51: 0.9, 52: 1.0, 53: 1.0}, {53: 200})
        _ret, base, _status, v2, _reason, _excess = self._outcome_row(event_id, 1)
        # median of {+10%, -10%, 0%}; SN53's +99900% is left out
        self.assertEqual(v2, "recorded")
        self.assertAlmostEqual(base, 0.0, places=6)

    def test_legacy_entry_vector_judged_from_exit_registration(self):
        # A vector stored before this change has no occupant key. The exit
        # vector's registration block decides, through block anchors.
        t0 = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
        event_id = self._instant_event(netuid=50, created_at=t0.isoformat())
        self.conn.executemany(
            "INSERT INTO signal_prices (ts, netuid, price_tao) "
            "VALUES (?, ?, ?)", [(t0.isoformat(), 50, 1.0),
                                 (t0.isoformat(), 51, 1.0)])
        self.conn.commit()
        anchors = [(1000, t0 - datetime.timedelta(days=30)),
                   (1000 + 7200 * 40, t0 + datetime.timedelta(days=10))]
        exit_time = t0 + datetime.timedelta(days=1, hours=1)
        # SN50 registered at block 1000 (30 days before entry): clean.
        # SN51 registered 12 h after entry: re-registered inside the window.
        reg51 = 1000 + int((30 * 86400 + 12 * 3600) / 12.0)
        sig.run_measurement(
            self.conn, self.config, now=exit_time.isoformat(),
            anchors=anchors,
            price_fetcher=lambda: snap({50: 1.2, 51: 9.0},
                                       {50: 1000, 51: reg51}))
        ret, base, _status, v2, _reason, _excess = self._outcome_row(event_id, 1)
        self.assertEqual(v2, "recorded")
        self.assertAlmostEqual(ret, 20.0, places=6)
        self.assertAlmostEqual(base, 20.0, places=6)  # SN51 excluded

    def test_deregistered_subnet_marked_unavailable(self):
        self._instant_event(netuid=77)
        sig.run_measurement(self.conn, self.config,
                            price_fetcher=lambda: snap({50: 0.01}))
        status = self.conn.execute(
            "SELECT status FROM signal_entries WHERE netuid=77"
        ).fetchone()[0]
        self.assertEqual(status, "unavailable")
        past = (datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(hours=1)).isoformat()
        self.conn.execute("UPDATE signal_outcomes SET due_at = ?", (past,))
        self.conn.commit()
        sig.run_measurement(self.conn, self.config,
                            price_fetcher=lambda: snap({50: 0.01}))
        states = {row[0] for row in self.conn.execute(
            "SELECT status FROM signal_outcomes")}
        self.assertEqual(states, {"unavailable"})

    def test_retention_never_below_horizon_floor(self):
        self.config["signals"] = {"price_retention_days": 1,
                                  "outcome_horizons_days": [1, 7, 30]}
        self._instant_event()
        stale = (datetime.datetime.now(tz=datetime.timezone.utc)
                 - datetime.timedelta(days=20)).isoformat()
        self.conn.execute(
            "INSERT INTO signal_prices (ts, netuid, price_tao) VALUES "
            "(?, 50, 0.5)", (stale,))
        self.conn.commit()
        sig.run_measurement(self.conn, self.config,
                            price_fetcher=lambda: snap({50: 0.01}))
        # 20-day-old vector survives: floor is max horizon (30) + 7
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_prices WHERE ts = ?",
            (stale,)).fetchone()[0], 1)

    def test_effectiveness_report_medians(self):
        event_id = self._instant_event(netuid=50)
        self.conn.execute(
            "INSERT INTO signal_entries (event_id, netuid, price_tao, "
            "as_of, status) VALUES (?, 50, 0.01, ?, 'recorded')",
            (event_id, _iso()))
        for horizon, ret, base, status in ((1, 10.0, 2.0, "recorded"),
                                           (7, -5.0, 1.0, "recorded"),
                                           (30, None, None, "pending")):
            self.conn.execute(
                "INSERT INTO signal_outcomes (event_id, netuid, "
                "horizon_days, due_at, return_pct, baseline_return_pct, "
                "status, v2_status, v2_entry_ts, v2_return_pct, "
                "v2_baseline_pct, v2_excess_pct, v2_rules) VALUES "
                "(?, 50, ?, ?, ?, ?, ?, ?, 'm1', ?, ?, ?, ?)",
                (event_id, horizon, _iso(), ret, base, status,
                 None if status == "pending" else status, ret, base,
                 None if ret is None else ret - base,
                 None if status == "pending" else sig.RULES_VERSION))
        self.conn.commit()
        report = sig.effectiveness(self.conn)
        by_horizon = {item["horizon_days"]: item
                      for item in report["report"]}
        self.assertEqual(by_horizon[1]["median_return_pct"], 10.0)
        self.assertEqual(by_horizon[1]["median_baseline_pct"], 2.0)
        self.assertEqual(by_horizon[1]["median_excess_pct"], 8.0)
        self.assertEqual(by_horizon[30]["pending"], 1)


class TestEffectivenessStatistics(SignalsBase):
    """Change signal-statistics-ties: the floor counts event moments, the
    headline is the median paired excess, and the interval resamples whole
    moments."""

    def _rows(self, event_class, moments, per_moment, excess_of,
              horizon=7, rules=None):
        rules = sig.RULES_VERSION if rules is None else rules
        event_id = 0
        for m in range(moments):
            for k in range(per_moment):
                event_id += 1
                excess = excess_of(m, k)
                self.conn.execute(
                    "INSERT INTO signal_outcomes (source_store, event_id, "
                    "netuid, source_class, horizon_days, due_at, status, "
                    "return_pct, baseline_return_pct, v2_status, "
                    "v2_entry_ts, v2_return_pct, v2_baseline_pct, "
                    "v2_excess_pct, v2_rules) VALUES ('livedata', ?, ?, ?, "
                    "?, ?, 'recorded', ?, 0.0, 'recorded', ?, ?, 0.0, ?, ?)",
                    (event_id, k, event_class, horizon, _iso(), excess,
                     "moment-%03d" % m, excess, excess, rules))
        self.conn.commit()

    def _entry(self, event_class, horizon=7):
        for item in sig.effectiveness(self.conn, self.config)["report"]:
            if item["class"] == event_class and \
                    item["horizon_days"] == horizon:
                return item
        raise AssertionError("no report entry")

    def test_many_rows_from_few_moments_fail_the_floor(self):
        # Regression (audit C13): 87 root-rotation rows from 8 event hours
        # passed the 30-outcome floor.
        self._rows("root-rotation", 8, 11, lambda m, k: 1.0 + m)
        entry = self._entry("root-rotation")
        self.assertEqual(entry["filled"], 88)
        self.assertEqual(entry["events"], 8)
        self.assertFalse(entry["meets_promotion_sample"])
        self.assertFalse(entry["beats_baseline"])
        self.assertIsNone(entry["excess_ci95"])  # below 10 moments

    def test_interval_is_repeatable(self):
        self._rows("econ-code", 40, 3, lambda m, k: (m % 7) - 2.0 + k)
        first = self._entry("econ-code")["excess_ci95"]
        second = self._entry("econ-code")["excess_ci95"]
        self.assertIsNotNone(first)
        self.assertEqual(first, second)

    def test_interval_touching_zero_does_not_beat_baseline(self):
        # Positive median, but half the moments sit below zero.
        self._rows("watchlist", 40, 1,
                   lambda m, k: 3.0 if m % 2 else -2.0 + (m % 5) * 0.1)
        entry = self._entry("watchlist")
        self.assertTrue(entry["meets_promotion_sample"])
        self.assertLessEqual(entry["excess_ci95"][0], 0)
        self.assertFalse(entry["beats_baseline"])

    def test_clear_excess_beats_baseline(self):
        self._rows("narrative-cluster", 40, 2, lambda m, k: 5.0 + (m % 3))
        entry = self._entry("narrative-cluster")
        self.assertTrue(entry["beats_baseline"])
        self.assertGreater(entry["excess_ci95"][0], 0)

    def test_rows_without_current_rules_are_unscored(self):
        self._rows("econ-code", 3, 1, lambda m, k: 1.0, rules=1)
        entry = self._entry("econ-code")
        self.assertEqual((entry["filled"], entry["unscored"]), (0, 3))

    def test_report_changes_no_state(self):
        self._rows("econ-code", 12, 2, lambda m, k: float(m))
        before = self.conn.total_changes
        sig.effectiveness(self.conn, self.config)
        self.assertEqual(self.conn.total_changes, before)


# ---------------------------------------------------------------------------
# run_pass installation semantics + reconcile isolation
# ---------------------------------------------------------------------------

class TestRunPass(SignalsBase):
    def test_first_run_installs_quietly(self):
        origin, clone_dir, state = self.make_slot(
            61, {"requirements.txt": "torch\n"})
        self.advance(61, origin, clone_dir, "requirements.txt",
                     "torch\nvllm\n", state["local_sha"])
        summary = sig.run_pass(self.conn, self.config,
                               price_fetcher=lambda: None)
        # pre-install range skipped (watermark seeded to max), epoch
        # seeded silently, zero events
        self.assertEqual(summary["extract"]["ranges"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_events").fetchone()[0], 0)
        self.assertTrue(sig.state_get(self.conn, "installed_at"))

    def test_disabled_kill_switch(self):
        self.config["signals"] = {"enabled": False}
        summary = sig.run_pass(self.conn, self.config)
        self.assertEqual(summary, {"disabled": True})

    def test_model_id_kill_switch(self):
        self.config["signals"] = {"model_ids": False}
        origin, clone_dir, state = self.make_slot(
            62, {"miner.py": "x = 1\n"})
        sig.run_pass(self.conn, self.config, price_fetcher=lambda: None)
        self.advance(62, origin, clone_dir, "miner.py",
                     'MODEL = "gpt-4o-mini"\n', state["local_sha"])
        summary = sig.run_pass(self.conn, self.config,
                               price_fetcher=lambda: None)
        self.assertEqual(summary["extract"]["ranges"], 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_adoptions WHERE kind='model-id'"
        ).fetchone()[0], 0)

    def test_reconcile_isolates_signals_failure(self):
        original = fleet._fleet_signals().run_pass

        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        fleet._fleet_signals().run_pass = broken
        try:
            identity = {"status": "ok", "freshness_status": "fresh",
                        "values": {"subnets": [], "complete": True}}
            summary = fleet.reconcile(self.conn, identity,
                                      {"clone_root": self.clone_root,
                                       "dashboard": self.config["dashboard"]})
        finally:
            fleet._fleet_signals().run_pass = original
        self.assertIn("error", summary["signals"])
        self.assertTrue(summary["fetch_ok"])  # the pass itself stayed healthy
        audit_row = self.conn.execute(
            "SELECT COUNT(*) FROM audit WHERE action='signals-failed'"
        ).fetchone()[0]
        self.assertEqual(audit_row, 1)

    def test_reconcile_runs_signals_inline(self):
        identity = {"status": "ok", "freshness_status": "fresh",
                    "values": {"subnets": [], "complete": True}}
        summary = fleet.reconcile(self.conn, identity,
                                  {"clone_root": self.clone_root,
                                   "signals": {},
                                   "dashboard": self.config["dashboard"]})
        self.assertIn("extract", summary["signals"])


# ---------------------------------------------------------------------------
# Econ-alert intelligence gate (change: econ-alert-intelligence-gate)
# ---------------------------------------------------------------------------

def _stub_judge(significance="high", direction="emissions_up", evidence="e",
                counter=None):
    def judge(diff_text, files, context):
        if counter is not None:
            counter.append((files, context))
        status = "ok" if significance != sig.ejudge.UNJUDGED else "unjudged"
        return {"status": status, "significance": significance,
                "direction": direction, "what_changed": "raised weight cap",
                "why_it_matters": "shifts emissions", "evidence": evidence}
    return judge


class TestEconGate(SignalsBase):
    def _gate_config(self, **judge_over):
        judge = {"enabled": True, "claude_path": "claude", "max_calls_per_run": 20,
                 "max_calls_per_day": 200, "max_diff_bytes": 20000,
                 "high_stakes_paths": ["mechanism", "set_weights", "emission"]}
        judge.update(judge_over)
        cfg = dict(self.config)
        cfg["signals"] = dict(cfg.get("signals") or {}, judge=judge)
        return cfg

    def _instant_econ(self):
        return self.conn.execute(
            "SELECT payload_json FROM signal_events WHERE class='econ-code' "
            "AND tier='instant' ORDER BY id").fetchall()

    def test_event_from_a_pass_enters_at_that_pass_vector(self):
        # Change signal-statistics-ties: an entry takes the first vector at
        # or after its event. A pass must stamp its events and its vector
        # with one clock, or every new event misses its own pass's vector.
        origin, clone_dir, state = self.make_slot(
            65, {"validator/reward.py": "W = 0.1\n"})
        config = self._gate_config()
        sig.run_pass(self.conn, config, price_fetcher=lambda: None)
        self.advance(65, origin, clone_dir, "validator/reward.py",
                     "W = 0.25\n", state["local_sha"])
        sig.run_pass(self.conn, config, judge=_stub_judge("high"),
                     price_fetcher=lambda: snap({65: 0.02, 1: 1.0}))
        created, status, entry_ts = self.conn.execute(
            "SELECT created_at, status, entry_ts FROM signal_entries "
            "WHERE netuid = 65").fetchone()
        vector_ts = self.conn.execute(
            "SELECT MAX(ts) FROM signal_prices").fetchone()[0]
        self.assertEqual(status, "recorded")
        self.assertEqual(entry_ts, vector_ts)
        self.assertEqual(created, vector_ts)

    def test_material_change_pages_with_verdict(self):
        origin, clone_dir, state = self.make_slot(
            60, {"validator/reward.py": "W = 0.1\n"})
        self.advance(60, origin, clone_dir, "validator/reward.py",
                     "W = 0.25\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(),
                        judge=_stub_judge("high"))
        rows = self._instant_econ()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload["significance"], "high")
        self.assertEqual(payload["what_changed"], "raised weight cap")
        outcome = self.conn.execute(
            "SELECT outcome FROM signal_econ_verdicts").fetchone()[0]
        self.assertEqual(outcome, "instant")

    def test_cosmetic_change_dropped_but_recorded(self):
        origin, clone_dir, state = self.make_slot(
            61, {"validator/reward.py": "W = 0.1\n"})
        self.advance(61, origin, clone_dir, "validator/reward.py",
                     "W = 0.1  # tidy\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(),
                        judge=_stub_judge("none", evidence=""))
        self.assertEqual(len(self._instant_econ()), 0)
        digests = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE class='signal-digest'"
        ).fetchone()[0]
        self.assertEqual(digests, 0)
        row = self.conn.execute(
            "SELECT outcome, significance FROM signal_econ_verdicts"
        ).fetchone()
        self.assertEqual(tuple(row), ("drop", "none"))

    def test_high_stakes_none_floors_to_digest(self):
        origin, clone_dir, state = self.make_slot(
            62, {"core/mechanism.rs": "fn w() {}\n"})
        self.advance(62, origin, clone_dir, "core/mechanism.rs",
                     "fn w() { /* x */ }\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(),
                        judge=_stub_judge("none", evidence=""))
        self.assertEqual(len(self._instant_econ()), 0)
        digest = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE dedup_key LIKE "
            "'econ-digest:%'").fetchone()[0]
        self.assertEqual(digest, 1)
        outcome = self.conn.execute(
            "SELECT outcome FROM signal_econ_verdicts").fetchone()[0]
        self.assertEqual(outcome, "digest")

    def test_high_breaks_cooldown(self):
        origin, clone_dir, state = self.make_slot(
            63, {"validator/reward.py": "W = 0.1\n"})
        _r, sha = self.advance(63, origin, clone_dir, "validator/reward.py",
                               "W = 0.2\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("high"))
        self.advance(63, origin, clone_dir, "validator/reward.py",
                     "W = 0.3\n", sha)
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("high"))
        self.assertEqual(len(self._instant_econ()), 2)

    def test_med_respects_cooldown(self):
        origin, clone_dir, state = self.make_slot(
            64, {"validator/reward.py": "W = 0.1\n"})
        _r, sha = self.advance(64, origin, clone_dir, "validator/reward.py",
                               "W = 0.2\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("high"))
        self.advance(64, origin, clone_dir, "validator/reward.py",
                     "W = 0.3\n", sha)
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("med"))
        self.assertEqual(len(self._instant_econ()), 1)
        cooldown = self.conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE dedup_key LIKE "
            "'econ-cooldown:%'").fetchone()[0]
        self.assertEqual(cooldown, 1)

    def test_cache_hit_skips_the_judge(self):
        origin, clone_dir, state = self.make_slot(
            65, {"validator/reward.py": "W = 0.1\n"})
        self.advance(65, origin, clone_dir, "validator/reward.py",
                     "W = 0.2\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("high"))
        # reprocess the same range: content hash hits the cache
        sig.state_set(self.conn, "range_watermark", "0")
        self.conn.commit()
        calls = []
        sig.run_extract(self.conn, self._gate_config(),
                        judge=_stub_judge("high", counter=calls))
        self.assertEqual(calls, [])
        verdicts = self.conn.execute(
            "SELECT COUNT(*) FROM signal_econ_verdicts").fetchone()[0]
        self.assertEqual(verdicts, 1)  # idempotent — one row

    def test_budget_exhaustion_ships_unjudged(self):
        origin, clone_dir, state = self.make_slot(
            66, {"validator/reward.py": "W = 0.1\n"})
        self.advance(66, origin, clone_dir, "validator/reward.py",
                     "W = 0.2\n", state["local_sha"])
        calls = []
        sig.run_extract(self.conn, self._gate_config(max_calls_per_run=0),
                        judge=_stub_judge("high", counter=calls))
        self.assertEqual(calls, [])  # judge never called
        rows = self._instant_econ()
        self.assertEqual(len(rows), 1)
        self.assertTrue(json.loads(rows[0][0])["unjudged"])

    def test_gate_off_keeps_legacy_behaviour(self):
        origin, clone_dir, state = self.make_slot(
            67, {"validator/reward.py": "W = 0.1\n"})
        self.advance(67, origin, clone_dir, "validator/reward.py",
                     "W = 0.2\n", state["local_sha"])
        sig.run_extract(self.conn, self.config)  # no judge, gate off
        rows = self._instant_econ()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("significance", json.loads(rows[0][0]))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_econ_verdicts").fetchone()[0], 0)

    def test_status_surfaces_gate_counters(self):
        origin, clone_dir, state = self.make_slot(
            68, {"validator/reward.py": "W = 0.1\n"})
        self.advance(68, origin, clone_dir, "validator/reward.py",
                     "W = 0.25\n", state["local_sha"])
        sig.run_extract(self.conn, self._gate_config(), judge=_stub_judge("high"))
        status = sig.signals_status(self.conn)
        self.assertIn("econ_gate", status)
        self.assertEqual(status["econ_gate"]["verdicts"].get("instant"), 1)
        self.assertGreaterEqual(status["econ_gate"]["calls_today"], 1)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Generalized ledger: source triple, external entry, tiers, readability
# (change: rotation-signal-gate)
# ---------------------------------------------------------------------------

class TestLedgerSourceTriple(SignalsBase):
    def _fleet_event(self, netuid=50, event_class="econ-code", dedup="e:1"):
        cursor = self.conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) "
            "VALUES (?, 'instant', ?, NULL, ?, '{}', ?)",
            (event_class, netuid, dedup, _iso()))
        self.conn.commit()
        return cursor.lastrowid

    def _livedata_db(self, gate_rows=(), rotation_rows=()):
        path = os.path.join(self.tmp, "livedata.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE gate_events (
                id INTEGER PRIMARY KEY, netuid INTEGER, observed_at TEXT,
                eligibility TEXT);
            CREATE TABLE rotation_events (
                id INTEGER PRIMARY KEY, netuid INTEGER, observed_at TEXT);
        """)
        conn.executemany(
            "INSERT INTO gate_events (id, netuid, observed_at, eligibility) "
            "VALUES (?, ?, ?, ?)", gate_rows)
        conn.executemany(
            "INSERT INTO rotation_events (id, netuid, observed_at) "
            "VALUES (?, ?, ?)", rotation_rows)
        conn.commit()
        conn.close()
        return path

    def test_migration_backfills_class_and_created_at(self):
        # Rebuild the pre-change shape, insert a row, then migrate.
        self.conn.executescript("""
            DROP TABLE signal_entries;
            DROP TABLE signal_outcomes;
            CREATE TABLE signal_entries (
                event_id INTEGER NOT NULL, netuid INTEGER NOT NULL,
                price_tao REAL, as_of TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (event_id, netuid));
            CREATE TABLE signal_outcomes (
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL,
                netuid INTEGER NOT NULL, horizon_days INTEGER NOT NULL,
                due_at TEXT NOT NULL, exit_price_tao REAL, return_pct REAL,
                baseline_return_pct REAL,
                status TEXT NOT NULL DEFAULT 'pending', filled_at TEXT,
                UNIQUE (event_id, netuid, horizon_days));
        """)
        event_id = self._fleet_event(netuid=7, event_class="watchlist")
        self.conn.execute(
            "INSERT INTO signal_entries (event_id, netuid, status) "
            "VALUES (?, 7, 'recorded')", (event_id,))
        self.conn.execute(
            "INSERT INTO signal_outcomes (event_id, netuid, horizon_days, "
            "due_at, status) VALUES (?, 7, 7, ?, 'pending')",
            (event_id, _iso()))
        self.conn.commit()
        sig.ensure_schema(self.conn)
        store, klass, created = self.conn.execute(
            "SELECT source_store, source_class, created_at "
            "FROM signal_entries").fetchone()
        self.assertEqual(store, "fleet")
        self.assertEqual(klass, "watchlist")
        self.assertIsNotNone(created)
        self.assertEqual(self.conn.execute(
            "SELECT source_class FROM signal_outcomes").fetchone()[0],
            "watchlist")
        # idempotent: a second call leaves the migrated shape alone
        sig.ensure_schema(self.conn)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 1)

    def test_external_entry_is_idempotent(self):
        for _ in range(3):
            sig.enter_measured_event(self.conn, CFG, sig.SOURCE_LIVEDATA,
                                     11, 42, "gate-crossing", _iso())
        self.conn.commit()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_outcomes").fetchone()[0],
            len(CFG["outcome_horizons_days"]))

    def test_same_row_id_in_two_stores_does_not_collide(self):
        event_id = self._fleet_event(netuid=50)
        sig.run_measurement(self.conn, self.config,
                            price_fetcher=lambda: snap({50: 0.01}))
        sig.enter_measured_event(self.conn, CFG, sig.SOURCE_LIVEDATA,
                                 event_id, 50, "gate-crossing", _iso())
        self.conn.commit()
        stores = sorted(row[0] for row in self.conn.execute(
            "SELECT source_store FROM signal_entries WHERE event_id = ?",
            (event_id,)))
        self.assertEqual(stores, ["fleet", "livedata"])

    def test_first_ingest_seeds_silently(self):
        path = self._livedata_db(
            gate_rows=[(1, 10, _iso(), "eligible")],
            rotation_rows=[(1, 20, _iso())])
        entered = sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        self.assertEqual(entered, {})
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 0)
        self.assertEqual(sig.state_get(self.conn, "ingest:gate-crossing"), "1")

    def test_ingest_enters_eligible_crossings_only(self):
        path = self._livedata_db()
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)  # seed
        conn = sqlite3.connect(path)
        conn.executemany(
            "INSERT INTO gate_events (id, netuid, observed_at, eligibility) "
            "VALUES (?, ?, ?, ?)",
            [(1, 10, _iso(), "eligible"), (2, 11, _iso(), "reversed")])
        conn.execute("INSERT INTO rotation_events (id, netuid, observed_at) "
                     "VALUES (1, 20, ?)", (_iso(),))
        conn.commit()
        conn.close()
        entered = sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        self.assertEqual(entered.get("gate-crossing"), 1)
        # Spec 469 retired root-rotation (change: root-weight-drift): its
        # stored rows stay in livedata but are no longer ingested.
        self.assertNotIn("root-rotation", entered)
        rows = sorted(self.conn.execute(
            "SELECT source_class, netuid FROM signal_entries"))
        self.assertEqual(rows, [("gate-crossing", 10)])

    def test_pending_crossing_holds_the_ingest_mark(self):
        path = self._livedata_db()
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)  # seed
        conn = sqlite3.connect(path)
        conn.executemany(
            "INSERT INTO gate_events (id, netuid, observed_at, eligibility) "
            "VALUES (?, ?, ?, ?)",
            [(1, 10, _iso(), "pending"), (2, 11, _iso(), "eligible")])
        conn.commit()
        conn.close()
        entered = sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        # the eligible one is measured at once (waiting would only push its
        # entry price further from its event), but the mark stops before the
        # pending row so that row is still reconsidered
        self.assertEqual(entered.get("gate-crossing"), 1)
        self.assertEqual(sig.state_get(self.conn, "ingest:gate-crossing"), "0")
        # once the pending one settles it is entered too, and the mark moves
        conn = sqlite3.connect(path)
        conn.execute("UPDATE gate_events SET eligibility = 'eligible' "
                     "WHERE id = 1")
        conn.commit()
        conn.close()
        entered = sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        self.assertEqual(entered.get("gate-crossing"), 1)
        self.assertEqual(sig.state_get(self.conn, "ingest:gate-crossing"), "2")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 2)

    def test_historical_events_are_never_backfilled(self):
        old = _iso(days_ago=40)
        path = self._livedata_db(gate_rows=[(1, 10, old, "eligible"),
                                            (2, 11, old, "eligible")])
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_outcomes").fetchone()[0], 0)

    def test_ingest_is_fail_soft_on_missing_store(self):
        entered = sig.ingest_livedata_events(
            self.conn, CFG, db_path=os.path.join(self.tmp, "absent.db"))
        self.assertEqual(entered, {})
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 0)

    def test_ingest_rerun_does_not_duplicate(self):
        path = self._livedata_db()
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)  # seed
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO gate_events (id, netuid, observed_at, "
                     "eligibility) VALUES (1, 10, ?, 'eligible')", (_iso(),))
        conn.commit()
        conn.close()
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        second = sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        self.assertEqual(second, {})
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_entries").fetchone()[0], 1)

    def test_briefing_tier_class_is_still_measured(self):
        # A demoted class keeps filling: measurement never reads the tier.
        self._fleet_event(netuid=50, event_class="econ-code")
        sig.run_measurement(self.conn, self.config,
                            price_fetcher=lambda: snap({50: 0.01}))
        self.assertEqual(self.conn.execute(
            "SELECT status FROM signal_entries").fetchone()[0], "recorded")

    def test_report_names_tier_and_marks_unreadable(self):
        sig.enter_measured_event(self.conn, CFG, sig.SOURCE_LIVEDATA,
                                 1, 10, "gate-crossing", _iso())
        self.conn.execute(
            "UPDATE signal_outcomes SET status = 'recorded', "
            "return_pct = 5.0, baseline_return_pct = 1.0 "
            "WHERE horizon_days = 1")
        self.conn.commit()
        report = sig.effectiveness(self.conn, self.config)["report"]
        by_horizon = {row["horizon_days"]: row for row in report
                      if row["class"] == "gate-crossing"}
        self.assertTrue(by_horizon[1]["readable"])
        self.assertFalse(by_horizon[7]["readable"])
        self.assertFalse(by_horizon[7]["meets_promotion_sample"])
        self.assertIn("tier", by_horizon[1])

    def test_report_covers_external_classes(self):
        sig.enter_measured_event(self.conn, CFG, sig.SOURCE_LIVEDATA,
                                 1, 10, "gate-crossing", _iso())
        self.conn.commit()
        classes = {row["class"] for row
                   in sig.effectiveness(self.conn, self.config)["report"]}
        self.assertIn("gate-crossing", classes)


class TestRegistrationKeyedLedger(SignalsBase):
    """Change signal-statistics-ties: vectors carry occupant keys, a
    snapshot without them is refused, and gate crossings anchor at
    eligibility."""

    T0 = datetime.datetime(2026, 9, 9, 16, 0, tzinfo=datetime.timezone.utc)

    def _event(self, netuid=50):
        cursor = self.conn.execute(
            "INSERT INTO signal_events (class, tier, netuid, term, "
            "dedup_key, payload_json, created_at) VALUES ('econ-code', "
            "'instant', ?, NULL, 'e:1', '{}', ?)",
            (netuid, self.T0.isoformat()))
        self.conn.commit()
        return cursor.lastrowid

    def test_snapshot_without_registration_is_not_stored(self):
        self._event()
        summary = sig.run_measurement(
            self.conn, self.config, now=self.T0.isoformat(),
            price_fetcher=lambda: {"prices": {50: 0.01, 51: 1.0},
                                   "registered": {50: 1}})
        self.assertTrue(summary.get("fetch_failed"))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM signal_prices").fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM signal_entries").fetchone()[0], "pending")

    def test_plain_price_dict_is_refused(self):
        self.assertIsNone(sig._normalize_snapshot({50: 0.01}))

    def test_default_fetcher_fails_when_registration_read_fails(self):
        import types
        fake = types.SimpleNamespace(
            load_config=lambda: {"db": "x"}, load_env=lambda: {},
            resolve=lambda p: os.path.join(self.tmp, "live.db"),
            open_store=lambda p: sqlite3.connect(p),
            QuotaLedger=lambda conn, cfg: None,
            run_operation=lambda *a, **k: {
                "status": "ok",
                "values": {"subnets": [{"netuid": 50,
                                        "alpha_price_tao": 0.01}]}},
            read_registration_blocks=lambda cfg, connection=None: {
                "ok": False, "error": "rpc down"})
        saved = sys.modules.get("atlas_live")
        sys.modules["atlas_live"] = fake
        try:
            self.assertIsNone(sig.default_price_fetcher())
            fake.read_registration_blocks = lambda cfg, connection=None: {
                "ok": True, "values": {50: 9155260}, "default_block": 0,
                "block_number": 9423800}
            got = sig.default_price_fetcher()
        finally:
            if saved is None:
                sys.modules.pop("atlas_live", None)
            else:
                sys.modules["atlas_live"] = saved
        self.assertEqual(got, {"prices": {50: 0.01},
                               "registered": {50: 9155260},
                               "block_number": 9423800})

    def test_vector_stores_registration_and_block(self):
        self._event()
        sig.run_measurement(
            self.conn, self.config, now=self.T0.isoformat(),
            price_fetcher=lambda: snap({50: 0.01}, {50: 77}, block=9000))
        self.assertEqual(self.conn.execute(
            "SELECT reg_block FROM signal_prices").fetchone()[0], 77)
        self.assertEqual(self.conn.execute(
            "SELECT block_number FROM signal_vectors").fetchone()[0], 9000)

    def _livedata(self, rows):
        path = os.path.join(self.tmp, "livedata.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE gate_events (id INTEGER PRIMARY KEY, netuid "
            "INTEGER, observed_at TEXT, eligibility TEXT, eligibility_at "
            "TEXT)")
        conn.executemany("INSERT INTO gate_events VALUES (?, ?, ?, ?, ?)",
                         rows)
        conn.commit()
        conn.close()
        return path

    def test_gate_crossing_anchors_at_eligibility(self):
        # Regression (audit C13): every gate-crossing 1-day outcome on the
        # Pi read 0.000%, because entry filled at eligibility (about 48 h
        # after the crossing) while the 1-day horizon fell due from the
        # crossing, so entry and exit were the same vector.
        crossed = self.T0
        eligible = crossed + datetime.timedelta(hours=48)
        path = self._livedata([])
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)  # seed
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO gate_events VALUES (1, 34, ?, "
                     "'eligible', ?)", (crossed.isoformat(),
                                        eligible.isoformat()))
        conn.commit()
        conn.close()
        sig.ingest_livedata_events(self.conn, CFG, db_path=path)
        self.conn.commit()
        created, anchor, due = self.conn.execute(
            "SELECT en.created_at, en.anchor_at, o.due_at FROM "
            "signal_entries en JOIN signal_outcomes o USING (source_store, "
            "event_id, netuid) WHERE o.horizon_days = 1").fetchone()
        self.assertEqual(created, crossed.isoformat())
        self.assertEqual(anchor, eligible.isoformat())
        self.assertEqual(due, (eligible + datetime.timedelta(days=1))
                         .isoformat())
        # Entry at eligibility, exit one real day later: a real return.
        for when, price in ((eligible + datetime.timedelta(hours=1), 1.0),
                            (eligible + datetime.timedelta(days=1, hours=2),
                             0.9)):
            sig.run_measurement(self.conn, self.config,
                                now=when.isoformat(),
                                price_fetcher=lambda p=price: snap({34: p}))
        entry_ts, exit_ts, ret = self.conn.execute(
            "SELECT v2_entry_ts, v2_exit_ts, v2_return_pct FROM "
            "signal_outcomes WHERE horizon_days = 1").fetchone()
        self.assertNotEqual(entry_ts, exit_ts)
        self.assertAlmostEqual(ret, -10.0, places=6)


class TestRegistrationMigration(unittest.TestCase):
    def test_pre_change_store_migrates_and_keeps_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE signal_prices (ts TEXT NOT NULL, netuid INTEGER
                NOT NULL, price_tao REAL, PRIMARY KEY (ts, netuid));
            CREATE TABLE signal_entries (source_store TEXT NOT NULL DEFAULT
                'fleet', event_id INTEGER NOT NULL, netuid INTEGER NOT NULL,
                source_class TEXT, created_at TEXT, price_tao REAL,
                as_of TEXT, status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (source_store, event_id, netuid));
            CREATE TABLE signal_outcomes (id INTEGER PRIMARY KEY,
                source_store TEXT NOT NULL DEFAULT 'fleet', event_id INTEGER
                NOT NULL, netuid INTEGER NOT NULL, source_class TEXT,
                horizon_days INTEGER NOT NULL, due_at TEXT NOT NULL,
                exit_price_tao REAL, return_pct REAL, baseline_return_pct
                REAL, status TEXT NOT NULL DEFAULT 'pending', filled_at TEXT,
                UNIQUE (source_store, event_id, netuid, horizon_days));
            INSERT INTO signal_prices VALUES ('2026-09-17T12:00:00+00:00',
                82, 0.001);
            INSERT INTO signal_entries VALUES ('livedata', 68, 82,
                'root-rotation', '2026-09-17T12:04:17+00:00', 0.001,
                '2026-09-17T12:29:47+00:00', 'recorded');
            INSERT INTO signal_outcomes VALUES (1, 'livedata', 68, 82,
                'root-rotation', 30, '2026-10-17T12:04:17+00:00', 0.0263,
                2533.185, -9.324, 'recorded', '2026-10-17T17:28:21+00:00');
        """)
        sig.ensure_schema(conn)
        sig.ensure_schema(conn)
        self.assertEqual(conn.execute(
            "SELECT return_pct, baseline_return_pct, status, v2_status "
            "FROM signal_outcomes").fetchone(),
            (2533.185, -9.324, "recorded", None))
        self.assertEqual(conn.execute(
            "SELECT price_tao, reg_block FROM signal_prices").fetchone(),
            (0.001, None))
        self.assertEqual(conn.execute(
            "SELECT status, anchor_at FROM signal_entries").fetchone(),
            ("recorded", None))
        conn.close()


class TestRescore(SignalsBase):
    """`rescore` (change: signal-statistics-ties) writes v2 columns only,
    re-anchors gate crossings, and is idempotent."""

    T0 = datetime.datetime(2026, 9, 9, 16, 0, tzinfo=datetime.timezone.utc)

    def _vector(self, when, prices, reg=None):
        self.conn.executemany(
            "INSERT INTO signal_prices (ts, netuid, price_tao, reg_block) "
            "VALUES (?, ?, ?, ?)",
            [(when.isoformat(), n, p, (reg or {}).get(n))
             for n, p in prices.items()])

    def _livedata(self, rows):
        path = os.path.join(self.tmp, "livedata.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE gate_events (id INTEGER PRIMARY KEY, netuid "
            "INTEGER, observed_at TEXT, eligibility TEXT, eligibility_at "
            "TEXT)")
        conn.executemany("INSERT INTO gate_events VALUES (?, ?, ?, ?, ?)",
                         rows)
        conn.commit()
        conn.close()
        return path

    def _old_gate_row(self):
        """A gate crossing as the old code left it: entry filled 48 h late
        at eligibility, 7-day horizon due from the crossing and filled 5
        days after entry, 1-day horizon filled at 0.000%."""
        crossed = self.T0
        eligible = crossed + datetime.timedelta(hours=48)
        sig.enter_measured_event(self.conn, CFG, sig.SOURCE_LIVEDATA, 1, 34,
                                 "gate-crossing", crossed.isoformat())
        self.conn.execute(
            "UPDATE signal_entries SET price_tao = 1.0, as_of = ?, "
            "status = 'late'", ((eligible + datetime.timedelta(hours=1))
                                .isoformat(),))
        self.conn.execute(
            "UPDATE signal_outcomes SET status = 'late', return_pct = 0.0, "
            "baseline_return_pct = 0.0 WHERE horizon_days = 1")
        self.conn.execute(
            "UPDATE signal_outcomes SET status = 'recorded', "
            "return_pct = -4.0, baseline_return_pct = -1.0 "
            "WHERE horizon_days = 7")
        self.conn.commit()
        return crossed, eligible

    def test_rescore_recomputes_from_eligibility_and_keeps_originals(self):
        crossed, eligible = self._old_gate_row()
        # Legacy vectors (no occupant key), as stored before this change.
        self._vector(eligible + datetime.timedelta(hours=1),
                     {34: 1.0, 51: 1.0})
        self._vector(eligible + datetime.timedelta(days=1, hours=2),
                     {34: 0.95, 51: 1.0})
        self._vector(eligible + datetime.timedelta(days=7, hours=3),
                     {34: 0.8, 51: 1.1})
        self.conn.commit()
        path = self._livedata([(1, 34, crossed.isoformat(), "eligible",
                                eligible.isoformat())])
        now = (crossed + datetime.timedelta(days=40)).isoformat()
        out = sig.rescore(self.conn, self.config, now=now,
                          registered_now={34: 0, 51: 0}, livedata_path=path,
                          anchors=[])
        self.assertEqual(out["reanchored_gate_entries"], 1)
        rows = {h: r for h, *r in self.conn.execute(
            "SELECT horizon_days, return_pct, status, v2_status, v2_reason, "
            "v2_return_pct FROM signal_outcomes ORDER BY horizon_days")}
        # Originals untouched.
        self.assertEqual(rows[1][:2], [0.0, "late"])
        self.assertEqual(rows[7][:2], [-4.0, "recorded"])
        # 1 day is a real day now; 7 days a real week.
        self.assertEqual(rows[1][2], "recorded")
        self.assertAlmostEqual(rows[1][4], -5.0, places=6)
        self.assertEqual(rows[7][2], "recorded")
        self.assertAlmostEqual(rows[7][4], -20.0, places=6)
        # 30 days: no vector near its due time.
        self.assertEqual(rows[30][1:4], ["pending", None, None])

    def test_stretched_window_without_vector_is_unavailable(self):
        crossed, eligible = self._old_gate_row()
        self._vector(eligible + datetime.timedelta(hours=1), {34: 1.0})
        self.conn.commit()
        path = self._livedata([(1, 34, crossed.isoformat(), "eligible",
                                eligible.isoformat())])
        sig.rescore(self.conn, self.config,
                    now=(crossed + datetime.timedelta(days=40)).isoformat(),
                    registered_now={34: 0}, livedata_path=path, anchors=[])
        v2, reason = self.conn.execute(
            "SELECT v2_status, v2_reason FROM signal_outcomes WHERE "
            "horizon_days = 7").fetchone()
        self.assertEqual((v2, reason), ("unavailable", "no-vector"))

    def test_window_wholly_before_a_later_registration_is_unverified(self):
        crossed, eligible = self._old_gate_row()
        start = eligible + datetime.timedelta(hours=1)
        self._vector(start, {34: 1.0})
        self._vector(eligible + datetime.timedelta(days=1, hours=2),
                     {34: 0.5})
        self.conn.commit()
        path = self._livedata([(1, 34, crossed.isoformat(), "eligible",
                                eligible.isoformat())])
        # SN34's current registration is 30 days after the window.
        anchors = [(5000, start),
                   (5000 + 7200 * 60, start + datetime.timedelta(days=60))]
        sig.rescore(self.conn, self.config,
                    now=(crossed + datetime.timedelta(days=40)).isoformat(),
                    registered_now={34: 5000 + 7200 * 30},
                    livedata_path=path, anchors=anchors)
        v2, reason = self.conn.execute(
            "SELECT v2_status, v2_reason FROM signal_outcomes WHERE "
            "horizon_days = 1").fetchone()
        self.assertEqual((v2, reason), ("unverified", "unverified"))

    def test_rescore_is_idempotent(self):
        crossed, eligible = self._old_gate_row()
        self._vector(eligible + datetime.timedelta(hours=1), {34: 1.0})
        self._vector(eligible + datetime.timedelta(days=1, hours=2),
                     {34: 0.9})
        self.conn.commit()
        path = self._livedata([(1, 34, crossed.isoformat(), "eligible",
                                eligible.isoformat())])
        kwargs = dict(now=(crossed + datetime.timedelta(days=40)).isoformat(),
                      registered_now={34: 0}, livedata_path=path, anchors=[])
        sig.rescore(self.conn, self.config, **kwargs)
        query = ("SELECT id, due_at, status, return_pct, v2_status, "
                 "v2_reason, v2_entry_ts, v2_exit_ts, v2_return_pct, "
                 "v2_baseline_pct, v2_excess_pct FROM signal_outcomes "
                 "ORDER BY id")
        first = self.conn.execute(query).fetchall()
        out = sig.rescore(self.conn, self.config, **kwargs)
        self.assertEqual(self.conn.execute(query).fetchall(), first)
        self.assertEqual(out["reanchored_gate_entries"], 0)

    def test_rescore_fails_without_registration_map(self):
        def broken(_config):
            raise RuntimeError("registration read failed: rpc down")
        saved = sig._registration_now
        sig._registration_now = broken
        try:
            with self.assertRaises(RuntimeError):
                sig.rescore(self.conn, self.config)
        finally:
            sig._registration_now = saved


class TestLivePassReanchors(TestRescore):
    def test_live_pass_reanchors_before_scoring(self):
        # Without this, the first pass after deploy scored old gate rows
        # from the crossing time before `rescore` ran.
        crossed, eligible = self._old_gate_row()
        self._vector(eligible + datetime.timedelta(hours=1), {34: 1.0},
                     {34: 0})
        self._vector(eligible + datetime.timedelta(days=1, hours=2),
                     {34: 0.95}, {34: 0})
        self.conn.commit()
        path = self._livedata([(1, 34, crossed.isoformat(), "eligible",
                                eligible.isoformat())])
        saved = sig._livedata_db_path
        sig._livedata_db_path = lambda: path
        try:
            sig.state_set(self.conn, "ingest:gate-crossing", "1")
            out = sig.run_measurement(
                self.conn, self.config,
                now=(crossed + datetime.timedelta(days=40)).isoformat(),
                price_fetcher=lambda: None, anchors=[])
        finally:
            sig._livedata_db_path = saved
        self.assertEqual(out.get("reanchored"), 1)
        ret = self.conn.execute(
            "SELECT v2_return_pct FROM signal_outcomes WHERE "
            "horizon_days = 1").fetchone()[0]
        self.assertAlmostEqual(ret, -5.0, places=6)
