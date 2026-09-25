#!/usr/bin/env python3
"""Atlas subnt publisher (changes: subnt-renderer, subnt-json-export).

Composes the public subnt.dev edition from rows already persisted in the
livedata and fleet stores, all opened read-only, as six data files that
the subnt page builds from: `edition.json` and one file per section. The
files follow schema `subnt/1.x`; a copy of the subnt schema lives at
`subnt/schema/subnt-1.0.json` and every file is validated against it
before anything is written. Composing makes no chain call, no provider
call and no model call: every figure traces to a stored row with its
reference block or observation date, and an input that is missing or past
its own stale bound is named instead of estimated.

This module is a second reader over those stores, not a wrapper around the
Telegram briefing. `telegram/atlas_briefing.py` returns operator lines and
closes with the LAN board URL or a next action; carrying those over would
publish the board address, the provider quota and the budget-band prompt
to the open internet. `_Sources`, `_movers`, `_delta_pct` and
`_release_for_upgrade` are imported and reused; nothing formatted for
Telegram crosses into the data.

Stale bounds are per input. The emission-gate bar uses the briefing bound
of 26 hours. Network vitals carry their observation date and are never
called stale for age alone. Movers use the window since the previous
subnt publish, or `window_hours` before compose on a first edition.

The publish path is one direction only: Atlas writes subnt's `data/`, and
no file in the subnt checkout is read as an input to an edition. Before
any write every file is scanned for operator material and validated
against the schema; a hit fails the pass closed. Atlas renders no HTML:
layout belongs to the subnt repo.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.json")
SCHEMA_FILE = os.path.join(_MODULE_DIR, "schema", "subnt-1.0.json")

SCHEMA_VERSION = "subnt/1.0"

# Contract order: (section id, file name, question). The questions match
# the subnt page's own section list.
SECTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("network", "network",
     "What changed on the network since the last edition?"),
    ("movers", "movers", "Which subnets moved, and which crossed the bar?"),
    ("mining", "mining", "Where is mining worth a look now?"),
    ("attention", "attention",
     "Which subnets deserve a closer read, and why?"),
    ("code-narrative", "code",
     "Where is code shipping, and what is being adopted?"),
)

# Every file an edition consists of. The subnt build rejects any other name.
FILES: Tuple[str, ...] = ("edition",) + tuple(f for _s, f, _q in SECTIONS)

# Top-level fields that move on every pass or every publish without any
# fact moving. The publish gate ignores them.
_VOLATILE = ("composed_at", "block", "previous_composed_at")

# The reason token alone is not enough to publish. On the real fleet 93 of
# 106 public rows score `divergence`, so mapping the six tokens to six
# fixed phrases produces a list of near-identical lines that says nothing.
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


class SubntError(Exception):
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
        raise SubntError("cannot load config %s: %s" % (path, exc))
    for key in ("enabled", "publish", "checkout_dir", "state_db", "live_db",
                "fleet_db"):
        if key not in config:
            raise SubntError("config %s is missing %r" % (path, key))
    return config


STATE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def open_state(db_path: str) -> sqlite3.Connection:
    """The publisher's own store. Subnt deltas compare against the last
    subnt publish on a six-hour clock, which is a different series from
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
# Data shapes. Each helper builds one object of the subnt schema. Keys that
# carry nothing are left out rather than written as null, except `delta`,
# which a comparable figure always carries so that "did not move" is stated.
# ---------------------------------------------------------------------------

_NO_DELTA = object()


def _clean(text: Any) -> Optional[str]:
    """A stored string made fit for the public files. Recorded text can
    carry an em dash (a verdict line, a subnet name), which the schema and
    the house style both refuse; a comma says the same thing. Empty is
    None, so the caller names the gap instead of publishing a blank."""
    if text is None:
        return None
    out = re.sub(r"\s*\u2014\s*", ", ", str(text)).strip()
    return out or None


def _clip(text: str, limit: int) -> str:
    """Text shortened to at most `limit` characters on a word boundary,
    with an ellipsis marking the cut. A plain slice cut verdict lines
    mid-word ("the unused UAV share now goes to t"), which reads as a typo
    rather than a shortened line."""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "\u2026"


def _fact(fid: str, label: str, text: str, *, value: Any = None,
          unit: Optional[str] = None, headline: bool = False,
          ref_block: Optional[int] = None, observed: Optional[str] = None,
          freshness: Optional[str] = None,
          delta: Any = _NO_DELTA) -> Dict[str, Any]:
    fact: Dict[str, Any] = {"id": fid, "label": label, "text": text}
    if value is not None:
        fact["value"] = value
    if unit is not None:
        fact["unit"] = unit
    if headline:
        fact["headline"] = True
    if ref_block is not None:
        fact["ref_block"] = int(ref_block)
    if observed is not None:
        fact["observed"] = observed
    if freshness:
        fact["freshness"] = freshness
    if delta is not _NO_DELTA:
        fact["delta"] = delta
    return fact


def _block(bid: str, *, title: Optional[str] = None,
           facts: Optional[List[Dict[str, Any]]] = None,
           notes: Optional[List[str]] = None,
           gaps: Optional[List[str]] = None,
           **extra: Any) -> Dict[str, Any]:
    block: Dict[str, Any] = {"id": bid, "access": "public"}
    if title:
        block["title"] = title
    block["facts"] = facts or []
    block["notes"] = notes or []
    block["gaps"] = gaps or []
    for key in ("series", "rows", "groups"):
        if extra.get(key):
            block[key] = extra[key]
    return block


def _section(lead: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"lead": lead, "blocks": blocks}


def _series(sid: str, kind: str, label: str, caption: str,
            points: Sequence[float], **extra: Any) -> Optional[Dict[str, Any]]:
    """A recorded series, or None. Two points is the minimum that means
    anything; fewer yields no series rather than a misleading flat line."""
    if len(points) < 2:
        return None
    series: Dict[str, Any] = {"id": sid, "kind": kind, "label": label,
                              "caption": caption,
                              "points": [float(p) for p in points]}
    series.update({k: v for k, v in extra.items() if v is not None})
    return series


def _utc(now: Optional[datetime.datetime] = None) -> datetime.datetime:
    return now or datetime.datetime.now(datetime.timezone.utc)


def _stamp(moment: datetime.datetime) -> str:
    """The schema's `composed_at` form: UTC, to the second, `Z`."""
    return moment.astimezone(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


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
    """The signed change since the previous subnt publish, or None.
    A change that rounds to zero is suppressed: `+0.0%` is noise."""
    pct = _brief()._delta_pct(new, old)
    if not pct or pct in ("+0.0%", "-0.0%"):
        return None
    return pct


def _delta(new: Any, old: Any) -> Optional[Dict[str, str]]:
    """The schema delta object, or None when the figure did not move or
    has no prior value."""
    pct = _delta_value(new, old)
    if pct is None:
        return None
    return {"text": "%s since last publish" % pct,
            "direction": "down" if pct.startswith("-") else "up"}


# ---------------------------------------------------------------------------
# Fact layer. Each function re-derives its section from stored rows with the
# same SQL semantics the briefing uses, and returns the section (a lead and
# its blocks) plus the figures a later edition compares against. An absent
# store, an absent table or an empty result is a named gap, never an
# exception.
# ---------------------------------------------------------------------------

def network_facts(src: Any, cfg: Dict[str, Any], start: str,
                  prev: Dict[str, Any], now: datetime.datetime
                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    brief = _brief()
    facts: List[Dict[str, Any]] = []
    notes: List[str] = []
    gaps: List[str] = []
    series: List[Dict[str, Any]] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is None:
        return _section(
            "No network facts are recorded for this edition.",
            [_block("vitals", gaps=["Missing the live store: no network "
                                    "facts recorded."])]), figures

    bar_fresh = False
    row = live.execute(
        "SELECT theta, rank, above_count, observed_at FROM gate_state "
        "WHERE gate_active = 1 ORDER BY id DESC LIMIT 1").fetchone() \
        if brief._table(live, "gate_state") else None
    if row is None:
        gaps.append("Missing the emission-gate bar.")
    else:
        theta, rank, above, observed_at = row
        stale_hours = float(cfg.get("stale_hours", 26))
        cutoff = (now - datetime.timedelta(hours=stale_hours)).isoformat()
        if observed_at < cutoff:
            gaps.append(
                "The emission-gate bar is stale: last observed %s, past its "
                "%g hour bound." % (observed_at[:16], stale_hours))
        else:
            bar_fresh = True
            figures["theta"] = theta
            figures["rank"] = rank
            figures["above"] = above
            # rank and above_count are recorded per poll and either can be
            # NULL. State what is present and name what is not.
            bits = []
            if rank is not None:
                bits.append("rank %s" % _num(rank))
            if above is not None:
                bits.append("%s above" % _num(above))
            facts.append(_fact(
                "bar", "Emission-gate bar", _num(theta, 5), value=theta,
                headline=True, observed=observed_at[:10],
                freshness=", ".join(bits) or None,
                delta=_delta(theta, prev.get("theta"))))
            absent = [label for label, value in (("its rank", rank),
                                                 ("the above-bar count",
                                                  above))
                      if value is None]
            if absent:
                gaps.append("The bar is recorded without %s."
                            % " and ".join(absent))
            series.append(_series(
                "bar-trend", "line", "Emission-gate bar",
                "", theta_series(src)))

    vit = live.execute(
        "SELECT date, tao_usd, total_staked_tao, subnets_share_pct, "
        "new_accounts_today FROM network_vitals "
        "ORDER BY date DESC LIMIT 1").fetchone() \
        if brief._table(live, "network_vitals") else None
    if vit is None:
        gaps.append("Missing network vitals.")
    else:
        date, usd, staked, share, accounts = vit
        figures["tao_usd"] = usd
        figures["staked"] = staked
        figures["share_pct"] = share
        figures["accounts"] = accounts
        figures["vitals_date"] = date
        # Vitals are a daily observation. They carry their date and are not
        # stale for age alone.
        dated = "observed %s" % date
        if usd is None:
            gaps.append("TAO price is not recorded in the newest vitals.")
        else:
            facts.append(_fact(
                "tao", "TAO", "$%s" % _num(usd, 2), value=usd, unit="USD",
                headline=True, observed=date, freshness=dated,
                delta=_delta(usd, prev.get("tao_usd"))))
        if staked is None:
            gaps.append("Stake is not recorded in the newest vitals.")
        else:
            facts.append(_fact(
                "staked", "Staked", "%s TAO" % _grouped(staked),
                value=staked, unit="TAO", headline=True, observed=date,
                freshness=("%s%% held by subnets" % _num(share, 2)
                           if share is not None else dated)))
        if accounts is not None:
            facts.append(_fact(
                "accounts", "New accounts", _grouped(accounts),
                value=accounts, observed=date, freshness=dated))
        tao = vitals_series(src, "tao_usd")
        series.append(_series(
            "tao-trend", "line", "TAO in USD", "", [v for _d, v in tao]))

    spec = brief._one(live,
                      "SELECT value FROM meta WHERE key = 'last_live_spec'")
    if spec is None:
        gaps.append("Missing the runtime spec.")
    else:
        release = None
        try:
            release = _tg()._release_for_upgrade(
                cfg.get("repo_db", "var/repotrack/repotrack.db"), int(spec))
        except (ValueError, sqlite3.Error):
            release = None
        figures["spec"] = int(spec)
        facts.append(_fact("spec", "Runtime spec", str(spec),
                           value=int(spec), headline=True))
        subject = _clean(release["subject"]) if release is not None else None
        if subject:
            figures["release"] = subject
            notes.append("Runtime spec %s, released as %s." % (spec, subject))

    moves = None
    if brief._table(live, "gate_events"):
        moves = brief._one(live, "SELECT COUNT(*) FROM gate_events "
                                 "WHERE observed_at > ?", (start,))
        figures["side_changes"] = moves
        facts.append(_fact("side-changes", "Side changes at the bar",
                           _num(moves), value=moves,
                           freshness="in this window"))

    if brief._table(live, "chain_param_events"):
        for item, prev_v, new_v in live.execute(
                "SELECT item, prev_value, new_value FROM chain_param_events "
                "WHERE observed_at > ? ORDER BY id", (start,)).fetchall():
            notes.append("Rule change: %s moved from %s to %s."
                         % (_clean(item), _clean(prev_v), _clean(new_v)))

    if bar_fresh:
        shares = share_distribution(src)
        rank = figures.get("rank")
        zero = sum(1 for _n, v in shares if not v)
        caption = "%s sorted by demand share, log scale" % _plural(
            len(shares), "subnet", "subnets")
        if rank is not None and 0 < rank <= len(shares):
            caption += "; the bar sits at rank %d" % rank
        if zero:
            caption += "; %d at zero share" % zero
        series.append(_series(
            "share-strip", "strip", "Demand share across the bar universe",
            caption + ".", [v for _n, v in shares], log=True,
            mark=(rank - 1) if rank is not None and 0 < rank <= len(shares)
            else None))

    for item in series:
        if item is not None and not item["caption"]:
            item["caption"] = _trend_caption(item)

    if bar_fresh:
        lead = "The bar is at %s" % _num(figures["theta"], 5)
        if figures.get("above") is not None:
            lead += " with %s above it" % _plural(
                int(figures["above"]), "subnet", "subnets")
        if moves == 0:
            lead += "; no subnet crossed it"
        elif isinstance(moves, int):
            lead += "; %s at the bar in this window" % _plural(
                moves, "side change", "side changes")
        lead += "."
    elif figures.get("tao_usd") is not None:
        lead = ("The bar is not current; TAO is at $%s, observed %s."
                % (_num(figures["tao_usd"], 2), figures["vitals_date"]))
    else:
        lead = "The network facts for this edition are missing."
    return _section(lead, [_block(
        "vitals", facts=facts, notes=notes, gaps=gaps,
        series=[s for s in series if s is not None])]), figures


def _trend_caption(series: Dict[str, Any]) -> str:
    """States the figures a trend shows: how many readings, first and last."""
    points = series["points"]
    if series["id"] == "bar-trend":
        return ("Emission-gate bar over the last %d readings, from %s to %s."
                % (len(points), _num(points[0], 5), _num(points[-1], 5)))
    return ("TAO over the last %d daily readings, from $%s to $%s."
            % (len(points), _num(points[0], 2), _num(points[-1], 2)))


_MOVER_KINDS = (
    # (panel column, public label, threshold key, default, limit)
    ("moving_price_tao", "alpha price", "price_move_threshold_pct", 15, 6),
    ("share", "demand share", "share_move_threshold_pct", 25, 4),
)


def _mover_reading(column: str, value: float) -> str:
    if column == "share":
        return "%.4f%%" % (value * 100)
    return "%.5f TAO" % value


def mover_facts(src: Any, cfg: Dict[str, Any], start: str
                ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """(section, lead). The largest mover is returned alongside the section
    so compose can name it in the edition headline."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return _section(
            "Movers cannot be ranked for this edition.",
            [_block("board", gaps=["Missing panel snapshots: no movers can "
                                   "be ranked."])]), None

    names = recorded_names(src)
    rows: List[Dict[str, Any]] = []
    lead: Optional[Dict[str, Any]] = None
    for column, kind, key, default, limit in _MOVER_KINDS:
        for netuid, old, new, ob, nb, pct in brief._movers(
                live, start, column, float(cfg.get(key, default)), limit):
            detail = ("%s at block %s to %s at block %s"
                      % (_mover_reading(column, old), ob,
                         _mover_reading(column, new), nb))
            figure = "%+.1f%%" % pct
            rows.append({
                "netuid": int(netuid),
                "name": _clean(names.get(int(netuid))),
                "summary": kind, "figure": figure, "sort": round(pct, 1),
                "detail": [_fact("move", "Reading", "SN%d %s %s, from %s."
                                 % (netuid, kind, figure, detail))]})
            if lead is None or abs(pct) > abs(lead["raw"]):
                lead = {"netuid": int(netuid), "kind": kind, "pct": figure,
                        "raw": pct, "column": column, "detail": detail}

    notes: List[str] = []
    if not rows:
        notes.append("No subnet crossed a mover threshold in this window.")
    risk = [r[0] for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND dereg_risk_level = 'high' ORDER BY netuid")]
    if risk:
        notes.append("High deregistration risk: %s." % _sn_list(risk[:8]))
    contested = [r[0] for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND (conviction_is_contested = 1 OR takeover_eligible = 1) "
        "ORDER BY netuid")]
    if contested:
        notes.append("Ownership contested or takeover-eligible: %s."
                     % _sn_list(contested[:8]))
    if brief._table(live, "gate_sides"):
        try:
            hover = [r[0] for r in live.execute(
                "SELECT netuid FROM gate_sides WHERE hovering = 1 "
                "ORDER BY netuid")]
        except sqlite3.Error:
            hover = []
        if hover:
            notes.append("Hovering at the bar (%d): %s."
                         % (len(hover), _sn_list(hover)))

    blocks: List[Dict[str, Any]] = []
    if lead is not None:
        label = "SN%d %s" % (lead["netuid"], lead["kind"])
        points = netuid_series(src, lead["netuid"], lead["column"])
        trend = None
        if len(points) >= 2:
            trend = _series(
                "lead-mover-trend", "line", label,
                "%s over the last %d readings, from %s to %s."
                % (label, len(points),
                   _mover_reading(lead["column"], points[0]),
                   _mover_reading(lead["column"], points[-1])), points)
        blocks.append(_block(
            "lead", facts=[_fact("lead-mover", label, lead["pct"],
                                 value=round(lead["raw"], 1), unit="%",
                                 headline=True, freshness=lead["detail"])],
            series=[trend] if trend else []))
        text = ("SN%d moved %s on %s in this window."
                % (lead["netuid"], lead["pct"], lead["kind"]))
    else:
        text = "No subnet crossed a mover threshold in this window."
    blocks.append(_block(
        "board", notes=notes,
        rows={"label": "Movers this window", "sortable": True,
              "items": rows} if rows else None))
    return _section(text, blocks), lead


def mining_facts(src: Any, cfg: Dict[str, Any], prev: Dict[str, Any]
                 ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The ranking the last complete mining pass stored, read through the
    briefing's shared reader so the page and the pulse report identical
    counts and head. Rent, the budget band and the hardware rung are
    operator material and stay off the page."""
    brief = _brief()
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None or not brief._table(fleet, "mine_econ"):
        return _section("No mining pass is recorded for this edition.",
                        [_block("board", gaps=["Missing the mining "
                                               "screen."])]), figures
    board = brief.stored_mining(fleet)
    if board is None:
        return _section("No mining pass is recorded for this edition.",
                        [_block("board", gaps=["Missing a mining pass: no "
                                               "classified pass yet."])]), \
            figures

    facts: List[Dict[str, Any]] = []
    notes: List[str] = []
    gaps: List[str] = []
    ranked = board["ranked"]
    top = [netuid for netuid, _ in ranked[:10]]
    figures["mining_top10"] = top
    figures["mining_model_version"] = board["model_version"]
    figures["mining_observed"] = board["observed"]
    figures["mining_ranked"] = len(ranked)
    figures["mining_cut"] = board["cut"]
    figures["mining_unrated"] = len(board["unrated"])

    facts.append(_fact(
        "ranked", "Ranked of observed",
        "%d / %d" % (len(ranked), board["observed"]), headline=True,
        freshness="%d cut, %d unrated" % (board["cut"],
                                          len(board["unrated"]))))
    head_name = None
    if not ranked:
        gaps.append("Missing a ranked mining head: no observed subnet was "
                    "ranked.")
    else:
        netuid, name = ranked[0]
        head_name = _clean(name)
        figures["mining_head"] = netuid
        figures["mining_head_name"] = head_name
        facts.append(_fact("head", "Board head", "SN%d" % netuid,
                           value=netuid, headline=True,
                           freshness=head_name or "name not recorded"))
    if board["unrated"]:
        gaps.append("Unrated, no figure: %s."
                    % _sn_list([n for n, _ in board["unrated"]]))

    state, entered, left = brief.mining_top_delta(prev, top,
                                                  board["model_version"])
    if state == "model-changed":
        notes.append("Top-ten changes are not compared: the mining model "
                     "changed since the last publish.")
    elif state == "changed":
        if entered:
            notes.append("Entered the top ten: %s." % _sn_list(entered))
        if left:
            notes.append("Left the top ten: %s." % _sn_list(left))
    elif state == "unchanged":
        notes.append("The top ten is unchanged since the last publish.")

    items = [{"netuid": int(n), "name": _clean(nm),
              "summary": "top ten, position %d" % (i + 1), "sort": i + 1}
             for i, (n, nm) in enumerate(ranked[:10])]
    if ranked:
        netuid = ranked[0][0]
        lead = ("SN%d%s heads the mining board; %d of %d observed subnets "
                "rank." % (netuid, ", %s," % head_name if head_name else "",
                           len(ranked), board["observed"]))
    else:
        lead = "No observed subnet ranks on the mining board."
    return _section(lead, [_block(
        "board", facts=facts, notes=notes, gaps=gaps,
        rows={"label": "Top ten on the mining board", "sortable": False,
              "items": items} if items else None)]), figures


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
    """Rows for the attention section, or a gap. `build_board` already runs
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
        rows.append({"netuid": netuid, "name": _clean(names.get(int(netuid))),
                     "why": why_phrase(item["sc"])})
    if not rows:
        return [], "Missing attention rows: no subnet carries a public " \
                   "attention signal."
    return rows, None


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


def attention_section(rows: List[Dict[str, Any]], gap: Optional[str]
                      ) -> Dict[str, Any]:
    """One block of groups. Each group states its reason once with its
    membership count; rows carry netuid, recorded name and reason only."""
    if not rows:
        return _section("No subnet carries a public attention signal in "
                        "this edition.",
                        [_block("groups", gaps=[gap or "Missing fleet "
                                                "attention facts."])])
    groups = group_attention(rows)
    out = []
    for reason, members in groups:
        out.append({
            "label": "%s: %s" % (reason, _plural(len(members), "subnet",
                                                  "subnets")),
            "rows": [{"netuid": int(r["netuid"]), "name": r.get("name"),
                      "summary": reason} for r in members]})
    unnamed = [r["netuid"] for r in rows if not r.get("name")]
    gaps = (["Name not recorded for %s." % _sn_list(unnamed)]
            if unnamed else [])
    lead = "%s deserve a closer read" % _plural(len(rows), "subnet",
                                                "subnets")
    largest = max(groups, key=lambda g: len(g[1]))
    if len(groups) > 1 and len(largest[1]) > 1:
        lead += "; %d share one reason: %s" % (len(largest[1]), largest[0])
    elif len(groups) == 1 and len(rows) > 1:
        lead += "; all share one reason: %s" % largest[0]
    return _section(lead + ".", [_block("groups", gaps=gaps, groups=out)])


def code_facts(src: Any, cfg: Dict[str, Any], start: str,
               prev: Dict[str, Any]
               ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The `code` block, and the lead of the code-narrative section."""
    brief = _brief()
    facts: List[Dict[str, Any]] = []
    notes: List[str] = []
    gaps: List[str] = []
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None:
        return _section("Code activity is missing for this edition.",
                        [_block("code", title="Code",
                                gaps=["Missing the fleet store: no code "
                                      "facts."])]), figures

    lead = "The seven-day push count is missing for this edition."
    latest = brief._one(fleet, "SELECT MAX(pass_ts) FROM metric_activity") \
        if brief._table(fleet, "metric_activity") else None
    if not latest:
        gaps.append("Missing the seven-day push count.")
    else:
        # The stored seven-day fact, not a count over the publish window.
        pushed, total = fleet.execute(
            "SELECT SUM(c7 > 0), COUNT(*) FROM metric_activity "
            "WHERE pass_ts = ?", (latest,)).fetchone()
        figures["pushed_7d"] = pushed
        figures["tracked"] = total
        facts.append(_fact(
            "pushed", "Pushed in 7 days", "%s / %s" % (_num(pushed),
                                                       _num(total)),
            value=pushed, headline=True, freshness="tracked subnets",
            delta=_delta(pushed, prev.get("pushed_7d"))))
        lead = ("%s of %s tracked subnets pushed code in the last seven "
                "days." % (_num(pushed), _num(total)))

    if not brief._table(fleet, "signal_econ_verdicts"):
        gaps.append("Missing incentive-code verdicts.")
    else:
        highs = fleet.execute(
            "SELECT netuid, what_changed, new_sha FROM signal_econ_verdicts "
            "WHERE created_at > ? AND significance = 'high' "
            "ORDER BY created_at DESC LIMIT 5", (start,)).fetchall()
        for netuid, what, sha in highs:
            notes.append(
                "SN%d, %s, at commit %s."
                % (netuid, _clip(_clean(what) or "no verdict line", 90),
                   sha[:12] if sha else "not recorded"))
        med = brief._one(fleet, "SELECT COUNT(*) FROM signal_econ_verdicts "
                                "WHERE created_at > ? AND significance = "
                                "'med'", (start,))
        figures["high_count"] = len(highs)
        figures["med_count"] = med
        notes.append(
            "%s and %s of middling significance in the window."
            % (_plural(len(highs), "material incentive-code change",
                       "material incentive-code changes"), _num(med)))

    if brief._table(fleet, "epochs"):
        for netuid, epoch in fleet.execute(
                "SELECT netuid, epoch FROM epochs WHERE opened_at > ? "
                "AND epoch > 1 ORDER BY opened_at DESC LIMIT 5",
                (start,)).fetchall():
            notes.append("SN%d re-pointed its repository (epoch %d)."
                         % (netuid, epoch))
    return _section(lead, [_block("code", title="Code", facts=facts,
                                  notes=notes, gaps=gaps)]), figures


def narrative_facts(src: Any, start: str) -> Dict[str, Any]:
    """The `narrative` block of the code-narrative section."""
    brief = _brief()
    fleet = src.fleet
    if fleet is None or not brief._table(fleet, "signal_adoptions"):
        return _block("narrative", title="Narrative",
                      gaps=["Missing the adoption ledger."])
    notes: List[str] = []
    # Model identifiers only. Dependency-kind terms say nothing about a
    # subnet's direction and the contract excludes them.
    for term, netuids in fleet.execute(
            "SELECT term, GROUP_CONCAT(DISTINCT netuid) FROM "
            "signal_adoptions WHERE kind = 'model-id' AND seeded = 0 "
            "AND adopted_at > ? GROUP BY term ORDER BY COUNT(*) DESC "
            "LIMIT 6", (start,)).fetchall():
        notes.append("Model %s adopted by %s."
                     % (_clean(term), _sn_list((netuids or "").split(","))))
    if brief._table(fleet, "signal_events"):
        for (term,) in fleet.execute(
                "SELECT term FROM signal_events WHERE class = "
                "'narrative-cluster' AND created_at > ?", (start,)).fetchall():
            notes.append("A cluster formed around %s." % _clean(term))
    return _block("narrative", title="Narrative", notes=notes or [
        "No model-identifier adoption and no cluster formed in this "
        "window."])


# ---------------------------------------------------------------------------
# Series. Drawn from recorded rows like every other figure: a series that is
# not recorded yields an empty list and no series is emitted.
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
        raise SubntError("refusing an unrecognised vitals column %r"
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
        raise SubntError("refusing an unrecognised panel column %r"
                         % column)
    rows = live.execute(
        "SELECT %s FROM panel_snapshot WHERE netuid = ? AND %s IS NOT NULL "
        "ORDER BY id DESC LIMIT ?" % (column, column),
        (int(netuid), int(limit))).fetchall()
    return [r[0] for r in rows][::-1]


def asof_block(src: Any) -> Optional[int]:
    """Newest recorded chain block from the panel snapshot."""
    brief = _brief()
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return None
    block = brief._one(live, "SELECT MAX(block_number) FROM panel_snapshot")
    return int(block) if block is not None else None


# ---------------------------------------------------------------------------
# Compose. Pure read: resolves the window, assembles the sections, and
# returns the six documents and the new figure set. Persisting figures
# belongs to publish, so a composed but unpublished edition does not consume
# the comparison point.
# ---------------------------------------------------------------------------

def _unreadable(name: str, exc: Exception) -> str:
    return ("Missing %s facts: the store is not readable (%s)."
            % (name, type(exc).__name__))


def compose(config: Dict[str, Any], state: Optional[sqlite3.Connection],
            now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    now = _utc(now)
    prev_raw = state_get(state, "figures") if state is not None else None
    prev_at = state_get(state, "published_at") if state is not None else None
    first_edition = prev_at is None
    # A first edition shows no deltas, whatever a stray figure set says.
    prev: Dict[str, Any] = (json.loads(prev_raw)
                            if prev_raw and not first_edition else {})
    if first_edition:
        start = (now - datetime.timedelta(
            hours=float(config.get("window_hours", 6)))).isoformat()
        previous_composed_at = None
    else:
        start = prev_at
        previous_composed_at = _stamp(
            datetime.datetime.fromisoformat(prev_at))

    src = _brief()._Sources(config)
    sections: Dict[str, Dict[str, Any]] = {}
    figures: Dict[str, Any] = {}
    lead: Optional[Dict[str, Any]] = None
    try:
        try:
            fleet_config = _fleet().load_config()
        except Exception:
            fleet_config = {}

        try:
            sections["network"], figs = network_facts(src, config, start,
                                                      prev, now)
            figures.update(figs)
        except sqlite3.Error as exc:
            sections["network"] = _section(
                "The network facts for this edition are missing.",
                [_block("vitals", gaps=[_unreadable("network", exc)])])
        try:
            sections["movers"], lead = mover_facts(src, config, start)
        except sqlite3.Error as exc:
            sections["movers"] = _section(
                "Movers cannot be ranked for this edition.",
                [_block("board", gaps=[_unreadable("movers", exc)])])
        try:
            sections["mining"], figs = mining_facts(src, config, prev)
            figures.update(figs)
        except sqlite3.Error as exc:
            sections["mining"] = _section(
                "No mining pass is recorded for this edition.",
                [_block("board", gaps=[_unreadable("mining", exc)])])
        try:
            rows, gap = attention_rows(src, config, fleet_config)
        except sqlite3.Error as exc:
            rows, gap = [], _unreadable("fleet attention", exc)
        sections["attention"] = attention_section(rows, gap)
        try:
            code, figs = code_facts(src, config, start, prev)
            figures.update(figs)
        except sqlite3.Error as exc:
            code = _section("Code activity is missing for this edition.",
                            [_block("code", title="Code",
                                    gaps=[_unreadable("code", exc)])])
        try:
            narrative = narrative_facts(src, start)
        except sqlite3.Error as exc:
            narrative = _block("narrative", title="Narrative",
                               gaps=[_unreadable("narrative", exc)])
        code["blocks"].append(narrative)
        sections["code-narrative"] = code
        block = asof_block(src)
    finally:
        src.close()

    composed_at = _stamp(now)
    edition: Dict[str, Any] = {
        "schema": SCHEMA_VERSION, "kind": "edition",
        "composed_at": composed_at, "block": block,
        "first_edition": first_edition,
        "previous_composed_at": previous_composed_at,
        "headline": _lede(lead, figures)}
    docs: Dict[str, Dict[str, Any]] = {"edition": edition}
    for sid, fname, question in SECTIONS:
        body = sections[sid]
        docs[fname] = {
            "schema": SCHEMA_VERSION, "kind": "section",
            "composed_at": composed_at, "block": block, "section": sid,
            "question": question, "lead": body["lead"], "access": "public",
            "blocks": body["blocks"]}
    return {"docs": docs, "figures": figures, "first_edition": first_edition,
            "window_start": start, "composed_at": composed_at,
            "block": block}


def _lede(lead: Optional[Dict[str, Any]], figures: Dict[str, Any]) -> str:
    """One sentence naming the largest recorded movement in this edition.
    It states nothing the files do not also carry, and falls back to the
    quiet case rather than reaching for something to say."""
    if lead:
        return ("SN%d moved %s on %s in this window."
                % (lead["netuid"], lead["pct"], lead["kind"]))
    theta = figures.get("theta")
    if theta is not None and figures.get("rank") is not None:
        return ("The bar held at %s and no subnet crossed it."
                % _num(theta, 5))
    return "No recorded figure moved in this window."


def serialise(doc: Dict[str, Any]) -> str:
    """The exact text written. Not ASCII-escaped, so the scan reads what the
    subnt build reads: a token or an em dash cannot hide behind `\\u`."""
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


# ---------------------------------------------------------------------------
# Exclusion scan. Belt and braces on top of composing from facts: the guarded
# failure is a stored row that itself carries operator material, for example
# a verdict line quoting a path or an address. The composer cannot know that
# in advance; the scan can.
# ---------------------------------------------------------------------------

# The exact strings the subnt build bans (src/lib/leak.mjs), first.
OPERATOR_TOKENS: Tuple[str, ...] = (
    "mining.budget_band",
    "budget_band",
    "TaoStats quota",
    "TAOSTATS_API_KEY",
    "192.168.0.150",
    "t.me/",
    "api.telegram.org",
    "next: pick mining.budget_band",
    "rent_band",
    "watermark",
    # The wider off-page list from the page contract.
    "budget band",
    "rent band",
    "hardware rung",
    "taostats",
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

# The subnt build's patterns, then the house rule on em dashes.
_LEAK_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("SS58 address", r"\b5[1-9A-HJ-NP-Za-km-z]{46,47}\b"),
    ("private IPv4", r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    ("private IPv4", r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    ("private IPv4", r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("32-byte hex secret", r"\b0x[0-9a-fA-F]{64}\b"),
    ("Telegram bot token", r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    ("operator next-action line", r"(?m)^next: "),
    ("em dash", "\u2014"),
)


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def scan(text: str) -> List[str]:
    """Every reason this text must not be published. Empty means clean.

    The raw file text is scanned together with each string value on its own
    line, so a line-anchored pattern such as `^next: ` still fires on a
    value that sits mid-line in the serialised JSON."""
    try:
        values = _strings(json.loads(text))
    except ValueError:
        values = []
    body = "\n".join([text] + values)
    found: List[str] = []
    lowered = body.lower()
    for token in OPERATOR_TOKENS:
        if token.lower() in lowered:
            found.append("operator token %r" % token)
    for label, pattern in _LEAK_PATTERNS:
        match = re.search(pattern, body)
        if match is not None:
            found.append("%s %r" % (label, match.group(0)))
    return found


def scan_files(files: Dict[str, str]) -> List[str]:
    """`scan` over every file, each hit prefixed with its file name."""
    return ["%s: %s" % (name, hit) for name, text in files.items()
            for hit in scan(text)]


# ---------------------------------------------------------------------------
# Schema validation. The copy at subnt/schema/subnt-1.0.json is the subnt
# repo's file byte for byte; a test fails when the two drift.
# ---------------------------------------------------------------------------

_VALIDATOR: Any = None


def _validator() -> Any:
    global _VALIDATOR
    if _VALIDATOR is None:
        try:
            import jsonschema  # noqa: E402
        except ImportError:
            raise SubntError("cannot validate: the jsonschema library is "
                             "not installed")
        try:
            with open(SCHEMA_FILE, "r", encoding="utf-8") as handle:
                schema = json.load(handle)
        except (OSError, ValueError) as exc:
            raise SubntError("cannot load schema %s: %s" % (SCHEMA_FILE, exc))
        _VALIDATOR = jsonschema.Draft202012Validator(schema)
    return _VALIDATOR


def validate(files: Dict[str, str]) -> List[str]:
    """Every schema failure, as `file: /path message`. Empty means valid."""
    validator = _validator()
    found: List[str] = []
    for name, text in files.items():
        try:
            doc = json.loads(text)
        except ValueError as exc:
            found.append("%s: not JSON (%s)" % (name, exc))
            continue
        for error in sorted(validator.iter_errors(doc),
                            key=lambda e: list(e.absolute_path)):
            path = "/" + "/".join(str(p) for p in error.absolute_path)
            found.append("%s: schema check failed at %s: %s"
                         % (name, path, error.message))
    return found


# ---------------------------------------------------------------------------
# Publish. Fact-gated and one direction only: no file in the checkout is read
# as an input to an edition. The committed data files are read only to decide
# whether any fact moved.
# ---------------------------------------------------------------------------

# The pass runs from a timer with no terminal. Git must never sit waiting
# for a credential prompt: without these, an interactive run would block on
# "Username for https://github.com" and a oneshot unit would hang instead of
# failing.
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
        raise SubntError("git %s did not finish in %ds"
                         % (args[0] if args else "", _GIT_TIMEOUT))
    return proc.returncode, proc.stdout, proc.stderr


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_names() -> List[str]:
    return ["%s.json" % name for name in FILES]


def fact_digest(files: Dict[str, str]) -> Optional[str]:
    """The content digest of an edition with its clock fields removed.

    `composed_at` moves every pass, `block` every hourly panel poll, and
    `previous_composed_at` every publish. A plain hash would therefore
    differ every pass and the gate would never hold, committing new
    timestamps over unchanged facts. Gating on the facts means an edition
    is republished only when something it reports moved, and the files
    left in place keep the compose time of the edition that is published.

    None when any file is missing or unreadable: that always counts as a
    change."""
    parts = []
    for name in file_names():
        text = files.get(name)
        if text is None:
            return None
        try:
            doc = json.loads(text)
        except ValueError:
            return None
        if not isinstance(doc, dict):
            return None
        for key in _VOLATILE:
            doc.pop(key, None)
        parts.append(json.dumps(doc, sort_keys=True, ensure_ascii=False))
    return _sha256("\n".join(parts))


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def data_dir(config: Dict[str, Any]) -> str:
    return os.path.join(os.path.expanduser(config["checkout_dir"]),
                        config.get("data_dir", "data"))


def publish(config: Dict[str, Any], files: Dict[str, str]) -> Dict[str, Any]:
    """Write, fact-gate, commit and push. Fails closed and leaves the
    checkout unchanged on any precondition failure. Creates and moves no
    credential, and touches no file outside the data directory."""
    checkout = os.path.expanduser(config["checkout_dir"])
    rel = config.get("data_dir", "data")
    target = data_dir(config)
    digest = fact_digest(files)

    if not os.path.isdir(checkout):
        raise SubntError("subnt checkout %s does not exist" % checkout)
    if not os.path.isdir(os.path.join(checkout, ".git")):
        raise SubntError("subnt checkout %s is not a git repository"
                         % checkout)
    code, out, err = _git(checkout, "status", "--porcelain")
    if code != 0:
        raise SubntError("cannot read the checkout state: %s"
                         % (err.strip() or out.strip()))
    if out.strip():
        raise SubntError("subnt checkout %s is dirty; refusing to write "
                         "over uncommitted work" % checkout)

    # Anyone may commit to the subnt repo directly (the page and its tests
    # live there). A checkout left behind origin would have its push
    # rejected, and an unattended timer cannot resolve that, so sync first.
    # Fast-forward only: a diverged checkout is an operator problem, not
    # something this pass may paper over with a merge.
    branch = config.get("branch", "main")
    code, out, err = _git(checkout, "fetch", "--quiet", "origin", branch)
    if code != 0:
        raise SubntError("cannot reach origin/%s: %s"
                         % (branch, err.strip() or out.strip()))
    code, counts, _err = _git(checkout, "rev-list", "--left-right",
                              "--count", "HEAD...FETCH_HEAD")
    if code == 0 and counts.split():
        ahead, behind = (int(x) for x in counts.split())
        if behind and ahead:
            raise SubntError(
                "subnt checkout has diverged from origin/%s (%d ahead, "
                "%d behind); refusing to publish over it" % (branch, ahead,
                                                             behind))
        if behind:
            code, out, err = _git(checkout, "merge", "--ff-only",
                                  "FETCH_HEAD")
            if code != 0:
                raise SubntError("cannot fast-forward to origin/%s: %s"
                                 % (branch, err.strip() or out.strip()))

    committed: Dict[str, str] = {}
    for name in file_names():
        code, text, _err = _git(checkout, "show",
                                "HEAD:%s/%s" % (rel, name))
        if code == 0:
            committed[name] = text
    if digest is not None and fact_digest(committed) == digest:
        return {"changed": False, "digest": digest, "path": target,
                "pushed": False}

    os.makedirs(target, exist_ok=True)
    paths = []
    for name in file_names():
        _atomic_write(os.path.join(target, name), files[name])
        paths.append("%s/%s" % (rel, name))
    code, out, err = _git(checkout, "add", "--", *paths)
    if code != 0:
        raise SubntError("cannot stage %s: %s" % (rel, err.strip()))
    code, out, err = _git(
        checkout,
        "-c", "user.name=%s" % config.get("commit_name", "vaNlabs"),
        "-c", "user.email=%s" % config.get("commit_email", "vanlabs@pm.me"),
        "commit", "-m", "Publish edition", "--", *paths)
    if code != 0:
        raise SubntError("cannot commit: %s" % (err.strip() or out.strip()))

    # A failed push leaves the local commit in place and the last deploy
    # live. Recovering it is the operator's call; this does not reset.
    code, out, err = _git(checkout, "push", "origin", branch)
    if code != 0:
        raise SubntError(
            "cannot push to origin/%s: %s. The commit is local and "
            "recoverable; nothing was reset."
            % (branch, err.strip() or out.strip()))
    return {"changed": True, "digest": digest, "path": target,
            "pushed": True}


# ---------------------------------------------------------------------------
# Pass and CLI
# ---------------------------------------------------------------------------

def build(config: Dict[str, Any], state: Optional[sqlite3.Connection],
          now: Optional[datetime.datetime] = None
          ) -> Tuple[Dict[str, Any], Dict[str, str], List[str]]:
    """Compose, serialise, scan and validate. Writes nothing anywhere.
    Returns (edition, files by file name, every problem found)."""
    edition = compose(config, state, now=now)
    files = {"%s.json" % name: serialise(edition["docs"][name])
             for name in FILES}
    return edition, files, scan_files(files) + validate(files)


def run(config: Dict[str, Any], now: Optional[datetime.datetime] = None
        ) -> Dict[str, Any]:
    """The full pass. Composes, scans, validates, and publishes when a fact
    has moved. Persists the figure set only after a successful publish, so
    an unpublished edition does not consume the comparison point."""
    if not config.get("enabled"):
        return {"status": "disabled"}
    state = open_state(_tg().resolve(config["state_db"]))
    try:
        edition, files, problems = build(config, state, now=now)
        if problems:
            raise SubntError("refusing to publish: %s" % "; ".join(problems))
        size = sum(len(t.encode("utf-8")) for t in files.values())
        if not config.get("publish"):
            return {"status": "composed", "published": False,
                    "would_write": data_dir(config), "bytes": size,
                    "digest": fact_digest(files),
                    "first_edition": edition["first_edition"]}
        result = publish(config, files)
        if result["changed"]:
            state_set(state, "figures", json.dumps(edition["figures"],
                                                   sort_keys=True))
            state_set(state, "published_at", _utc(now).isoformat())
            state_set(state, "content_sha256", result["digest"] or "")
        return {"status": "published" if result["changed"] else "unchanged",
                "published": result["changed"], "path": result["path"],
                "bytes": size, "digest": result["digest"],
                "first_edition": edition["first_edition"]}
    finally:
        state.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_subnt",
        description="Atlas subnt publisher: compose the public edition "
                    "from the Atlas stores as subnt data files and publish "
                    "them when a fact moves.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    comp = sub.add_parser("compose", help="print the edition and the check "
                                          "result; write nothing")
    comp.add_argument("--dry-run", action="store_true",
                      help="the default: nothing is written")
    comp.add_argument("--out", default=None,
                      help="also write the six files into this directory")
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
                edition, files, problems = build(config, state)
            finally:
                if state is not None:
                    state.close()
            if args.out:
                os.makedirs(args.out, exist_ok=True)
                for name, text in files.items():
                    _atomic_write(os.path.join(args.out, name), text)
            sys.stdout.write(json.dumps(edition["docs"], ensure_ascii=False,
                                        indent=1) + "\n")
            summary = {"problems": problems or "clean",
                       "bytes": sum(len(t.encode("utf-8"))
                                    for t in files.values()),
                       "digest": fact_digest(files),
                       "first_edition": edition["first_edition"],
                       "window_start": edition["window_start"],
                       "block": edition["block"],
                       "written": args.out}
            print(json.dumps(summary, indent=2, sort_keys=True),
                  file=sys.stderr)
            return 0 if not problems else 2
        print(json.dumps(run(config), indent=2, sort_keys=True))
        return 0
    except SubntError as exc:
        print("fatal: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
