"""Pre-activation retrieval check (change: kb-battery-honesty).

Every grounded battery exchange must be answerable from the top 5 search
results over the repo corpus. The upgrade job runs every suite before its
ingest and push, so a corpus edit that drops a battery fact blocks there."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest

from _helpers import CORPUS_DIR, akb, kbb

import atlas_kb_server as srv

TOP_K = 5


def ingest_and_activate(tmp, corpus_dir=CORPUS_DIR):
    db = os.path.join(tmp, "kb.db")
    with contextlib.redirect_stdout(io.StringIO()):
        run_id, _ = akb.ingest(db, tmp, corpus_dir,
                               os.path.join(corpus_dir, "hashes.json"))
        akb.activate(db, run_id, actor="test")
    return db


def retrieval_misses(db):
    store = srv.KnowledgeStore(db)
    misses = []
    for exchange in kbb.battery():
        if exchange["set"] not in kbb.GROUNDED_SETS:
            continue
        result = store.search(str(exchange["search_query"]), TOP_K)
        text = "\n".join(unit["heading_path"] + " " + unit["content"]
                         for unit in result.get("results", []))
        for group in exchange["expected"]:  # type: ignore[union-attr]
            if not kbb.markers_match([group], text):
                misses.append("%s %r" % (exchange["tag"], group))
    return misses


def corpus_copy(tmp, edit):
    """A corpus copy with `edit(name, text) -> text` applied and hashes
    regenerated, so ingest accepts it."""
    target = os.path.join(tmp, "corpus")
    shutil.copytree(CORPUS_DIR, target)
    with open(os.path.join(target, "hashes.json"), encoding="utf-8") as h:
        manifest = json.load(h)
    for name in manifest["files"]:
        path = os.path.join(target, name)
        with open(path, encoding="utf-8") as handle:
            text = edit(name, handle.read())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        manifest["files"][name] = hashlib.sha256(
            text.encode("utf-8").replace(b"\r\n", b"\n")).hexdigest()
    with open(os.path.join(target, "hashes.json"), "w",
              encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return target


class BatteryRetrievalTests(unittest.TestCase):
    def test_every_grounded_exchange_is_retrievable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(retrieval_misses(ingest_and_activate(tmp)), [])

    def test_removing_a_battery_fact_fails(self):
        # KB-EX-15 expects the live maturity half-life; drop every line
        # that states it
        def drop(name, text):
            return "\n".join(line for line in text.splitlines()
                             if "MaturityRate" not in line) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            db = ingest_and_activate(tmp, corpus_copy(tmp, drop))
            misses = retrieval_misses(db)
        self.assertTrue(any(miss.startswith("KB-EX-15") for miss in misses),
                        misses)


if __name__ == "__main__":
    unittest.main()
