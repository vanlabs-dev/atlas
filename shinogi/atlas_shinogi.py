#!/usr/bin/env python3
"""Atlas shinogi renderer (change: shinogi-renderer).

Composes the public shinogi.dev edition from rows already persisted in the
livedata and fleet stores, all opened read-only, and publishes it into a
second checkout when the content hash changes. Composing makes no chain
call, no provider call and no model call: every figure traces to a stored
row with its reference block or observation date, and an input that is
missing or past its own stale bound is named instead of estimated.

This module is a second reader over those stores, not a wrapper around the
Telegram briefing. `telegram/atlas_briefing.py` returns operator lines and
closes with the LAN board URL or a next action; dressing those in HTML
would publish the board address, the provider quota and the budget-band
prompt to the open internet. `_Sources`, `_movers`, `_delta_pct` and
`_release_for_upgrade` are imported and reused; nothing formatted for
Telegram crosses into the page.

Stale bounds are per input. The emission-gate bar uses the briefing bound
of 26 hours. Network vitals carry their observation date and are never
called stale for age alone. Movers use the window since the previous
shinogi publish, or `window_hours` before compose on a first edition.

The publish path is one direction only: Atlas writes shinogi, and no file
in the shinogi checkout is read as an input to an edition. Before any
write the rendered document is scanned for operator material and for the
self-contained rules the page contract fixes; a hit fails the pass closed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")

TAGLINE = "A lean read on Bittensor subnets"
FOOTER = "shinogi.dev · public read-only · data from Atlas"

# Contract order. Every landmark is present on every edition, including one
# whose every input is missing.
SECTION_ORDER = (("network", "Network"), ("movers", "Subnet movers"),
                 ("mining", "Mining"), ("attention", "Attention"),
                 ("code-narrative", "Code / narrative"))

# The reason token alone is not enough to render. On the real fleet 93 of
# 106 public rows score `divergence`, so mapping the six tokens to six
# fixed phrases produces a page of near-identical lines that says nothing.
# `score_subnet` also returns div_signed, cold, econ_fresh and pulse_spike;
# the contract bans direction-cue *glyphs*, the numeric score and the board
# thesis, not direction stated in words. So the phrase is derived.
WHY_PHRASE = {
    "divergence": "code activity and price are moving apart",
    "emission": "emission routed away from miners",
    "abandon": "repository has gone quiet",
    "fresh": "something changed this pass",
    "opaque": "emission split is not readable from the repository",
    "quiet": "no signal beyond presence",
}


def why_phrase(sc: Dict[str, Any]) -> Optional[str]:
    """A short public reason, differentiated by the score's own components.
    Returns None when the reason token is unrecognised, so the row names
    that gap instead of printing a raw token."""
    why = sc.get("why")
    if why == "divergence":
        signed = sc.get("div_signed")
        if signed is None:
            return WHY_PHRASE["divergence"]
        if signed < 0:
            return ("priced ahead of a repository that has gone quiet"
                    if sc.get("cold") else "priced ahead of its code activity")
        return "building faster than the price reflects"
    if why == "fresh":
        if sc.get("econ_fresh"):
            return "reward or emission code changed this pass"
        if sc.get("pulse_spike"):
            return "branch activity spiked this pass"
        return WHY_PHRASE["fresh"]
    if why == "abandon":
        return ("repository has gone quiet while the price holds up"
                if sc.get("cold") else WHY_PHRASE["abandon"])
    return WHY_PHRASE.get(why)


class ShinogiError(Exception):
    """The pass fails closed. Nothing is written."""


# ---------------------------------------------------------------------------
# Lazy cross-directory imports. Same pattern as fleet/atlas_fleet_mining.py
# reaching livedata/ and telegram/atlas_telegram.py reaching inventory/.
# ---------------------------------------------------------------------------

_TG: Any = None
_BRIEF: Any = None
_BOARD: Any = None
_FLEET: Any = None


def _tg() -> Any:
    global _TG
    if _TG is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "telegram"))
        import atlas_telegram  # noqa: E402
        _TG = atlas_telegram
    return _TG


def _brief() -> Any:
    global _BRIEF
    if _BRIEF is None:
        _tg()
        sys.path.insert(0, os.path.join(_REPO_ROOT, "telegram"))
        import atlas_briefing  # noqa: E402
        _BRIEF = atlas_briefing
    return _BRIEF


def _board() -> Any:
    global _BOARD
    if _BOARD is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "fleet"))
        import atlas_fleet_dashboard  # noqa: E402
        _BOARD = atlas_fleet_dashboard
    return _BOARD


def _fleet() -> Any:
    global _FLEET
    if _FLEET is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "fleet"))
        import atlas_fleet  # noqa: E402
        _FLEET = atlas_fleet
    return _FLEET


# ---------------------------------------------------------------------------
# Config and publish state
# ---------------------------------------------------------------------------

def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ShinogiError("cannot load config %s: %s" % (path, exc))
    for key in ("enabled", "publish", "checkout_dir", "state_db", "live_db",
                "fleet_db"):
        if key not in config:
            raise ShinogiError("config %s is missing %r" % (path, key))
    return config


STATE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def open_state(db_path: str) -> sqlite3.Connection:
    """The renderer's own store. Shinogi deltas compare against the last
    shinogi publish on a six-hour clock, which is a different series from
    the notifier's daily and weekly `briefing:figures`; keeping them apart
    also keeps compose read-only against every Atlas store."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.executescript(STATE_SQL)
    return connection


def state_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM meta WHERE key = ?",
                             (key,)).fetchone()
    return row[0] if row else None


def state_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    connection.commit()


# ---------------------------------------------------------------------------
# Items. A section is a list of (kind, text): "fact" renders in the list,
# "gap" names a missing or stale input and renders as its own line.
# ---------------------------------------------------------------------------

def _fact(text: str) -> Tuple[str, str]:
    return ("fact", text)


def _gap(text: str) -> Tuple[str, str]:
    return ("gap", text)


def _utc(now: Optional[datetime.datetime] = None) -> datetime.datetime:
    return now or datetime.datetime.now(datetime.timezone.utc)


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, float):
        return ("%%.%df" % digits) % value
    return str(value)


def _grouped(value: Any) -> str:
    """A large count with thousands separators, for a public reader."""
    if value is None:
        return "not recorded"
    try:
        return "{:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return str(value)


def _plural(count: int, singular: str, plural: str) -> str:
    return "%d %s" % (count, singular if count == 1 else plural)


def _sn_list(netuids: Sequence[Any]) -> str:
    return ", ".join("SN%s" % n for n in netuids)


def _delta_value(new: Any, old: Any) -> Optional[str]:
    """The signed change since the previous shinogi publish, or None.
    A change that rounds to zero is suppressed: `+0.0%` is noise."""
    pct = _brief()._delta_pct(new, old)
    if not pct or pct in ("+0.0%", "-0.0%"):
        return None
    return pct


def _delta(new: Any, old: Any) -> str:
    pct = _delta_value(new, old)
    return " (%s since last publish)" % pct if pct else ""


# ---------------------------------------------------------------------------
# Fact layer. Each function re-derives its section from stored rows with the
# same SQL semantics the briefing uses, and returns public items plus the
# figures a later edition compares against. An absent store, an absent table
# or an empty result is a named gap, never an exception.
# ---------------------------------------------------------------------------

def network_facts(src: Any, cfg: Dict[str, Any], start: str,
                  prev: Dict[str, Any], now: datetime.datetime
                  ) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    brief = _brief()
    items: List[Tuple[str, str]] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is None:
        return [_gap("Missing the live store: no network facts recorded.")], \
            figures

    spec = brief._one(live,
                      "SELECT value FROM meta WHERE key = 'last_live_spec'")
    if spec is None:
        items.append(_gap("Missing the runtime spec."))
    else:
        line = "Runtime spec %s" % spec
        release = None
        try:
            release = _tg()._release_for_upgrade(
                cfg.get("repo_db", "var/repotrack/repotrack.db"), int(spec))
        except (ValueError, sqlite3.Error):
            release = None
        if release is not None:
            line += ", released as %s" % release["subject"]
            figures["release"] = release["subject"]
        items.append(_fact(line + "."))
        figures["spec"] = int(spec)

    if brief._table(live, "chain_param_events"):
        changes = live.execute(
            "SELECT item, prev_value, new_value FROM chain_param_events "
            "WHERE observed_at > ? ORDER BY id", (start,)).fetchall()
        for item, prev_v, new_v in changes:
            items.append(_fact("Rule change: %s moved from %s to %s."
                               % (item, prev_v, new_v)))

    row = live.execute(
        "SELECT theta, rank, above_count, observed_at FROM gate_state "
        "WHERE gate_active = 1 ORDER BY id DESC LIMIT 1").fetchone() \
        if brief._table(live, "gate_state") else None
    if row is None:
        items.append(_gap("Missing the emission-gate bar."))
    else:
        theta, rank, above, observed_at = row
        stale_hours = float(cfg.get("stale_hours", 26))
        cutoff = (now - datetime.timedelta(hours=stale_hours)).isoformat()
        if observed_at < cutoff:
            items.append(_gap(
                "The emission-gate bar is stale: last observed %s, past its "
                "%g hour bound." % (observed_at[:16], stale_hours)))
        else:
            figures["theta"] = theta
            figures["rank"] = rank
            figures["above"] = above
            # rank and above_count are recorded per poll and either can be
            # NULL. Build the line from what is present and name what is
            # not, rather than letting "not recorded" stand in mid-sentence.
            bits = ["Emission-gate bar at %s%s"
                    % (_num(theta, 5), _delta(theta, prev.get("theta")))]
            if rank is not None:
                bits.append("rank %s" % _num(rank))
            if above is not None:
                bits.append("%s above it"
                            % _plural(int(above), "subnet", "subnets"))
            items.append(_fact(", ".join(bits) + "."))
            absent = [label for label, value in (("its rank", rank),
                                                 ("the above-bar count",
                                                  above))
                      if value is None]
            if absent:
                items.append(_gap("The bar is recorded without %s."
                                  % " and ".join(absent)))
        if brief._table(live, "gate_events"):
            moves = brief._one(live, "SELECT COUNT(*) FROM gate_events "
                                     "WHERE observed_at > ?", (start,))
            figures["side_changes"] = moves
            items.append(_fact(
                "%s at the bar in the window."
                % (_plural(moves, "side change", "side changes")
                   if isinstance(moves, int) else
                   "%s side changes" % _num(moves))))

    vit = live.execute(
        "SELECT date, tao_usd, total_staked_tao, subnets_share_pct, "
        "new_accounts_today FROM network_vitals "
        "ORDER BY date DESC LIMIT 1").fetchone() \
        if brief._table(live, "network_vitals") else None
    if vit is None:
        items.append(_gap("Missing network vitals."))
    else:
        date, usd, staked, share, accounts = vit
        figures["tao_usd"] = usd
        figures["staked"] = staked
        figures["share_pct"] = share
        figures["accounts"] = accounts
        figures["vitals_date"] = date
        # Vitals are a daily observation. They carry their date and are not
        # stale for age alone.
        items.append(_fact(
            "TAO at %s USD%s, %s TAO staked, subnets hold %s%% of stake, "
            "%s new accounts, observed %s."
            % (_num(usd, 2), _delta(usd, prev.get("tao_usd")),
               _grouped(staked), _num(share, 2), _grouped(accounts), date)))
    return items, figures


def mover_facts(src: Any, cfg: Dict[str, Any], start: str
                ) -> Tuple[List[Tuple[str, str]], Optional[Dict[str, Any]]]:
    """(items, lead). The largest mover is returned alongside the items so
    compose can chart it without a second pass over the panel."""
    brief = _brief()
    items: List[Tuple[str, str]] = []
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return [_gap("Missing panel snapshots: no movers can be "
                     "ranked.")], None

    lead: Optional[Dict[str, Any]] = None
    for netuid, old, new, ob, nb, pct in brief._movers(
            live, start, "moving_price_tao",
            float(cfg.get("price_move_threshold_pct", 15)), 6):
        items.append(_fact(
            "SN%d alpha price %+.1f%%, from %.5f TAO at block %s to %.5f TAO "
            "at block %s." % (netuid, pct, old, ob, new, nb)))
        if lead is None or abs(pct) > abs(lead["raw"]):
            lead = {"netuid": netuid, "kind": "alpha price",
                    "pct": "%+.1f%%" % pct, "raw": pct, "column": "share",
                    "detail": "%.5f TAO at block %s to %.5f TAO at block %s"
                              % (old, ob, new, nb)}
    for netuid, old, new, ob, nb, pct in brief._movers(
            live, start, "share",
            float(cfg.get("share_move_threshold_pct", 25)), 4):
        items.append(_fact(
            "SN%d demand share %+.1f%%, from %.4f%% at block %s to %.4f%% at "
            "block %s." % (netuid, pct, old * 100, ob, new * 100, nb)))
        if lead is None or abs(pct) > abs(lead["raw"]):
            lead = {"netuid": netuid, "kind": "demand share",
                    "pct": "%+.1f%%" % pct, "raw": pct, "column": "share",
                    "detail": "%.4f%% at block %s to %.4f%% at block %s"
                              % (old * 100, ob, new * 100, nb)}
    if not items:
        items.append(_fact("No subnet crossed a mover threshold in this "
                           "window."))

    risk = [r[0] for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND dereg_risk_level = 'high' ORDER BY netuid")]
    if risk:
        items.append(_fact("High deregistration risk: %s."
                           % _sn_list(risk[:8])))
    contested = [r[0] for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND (conviction_is_contested = 1 OR takeover_eligible = 1) "
        "ORDER BY netuid")]
    if contested:
        items.append(_fact("Ownership contested or takeover-eligible: %s."
                           % _sn_list(contested[:8])))
    if brief._table(live, "gate_sides"):
        try:
            hover = [r[0] for r in live.execute(
                "SELECT netuid FROM gate_sides WHERE hovering = 1 "
                "ORDER BY netuid")]
        except sqlite3.Error:
            hover = []
        if hover:
            items.append(_fact("Hovering at the bar (%d): %s."
                               % (len(hover), _sn_list(hover))))
    return items, lead


def mining_facts(src: Any, cfg: Dict[str, Any], prev: Dict[str, Any]
                 ) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    brief = _brief()
    items: List[Tuple[str, str]] = []
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None or not brief._table(fleet, "mine_econ"):
        return [_gap("Missing the mining screen.")], figures
    latest = brief._one(fleet, "SELECT MAX(ts) FROM mine_econ")
    if not latest:
        return [_gap("Missing a mining pass: no economics recorded yet.")], \
            figures

    # rent_band is deliberately not selected: rent, the budget band and the
    # hardware rung are operator material and stay off the page.
    rows = fleet.execute(
        "SELECT netuid, subnet_name, cut_reason, net_tao_month, "
        "gross_tao_month FROM mine_econ WHERE ts = ?", (latest,)).fetchall()
    ranked = [r for r in rows if r[2] is None]
    ranked.sort(key=lambda r: (0, -(r[3] if r[3] is not None else
                                    (r[4] or 0.0)))
                if (r[3] is not None or r[4] is not None) else (1, 0.0))
    top = [int(r[0]) for r in ranked[:10]]
    figures["mining_top10"] = top

    figures["mining_observed"] = len(rows)
    figures["mining_ranked"] = len(ranked)
    if not ranked:
        items.append(_gap("Missing a ranked mining head: every observed "
                          "subnet was cut."))
    else:
        head = ranked[0]
        name = head[1]
        figures["mining_head"] = int(head[0])
        figures["mining_head_name"] = name
        items.append(_fact(
            "Board head: SN%d, %s." % (head[0], name if name else
                                       "name not recorded")))
    items.append(_fact("%d ranked, %d cut, %d observed."
                       % (len(ranked), len(rows) - len(ranked), len(rows))))

    prev_top = prev.get("mining_top10") or []
    if prev_top:
        entered = [n for n in top if n not in prev_top]
        left = [n for n in prev_top if n not in top]
        if entered:
            items.append(_fact("Entered the top ten: %s." % _sn_list(entered)))
        if left:
            items.append(_fact("Left the top ten: %s." % _sn_list(left)))
        if not entered and not left:
            items.append(_fact("The top ten is unchanged since the last "
                               "publish."))
    return items, figures


def recorded_names(src: Any) -> Dict[int, str]:
    """Newest recorded on-chain name per netuid, from the same store and
    the same pass the movers, vitals and block number come from. The fleet
    metrics report carries `netuid` and `org` and no subnet name, and `org`
    is a GitHub organisation, not the subnet's recorded name."""
    live = src.live
    if live is None or not _brief()._table(live, "panel_snapshot"):
        return {}
    names: Dict[int, str] = {}
    for netuid, name in live.execute(
            "SELECT netuid, name FROM panel_snapshot WHERE id IN "
            "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid)"):
        if name:
            names[int(netuid)] = name
    return names


def attention_rows(src: Any, cfg: Dict[str, Any], fleet_config: Dict[str, Any]
                   ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Rows for the attention strip, or a gap. `build_board` already runs
    the metrics report, scores every active subnet through `score_subnet`
    and sorts descending; this takes its order, its netuids, its `why` and
    its `pure_opaque` flag and discards the thesis, cue, badges and score.
    Reimplementing the scoring here would fork the definition of attention."""
    fleet = src.fleet
    if fleet is None:
        return [], "Missing the fleet store: no attention facts."
    try:
        board = _board().build_board(fleet, fleet_config)
    except sqlite3.Error:
        return [], "Missing fleet attention facts: the metrics report is " \
                   "not readable."
    names = recorded_names(src)
    limit = int(cfg.get("attention_rows", 10))
    rows: List[Dict[str, Any]] = []
    for item in (board["head"] + board["mid"] + board["quiet"]):
        if len(rows) >= limit:
            break
        if item["sc"]["pure_opaque"]:
            continue
        netuid = item["row"]["netuid"]
        rows.append({"netuid": netuid, "name": names.get(int(netuid)),
                     "why": why_phrase(item["sc"])})
    if not rows:
        return [], "Missing attention rows: no subnet carries a public " \
                   "attention signal."
    return rows, None


def code_facts(src: Any, cfg: Dict[str, Any], start: str,
               prev: Dict[str, Any]
               ) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    brief = _brief()
    items: List[Tuple[str, str]] = []
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None:
        return [_gap("Missing the fleet store: no code facts.")], figures

    if not brief._table(fleet, "metric_activity"):
        items.append(_gap("Missing the seven-day push count."))
    else:
        latest = brief._one(fleet, "SELECT MAX(pass_ts) FROM metric_activity")
        if not latest:
            items.append(_gap("Missing the seven-day push count."))
        else:
            # The stored seven-day fact, not a count over the publish window.
            pushed, total = fleet.execute(
                "SELECT SUM(c7 > 0), COUNT(*) FROM metric_activity "
                "WHERE pass_ts = ?", (latest,)).fetchone()
            figures["pushed_7d"] = pushed
            figures["tracked"] = total
            items.append(_fact(
                "%s of %s tracked subnets pushed in the last seven days%s."
                % (_num(pushed), _num(total),
                   _delta(pushed, prev.get("pushed_7d")))))

    if not brief._table(fleet, "signal_econ_verdicts"):
        items.append(_gap("Missing incentive-code verdicts."))
    else:
        highs = fleet.execute(
            "SELECT netuid, what_changed, new_sha FROM signal_econ_verdicts "
            "WHERE created_at > ? AND significance = 'high' "
            "ORDER BY created_at DESC LIMIT 5", (start,)).fetchall()
        for netuid, what, sha in highs:
            items.append(_fact(
                "SN%d, %s, at commit %s."
                % (netuid, (what or "no verdict line")[:90],
                   sha[:12] if sha else "not recorded")))
        med = brief._one(fleet, "SELECT COUNT(*) FROM signal_econ_verdicts "
                                "WHERE created_at > ? AND significance = "
                                "'med'", (start,))
        figures["high_count"] = len(highs)
        figures["med_count"] = med
        items.append(_fact(
            "%s and %s of middling significance in the window."
            % (_plural(len(highs), "material incentive-code change",
                       "material incentive-code changes"), _num(med))))

    if brief._table(fleet, "epochs"):
        for netuid, epoch in fleet.execute(
                "SELECT netuid, epoch FROM epochs WHERE opened_at > ? "
                "AND epoch > 1 ORDER BY opened_at DESC LIMIT 5",
                (start,)).fetchall():
            items.append(_fact("SN%d re-pointed its repository (epoch %d)."
                               % (netuid, epoch)))
    return items, figures


def narrative_facts(src: Any, start: str) -> List[Tuple[str, str]]:
    brief = _brief()
    items: List[Tuple[str, str]] = []
    fleet = src.fleet
    if fleet is None or not brief._table(fleet, "signal_adoptions"):
        return [_gap("Missing the adoption ledger.")]
    # Model identifiers only. Dependency-kind terms say nothing about a
    # subnet's direction and the contract excludes them.
    for term, netuids in fleet.execute(
            "SELECT term, GROUP_CONCAT(DISTINCT netuid) FROM "
            "signal_adoptions WHERE kind = 'model-id' AND seeded = 0 "
            "AND adopted_at > ? GROUP BY term ORDER BY COUNT(*) DESC "
            "LIMIT 6", (start,)).fetchall():
        items.append(_fact("Model %s adopted by %s."
                           % (term, _sn_list((netuids or "").split(",")))))
    if brief._table(fleet, "signal_events"):
        for (term,) in fleet.execute(
                "SELECT term FROM signal_events WHERE class = "
                "'narrative-cluster' AND created_at > ?", (start,)).fetchall():
            items.append(_fact("A cluster formed around %s." % term))
    return items or [_fact("No model-identifier adoption and no cluster "
                           "formed in this window.")]


# ---------------------------------------------------------------------------
# Series. The charts are drawn from recorded rows like every other figure:
# a series that is not recorded yields None and its chart is simply absent.
# ---------------------------------------------------------------------------

def theta_series(src: Any, limit: int = 48) -> List[float]:
    """Recent emission-gate bar observations, oldest first."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "gate_state"):
        return []
    rows = live.execute(
        "SELECT theta FROM gate_state WHERE theta IS NOT NULL "
        "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [r[0] for r in rows][::-1]


def vitals_series(src: Any, column: str, limit: int = 30
                  ) -> List[Tuple[str, float]]:
    """(date, value) for a network_vitals column, oldest first."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "network_vitals"):
        return []
    if column not in ("tao_usd", "total_staked_tao", "subnets_share_pct"):
        raise ShinogiError("refusing an unrecognised vitals column %r"
                           % column)
    rows = live.execute(
        "SELECT date, %s FROM network_vitals WHERE %s IS NOT NULL "
        "ORDER BY date DESC LIMIT ?" % (column, column),
        (int(limit),)).fetchall()
    return [(r[0], r[1]) for r in rows][::-1]


def share_distribution(src: Any) -> List[Tuple[int, float]]:
    """(netuid, share) for the newest snapshot of every subnet, largest
    first. This is the bar universe, and the emission-gate rank indexes
    straight into it."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return []
    return [(int(r[0]), r[1]) for r in live.execute(
        "SELECT netuid, share FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND share IS NOT NULL ORDER BY share DESC")]


def netuid_series(src: Any, netuid: int, column: str, limit: int = 14
                  ) -> List[float]:
    """One subnet's recent panel readings, oldest first."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return []
    if column not in ("share", "moving_price_tao", "alpha_price_tao"):
        raise ShinogiError("refusing an unrecognised panel column %r"
                           % column)
    rows = live.execute(
        "SELECT %s FROM panel_snapshot WHERE netuid = ? AND %s IS NOT NULL "
        "ORDER BY id DESC LIMIT ?" % (column, column),
        (int(netuid), int(limit))).fetchall()
    return [r[0] for r in rows][::-1]


def group_attention(rows: List[Dict[str, Any]]
                    ) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Collapse rows that share a reason. Ten rows carrying one phrase is
    the failure this exists to prevent: grouped, the repetition is stated
    once and the exceptions become visible."""
    groups: List[Tuple[str, List[Dict[str, Any]]]] = []
    index: Dict[str, int] = {}
    for row in rows:
        key = row.get("why") or "reason not recorded"
        if key not in index:
            index[key] = len(groups)
            groups.append((key, []))
        groups[index[key]][1].append(row)
    return groups


def asof_block(src: Any) -> Optional[int]:
    """Newest recorded chain block from the panel snapshot."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return None
    block = brief._one(live, "SELECT MAX(block_number) FROM panel_snapshot")
    return int(block) if block is not None else None


# ---------------------------------------------------------------------------
# Charts. Inline SVG drawn from the recorded series. No library, no script,
# no external asset: the geometry is computed here and the marks ship in the
# document, so the page still reads with scripting off.
# ---------------------------------------------------------------------------

def _points(values: Sequence[float], width: float, height: float,
            pad: float = 1.0) -> List[Tuple[float, float]]:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    last = len(values) - 1 or 1
    return [(pad + (width - 2 * pad) * (i / last),
             height - pad - (height - 2 * pad) * ((v - lo) / span))
            for i, v in enumerate(values)]


def sparkline(values: Sequence[float], width: float = 160.0,
              height: float = 40.0, stroke: str = "#c9b98d",
              fill_id: Optional[str] = None, label: str = "") -> str:
    """A single-series trend. Two points is the minimum that means
    anything; fewer renders nothing rather than a misleading flat line."""
    if len(values) < 2:
        return ""
    pts = _points(values, width, height)
    line = "M " + " L ".join("%.2f %.2f" % p for p in pts)
    area = ("%s L %.2f %.2f L %.2f %.2f Z"
            % (line, pts[-1][0], height, pts[0][0], height))
    out = ['<svg class="spark" width="%g" height="%g" viewBox="0 0 %g %g" '
           'role="img" aria-label="%s">' % (width, height, width, height,
                                            _esc(label))]
    if fill_id:
        out.append(
            '<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0%%" stop-color="%s" stop-opacity=".30"/>'
            '<stop offset="100%%" stop-color="%s" stop-opacity="0"/>'
            '</linearGradient></defs>' % (fill_id, stroke, stroke))
        out.append('<path d="%s" fill="url(#%s)"/>' % (area, fill_id))
    out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.6" '
               'stroke-linejoin="round" stroke-linecap="round"/>'
               % (line, stroke))
    out.append('<circle cx="%.2f" cy="%.2f" r="2.7" fill="%s"/>'
               % (pts[-1][0], pts[-1][1], stroke))
    out.append("</svg>")
    return "".join(out)


# The distribution stretches to any viewport, so its geometry is authored
# in a fixed user space and the browser scales x. Bars are square-ended:
# a corner radius would distort under the non-uniform scale.
_DIST_W = 1600.0
_DIST_H = 210.0


def distribution_svg(shares: Sequence[Tuple[int, float]], rank: Optional[int],
                     highlight: Sequence[int] = (),
                     falling: Sequence[int] = ()) -> str:
    """Every subnet's demand share, sorted, on a log scale so the tail stays
    visible. The emission-gate rank indexes straight into this order, which
    is why the threshold line lands where it does."""
    if len(shares) < 2:
        return ""
    values = [max(v * 100.0, 0.0) for _n, v in shares]
    floor = 0.01
    top = max(values)
    lo, hi = math.log10(floor), math.log10(top + floor)
    span = (hi - lo) or 1.0
    slot = _DIST_W / len(shares)
    bar = slot * 0.72
    out = ['<svg class="dist" viewBox="0 0 %g %g" preserveAspectRatio="none" '
           'role="img" aria-label="Demand share for %d subnets, sorted, '
           'with the emission-gate bar marked">'
           % (_DIST_W, _DIST_H, len(shares))]
    for i, (netuid, share) in enumerate(shares):
        value = max(share * 100.0, 0.0)
        height = max(1.5, _DIST_H * (math.log10(value + floor) - lo) / span)
        if netuid in falling:
            cls = "b fall"
        elif netuid in highlight:
            cls = "b hi"
        elif rank is not None and i < rank:
            cls = "b above"
        else:
            cls = "b below"
        out.append(
            '<rect class="%s" x="%.2f" y="%.2f" width="%.2f" height="%.2f">'
            '<title>SN%d  %.3f%% demand share  rank %d</title></rect>'
            % (cls, i * slot + (slot - bar) / 2, _DIST_H - height, bar,
               height, netuid, value, i + 1))
    if rank is not None and 0 < rank <= len(shares):
        out.append('<line class="thresh" x1="%.1f" y1="0" x2="%.1f" y2="%g"/>'
                   % (rank * slot, rank * slot, _DIST_H))
    out.append("</svg>")
    return "".join(out)


def meter(fraction: float, left: str, right: str) -> str:
    pct = max(0.0, min(1.0, fraction)) * 100.0
    return ('<div class="meter"><div class="mtrack">'
            '<div class="mfill" style="width:%.2f%%"></div></div>'
            '<div class="mlab"><span>%s</span><span>%s</span></div></div>'
            % (pct, _esc(left), _esc(right)))


# ---------------------------------------------------------------------------
# Compose. Pure read: resolves the window, assembles the sections, and
# returns the edition and its new figure set. Persisting figures belongs to
# publish, so a composed but unpublished edition does not consume the
# comparison point.
# ---------------------------------------------------------------------------

def compose(config: Dict[str, Any], state: Optional[sqlite3.Connection],
            now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    now = _utc(now)
    prev_raw = state_get(state, "figures") if state is not None else None
    prev_at = state_get(state, "published_at") if state is not None else None
    prev: Dict[str, Any] = json.loads(prev_raw) if prev_raw else {}
    first_edition = prev_at is None
    if first_edition:
        start = (now - datetime.timedelta(
            hours=float(config.get("window_hours", 6)))).isoformat()
    else:
        start = prev_at

    src = _brief()._Sources(config)
    sections: Dict[str, Any] = {}
    figures: Dict[str, Any] = {}
    try:
        try:
            fleet_config = _fleet().load_config()
        except Exception:
            fleet_config = {}

        for name, builder in (
                ("network", lambda: network_facts(src, config, start, prev,
                                                  now)),
                ("mining", lambda: mining_facts(src, config, prev)),
                ("code", lambda: code_facts(src, config, start, prev))):
            try:
                items, figs = builder()
            except sqlite3.Error as exc:
                items, figs = [_gap("Missing %s facts: the store is not "
                                    "readable (%s)."
                                    % (name, type(exc).__name__))], {}
            sections[name] = items
            figures.update(figs)

        lead: Optional[Dict[str, Any]] = None
        try:
            sections["movers"], lead = mover_facts(src, config, start)
        except sqlite3.Error as exc:
            sections["movers"] = [_gap("Missing movers facts: the store is "
                                       "not readable (%s)."
                                       % type(exc).__name__)]
        try:
            sections["narrative"] = narrative_facts(src, start)
        except sqlite3.Error as exc:
            sections["narrative"] = [_gap("Missing narrative facts: the "
                                          "store is not readable (%s)."
                                          % type(exc).__name__)]

        try:
            rows, gap = attention_rows(src, config, fleet_config)
        except sqlite3.Error as exc:
            rows, gap = [], ("Missing fleet attention facts: the store is "
                             "not readable (%s)." % type(exc).__name__)
        sections["attention"] = rows
        sections["attention_gap"] = gap

        block = asof_block(src)
        charts = {
            "theta": theta_series(src),
            "tao": [v for _d, v in vitals_series(src, "tao_usd")],
            "shares": share_distribution(src),
        }
        if lead:
            charts["mover"] = dict(
                lead, series=netuid_series(src, lead["netuid"],
                                           lead["column"]))
    finally:
        src.close()

    sections["attention_groups"] = group_attention(
        sections.get("attention") or [])
    return {"asof_time": now.strftime("%Y-%m-%d %H:%M UTC"),
            "asof_block": block, "first_edition": first_edition,
            "window_start": start, "sections": sections, "figures": figures,
            "charts": charts, "lede": _lede(sections, figures, charts),
            "prev_theta": prev.get("theta")}


def _lede(sections: Dict[str, Any], figures: Dict[str, Any],
          charts: Dict[str, Any]) -> str:
    """One sentence naming the largest recorded movement in this edition.
    Derived from the facts already assembled; it states nothing the page
    does not also show, and falls back to the quiet case rather than
    reaching for something to say."""
    mover = charts.get("mover")
    if mover:
        return ("SN%d moved %s on %s in this window."
                % (mover["netuid"], mover["pct"], mover["kind"]))
    theta = figures.get("theta")
    if theta is not None and figures.get("rank") is not None:
        return ("The bar held at %s and no subnet crossed it."
                % _num(theta, 5))
    return "No recorded figure moved in this window."


# ---------------------------------------------------------------------------
# Render. The shell's exact shape and CSS, with the section bodies filled.
# Every interpolated value is escaped.
# ---------------------------------------------------------------------------

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Inter:wght@400;500;600;700&'
    'family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)

_CSS = """
:root{
  --bg:#0b0d10; --s1:#111419; --s2:#161a20; --line:#232830; --hair:#1a1f26;
  --fg:#eceef1; --fg2:#9aa3ad; --fg3:#646d78;
  --accent:#c9b98d; --accent-dim:#7a7057; --dn:#e2806c; --up:#74b98a;
  --r:14px; --pad:40px;
}
*{box-sizing:border-box}
body{
  margin:0;background:var(--bg);color:var(--fg);min-width:1100px;
  font:400 15.5px/1.6 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased;
  background-image:radial-gradient(1600px 620px at 8% -10%, rgba(201,185,141,.07), transparent 60%);
}
.mono{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
.bar{
  position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;
  padding:0 var(--pad);height:58px;background:rgba(11,13,16,.82);
  backdrop-filter:blur(14px);border-bottom:1px solid var(--line);
}
h1{margin:0;font-size:13.5px;font-weight:700;letter-spacing:.28em}
.tagline{color:var(--fg2);font-size:13.5px}
.asof{
  font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums;
  margin-left:auto;display:flex;align-items:center;gap:9px;font-size:12.5px;
  color:var(--fg2);background:var(--s1);border:1px solid var(--line);
  padding:6px 13px;border-radius:999px;
}
.pulse{width:6px;height:6px;border-radius:50%;background:var(--up);box-shadow:0 0 0 3px rgba(116,185,138,.14)}
.hero{
  display:grid;grid-template-columns:minmax(30ch,0.9fr) 2.1fr;gap:56px;
  align-items:center;padding:52px var(--pad) 46px;border-bottom:1px solid var(--hair);
}
.eyebrow{font-size:11px;letter-spacing:.22em;color:var(--accent-dim);font-weight:600;margin:0 0 14px}
.lede{margin:0;font-size:clamp(28px,2.5vw,44px);line-height:1.2;font-weight:600;letter-spacing:-.024em}
.lede em{font-style:normal;color:var(--accent)}
.edition{margin:16px 0 0;font-size:13px;color:var(--fg3)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.kpi{background:var(--s1);border:1px solid var(--line);border-radius:var(--r);padding:17px 19px 15px}
.kpi .k{font-size:11.5px;color:var(--fg2);letter-spacing:.04em;text-transform:uppercase}
.kpi .v{font-size:27px;font-weight:600;letter-spacing:-.022em;margin-top:7px;line-height:1.1}
.kpi .v small{font-size:14px;color:var(--fg3);font-weight:500}
.kpi .m{display:flex;gap:7px;align-items:baseline;font-size:12px;color:var(--fg3);margin-top:3px;flex-wrap:wrap}
.kpi .gap{font-size:13px;color:var(--fg3);margin-top:9px;line-height:1.4}
.spark{margin-top:11px;display:block}
.d{font-weight:600} .d.up{color:var(--up)} .d.dn{color:var(--dn)}
section{padding:44px var(--pad);border-bottom:1px solid var(--hair)}
section:last-of-type{border-bottom:0}
.sh{display:flex;align-items:center;gap:10px;margin:0 0 8px}
.sh svg{flex:none;color:var(--accent)}
h2{margin:0;font-size:12px;font-weight:600;letter-spacing:.18em;color:var(--fg2);text-transform:uppercase}
h3{margin:0 0 12px;font-size:11px;font-weight:600;letter-spacing:.2em;color:var(--fg3);text-transform:uppercase}
.take{margin:0 0 24px;font-size:20px;line-height:1.4;font-weight:500;letter-spacing:-.012em;max-width:78ch}
.panel{background:var(--s1);border:1px solid var(--line);border-radius:var(--r);padding:20px 22px}
.cap{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin-bottom:16px}
.cap .t{font-size:13px;font-weight:500}
.cap .n{font-size:12px;color:var(--fg3)}
.dist{width:100%;height:210px;display:block}
.dist .below{fill:#2a313a} .dist .above{fill:#49535f}
.dist .hi{fill:var(--accent)} .dist .fall{fill:var(--dn)}
.dist:hover rect{opacity:.4} .dist rect:hover{opacity:1}
.thresh{stroke:var(--fg2);stroke-width:1}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px;align-items:start}
.stack{display:flex;flex-direction:column;gap:16px}
.rows{display:flex;flex-direction:column}
.r{display:grid;grid-template-columns:9em 1fr auto;gap:20px;align-items:center;
   padding:13px 0;border-top:1px solid var(--hair)}
.r:first-child{border-top:0}
.id{display:flex;flex-direction:column;gap:1px}
.uid{font-size:14px;font-weight:600}
.nm{font-size:12px;color:var(--fg2)}
.why{font-size:14.5px;line-height:1.45}
.why .q{color:var(--fg3);font-size:12.5px;display:block;margin-top:3px}
.fig{text-align:right;font-size:20px;font-weight:600;letter-spacing:-.015em}
.fig .q{display:block;font-size:11px;color:var(--fg3);font-weight:400;margin-top:2px}
.facts{margin:0;padding:0;list-style:none;display:flex;flex-direction:column}
.facts li{padding:11px 0;border-top:1px solid var(--hair);font-size:14.5px;line-height:1.5}
.facts li:first-child{border-top:0}
.gap{color:var(--fg3);font-size:14px;line-height:1.5;margin:0 0 8px}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chip{font-size:12px;padding:3px 9px;border-radius:7px;background:var(--s2);
      border:1px solid var(--line);color:var(--fg2)}
.chip b{color:var(--fg);font-weight:600}
.grouphd{font-size:11px;letter-spacing:.14em;color:var(--fg3);margin:0 0 4px;
         padding-top:4px;text-transform:uppercase}
.meter{margin-top:14px}
.mtrack{height:7px;border-radius:99px;background:#232a33;overflow:hidden}
.mfill{height:100%;background:var(--accent);border-radius:99px}
.mlab{display:flex;justify-content:space-between;font-size:12px;color:var(--fg3);margin-top:9px}
footer{padding:34px var(--pad) 54px;color:var(--fg3);font-size:12.5px;display:flex;gap:13px;flex-wrap:wrap}
.dot{color:var(--line)}
"""

_ICON = {
    "network": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
               '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 '
               '0 18a14 14 0 0 1 0-18"/></svg>',
    "movers": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
              'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
              'stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/>'
              '<path d="M21 7v5h-5"/></svg>',
    "mining": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
              'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
              'stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/>'
              '<path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>',
    "attention": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
                 'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
                 '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1'
                 'M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>'
                 '<circle cx="12" cy="12" r="3.2"/></svg>',
    "code-narrative": '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
                      'stroke="currentColor" stroke-width="1.8" '
                      'stroke-linecap="round" stroke-linejoin="round">'
                      '<path d="M8 6l-5 6 5 6M16 6l5 6-5 6"/></svg>',
}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _facts_list(items: Sequence[Tuple[str, str]]) -> str:
    """Facts as a list, each gap as its own line. A section with neither
    still says so, because an empty landmark is not allowed to be silent."""
    facts = [t for kind, t in items if kind == "fact"]
    gaps = [t for kind, t in items if kind == "gap"]
    out = []
    if facts:
        out.append('<ul class="facts">')
        out.extend("<li>%s</li>" % _esc(t) for t in facts)
        out.append("</ul>")
    out.extend('<p class="gap">%s</p>' % _esc(t) for t in gaps)
    if not out:
        out.append('<p class="gap">Missing every input for this section.</p>')
    return "".join(out)


def _kpi(label: str, value: Optional[str], meta: str = "",
         extra: str = "", gap: str = "") -> str:
    """One stat tile. A figure the fact layer withheld (absent, or past its
    own stale bound) renders the gap by name and no number."""
    out = ['<div class="kpi"><div class="k">%s</div>' % _esc(label)]
    if value is None:
        out.append('<p class="gap">%s</p>' % _esc(gap or "not recorded"))
    else:
        out.append('<div class="v mono">%s</div>' % value)
        if meta:
            out.append('<div class="m">%s</div>' % meta)
        out.append(extra)
    out.append("</div>")
    return "".join(out)


def _section(sid: str, heading: str, take: str, body: str) -> List[str]:
    return ['<section id="%s">' % sid,
            '<div class="sh">%s<h2>%s</h2></div>'
            % (_ICON.get(sid, ""), _esc(heading)),
            '<p class="take">%s</p>' % _esc(take) if take else "",
            body, "</section>"]


def _hero(edition: Dict[str, Any]) -> str:
    figures = edition["figures"]
    charts = edition["charts"]
    theta = figures.get("theta")
    usd = figures.get("tao_usd")

    bar_meta = ""
    delta = _delta_value(theta, edition.get("prev_theta"))
    if delta:
        cls = "up" if delta.startswith("+") else "dn"
        bar_meta = ('<span class="d %s">%s</span><span>since last publish'
                    '</span>' % (cls, _esc(delta)))
    elif figures.get("rank") is not None:
        bar_meta = '<span>rank %s</span>' % _esc(figures["rank"])

    tiles = [
        _kpi("Emission-gate bar",
             None if theta is None else _esc(_num(theta, 5)),
             bar_meta,
             sparkline(charts.get("theta") or [], fill_id="sparkBar",
                       label="Emission-gate bar over recent observations"),
             gap="The bar is not recorded, or is past its stale bound."),
        _kpi("TAO", None if usd is None else "$" + _esc(_num(usd, 2)),
             '<span>observed %s</span>' % _esc(figures.get("vitals_date", "")),
             sparkline(charts.get("tao") or [], stroke="#9aa3ad",
                       fill_id="sparkTao",
                       label="TAO in USD over recorded days"),
             gap="Network vitals are not recorded."),
        _kpi("Staked",
             None if figures.get("staked") is None
             else "%s <small>TAO</small>" % _esc(_grouped(figures["staked"])),
             '<span class="d">%s%%</span><span>held by subnets</span>'
             % _esc(_num(figures.get("share_pct"), 2)),
             meter((figures.get("share_pct") or 0) / 100.0,
                   "subnets", "root and free"),
             gap="Stake is not recorded."),
        _kpi("Runtime spec",
             None if figures.get("spec") is None else _esc(figures["spec"]),
             '<span>%s</span>' % _esc(figures.get("release", "release not "
                                                  "recorded")),
             '<div class="chips" style="margin-top:18px">%s%s</div>'
             % ('<span class="chip"><b>%s</b> above the bar</span>'
                % _esc(figures["above"])
                if figures.get("above") is not None else "",
                '<span class="chip"><b>%s</b> side changes</span>'
                % _esc(figures["side_changes"])
                if figures.get("side_changes") is not None else ""),
             gap="The runtime spec is not recorded."),
    ]
    edition_note = ('<p class="edition">First edition. No previous publish '
                    'to compare against, so no figure shows a change.</p>'
                    if edition["first_edition"] else "")
    return ('<div class="hero"><div><p class="eyebrow">THIS EDITION</p>'
            '<p class="lede">%s</p>%s</div><div class="kpis">%s</div></div>'
            % (_esc(edition["lede"]), edition_note, "".join(tiles)))


def _attention_body(edition: Dict[str, Any]) -> str:
    groups = edition["sections"].get("attention_groups") or []
    if not groups:
        return ('<p class="gap">%s</p>'
                % _esc(edition["sections"].get("attention_gap")
                       or "Missing fleet attention facts."))
    panels = []
    for reason, rows in groups:
        body = []
        for row in rows:
            name = row.get("name")
            body.append(
                '<div class="r" style="grid-template-columns:9em 1fr">'
                '<div class="id"><span class="uid mono">SN%s</span>'
                '<span class="nm">%s</span></div><div class="why">%s</div>'
                '</div>'
                % (_esc(row["netuid"]),
                   _esc(name) if name else "name not recorded",
                   _esc(reason)))
        panels.append('<div class="panel"><p class="grouphd">%s &#183; %d</p>'
                      '<div class="rows">%s</div></div>'
                      % (_esc(reason), len(rows), "".join(body)))
    if len(panels) == 1:
        return panels[0]
    return ('<div class="grid">%s<div class="stack">%s</div></div>'
            % (panels[0], "".join(panels[1:])))


def _movers_body(edition: Dict[str, Any]) -> str:
    charts = edition["charts"]
    mover = charts.get("mover")
    items = edition["sections"].get("movers") or []
    if not mover:
        return '<div class="panel">%s</div>' % _facts_list(items)
    cls = "dn" if mover["raw"] < 0 else "up"
    lead = ('<div class="panel"><div class="r">'
            '<div class="id"><span class="uid mono">SN%s</span>'
            '<span class="nm">%s</span></div>'
            '<div class="why">%s<span class="q mono">%s</span></div>'
            '<div class="fig mono" style="color:var(--%s)">%s</div></div></div>'
            % (_esc(mover["netuid"]), _esc(mover["kind"]),
               sparkline(mover.get("series") or [], width=260, height=58,
                         stroke="#e2806c" if mover["raw"] < 0 else "#74b98a",
                         label="SN%s recent readings" % mover["netuid"]),
               _esc(mover["detail"]), cls, _esc(mover["pct"])))
    rest = [t for kind, t in items if kind == "fact"
            and not t.startswith("SN%d " % mover["netuid"])]
    side = "".join('<div class="panel">%s</div>' % _esc(t) for t in rest)
    gaps = "".join('<p class="gap">%s</p>' % _esc(t)
                   for kind, t in items if kind == "gap")
    return ('<div class="grid">%s<div class="stack">%s</div></div>%s'
            % (lead, side or '<div class="panel">Nothing else crossed a '
                             'threshold.</div>', gaps))


def render(edition: Dict[str, Any]) -> str:
    sections = edition["sections"]
    figures = edition["figures"]
    block = edition["asof_block"]
    asof = "as of %s \u00b7 block %s" % (
        edition["asof_time"], block if block is not None else "not recorded")

    dist = distribution_svg(
        edition["charts"].get("shares") or [], figures.get("rank"),
        falling=[edition["charts"]["mover"]["netuid"]]
        if edition["charts"].get("mover") else [])
    network_body = _facts_list(sections.get("network") or [])
    if dist:
        network_body = (
            '<div class="panel"><div class="cap">'
            '<div class="t">Demand share across the bar universe</div>'
            '<div class="n mono">%d subnets &#183; sorted &#183; log scale'
            '</div></div>%s</div>'
            '<div style="margin-top:16px">%s</div>'
            % (len(edition["charts"]["shares"]), dist, network_body))

    ranked = figures.get("mining_ranked")
    observed = figures.get("mining_observed")
    if ranked is not None and observed:
        head = figures.get("mining_head")
        mining_body = (
            '<div class="grid"><div class="panel"><div class="cap" '
            'style="margin:0"><div class="t">Ranked of observed</div>'
            '<div class="n mono">%s / %s</div></div>%s</div>'
            '<div class="panel"><div class="k" style="font-size:11.5px;'
            'color:var(--fg2);letter-spacing:.04em;text-transform:uppercase">'
            'Board head</div><div class="v mono" style="font-size:27px;'
            'font-weight:600;margin-top:7px">%s</div>'
            '<div style="font-size:13px;color:var(--accent);margin-top:2px">'
            '%s</div></div></div>'
            % (_esc(ranked), _esc(observed),
               meter(ranked / float(observed), "%s ranked" % _esc(ranked),
                     "%s cut" % _esc(observed - ranked)),
               "SN%s" % _esc(head) if head is not None else "not recorded",
               _esc(figures.get("mining_head_name") or "name not recorded")))
    else:
        mining_body = '<div class="panel">%s</div>' % _facts_list(
            sections.get("mining") or [])

    out: List[str] = [
        "<!DOCTYPE html>", '<html lang="en">', "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>shinogi</title>",
        '<meta name="description" content="A lean read on Bittensor subnets.">',
        _FONTS,
        "<style>" + _CSS + "</style>",
        "</head>", "<body>",
        '<div class="bar"><h1>SHINOGI</h1>'
        '<div class="tagline">%s</div>'
        '<div class="asof"><span class="pulse"></span>%s</div></div>'
        % (_esc(TAGLINE), _esc(asof)),
        _hero(edition),
    ]
    out += _section("network", "Network", "", network_body)
    out += _section("movers", "Subnet movers", "", _movers_body(edition))
    out += _section("mining", "Mining", "", mining_body)
    out += _section("attention", "Attention", "", _attention_body(edition))
    out += ['<section id="code-narrative">',
            '<div class="sh">%s<h2>Code / narrative</h2></div>'
            % _ICON["code-narrative"],
            '<div class="grid"><div><h3>Code</h3>'
            '<div class="panel">%s</div></div>'
            '<div><h3>Narrative</h3><div class="panel">%s</div></div></div>'
            % (_facts_list(sections.get("code") or []),
               _facts_list(sections.get("narrative") or [])),
            "</section>"]
    out += ["<footer><span>shinogi.dev</span><span class=\"dot\">&#183;</span>"
            "<span>public read-only</span><span class=\"dot\">&#183;</span>"
            "<span>data from Atlas</span><span class=\"dot\">&#183;</span>"
            "<span>every figure traces to a recorded row</span></footer>",
            "</body>", "</html>", ""]
    return "\n".join(x for x in out if x)


# ---------------------------------------------------------------------------
# Exclusion scan. Belt and braces on top of composing from facts: the guarded
# failure is a stored row that itself carries operator material, for example
# a verdict line quoting a path or an address. The composer cannot know that
# in advance; the scan can.
# ---------------------------------------------------------------------------

# The exact strings shinogi/tests/test_page_contract.py bans, first.
OPERATOR_TOKENS: Tuple[str, ...] = (
    "mining.budget_band",
    "TaoStats quota",
    "192.168.0.150",
    "t.me/",
    "api.telegram.org",
    "next: pick mining.budget_band",
    # The wider off-page list from the page contract.
    "budget_band",
    "budget band",
    "rent_band",
    "rent band",
    "hardware rung",
    "taostats",
    "watermark",
    "seed phrase",
    "mnemonic",
    "private key",
    "bot_token",
    "chat_id",
    "coldkey",
    "hotkey",
    "owner_ss58",
    "/home/pi",
    "localhost",
    "127.0.0.1",
    ":8480",
)

_LEAK_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("LAN address", r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))"
                    r"\.\d{1,3}\.\d{1,3}\b"),
    ("SS58 address", r"\b5[1-9A-HJ-NP-Za-km-z]{46,47}\b"),
    ("key material", r"\b0x[0-9a-fA-F]{64}\b"),
)

# The page contract's self-contained rules.
# What must never reach the page. Presentation may load a typeface and run
# script; pulling a reported figure in the browser may not, because Atlas is
# the only writer and the page must read with scripting off.
_DATA_FETCH_TOKENS: Tuple[str, ...] = (
    "XMLHttpRequest", "fetch(", "EventSource", "new WebSocket",
    "navigator.sendBeacon", "@import",
)

_FONT_HOSTS: Tuple[str, ...] = ("fonts.googleapis.com", "fonts.gstatic.com")


def scan(document: str) -> List[str]:
    """Every reason this document must not be published. Empty means clean."""
    found: List[str] = []
    lowered = document.lower()
    for token in OPERATOR_TOKENS:
        if token.lower() in lowered:
            found.append("operator token %r" % token)
    for label, pattern in _LEAK_PATTERNS:
        match = re.search(pattern, document)
        if match is not None:
            found.append("%s %r" % (label, match.group(0)))
    for token in _DATA_FETCH_TOKENS:
        if token.lower() in lowered:
            found.append("browser data fetch %r" % token)
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', document):
        if not any(host in url for host in _FONT_HOSTS):
            found.append("external asset that is not a typeface %r" % url)
    if re.search(r'<script[^>]*\ssrc=', document, re.I):
        found.append("external script")
    for tag in re.findall(r'<link[^>]*>', document, re.I):
        if "stylesheet" not in tag.lower():
            continue
        href = re.search(r'href="([^"]*)"', tag)
        target = href.group(1) if href else ""
        if not any(host in target for host in _FONT_HOSTS):
            found.append("stylesheet that is not a typeface source %r"
                         % target)
    return found


# ---------------------------------------------------------------------------
# Publish. Hash-gated and one direction only: no file in the checkout other
# than the published document is read, and never as an input to an edition.
# ---------------------------------------------------------------------------

# The pass runs from a timer with no terminal. Git must never sit waiting
# for a credential prompt: the Pi reaches GitHub over HTTPS anonymously and
# holds no key, so a push has nothing to authenticate with. Without these,
# an interactive run would block on "Username for https://github.com" and a
# oneshot unit would hang instead of failing.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true",
            "SSH_ASKPASS": "/bin/true", "GIT_SSH_COMMAND":
            "ssh -o BatchMode=yes"}

_GIT_TIMEOUT = 120


def _git(cwd: str, *args: str) -> Tuple[int, str, str]:
    env = dict(os.environ)
    env.update(_GIT_ENV)
    env.pop("GIT_DIR", None)
    try:
        proc = subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                              text=True, env=env, stdin=subprocess.DEVNULL,
                              timeout=_GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ShinogiError("git %s did not finish in %ds"
                           % (args[0] if args else "", _GIT_TIMEOUT))
    return proc.returncode, proc.stdout, proc.stderr


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_ASOF_RE = re.compile(r'(<div class="asof">).*?(</div>)', re.S)


def fact_digest(document: str) -> str:
    """The content hash with the as-of line normalised out.

    The as-of line carries the compose time, which moves on every pass. A
    plain document hash would therefore differ every six hours and the
    gate would never hold, committing a new timestamp over unchanged facts
    about 124 times a month. Gating on the facts means an edition is
    republished only when something it reports actually moved, and a page
    left in place keeps the compose time of the edition that is published,
    which is the time the contract asks it to state."""
    return _sha256(_ASOF_RE.sub(r"\1\2", document))


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def publish(config: Dict[str, Any], document: str) -> Dict[str, Any]:
    """Write, hash-gate, commit and push. Fails closed and leaves the
    checkout unchanged on any precondition failure. Creates and moves no
    credential."""
    checkout = os.path.expanduser(config["checkout_dir"])
    page = config.get("page_file", "index.html")
    target = os.path.join(checkout, page)
    digest = _sha256(document)

    if not os.path.isdir(checkout):
        raise ShinogiError("shinogi checkout %s does not exist" % checkout)
    if not os.path.isdir(os.path.join(checkout, ".git")):
        raise ShinogiError("shinogi checkout %s is not a git repository"
                           % checkout)
    code, out, err = _git(checkout, "status", "--porcelain")
    if code != 0:
        raise ShinogiError("cannot read the checkout state: %s"
                           % (err.strip() or out.strip()))
    if out.strip():
        raise ShinogiError("shinogi checkout %s is dirty; refusing to write "
                           "over uncommitted work" % checkout)

    # Anyone may commit to the shinogi repo directly (the contract and its
    # test live there). A checkout left behind origin would have its push
    # rejected, and an unattended timer cannot resolve that, so sync first.
    # Fast-forward only: a diverged checkout is an operator problem, not
    # something this pass may paper over with a merge.
    branch = config.get("branch", "main")
    code, out, err = _git(checkout, "fetch", "--quiet", "origin", branch)
    if code != 0:
        raise ShinogiError("cannot reach origin/%s: %s"
                           % (branch, err.strip() or out.strip()))
    code, counts, _err = _git(checkout, "rev-list", "--left-right",
                              "--count", "HEAD...FETCH_HEAD")
    if code == 0 and counts.split():
        ahead, behind = (int(x) for x in counts.split())
        if behind and ahead:
            raise ShinogiError(
                "shinogi checkout has diverged from origin/%s (%d ahead, "
                "%d behind); refusing to publish over it" % (branch, ahead,
                                                             behind))
        if behind:
            code, out, err = _git(checkout, "merge", "--ff-only",
                                  "FETCH_HEAD")
            if code != 0:
                raise ShinogiError("cannot fast-forward to origin/%s: %s"
                                   % (branch, err.strip() or out.strip()))

    code, committed, _err = _git(checkout, "show", "HEAD:%s" % page)
    if code == 0 and fact_digest(committed) == fact_digest(document):
        return {"changed": False, "sha256": digest, "path": target,
                "pushed": False}

    _atomic_write(target, document)
    code, out, err = _git(checkout, "add", page)
    if code != 0:
        raise ShinogiError("cannot stage %s: %s" % (page, err.strip()))
    code, out, err = _git(
        checkout,
        "-c", "user.name=%s" % config.get("commit_name", "vanlabs-dev"),
        "-c", "user.email=%s" % config.get("commit_email", "vanlabs@pm.me"),
        "commit", "-m", "Publish edition")
    if code != 0:
        raise ShinogiError("cannot commit: %s" % (err.strip() or out.strip()))

    # A failed push leaves the local commit in place and the last deploy
    # live. Recovering it is the operator's call; this does not reset.
    code, out, err = _git(checkout, "push", "origin", branch)
    if code != 0:
        raise ShinogiError(
            "cannot push to origin/%s: %s. The commit is local and "
            "recoverable; nothing was reset."
            % (branch, err.strip() or out.strip()))
    return {"changed": True, "sha256": digest, "path": target, "pushed": True}


# ---------------------------------------------------------------------------
# Pass and CLI
# ---------------------------------------------------------------------------

def build(config: Dict[str, Any], state: Optional[sqlite3.Connection],
          now: Optional[datetime.datetime] = None
          ) -> Tuple[Dict[str, Any], str, List[str]]:
    """Compose, render and scan. Writes nothing anywhere."""
    edition = compose(config, state, now=now)
    document = render(edition)
    return edition, document, scan(document)


def run(config: Dict[str, Any], now: Optional[datetime.datetime] = None
        ) -> Dict[str, Any]:
    """The full pass. Composes, scans, and publishes when the content hash
    has moved. Persists the figure set only after a successful publish, so
    an unpublished edition does not consume the comparison point."""
    if not config.get("enabled"):
        return {"status": "disabled"}
    state = open_state(_tg().resolve(config["state_db"]))
    try:
        edition, document, leaks = build(config, state, now=now)
        if leaks:
            raise ShinogiError("refusing to publish: %s" % "; ".join(leaks))
        checkout = os.path.expanduser(config["checkout_dir"])
        target = os.path.join(checkout, config.get("page_file", "index.html"))
        if not config.get("publish"):
            return {"status": "composed", "published": False,
                    "would_write": target, "bytes": len(document),
                    "sha256": _sha256(document),
                    "first_edition": edition["first_edition"]}
        result = publish(config, document)
        if result["changed"]:
            state_set(state, "figures", json.dumps(edition["figures"],
                                                   sort_keys=True))
            state_set(state, "published_at", _utc(now).isoformat())
            state_set(state, "content_sha256", result["sha256"])
        return {"status": "published" if result["changed"] else "unchanged",
                "published": result["changed"], "path": result["path"],
                "bytes": len(document), "sha256": result["sha256"],
                "first_edition": edition["first_edition"]}
    finally:
        state.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_shinogi",
        description="Atlas shinogi renderer: compose the public edition "
                    "from the Atlas stores and publish it on a content "
                    "change.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    comp = sub.add_parser("compose", help="print the edition and the scan "
                                          "result; write nothing")
    comp.add_argument("--dry-run", action="store_true",
                      help="the default: nothing is written")
    comp.add_argument("--out", default=None,
                      help="also write the document to this path")
    sub.add_parser("publish", help="run the full pass")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config or CONFIG_FILE)
        if not config.get("enabled"):
            print(json.dumps({"status": "disabled"}, indent=2))
            return 0
        if args.command == "compose":
            state_path = _tg().resolve(config["state_db"])
            state = open_state(state_path) if os.path.exists(state_path) \
                else None
            try:
                edition, document, leaks = build(config, state)
            finally:
                if state is not None:
                    state.close()
            if args.out:
                _atomic_write(args.out, document)
            sys.stdout.write(document)
            summary = {"scan": leaks or "clean", "bytes": len(document),
                       "sha256": _sha256(document),
                       "first_edition": edition["first_edition"],
                       "window_start": edition["window_start"],
                       "asof_block": edition["asof_block"],
                       "written": args.out}
            print(json.dumps(summary, indent=2, sort_keys=True),
                  file=sys.stderr)
            return 0 if not leaks else 2
        print(json.dumps(run(config), indent=2, sort_keys=True))
        return 0
    except ShinogiError as exc:
        print("fatal: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
