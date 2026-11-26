"""Tests for the chain grounding job (change: chain-grounding). No test
reaches the network or runs a model."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GROUNDING_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(GROUNDING_DIR)
sys.path.insert(0, GROUNDING_DIR)

import atlas_grounding as ag  # noqa: E402
import grounding_scope  # noqa: E402
import history  # noqa: E402
import ledger  # noqa: E402
import render  # noqa: E402
import snapshot  # noqa: E402
import verify  # noqa: E402
import yamlsub  # noqa: E402

CONFIG = ag.load_config()


def claim(cid: str, **fields) -> dict:
    section = cid.rsplit("-", 1)[0]
    base = {"id": cid, "section": section, "statement": "A statement.",
            "evidence": [{"path": "pallets/subtensor/src/lib.rs",
                          "lines": "1-2", "ref": "v497", "commit": "c" * 40,
                          "pr": None}],
            "live_since_spec": 497, "status": "live",
            "last_verified": "2026-11-27T00:00:00Z",
            "watched_paths": ["pallets/subtensor/src/coinbase/"],
            "stale": False, "review": None}
    base.update(fields)
    return base


class YamlSubsetTest(unittest.TestCase):
    def test_round_trip(self):
        data = {"version": 1, "meta": {"a": None, "b": False, "n": -3,
                                       "s": 'quote " colon: x\nline',
                                       "empty": [], "map": {}},
                "claims": [{"id": "x", "ev": [{"p": "a", "q": 1}],
                            "w": ["a", "b"]}, {"id": "y", "ev": []}]}
        self.assertEqual(yamlsub.load(yamlsub.dump(data, "head")), data)

    def test_rejects_unknown_shapes(self):
        for text in ("a: b", "a:\n\tb: 1", "a: 1\na: 2", " a: 1",
                     "a: 1.5", "a: [1]"):
            with self.assertRaises(ValueError, msg=text):
                yamlsub.load(text)

    def test_rejects_unsupported_values(self):
        with self.assertRaises(ValueError):
            yamlsub.dump({"a": 1.5})
        with self.assertRaises(ValueError):
            yamlsub.dump({"bad key": 1})


class LedgerTest(unittest.TestCase):
    def data(self, *claims):
        data = ledger.empty()
        data["claims"] = list(claims)
        return data

    def test_validate_rejects_bad_ids_and_status(self):
        for bad in (claim("emission-001", section="yuma"),
                    claim("emission-001", status="maybe"),
                    claim("emission-1")):
            with self.assertRaises(ValueError):
                ledger.validate(self.data(bad))
        with self.assertRaises(ValueError):
            ledger.validate(self.data(claim("emission-001"),
                                      claim("emission-001")))

    def test_save_load_round_trip(self):
        data = self.data(claim("emission-001"), claim("yuma-002"))
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "claims.yaml")
        ledger.save(path, data)
        self.assertEqual(ledger.load(path), data)

    def test_mark_stale_by_watched_and_evidence_paths(self):
        data = self.data(
            claim("emission-001"),
            claim("yuma-001", watched_paths=["pallets/subtensor/src/epoch/*.rs"],
                  evidence=[{"path": "pallets/x.rs", "lines": "1-1",
                             "ref": "v497", "commit": "c"}]),
            claim("staking-001", watched_paths=[],
                  evidence=[{"path": "pallets/staking.rs", "lines": "1-1",
                             "ref": "v497", "commit": "c"}]),
            claim("safety-001", watched_paths=["pallets/other/"]))
        marked = ledger.mark_stale(data, [
            "pallets/subtensor/src/coinbase/run_coinbase.rs",
            "pallets/subtensor/src/epoch/run_epoch.rs",
            "pallets/staking.rs"])
        self.assertEqual(marked, ["emission-001", "yuma-001", "staking-001"])
        self.assertEqual(ledger.stale_sections(data),
                         ["emission", "yuma", "staking"])

    def test_route_items(self):
        routed = ledger.route_items(
            ["schedule_coldkey_swap", "SubnetOwnerCut", "add_stake",
             "Unknown"], CONFIG["section_keywords"])
        self.assertEqual(routed["safety"], ["schedule_coldkey_swap"])
        self.assertEqual(routed["emission"], ["SubnetOwnerCut"])
        self.assertEqual(routed["staking"], ["add_stake"])
        self.assertEqual(routed["hyperparameters"], ["Unknown"])

    def test_next_id(self):
        data = self.data(claim("emission-001"), claim("emission-007"))
        self.assertEqual(ledger.next_id(data, "emission"), "emission-008")
        self.assertEqual(ledger.next_id(data, "yuma"), "yuma-001")


class CitationCheckTest(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.src)
        os.makedirs(os.path.join(self.src, "pallets", "subtensor"))
        with open(os.path.join(self.src, "pallets", "subtensor", "lib.rs"),
                  "w") as handle:
            handle.write("pub fn DefaultTempo() -> u16 {\n    360\n}\n"
                         "pub const BURN: u64 = 1_000_000_000;\n"
                         "let cut = 0.18;\n")

    def check(self, statement, start=1, end=5, path="pallets/subtensor/"
              "lib.rs", **extra):
        proposal = dict(statement=statement, section=extra.pop(
            "section", "emission"), evidence=[
            {"path": path, "start": start, "end": end}], **extra)
        return verify.check_claim(proposal, self.src, 120, extra.pop(
            "pallets", None))[0]

    def test_numbers_must_be_in_cited_lines(self):
        self.assertEqual(self.check("`DefaultTempo` is 360 blocks."), [])
        self.assertEqual(self.check("The burn is 1,000,000,000 rao."), [])
        self.assertEqual(self.check("The cut is 0.18."), [])
        self.assertEqual(self.check("The cut is 18%."),
                         ["number 18 is not in the cited lines"])
        self.assertEqual(self.check("Tempo is 360.", 4, 5),
                         ["number 360 is not in the cited lines"])

    def test_spec_pr_and_dates_are_not_checked(self):
        self.assertEqual(self.check(
            "Since spec 488 (v488, #3201, 2026-11-05) tempo is 360."), [])

    def test_identifiers_must_be_in_cited_lines(self):
        self.assertEqual(self.check("`DefaultTempo` returns `u16`."), [])
        self.assertEqual(self.check("`run_coinbase` pays out."),
                         ["`run_coinbase` is not in the cited lines"])

    def test_bad_citations(self):
        self.assertTrue(self.check("x", 4, 99))
        self.assertTrue(self.check("x", 0, 1))
        self.assertTrue(self.check("x", path="../../etc/passwd"))
        self.assertTrue(self.check("x", path="/etc/passwd"))
        self.assertEqual(verify.check_claim({"statement": "x"}, self.src,
                                            120)[0], ["no citation"])

    def test_evidence_range_cap(self):
        problems, _ = verify.check_claim(
            {"statement": "x", "evidence": [
                {"path": "pallets/subtensor/lib.rs", "start": 1,
                 "end": 5}]}, self.src, 3)
        self.assertIn("over 3 lines", problems[0])

    def test_hyperparameter_default_against_metadata(self):
        pallets = {"SubtensorModule": {"storage": {
            "Tempo": {"default": 360}, "Kappa": {"default": 32767}}}}
        ok = verify.check_claim(
            {"statement": "`DefaultTempo` is 360.", "section":
             "hyperparameters", "item": "Tempo", "default": "360",
             "evidence": [{"path": "pallets/subtensor/lib.rs", "start": 1,
                           "end": 3}]}, self.src, 120, pallets)[0]
        self.assertEqual(ok, [])
        bad = verify.check_claim(
            {"statement": "`DefaultTempo` is 360.", "section":
             "hyperparameters", "item": "Kappa", "default": "360",
             "evidence": [{"path": "pallets/subtensor/lib.rs", "start": 1,
                           "end": 3}]}, self.src, 120, pallets)[0]
        self.assertIn("differs from the runtime metadata default", bad[0])


class ModelReplyTest(unittest.TestCase):
    def test_extract_json(self):
        self.assertEqual(verify.extract_json('x ```json\n{"a": 1}\n``` y'),
                         {"a": 1})
        self.assertEqual(verify.extract_json('noise {"a": {"b": 2}} end'),
                         {"a": {"b": 2}})
        with self.assertRaises(verify.ModelError):
            verify.extract_json("no json here")

    def test_missing_verdict_is_disagreement(self):
        verdicts = verify.parse_verdicts(
            {"verdicts": [{"key": "c0", "verdict": "agree", "reason": "ok"},
                          {"key": "c9", "verdict": "agree"}]}, ["c0", "c1"])
        self.assertEqual(verdicts["c0"][0], "agree")
        self.assertEqual(verdicts["c1"][0], "disagree")
        self.assertNotIn("c9", verdicts)

    def test_usage_limit_is_not_a_login_failure(self):
        self.assertEqual(verify.usage_limit(
            "You've hit your Fable limit \u00b7 resets Nov 28, 1pm "
            "(Pacific/Auckland). Switch to another model"),
            "Fable limit, resets Nov 28, 1pm")
        self.assertIsNone(verify.usage_limit("Invalid API key"))

    def test_worker_cannot_touch_unknown_ids(self):
        with self.assertRaises(verify.ModelError):
            verify.validate_worker({"claims": [
                {"id": "emission-099", "action": "keep", "statement": "x"}]},
                "emission", ["emission-001"])
        with self.assertRaises(verify.ModelError):
            verify.validate_worker({"claims": [
                {"id": None, "action": "invent", "statement": "x"}]},
                "emission", [])

    def test_critic_gets_no_tools(self):
        cmd = verify.critic_cmd("claude", ag.up.MODEL, "p")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--model") + 1], ag.up.MODEL)

    def test_worker_cannot_write_or_run(self):
        cmd = verify.worker_cmd("claude", ag.up.MODEL, "p", "/src",
                                "/corpus", 10)
        # --restricted ignores user settings, so the model is explicit.
        self.assertEqual(cmd[cmd.index("--model") + 1], ag.up.MODEL)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob")
        denied = cmd[cmd.index("--disallowedTools"):]
        for tool in ("Bash", "Edit", "Write", "WebFetch"):
            self.assertIn(tool, denied)


class RenderTest(unittest.TestCase):
    def data(self):
        data = ledger.empty()
        data["meta"].update(spec_version=497, subtensor_tag="v497",
                            subtensor_commit="c" * 40, newest_tag="v497",
                            newest_tag_live=True,
                            last_updated="2026-11-27T00:00:00Z",
                            content_changed="2026-11-27T00:00:00Z",
                            pending_on_main=["#1 org/x"],
                            changelog=["spec 497 live 2026-11-26 (from 495):"
                                       " 1 PRs: #3367"],
                            spec_dates=[{"spec": 490, "date": "2026-11-12"}])
        data["claims"] = [
            claim("emission-001", statement="Emission is X."),
            claim("emission-002", review={"reason": "critic: wrong",
                                          "proposed": "Emission is Y."}),
            claim("yuma-001", last_verified=None, review={
                "reason": "number 5 is not in the cited lines",
                "proposed": "Bonds are 5."}),
            claim("yuma-002", stale=True),
            claim("staking-001", status="deprecated",
                  deprecated_since_spec=490, statement="Old thing is gone.")]
        return data

    def test_front_matter_field_names(self):
        text = render.render(self.data(), CONFIG)
        head = text.split("---\n")[1]
        meta = yamlsub.load(head)
        self.assertEqual(list(meta), list(render.FRONT_KEYS))
        for key in ("spec_version", "subtensor_tag", "subtensor_commit",
                    "last_updated", "content_changed", "pending_on_main"):
            self.assertIn(key, meta)
        self.assertTrue(text.startswith("---\nspec_version: 497\n"))

    def test_claim_lines(self):
        text = render.render(self.data(), CONFIG)
        self.assertIn("- Emission is X. [v497 st/lib.rs:1-2]", text)
        self.assertIn("**UNVERIFIED (pending review)** (critic: wrong). last "
                      "verified 2026-11-27: A statement.", text)
        self.assertIn("never verified, proposed: Bonds are 5.", text)
        self.assertIn("(re-check queued)", text)
        traps = text.split("## 8.")[1]
        self.assertIn("Old thing is gone. (stopped applying at spec 490, "
                      "2026-11-12)", traps)
        self.assertNotIn("Old thing", text.split("## 8.")[0])
        self.assertIn("spec 497 live 2026-11-26", text.split("## 9.")[1])

    def test_ref_groups_tag_and_file(self):
        ev = lambda path, lines, tag="v497": {
            "path": path, "lines": lines, "ref": tag, "commit": "c"}
        c = claim("emission-001", evidence=[
            ev("pallets/subtensor/src/a.rs", "1-2"),
            ev("pallets/subtensor/src/a.rs", "9-10"),
            ev("runtime/src/lib.rs", "5-5"),
            ev("pallets/swap/src/b.rs", "3-4", "v490")])
        self.assertEqual(render.ref(c), "[v497 st/a.rs:1-2,9-10; "
                         "runtime/src/lib.rs:5-5; v490 sw/b.rs:3-4]")

    def test_sections_in_order(self):
        text = render.render(self.data(), CONFIG)
        positions = [text.index("## %d. " % n) for n in range(1, 10)]
        self.assertEqual(positions, sorted(positions))

    def test_content_hash_ignores_timestamps(self):
        a, b = self.data(), self.data()
        b["meta"]["last_updated"] = "2030-01-01T00:00:00Z"
        self.assertEqual(render.content_hash(a, CONFIG),
                         render.content_hash(b, CONFIG))
        b["claims"][0]["statement"] = "Changed."
        self.assertNotEqual(render.content_hash(a, CONFIG),
                            render.content_hash(b, CONFIG))


class FixesTest(unittest.TestCase):
    def test_live_value_chain_and_subnets(self):
        chain = {"SubnetLimit": {"state": "explicit", "value": 160},
                 "TxRateLimit": {"state": "unset", "value": 1000},
                 "Blob": {"state": "explicit", "value": {"hex": "0x00"}}}
        subnets = {"netuids": [0, 1, 2, 3], "items": {
            "Tempo": {"default": 360, "values": {"3": 99}},
            "Swap.FeeRate": {"default": 33, "values": {}}}}
        self.assertEqual(ag.live_value("SubnetLimit", chain, subnets), "160")
        self.assertEqual(ag.live_value("TxRateLimit", chain, subnets),
                         "1000 (unset, default)")
        self.assertIsNone(ag.live_value("Blob", chain, subnets))
        self.assertEqual(ag.live_value("Tempo", chain, subnets),
                         "360 on 2 of 3 subnets")
        self.assertEqual(ag.live_value("FeeRate", chain, subnets),
                         "33 on all 3 subnets")
        self.assertIsNone(ag.live_value("Nope", chain, subnets))

    def test_date_floor_at_oldest_tag(self):
        line = render.claim_line(claim(
            "traps-001", status="deprecated", deprecated_since_spec=430,
            deprecated_since_floor=True), {430: "2026-07-10"})
        self.assertIn("(stopped applying at or before spec 430)", line)

    def test_oldest_release(self):
        git = lambda *a: (0, "v1.0.0\nv497\nv430\nv431\n")
        self.assertEqual(history.oldest_release(git), 430)

    def test_signature_context_for_a_body_citation(self):
        src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, src)
        os.makedirs(os.path.join(src, "p"))
        with open(os.path.join(src, "p", "a.rs"), "w") as handle:
            handle.write("impl X {\n    pub fn init_new_network(n: u16) {\n"
                         "        let a = 1;\n        set_immunity(5000);\n"
                         "    }\n}\n")
        problems, cited = verify.check_claim(
            {"statement": "`init_new_network` sets immunity to 5000.",
             "evidence": [{"path": "p/a.rs", "start": 4, "end": 4}]},
            src, 120)
        self.assertEqual(problems, [])
        self.assertEqual(cited[0]["signature_line"], 2)
        self.assertTrue(cited[0]["text"].startswith(
            "    pub fn init_new_network"))
        where = verify.critic_items([({"statement": "x"}, cited)],
                                    "v497")[0]["cited"][0]["where"]
        self.assertIn("enclosing fn, line 2", where)
        # A number only in the skipped lines between still fails.
        problems, _ = verify.check_claim(
            {"statement": "`a` is 1.",
             "evidence": [{"path": "p/a.rs", "start": 4, "end": 4}]},
            src, 120)
        self.assertEqual(problems, ["number 1 is not in the cited lines"])


class ReviewTest(unittest.TestCase):
    def test_remove_and_reject(self):
        import argparse
        tree = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tree)
        os.makedirs(os.path.join(tree, "grounding"))
        data = ledger.empty()
        data["claims"] = [claim("emission-001"), claim(
            "emission-002", review={"reason": "critic: x",
                                    "proposed": "New."})]
        ledger.save(os.path.join(tree, "grounding", "claims.yaml"), data)

        def run(action, cid):
            ag.review(argparse.Namespace(action=action, id=cid, tree=tree))
            return ledger.load(os.path.join(tree, "grounding",
                                            "claims.yaml"))

        after = run("reject", "emission-002")
        self.assertEqual(ledger.find(after, "emission-002")["statement"],
                         "A statement.")
        self.assertIsNone(ledger.find(after, "emission-002")["review"])
        after = run("remove", "emission-001")
        self.assertIsNone(ledger.find(after, "emission-001"))
        with open(os.path.join(tree, "GROUNDING.md")) as handle:
            self.assertEqual(handle.read(), render.render(after, CONFIG))


class CommittedFilesTest(unittest.TestCase):
    """GROUNDING.md is generated: it must equal the render of claims.yaml
    and stay under the size limit."""

    def test_grounding_md_is_the_render_of_the_ledger(self):
        path = os.path.join(ROOT, "GROUNDING.md")
        claims = os.path.join(ROOT, "grounding", "claims.yaml")
        if not os.path.exists(path) and not os.path.exists(claims):
            self.skipTest("no ledger committed yet")
        data = ledger.load(claims)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text, render.render(data, CONFIG))
        self.assertLessEqual(len(text.encode("utf-8")), CONFIG["max_bytes"])


class SnapshotTest(unittest.TestCase):
    TYPES = {
        1: {"path": [], "params": [], "def": {"kind": "primitive",
                                             "name": "u16"}},
        2: {"path": [], "params": [], "def": {"kind": "primitive",
                                             "name": "bool"}},
        3: {"path": ["Option"], "params": [["T", 1]], "def": {
            "kind": "variant", "variants": [
                {"name": "None", "fields": [], "index": 0},
                {"name": "Some", "fields": [{"name": None, "ty": 1}],
                 "index": 1}]}},
        4: {"path": ["Mode"], "params": [], "def": {
            "kind": "variant", "variants": [
                {"name": "Fast", "fields": [], "index": 0},
                {"name": "Slow", "fields": [], "index": 1}]}},
        5: {"path": [], "params": [], "def": {"kind": "sequence", "ty": 6}},
        6: {"path": [], "params": [], "def": {"kind": "primitive",
                                             "name": "u8"}},
    }

    def test_decode_value(self):
        t = self.TYPES
        self.assertEqual(snapshot.decode_value(t, 1, b"\x68\x01"), 360)
        self.assertIs(snapshot.decode_value(t, 2, b"\x01"), True)
        self.assertIsNone(snapshot.decode_value(t, 3, b"\x00"))
        self.assertEqual(snapshot.decode_value(t, 3, b"\x01\x02\x00"), 2)
        self.assertEqual(snapshot.decode_value(t, 4, b"\x01"), "Slow")
        self.assertEqual(snapshot.decode_value(t, 5, b"\x08\xab\xcd"),
                         "0xabcd")
        # Bytes that do not fit the type stay hex, never a guess.
        self.assertEqual(snapshot.decode_value(t, 1, b"\x01\x02\x03"),
                         {"hex": "0x010203"})

    def snap(self, spec, calls, tempo, chain_value):
        return {"meta": {"spec_version": spec, "block_number": 1,
                         "taken_at": "t"},
                "pallets": {"SubtensorModule": {
                    "calls": [{"name": n, "args": a} for n, a in calls],
                    "storage": {"Tempo": {"kind": "map", "value": "u16",
                                          "modifier": "default",
                                          "default": 360}}}},
                "chain": {"SubnetLimit": {"state": "explicit",
                                          "value": chain_value}},
                "subnets": {"netuids": [0, 1, 2], "items": {
                    "Tempo": {"default": 360, "values": tempo},
                    "Burn": {"default": 1, "values": {"1": 5, "2": 6}}}}}

    def test_diff_is_facts_only(self):
        old = self.snap(495, [("add_stake", [["amount", "u64"]])],
                        {"1": 99}, 128)
        new = self.snap(497, [("add_stake", [["amount", "u128"]]),
                              ("burn_alpha", [])], {"1": 100}, 160)
        new["subnets"]["items"]["Burn"]["values"] = {"1": 7, "2": 8}
        d = snapshot.diff(old, new, ["Burn"])
        calls = d["calls"]["SubtensorModule"]
        self.assertEqual(calls["added"], ["burn_alpha()"])
        self.assertEqual(len(calls["changed"]), 1)
        self.assertEqual(d["chain"], ["SubnetLimit: 128 -> 160"])
        self.assertIn("Tempo changed on 1 subnets: 1: 99 -> 100",
                      d["subnet_items"])
        self.assertIn("Burn: changed on 2 of 3 subnets (dynamic)",
                      d["subnet_items"])
        self.assertEqual(snapshot.new_items(d), ["burn_alpha"])
        text = snapshot.diff_markdown(d, new["meta"], old["meta"])
        self.assertIn("## SubtensorModule extrinsics added", text)

    def test_first_snapshot(self):
        d = snapshot.diff(None, self.snap(497, [], {}, 1), [])
        self.assertIn("first snapshot", snapshot.diff_markdown(
            d, {"spec_version": 497, "block_number": 1, "taken_at": "t"},
            None))
        self.assertEqual(snapshot.new_items(d), [])

    def test_previous_spec(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        for spec in ("490", "495", "497"):
            os.makedirs(os.path.join(tmp, spec))
            open(os.path.join(tmp, spec, "meta.json"), "w").close()
        self.assertEqual(snapshot.previous_spec(tmp, 497), 495)
        self.assertIsNone(snapshot.previous_spec(tmp, 490))


class HistoryTest(unittest.TestCase):
    def test_release_tags_prefer_peeled(self):
        refs = history.parse_ls_remote(
            "aaa\trefs/tags/v497\nbbb\trefs/tags/v497^{}\n"
            "ccc\trefs/tags/v1.0.0\nddd\trefs/heads/main\n")
        self.assertEqual(history.release_tags(refs), {497: "bbb"})

    def fake_git(self, outputs):
        def git(*args):
            for key, value in outputs.items():
                if key in " ".join(args):
                    return 0, value
            return 1, ""
        return git

    def test_changelog_and_pending(self):
        git = self.fake_git({
            "a495..a497": "Merge pull request #3367 from org/release-497\n"
                          "Merge pull request #3360 from org/fix\n"
                          "Merge branch 'main'\n",
            "a497..head": "Merge pull request #3370 from org/next\n"})
        lines = history.changelog(
            git, [{"prev": 495, "new": 497, "date": "2026-11-26"},
                  {"prev": 300, "new": 301, "date": "2025-01-01"}],
            lambda n: "a%d" % n if n >= 495 else None)
        self.assertEqual(lines[0], "spec 497 live 2026-11-26 (from 495): "
                                   "2 PRs: #3367 #3360")
        self.assertIn("PRs unknown", lines[1])
        self.assertEqual(history.pending(git, "a497", "head", 498, 497),
                         ["main states spec 498 (live is 497)",
                          "#3370 org/next"])

    def test_first_release_ignores_non_spec_tags(self):
        git = self.fake_git({"--contains": "v1.0.0\nv499\nv497\n"})
        self.assertEqual(history.first_release(git, "sha"), 497)


class ScopeTest(unittest.TestCase):
    def test_scope(self):
        ok = [(" M", "GROUNDING.md"), ("??", "snapshots/497/DIFF.md"),
              ("A ", "snapshots/497/chain.json"),
              (" M", "grounding/claims.yaml")]
        self.assertEqual(grounding_scope.scope_violations(ok), [])
        bad = grounding_scope.scope_violations([
            (" M", "grounding/atlas_grounding.py"),
            (" D", "snapshots/495/chain.json"),
            ("??", "snapshots/497/evil.py")])
        self.assertEqual(len(bad), 3)


class FakeJob(ag.Job):
    def __init__(self, target, refs, live):
        super().__init__(root=ROOT, no_push=True, target=target)
        self.var = os.path.join(target, "var")
        self.state_path = os.path.join(self.var, "state.json")
        self.refs, self.live = refs, live
        self.worked = 0
        self.clock = 1795700000.0
        self.sent = []

    def now(self):
        return self.clock

    def ls_remote(self):
        return self.refs

    def live_spec(self):
        return self.live

    def send(self, msg):
        self.sent.append(msg)
        return True

    def work(self, *args, **kwargs):
        self.worked += 1
        return {"backlog": False, "last_commit_at": self.clock}


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.refs = {"refs/tags/v497": "a", "refs/heads/main": "m"}

    def test_quiet_run_exits_without_work(self):
        job = FakeJob(self.tmp, self.refs, {"ok": True, "spec_version": 497})
        job._run()
        self.assertEqual(job.worked, 1)
        job.clock += 3600
        job._run()
        self.assertEqual(job.worked, 1)  # nothing moved
        state = job.load_state()
        self.assertEqual(state["last_success"], ag.utc(job.clock))

    def test_new_tag_or_main_triggers_work(self):
        job = FakeJob(self.tmp, self.refs, {"ok": True, "spec_version": 497})
        job._run()
        job.refs = dict(self.refs, **{"refs/heads/main": "m2"})
        job._run()
        self.assertEqual(job.worked, 2)

    def test_heartbeat_is_due_after_three_days(self):
        job = FakeJob(self.tmp, self.refs, {"ok": True, "spec_version": 497})
        job._run()
        job.clock += CONFIG["heartbeat_seconds"] - 60
        job._run()
        self.assertEqual(job.worked, 1)
        job.clock += 120
        job._run()
        self.assertEqual(job.worked, 2)

    def test_detection_failure_pages_once_at_three(self):
        job = FakeJob(self.tmp, None, {"ok": False, "error": "down"})
        for _ in range(5):
            job._run()
            job.clock += 3600
        self.assertEqual(len(job.sent), 1)
        self.assertEqual(job.worked, 0)


class VerifySectionTest(unittest.TestCase):
    """Worker, code check and critic, with the model runs faked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(self.src, "pallets"))
        with open(os.path.join(self.src, "pallets", "a.rs"), "w") as h:
            h.write("const TEMPO: u16 = 360;\nconst KAPPA: u16 = 32767;\n")
        self.job = FakeJob(os.path.join(self.tmp, "tree"), {}, {})
        self.data = ledger.empty()
        self.data["claims"] = [claim("emission-001", stale=True,
                                     statement="Old text.")]

    def fake(self, worker, critic):
        calls = []

        def run_model(cmd, cwd, timeout):
            calls.append(cmd)
            reply = worker if len(calls) == 1 else critic
            return 0, json.dumps({"result": json.dumps(reply),
                                  "is_error": False}), ""
        self.job.run_model = run_model
        return calls

    def test_agree_disagree_and_bad_citation(self):
        self.data["meta"]["queued_items"] = {"emission": ["NewItem"]}
        ev = [{"path": "pallets/a.rs", "start": 1, "end": 2}]
        calls = self.fake(
            {"claims": [
                {"id": "emission-001", "action": "rewrite",
                 "statement": "`TEMPO` is 360.", "evidence": ev,
                 "watched_paths": ["pallets/a.rs"]},
                {"id": None, "action": "new", "statement": "`KAPPA` is "
                 "32767.", "evidence": ev, "watched_paths": []},
                {"id": None, "action": "new", "statement": "Rho is 10.",
                 "evidence": ev, "watched_paths": []}]},
            {"verdicts": [{"key": "c0", "verdict": "agree", "reason": "ok"},
                          {"key": "c1", "verdict": "disagree",
                           "reason": "not shown"}]})
        counts, unverified = self.job.verify_section(
            {}, self.data, "emission", 497, "v497", "a" * 40, self.src,
            fresh=False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(counts, {"verified": 1, "unverified": 2,
                                  "removed": 0})
        first = ledger.find(self.data, "emission-001")
        self.assertEqual(first["statement"], "`TEMPO` is 360.")
        self.assertFalse(first["stale"])
        self.assertIsNone(first["review"])
        self.assertEqual(first["evidence"][0]["lines"], "1-2")
        # The critic sees the claims and cited text only.
        critic_prompt = calls[1][-1]
        self.assertIn("const TEMPO", critic_prompt)
        self.assertNotIn("watched_paths", critic_prompt)
        self.assertEqual(sorted(unverified), ["emission-002",
                                              "emission-003"])
        rho = ledger.find(self.data, "emission-002")
        self.assertIn("number 10", rho["review"]["reason"])
        kappa = ledger.find(self.data, "emission-003")
        self.assertIn("critic", kappa["review"]["reason"])
        self.assertIsNone(kappa["last_verified"])
        ledger.validate(self.data)

    def test_over_budget_drops_new_claims_from_the_end(self):
        cfg = self.job.section_cfg("emission")
        self.addCleanup(cfg.__setitem__, "budget", cfg["budget"])
        cfg["budget"] = 1
        self.data["meta"]["queued_items"] = {"emission": ["NewItem"]}
        ev = [{"path": "pallets/a.rs", "start": 1, "end": 2}]
        self.fake(
            {"claims": [
                {"id": "emission-001", "action": "keep",
                 "statement": "`TEMPO` is 360.", "evidence": ev},
                {"id": None, "action": "new", "statement": "`KAPPA` is "
                 "32767.", "evidence": ev},
                {"id": None, "action": "new", "statement": "Rho is 10.",
                 "evidence": ev}]},
            {"verdicts": [{"key": "c0", "verdict": "agree", "reason": "ok"},
                          {"key": "c1", "verdict": "agree",
                           "reason": "ok"}]})
        counts, unverified = self.job.verify_section(
            {}, self.data, "emission", 497, "v497", "a" * 40, self.src,
            fresh=False)
        # Both new claims go; the claim that existed before stays.
        self.assertEqual([c["id"] for c in self.data["claims"]],
                         ["emission-001"])
        self.assertEqual(counts["removed"], 2)
        self.assertEqual(unverified, [])

    def test_claims_that_are_not_stale_are_left_alone(self):
        self.data["claims"].append(claim("emission-002",
                                         statement="Untouched."))
        ev = [{"path": "pallets/a.rs", "start": 1, "end": 2}]
        calls = self.fake(
            {"claims": [
                {"id": "emission-001", "action": "keep",
                 "statement": "`TEMPO` is 360.", "evidence": ev},
                {"id": "emission-002", "action": "rewrite",
                 "statement": "Rewritten.", "evidence": ev}]},
            {"verdicts": [{"key": "c0", "verdict": "agree", "reason": "ok"}]})
        self.job.verify_section({}, self.data, "emission", 497, "v497",
                                "a" * 40, self.src, fresh=False)
        untouched = ledger.find(self.data, "emission-002")
        self.assertEqual(untouched["statement"], "Untouched.")
        self.assertIsNone(untouched["review"])
        self.assertNotIn("Rewritten", calls[1][-1])  # never sent to critic

    def test_new_claims_only_for_queued_items(self):
        ev = [{"path": "pallets/a.rs", "start": 1, "end": 2}]
        worker = {"claims": [
            {"id": "emission-001", "action": "keep",
             "statement": "`TEMPO` is 360.", "evidence": ev},
            {"id": None, "action": "new", "statement": "`KAPPA` is 32767.",
             "evidence": ev}]}
        both = {"verdicts": [{"key": "c0", "verdict": "agree"},
                             {"key": "c1", "verdict": "agree"}]}
        self.fake(worker, both)
        self.job.verify_section({}, self.data, "emission", 497, "v497",
                                "a" * 40, self.src, fresh=False)
        self.assertEqual(len(self.data["claims"]), 1)
        self.data["claims"][0]["stale"] = True
        self.data["meta"]["queued_items"] = {"emission": ["KappaThing"]}
        self.fake(worker, both)
        self.job.verify_section({}, self.data, "emission", 497, "v497",
                                "a" * 40, self.src, fresh=False)
        self.assertEqual(len(self.data["claims"]), 2)

    def test_worker_failure_keeps_claims_stale(self):
        def run_model(cmd, cwd, timeout):
            return 1, "", "boom"
        self.job.run_model = run_model
        state = {}
        for attempt in range(ag.WORKER_FAIL_LIMIT):
            counts, unverified = self.job.verify_section(
                state, self.data, "emission", 497, "v497", "a" * 40,
                self.src, fresh=False)
            if attempt < ag.WORKER_FAIL_LIMIT - 1:
                self.assertEqual(unverified, [])
                self.assertTrue(ledger.find(self.data,
                                            "emission-001")["stale"])
        self.assertEqual(unverified, ["emission-001"])

    def test_unreturned_stale_claim_goes_unverified(self):
        self.fake({"claims": []}, {"verdicts": []})
        _, unverified = self.job.verify_section(
            {}, self.data, "emission", 497, "v497", "a" * 40, self.src,
            fresh=False)
        self.assertEqual(unverified, ["emission-001"])
        self.assertEqual(ledger.find(self.data, "emission-001")["statement"],
                         "Old text.")


class UnitFilesTest(unittest.TestCase):
    def test_timer_is_hourly_and_service_has_failure_hook(self):
        base = os.path.join(GROUNDING_DIR, "systemd")
        with open(os.path.join(base, "atlas-grounding.timer")) as handle:
            timer = handle.read()
        with open(os.path.join(base, "atlas-grounding.service")) as handle:
            service = handle.read()
        self.assertIn("OnCalendar=*:45", timer)
        self.assertIn("OnFailure=atlas-notify-failure@%n.service", service)
        self.assertIn("grounding/atlas_grounding.py run", service)
        seconds = int(service.split("TimeoutStartSec=")[1].split("min")[0])
        self.assertGreater(seconds * 60, CONFIG["run_budget_seconds"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("git"), "git not installed")
class PushPathTest(unittest.TestCase):
    """prepare, commit_local and push against a local bare remote. The
    sandbox and test gates are replaced; they have their own tests in
    upgrade/tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
        self.env.update(HOME=self.tmp, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="vaNlabs",
                        GIT_AUTHOR_EMAIL="vanlabs@pm.me",
                        GIT_COMMITTER_NAME="vaNlabs",
                        GIT_COMMITTER_EMAIL="vanlabs@pm.me")
        self.remote = os.path.join(self.tmp, "remote.git")
        self.live = os.path.join(self.tmp, "live")
        self.sh("git", "init", "-q", "--bare", "-b", "main", self.remote)
        self.sh("git", "clone", "-q", self.remote, self.live)
        self.write(self.live, "README.md", "x\n")
        self.sh("git", "-C", self.live, "add", "-A")
        self.sh("git", "-C", self.live, "commit", "-qm", "init")
        self.sh("git", "-C", self.live, "push", "-q", "origin", "HEAD:main")
        os.environ["ATLAS_GROUNDING_WORKTREE"] = os.path.join(self.tmp, "wt")
        self.addCleanup(os.environ.pop, "ATLAS_GROUNDING_WORKTREE")
        self.job = ag.Job(root=self.live)
        self.job.git_env = dict(self.env)
        self.job.check_tree = lambda: None

    def sh(self, *cmd, cwd=None):
        import subprocess
        result = subprocess.run(list(cmd), cwd=cwd, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, base, rel, text):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def remote_files(self):
        return self.sh("git", "--git-dir", self.remote, "ls-tree", "-r",
                       "--name-only", "main").splitlines()

    def test_commit_and_push_generated_files(self):
        state = {}
        self.job.prepare(state)
        self.write(self.job.worktree, "GROUNDING.md", "g\n")
        self.write(self.job.worktree, "snapshots/497/DIFF.md", "d\n")
        self.job.commit_local("Snapshot runtime spec 497")
        head = self.job.push(state)
        self.assertIsNotNone(head)
        self.assertIn("snapshots/497/DIFF.md", self.remote_files())
        self.assertEqual(self.sh("git", "--git-dir", self.remote, "log",
                                 "-1", "--format=%an <%ae>", "main"),
                         "vaNlabs <vanlabs@pm.me>")
        self.assertIsNone(self.job.push(state))  # nothing left to push

    def test_out_of_scope_file_blocks_the_commit(self):
        self.job.prepare({})
        self.write(self.job.worktree, "grounding/evil.py", "x\n")
        with self.assertRaises(ag.Gate) as ctx:
            self.job.commit_local("x")
        self.assertEqual(ctx.exception.gate, "scope")

    def test_unpushed_commits_rebase_onto_a_moved_main(self):
        state = {}
        self.job.prepare(state)
        self.write(self.job.worktree, "GROUNDING.md", "g\n")
        self.job.commit_local("Ground chain claims at spec 497")
        # main moves before the push.
        self.write(self.live, "other.txt", "o\n")
        self.sh("git", "-C", self.live, "add", "-A")
        self.sh("git", "-C", self.live, "commit", "-qm", "other")
        self.sh("git", "-C", self.live, "push", "-q", "origin", "HEAD:main")
        self.job.prepare(state)
        self.assertIsNotNone(self.job.push(state))
        files = self.remote_files()
        self.assertIn("GROUNDING.md", files)
        self.assertIn("other.txt", files)
