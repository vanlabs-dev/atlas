"""Reconciler plan builder: the desired-vs-actual diff, the mass-discard
guard, and per-pass bounding. Pure logic over an identity map and a
registry snapshot — no store, no git, no network."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from _helpers import fleet  # noqa: E402


def desired(netuid, repo, owner="5Owner", name=None):
    return {"netuid": netuid, "github_repo": repo, "owner_ss58": owner,
            "subnet_name": name or ("sn%d" % netuid)}


def slot(netuid, repo, owner="5Owner", status="active", epoch=1):
    canonical, _ = fleet.normalize_repo_url(repo) if repo else (None, "")
    return {"netuid": netuid, "github_repo": canonical, "owner_ss58": owner,
            "fingerprint": fleet.fingerprint(owner, canonical) if canonical
            else None, "epoch": epoch, "status": status,
            "default_branch": "main", "local_sha": "sha", "clone_size_bytes": 1,
            "first_seen_block": 1, "last_reconciled": None,
            "last_fetch_success": None}


def by_action(plan):
    result = {}
    for action in plan:
        result.setdefault(action["action"], []).append(action)
    return result


class BuildPlanTests(unittest.TestCase):
    def test_new_repo_on_empty_registry_is_clone(self):
        plan = fleet.build_plan(
            [desired(23, "https://github.com/o/r")], [], fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.CLONE]], [23])
        self.assertEqual(acts[fleet.CLONE][0]["url"],
                         "https://github.com/o/r")
        self.assertIsNotNone(acts[fleet.CLONE][0]["fingerprint"])

    def test_active_slot_same_identity_is_update(self):
        registry = [slot(23, "https://github.com/o/r")]
        plan = fleet.build_plan(
            [desired(23, "https://github.com/o/r")], registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertIn(fleet.UPDATE, acts)
        self.assertNotIn(fleet.CLONE, acts)
        self.assertNotIn(fleet.DISCARD, acts)

    def test_changed_repo_is_repoint(self):
        registry = [slot(23, "https://github.com/o/old")]
        plan = fleet.build_plan(
            [desired(23, "https://github.com/o/new")], registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.REPOINT]], [23])
        self.assertEqual(acts[fleet.REPOINT][0]["url"],
                         "https://github.com/o/new")

    def test_changed_owner_is_repoint(self):
        registry = [slot(23, "https://github.com/o/r", owner="5Old")]
        plan = fleet.build_plan(
            [desired(23, "https://github.com/o/r", owner="5New")],
            registry, fetch_ok=True)
        self.assertIn(fleet.REPOINT, by_action(plan))

    def test_slot_absent_from_desired_is_discard(self):
        registry = [slot(23, "https://github.com/o/r")]
        plan = fleet.build_plan([], registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.DISCARD]], [23])

    def test_missing_github_repo_is_no_repo(self):
        plan = fleet.build_plan([desired(7, None)], [], fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.NO_REPO]], [7])
        self.assertNotIn(fleet.CLONE, acts)

    def test_invalid_url_is_no_repo_with_reason(self):
        plan = fleet.build_plan(
            [desired(7, "https://gitlab.com/o/r")], [], fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual(len(acts[fleet.NO_REPO]), 1)
        self.assertEqual(acts[fleet.NO_REPO][0]["reason"], "unsupported-host")

    def test_unreachable_within_backoff_produces_no_action(self):
        reg = [slot(9, "https://github.com/o/r", status="unreachable")]
        reg[0]["next_attempt_at"] = "2999-01-01T00:00:00+00:00"
        plan = fleet.build_plan([desired(9, "https://github.com/o/r")], reg,
                                fetch_ok=True, now="2026-07-14T00:00:00+00:00")
        self.assertEqual(plan, [])  # backed off — dead repo not retried

    def test_unreachable_past_backoff_is_retried(self):
        reg = [slot(9, "https://github.com/o/r", status="unreachable")]
        reg[0]["next_attempt_at"] = "2020-01-01T00:00:00+00:00"
        plan = fleet.build_plan([desired(9, "https://github.com/o/r")], reg,
                                fetch_ok=True, now="2026-07-14T00:00:00+00:00")
        self.assertEqual([a["netuid"] for a in by_action(plan)[fleet.CLONE]],
                         [9])

    def test_unreachable_repointed_on_fix_bypasses_backoff(self):
        # owner replaces a placeholder with a real repo → fingerprint changes
        # → immediate re-point, not subject to the unreachable backoff
        reg = [slot(9, "https://github.com/o/placeholder",
                    status="unreachable")]
        reg[0]["next_attempt_at"] = "2999-01-01T00:00:00+00:00"
        plan = fleet.build_plan([desired(9, "https://github.com/o/real")], reg,
                                fetch_ok=True, now="2026-07-14T00:00:00+00:00")
        self.assertIn(fleet.REPOINT, by_action(plan))

    def test_disk_limited_slot_resumes_as_clone(self):
        registry = [slot(9, "https://github.com/o/r", status="disk-limited")]
        plan = fleet.build_plan(
            [desired(9, "https://github.com/o/r")], registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.CLONE]], [9])
        self.assertEqual(acts[fleet.CLONE][0]["reason"], "resume")

    def test_pending_slot_same_identity_resumes_as_clone(self):
        registry = [slot(9, "https://github.com/o/r", status="pending")]
        plan = fleet.build_plan(
            [desired(9, "https://github.com/o/r")], registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.CLONE]], [9])
        self.assertEqual(acts[fleet.CLONE][0]["reason"], "resume")

    def test_converged_registry_only_updates(self):
        registry = [slot(1, "https://github.com/o/a"),
                    slot(2, "https://github.com/o/b")]
        desired_map = [desired(1, "https://github.com/o/a"),
                       desired(2, "https://github.com/o/b")]
        plan = fleet.build_plan(desired_map, registry, fetch_ok=True)
        acts = by_action(plan)
        self.assertEqual(set(acts), {fleet.UPDATE})


class MassDiscardGuardTests(unittest.TestCase):
    def test_degraded_fetch_produces_no_discard_or_repoint(self):
        registry = [slot(1, "https://github.com/o/a", status="active"),
                    slot(2, "https://github.com/o/b", status="active")]
        # A degraded fetch: the desired map is untrusted (here, empty).
        plan = fleet.build_plan([], registry, fetch_ok=False)
        acts = by_action(plan)
        self.assertNotIn(fleet.DISCARD, acts)
        self.assertNotIn(fleet.REPOINT, acts)
        self.assertNotIn(fleet.NO_REPO, acts)

    def test_degraded_fetch_still_updates_active_slots(self):
        registry = [slot(1, "https://github.com/o/a", status="active")]
        plan = fleet.build_plan([], registry, fetch_ok=False)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.UPDATE]], [1])

    def test_degraded_fetch_resumes_pending_clones(self):
        registry = [slot(2, "https://github.com/o/b", status="pending")]
        plan = fleet.build_plan([], registry, fetch_ok=False)
        acts = by_action(plan)
        self.assertEqual([a["netuid"] for a in acts[fleet.CLONE]], [2])

    def test_degraded_fetch_never_clones_new_from_map(self):
        # Even though the map lists a brand-new subnet, a degraded fetch
        # must not act on it.
        plan = fleet.build_plan(
            [desired(99, "https://github.com/o/new")], [], fetch_ok=False)
        self.assertEqual(plan, [])


class BoundPlanTests(unittest.TestCase):
    def _plan(self):
        return [
            fleet._action(fleet.CLONE, 1, url="u1"),
            fleet._action(fleet.CLONE, 2, url="u2"),
            fleet._action(fleet.CLONE, 3, url="u3"),
            fleet._action(fleet.UPDATE, 4),
            fleet._action(fleet.DISCARD, 5),
            fleet._action(fleet.REPOINT, 6, url="u6"),
        ]

    def test_no_bound_returns_plan_unchanged(self):
        plan = self._plan()
        self.assertEqual(fleet.apply_bound(plan, None), plan)

    def test_bound_caps_clone_and_repoint(self):
        bounded = fleet.apply_bound(self._plan(), 2)
        acts = by_action(bounded)
        started = acts.get(fleet.CLONE, []) + acts.get(fleet.REPOINT, [])
        self.assertEqual(len(started), 2)

    def test_bound_defers_the_excess(self):
        bounded = fleet.apply_bound(self._plan(), 2)
        acts = by_action(bounded)
        self.assertIn(fleet.DEFERRED, acts)
        self.assertEqual(len(acts[fleet.DEFERRED]), 2)  # 1 clone + 1 repoint

    def test_bound_does_not_touch_update_or_discard(self):
        bounded = fleet.apply_bound(self._plan(), 0)
        acts = by_action(bounded)
        self.assertEqual(len(acts[fleet.UPDATE]), 1)
        self.assertEqual(len(acts[fleet.DISCARD]), 1)


if __name__ == "__main__":
    unittest.main()
