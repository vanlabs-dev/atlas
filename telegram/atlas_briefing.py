#!/usr/bin/env python3
"""Atlas pulse briefing (changes: pulse-briefing, telegram-alert-redesign).

A scheduled Telegram briefing composed ONLY from rows already persisted in
the livedata, fleet, repotrack, knowledge, and notifier stores, all opened
read-only. Composing an edition makes no provider call and no model call:
every figure traces to a stored row with a reference block or timestamp,
and a section whose inputs are missing or stale says so instead of
estimating.

Editions: a daily at a configured UTC hour, replaced once a week by a
weekly edition with a seven-day window. Each edition is gated by a durable
watermark in the notifier ledger, so a restart or repeated scan cannot send
one twice, and a missed hour is caught up by the next scan that day. The
previous edition's figure set is persisted as JSON in the notifier meta
table; deltas compare against it, and the first edition says it has none.

Each edition opens with its marker (☀️ daily, 🗓️ weekly) and a one-line
summary built by fixed rules from the edition's own figures. Sections
render in fixed order (network, chain rule changes, price moves,
demand-share moves, watch list, high-impact incentive changes); system
health sits in an expandable fold. When the edition exceeds the message
bound the fold sheds first, then whole lines drop from the lowest-priority
section upward; the network section is never cut and the omission count is
stated. The final line is the next action when one exists.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

import atlas_telegram as tg

EDITION_DAILY = "daily"
EDITION_WEEKLY = "weekly"
EDITION_MARK = {EDITION_DAILY: "☀️", EDITION_WEEKLY: "🗓️"}

# Fixed render order and the bold title of each section. Truncation drops
# from the lowest-priority section upward; "network" is never dropped.
SECTION_ORDER = ("network", "rules", "price_moves", "share_moves", "watch",
                 "high_impact")
SECTION_TITLES = {
    "network": "Network",
    "rules": "Chain rule changes",
    "price_moves": "Biggest price moves",
    "share_moves": "Biggest demand-share moves",
    "watch": "Watch list",
    "high_impact": "High-impact incentive changes",
}
DROP_ORDER = ("high_impact", "share_moves", "price_moves", "watch", "rules")
WEEKLY_HIGH_IMPACT_LINES = 5
MOVER_LINES = 3

_WM_KEY = {EDITION_DAILY: "briefing:daily", EDITION_WEEKLY:
           "briefing:weekly"}
_FIGURES_KEY = "briefing:figures"


def _utc(now: Optional[datetime.datetime]) -> datetime.datetime:
    return now or datetime.datetime.now(datetime.timezone.utc)


def _iso_week(now: datetime.datetime) -> str:
    year, week, _ = now.isocalendar()
    return "%d-W%02d" % (year, week)


def _meta_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM meta WHERE key = ?",
                             (key,)).fetchone()
    return row[0] if row else None


def _meta_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))
    connection.commit()


def _table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone() is not None


def _one(conn: sqlite3.Connection, sql: str, params: Tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


class _Sources:
    """Read-only handles on the stores the briefing reads. A store that
    does not exist yields None and the section reports the gap."""

    def __init__(self, bcfg: Dict[str, Any]):
        self.live = tg.open_source_ro(tg.resolve(
            bcfg.get("live_db", "var/livedata/livedata.db")))
        self.fleet = tg.open_source_ro(tg.resolve(
            bcfg.get("fleet_db", "var/fleet/fleet.db")))
        self.repo = tg.open_source_ro(tg.resolve(
            bcfg.get("repo_db", "var/repotrack/repotrack.db")))
        self.knowledge = tg.open_source_ro(tg.resolve(
            bcfg.get("knowledge_db", "var/knowledge/knowledge.db")))

    def close(self) -> None:
        for conn in (self.live, self.fleet, self.repo, self.knowledge):
            if conn is not None:
                conn.close()


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return ("%%.%df" % digits) % value
    return str(value)


def _delta_pct(new: Optional[float], old: Optional[float]) -> Optional[str]:
    if new is None or old is None or old == 0:
        return None
    return "%+.1f%%" % ((new / old - 1.0) * 100.0)



def _movers(live: sqlite3.Connection, start: str, column: str,
            threshold_pct: float, limit: int
            ) -> List[Tuple[int, float, float, int, int]]:
    """(netuid, old, new, old_block, new_block) for the window's movers on
    one panel_snapshot column, largest absolute relative move first."""
    rows = live.execute(
        "SELECT s.netuid, "
        " (SELECT %(c)s FROM panel_snapshot f WHERE f.netuid = s.netuid "
        "   AND f.observed_at > ? AND f.%(c)s > 0 "
        "   ORDER BY f.id ASC LIMIT 1) old, "
        " (SELECT %(c)s FROM panel_snapshot l WHERE l.netuid = s.netuid "
        "   AND l.%(c)s > 0 ORDER BY l.id DESC LIMIT 1) new, "
        " (SELECT block_number FROM panel_snapshot f WHERE f.netuid = "
        "   s.netuid AND f.observed_at > ? AND f.%(c)s > 0 "
        "   ORDER BY f.id ASC LIMIT 1) ob, "
        " (SELECT block_number FROM panel_snapshot l WHERE l.netuid = "
        "   s.netuid AND l.%(c)s > 0 ORDER BY l.id DESC LIMIT 1) nb "
        "FROM (SELECT DISTINCT netuid FROM panel_snapshot) s"
        % {"c": column}, (start, start)).fetchall()
    movers = []
    for netuid, old, new, ob, nb in rows:
        if not old or not new:
            continue
        pct = (new / old - 1.0) * 100.0
        if abs(pct) >= threshold_pct:
            movers.append((netuid, old, new, ob, nb, pct))
    movers.sort(key=lambda m: -abs(m[5]))
    return movers[:limit]



# Mining model version assumed for an edition recorded before the version
# was stored (change: mining-board-accuracy shipped version 2).
MINING_MODEL_UNRECORDED = "1"


def stored_mining(fleet: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """The ranking the last complete mining pass stored, read as stored:
    rank order, cut and unrated counts, and the model version. Nothing is
    re-derived or re-sorted from raw figures. None when no pass has been
    classified. Shared with the subnt publisher."""
    if not _table(fleet, "mine_econ") or not _table(fleet, "mine_state"):
        return None
    ts = _one(fleet, "SELECT value FROM mine_state WHERE key = "
                     "'last_classified_ts'")
    if not ts:
        return None
    rows = fleet.execute(
        "SELECT netuid, subnet_name, rank, cut_reason, unrated_reason, "
        "rent_band FROM mine_econ WHERE ts = ?", (ts,)).fetchall()
    ranked = sorted((r for r in rows if r[2] is not None),
                    key=lambda r: r[2])
    return {
        "ts": ts,
        "model_version": _one(fleet, "SELECT value FROM mine_state WHERE "
                                     "key = 'model_version'"),
        "observed": len(rows),
        "ranked": [(int(r[0]), r[1]) for r in ranked],
        "cut": sum(1 for r in rows if r[3] is not None),
        "unrated": sorted((int(r[0]), r[4]) for r in rows
                          if r[2] is None and r[3] is None),
        "rent_unknown": bool(ranked) and all(r[5] is None for r in ranked),
    }


def mining_top_delta(prev: Dict[str, Any], top: List[int],
                     model_version: Optional[str]
                     ) -> Tuple[str, List[int], List[int]]:
    """Compare this edition's top ten with the previous edition's.
    Returns (state, entered, left): state is `first`, `model-changed`,
    `changed` or `unchanged`. Across a model version change the lists
    describe two different models, so no delta is reported."""
    prev_top = prev.get("mining_top10") or []
    if not prev_top:
        return "first", [], []
    prev_model = prev.get("mining_model_version") or MINING_MODEL_UNRECORDED
    if prev_model != model_version:
        return "model-changed", [], []
    entered = [n for n in top if n not in prev_top]
    left = [n for n in prev_top if n not in top]
    return ("changed" if entered or left else "unchanged"), entered, left


# ---------------------------------------------------------------------------
# Sections. Each returns (lines, figures). Every line is a recorded fact or
# a comparison of two recorded facts; absent inputs say so or omit the line.
# ---------------------------------------------------------------------------

def _change_pct(new: Optional[float], old: Optional[float]
                ) -> Optional[float]:
    """Numeric twin of _delta_pct (which subnt reads as a string)."""
    if new is None or old is None or old == 0:
        return None
    return (new / old - 1.0) * 100.0


def _window_word(kind: str) -> str:
    return "since last week's edition" if kind == EDITION_WEEKLY else \
        "since yesterday's edition"


def _network_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                     prev: Dict[str, Any], kind: str = EDITION_DAILY
                     ) -> Tuple[List[str], Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is None:
        return ["Live store unavailable"], figures

    if _table(live, "network_vitals"):
        vit = live.execute(
            "SELECT date, tao_usd FROM network_vitals "
            "ORDER BY date DESC LIMIT 1").fetchone()
        if vit is not None and vit[1] is not None:
            date, usd = vit
            figures["tao_usd"] = usd
            figures["tao_date"] = date
            change = _change_pct(usd, prev.get("tao_usd"))
            figures["tao_change"] = change
            lines.append("TAO %s%s · dated %s" % (
                tg.fmt_usd(usd),
                " · %s %s" % (tg.fmt_change(change), _window_word(kind))
                if change is not None else "",
                tg.fmt_date(date)))
        else:
            lines.append("TAO price: none recorded yet")
    else:
        lines.append("TAO price: none recorded yet")

    row = live.execute(
        "SELECT theta, rank, above_count, observed_at FROM gate_state "
        "WHERE gate_active = 1 ORDER BY id DESC LIMIT 1").fetchone() \
        if _table(live, "gate_state") else None
    crossings = None
    if _table(live, "gate_events"):
        crossings = _one(live, "SELECT COUNT(*) FROM gate_events "
                               "WHERE observed_at > ?", (start,))
        figures["side_changes"] = crossings
    if row is not None:
        theta, _rank, above, observed_at = row
        stale_hours = float(bcfg.get("stale_hours", 26))
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=stale_hours)).isoformat()
        if observed_at < cutoff:
            lines.append("Emission bar: dated (last observed %s)"
                         % tg.fmt_time(observed_at))
        else:
            figures["theta"] = theta
            change = _change_pct(theta, prev.get("theta"))
            parts = ["Emission bar %s" % tg.fmt_pct(theta)]
            if change is not None:
                parts.append(tg.fmt_change(change))
            if above is not None:
                parts.append("%s subnets above" % _fmt(above))
            if crossings is not None:
                parts.append("no crossings" if not crossings else
                             "%d crossing%s" % (crossings,
                                                "" if crossings == 1
                                                else "s"))
            lines.append(" · ".join(parts))

    spec = _one(live, "SELECT value FROM meta WHERE key = 'last_live_spec'") \
        if _table(live, "meta") else None
    if spec is not None:
        figures["spec"] = int(spec)
        first_prev = _one(live, "SELECT prev_spec FROM spec_upgrades WHERE "
                                "observed_at > ? ORDER BY id ASC LIMIT 1",
                          (start,)) if _table(live, "spec_upgrades") else None
        if first_prev is not None and int(first_prev) != int(spec):
            lines.append("Runtime spec %s → %s" % (first_prev, spec))
        else:
            lines.append("Runtime spec %s" % spec)
    return lines, figures


def _rules_section(src: _Sources, start: str,
                   names: Dict[int, str]) -> Tuple[List[str], Dict[str, Any]]:
    """Root-settable parameter transitions in the window, one line per
    item and subnet, a set-then-reset pair merged into one line."""
    live = src.live
    if live is None or not _table(live, "chain_param_events"):
        return [], {}
    groups: Dict[str, List[Tuple[str, str]]] = {}
    order: List[str] = []
    for item, prev_v, new_v in live.execute(
            "SELECT item, prev_value, new_value FROM chain_param_events "
            "WHERE observed_at > ? ORDER BY id", (start,)):
        if item not in groups:
            order.append(item)
            groups[item] = []
        groups[item].append((str(prev_v), str(new_v)))
    lines = []
    for item in order:
        base, netuid = tg.parse_netuid_item(item)
        moves = groups[item]
        first_prev, last_new = moves[0][0], moves[-1][1]
        if base == "SubnetEmissionEnabled":
            what = ("TAO emission switched back on"
                    if last_new.lower() == "true"
                    else "TAO emission switched off")
            if first_prev == last_new:
                what = "TAO emission switched and restored"
        elif len(moves) > 1 and first_prev == last_new:
            what = "%s set, then reset to %s" % (
                base, tg._param_value(last_new))
        else:
            what = "%s %s → %s" % (base, tg._param_value(first_prev),
                                   tg._param_value(last_new))
        who = tg.subnet_tag(netuid, names) if netuid is not None else None
        lines.append("%s: %s" % (who, what) if who else what)
    return lines, {"rule_changes": len(lines)}


def _price_moves_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                         names: Dict[int, str]
                         ) -> Tuple[List[str], Dict[str, Any]]:
    live = src.live
    if live is None or not _table(live, "panel_snapshot"):
        return [], {}
    threshold = float(bcfg.get("price_move_threshold_pct", 15))
    lines = []
    top = None
    for netuid, old, new, _ob, _nb, pct in _movers(
            live, start, "moving_price_tao", threshold, MOVER_LINES):
        lines.append("%s: %s → %s, %s" % (
            tg.subnet_tag(netuid, names), tg.fmt_tao(old).replace(" τ", ""),
            tg.fmt_tao(new), tg.fmt_change(pct)))
        if top is None:
            top = {"netuid": netuid, "pct": pct, "what": "price"}
    return lines, {"top_price": top} if top else {}


def _share_moves_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                         names: Dict[int, str]
                         ) -> Tuple[List[str], Dict[str, Any]]:
    live = src.live
    if live is None or not _table(live, "panel_snapshot"):
        return [], {}
    threshold = float(bcfg.get("share_move_threshold_pct", 25))
    lines = []
    top = None
    for netuid, old, new, _ob, _nb, pct in _movers(
            live, start, "share", threshold, MOVER_LINES):
        lines.append("%s: %s → %s, %s" % (
            tg.subnet_tag(netuid, names), tg.fmt_pct(old, 2),
            tg.fmt_pct(new, 2), tg.fmt_change(pct)))
        if top is None:
            top = {"netuid": netuid, "pct": pct, "what": "demand share"}
    return lines, {"top_share": top} if top else {}


def _watch_section(src: _Sources, names: Dict[int, str]
                   ) -> Tuple[List[str], Dict[str, Any]]:
    """The three non-immune subnets closest to deregistration, whatever
    their risk level, then the subnets hovering at the bar."""
    live = src.live
    lines: List[str] = []
    if live is None or not _table(live, "panel_snapshot"):
        return lines, {}
    columns = {r[1] for r in live.execute("PRAGMA table_info(panel_snapshot)")}
    if {"dereg_prune_rank", "dereg_is_immune"} <= columns:
        risk = live.execute(
            "SELECT netuid FROM panel_snapshot WHERE id IN "
            "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
            "AND dereg_prune_rank IS NOT NULL AND dereg_is_immune = 0 "
            "ORDER BY dereg_prune_rank ASC LIMIT 3").fetchall()
        if risk:
            lines.append("Closest to deregistration (not immune):")
            lines.extend("%d. %s" % (i, tg.subnet_tag(r[0], names))
                         for i, r in enumerate(risk, start=1))
    if _table(live, "gate_sides"):
        hover = [r[0] for r in live.execute(
            "SELECT netuid FROM gate_sides WHERE hovering = 1 "
            "ORDER BY netuid")]
        if hover:
            lines.append("At the bar: %s" % ", ".join(
                tg.subnet_tag(n, names) for n in hover))
    return lines, {}


def _high_impact_section(src: _Sources, start: str, names: Dict[int, str]
                         ) -> Tuple[List[str], Dict[str, Any]]:
    """Every high verdict in the window, named; medium verdicts are not
    counted or listed. An empty window omits the section."""
    fleet = src.fleet
    if fleet is None or not _table(fleet, "signal_econ_verdicts"):
        return [], {}
    rows = fleet.execute(
        "SELECT netuid, what_changed FROM signal_econ_verdicts "
        "WHERE created_at > ? AND significance = 'high' "
        "ORDER BY created_at DESC", (start,)).fetchall()
    lines = ["%s: %s" % (tg.subnet_tag(netuid, names),
                         tg.rec(tg._clip_words(what or "no summary", 90)))
             for netuid, what in rows]
    return lines, {"high_count": len(lines)}


def _health_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                    config: Dict[str, Any], connection: sqlite3.Connection,
                    figures: Dict[str, Any]
                    ) -> Tuple[List[str], Dict[str, Any]]:
    """System health for the details fold: provider events, the above-bar
    count distribution, TaoStats quota, the last knowledge ingest, the
    price data date, stalled watermarks, and the release subject."""
    lines: List[str] = []
    live = src.live
    if live is not None and _table(live, "integration_health"):
        fails = live.execute(
            "SELECT provider, COUNT(*) FROM integration_health "
            "WHERE timestamp > ? GROUP BY provider ORDER BY 2 DESC",
            (start,)).fetchall()
        lines.append("Provider events: %s" % " · ".join(
            "%s %d" % (tg.rec(p), n) for p, n in fails[:4])
            if fails else "Providers quiet")
    if live is not None and _table(live, "gate_state"):
        dist = live.execute(
            "SELECT above_count, COUNT(*) FROM gate_state "
            "WHERE observed_at > ? AND above_count IS NOT NULL "
            "GROUP BY above_count ORDER BY above_count", (start,)).fetchall()
        if dist:
            lines.append("Above-bar counts: %s" % " · ".join(
                "%s on %d polls" % (c, n) for c, n in dist))
    if live is not None and _table(live, "calls"):
        month_start = datetime.datetime.now(
            datetime.timezone.utc).replace(day=1, hour=0, minute=0,
                                           second=0, microsecond=0)
        used = _one(live, "SELECT COUNT(*) FROM calls WHERE provider = "
                          "'taostats' AND ts >= ?",
                    (month_start.timestamp(),))
        cap = int(bcfg.get("taostats_monthly_cap", 10000))
        lines.append("TaoStats %s of %s calls this month"
                     % (tg.fmt_int(used), tg.fmt_int(cap)))
    if src.knowledge is not None and _table(src.knowledge, "intake_runs"):
        last = _one(src.knowledge, "SELECT MAX(run_id) FROM intake_runs")
        if last:
            day = str(last)[:8]
            lines.append("Knowledge last ingested %s" % tg.fmt_date(
                "%s-%s-%s" % (day[:4], day[4:6], day[6:8])))
    if figures.get("tao_date"):
        lines.append("Price data dated %s" % tg.fmt_date(figures["tao_date"]))
    if figures.get("spec") is not None:
        release = tg._release_for_upgrade(
            bcfg.get("repo_db", "var/repotrack/repotrack.db"),
            int(figures["spec"]))
        if release is not None:
            lines.append("Release for spec %s: %s" % (
                figures["spec"], tg.rec(tg._clip_words(release["subject"],
                                                        90))))
    # A class is reported stalled only against a configured expectation.
    for name, spec in (config.get("classes") or {}).items():
        hours = spec.get("expected_interval_hours")
        if not spec.get("enabled") or not hours:
            continue
        row = connection.execute(
            "SELECT updated_at FROM watermarks WHERE source = ?",
            (name,)).fetchone()
        if row is None:
            continue
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=float(hours))).isoformat()
        if row[0] < cutoff:
            lines.append("Class %s: watermark stalled since %s"
                         % (name, row[0][:16]))
    return lines, {}


def _summary_line(kind: str, figures: Dict[str, Any],
                  names: Dict[int, str]) -> str:
    """One line built by fixed rules from figures already in the edition:
    quiet marker, TAO move, the largest mover, rule changes, high-impact
    changes. Nothing here is absent from the body."""
    parts: List[str] = []
    quiet = (not figures.get("side_changes")
             and not figures.get("rule_changes"))
    if quiet:
        parts.append("Quiet week." if kind == EDITION_WEEKLY
                     else "Quiet day.")
    usd = figures.get("tao_usd")
    change = figures.get("tao_change")
    if usd is not None:
        price = tg.fmt_usd(usd)
        if change is None:
            parts.append("TAO at %s." % price)
        elif abs(change) < 1.0:
            parts.append("TAO flat at %s." % price)
        else:
            parts.append("TAO %s %s." % ("rose" if change > 0 else "fell",
                                         tg.fmt_change(abs(change)).lstrip("+")))
    movers = [m for m in (figures.get("top_share"), figures.get("top_price"))
              if m]
    if movers:
        top = max(movers, key=lambda m: abs(m["pct"]))
        parts.append("%s %s %s %s." % (
            tg.subnet_tag(top["netuid"], names), top["what"],
            "rose" if top["pct"] > 0 else "fell",
            tg.fmt_change(abs(top["pct"])).lstrip("+")))
    if figures.get("rule_changes"):
        count = figures["rule_changes"]
        parts.append("%d chain rule change%s." % (count,
                                                  "" if count == 1 else "s"))
    if figures.get("high_count"):
        count = figures["high_count"]
        parts.append("%d high-impact incentive change%s." % (
            count, "" if count == 1 else "s"))
    return " ".join(parts) or "No recorded changes this window."


# ---------------------------------------------------------------------------
# Composition and delivery
# ---------------------------------------------------------------------------

def compose(config: Dict[str, Any], connection: sqlite3.Connection,
            kind: str, now: Optional[datetime.datetime] = None
            ) -> Dict[str, Any]:
    """Build the edition: header, summary, sections, fold, figures, and
    the closing next action. Pure read; delivery and watermarks belong to
    run_briefing."""
    bcfg = config.get("briefing") or {}
    now = _utc(now)
    window_days = 7 if kind == EDITION_WEEKLY else 1
    start = (now - datetime.timedelta(days=window_days)).isoformat()
    prev_raw = _meta_get(connection, "%s:%s" % (_FIGURES_KEY, kind))
    prev: Dict[str, Any] = json.loads(prev_raw) if prev_raw else {}
    first_edition = prev_raw is None

    src = _Sources(bcfg)
    sections: Dict[str, List[str]] = {}
    figures: Dict[str, Any] = {}
    health: List[str] = []
    try:
        names = tg.subnet_names_from(src.live)
        builders = (
            ("network", lambda: _network_section(src, bcfg, start, prev,
                                                 kind)),
            ("rules", lambda: _rules_section(src, start, names)),
            ("price_moves", lambda: _price_moves_section(src, bcfg, start,
                                                         names)),
            ("share_moves", lambda: _share_moves_section(src, bcfg, start,
                                                         names)),
            ("watch", lambda: _watch_section(src, names)),
            ("high_impact", lambda: _high_impact_section(src, start,
                                                         names)),
        )
        for name, builder in builders:
            try:
                lines, figs = builder()
            except sqlite3.Error as exc:
                lines, figs = ["%s: unreadable (%s)"
                               % (SECTION_TITLES[name], type(exc).__name__)
                               ], {}
            sections[name] = lines
            figures.update(figs)
        try:
            health, _figs = _health_section(src, bcfg, start, config,
                                            connection, figures)
        except sqlite3.Error as exc:
            health = ["System health unreadable (%s)" % type(exc).__name__]
    finally:
        src.close()

    if kind == EDITION_WEEKLY:
        header = "Atlas weekly · %s to %s" % (
            tg.fmt_date((now - datetime.timedelta(days=6)).isoformat()),
            tg.fmt_date(now.isoformat()))
    else:
        header = "Atlas daily · %s %s" % (
            now.strftime("%a"),
            tg.fmt_date(now.isoformat()))
    summary = _summary_line(kind, figures, names)
    if first_edition:
        summary += " First edition: changes begin next time."
    # Persist only plain figures the next edition compares against.
    persisted = {k: v for k, v in figures.items()
                 if k in ("tao_usd", "theta", "spec", "side_changes",
                          "rule_changes", "high_count")}
    return {"kind": kind, "header": header, "summary": summary,
            "sections": sections, "health": health, "figures": persisted,
            "first_edition": first_edition, "closing": None,
            "window_start": start}


def _to_messages(edition: Dict[str, Any], config: Dict[str, Any]
                 ) -> List[tg.Message]:
    """One or more Messages per edition. When the edition needs more
    messages than allowed, the health fold sheds first, then whole lines
    drop from the lowest-priority section upward; the network section is
    never cut and the omission count is stated."""
    bcfg = config.get("briefing") or {}
    max_messages = int(bcfg.get(
        "max_messages_weekly" if edition["kind"] == EDITION_WEEKLY
        else "max_messages_daily", 2))
    max_chars = int(config.get("message_max_chars", 3500))
    per_message = max_chars - 400  # markup + headline headroom
    sections = {name: list(lines)
                for name, lines in edition["sections"].items()}
    health = list(edition.get("health") or [])
    overflow: List[str] = []
    if (edition["kind"] == EDITION_WEEKLY
            and len(sections.get("high_impact") or []) > WEEKLY_HIGH_IMPACT_LINES):
        overflow = sections["high_impact"][WEEKLY_HIGH_IMPACT_LINES:]
        sections["high_impact"] = (
            sections["high_impact"][:WEEKLY_HIGH_IMPACT_LINES]
            + ["+%d more in the fold" % len(overflow)])

    def blocks() -> List[List[str]]:
        out = []
        for name in SECTION_ORDER:
            if sections.get(name):
                out.append([tg.bold(SECTION_TITLES[name])] + sections[name])
        return out

    def pack(omitted: int) -> List[tg.Message]:
        groups: List[List[str]] = []
        current: List[str] = []
        size = len(edition["summary"]) + 1
        for block in blocks():
            block_len = sum(len(line) + 1 for line in block) + 1
            if current and size + block_len > per_message:
                groups.append(current)
                current, size = [], 0
            current.extend(([""] if current else []) + block)
            size += block_len
        if current or not groups:
            groups.append(current)
        fold = ((["More high-impact changes:"] + overflow if overflow
                 else []) + (["System health:"] + health if health else []))
        messages = []
        for index, body in enumerate(groups):
            last = index == len(groups) - 1
            if last and omitted:
                body = body + ["", "%s omitted for size"
                               % tg.plural(omitted, "line")]
            messages.append(tg.Message(
                severity=EDITION_MARK[edition["kind"]],
                headline=edition["header"] + (
                    "" if index == 0 else " · %d" % (index + 1)),
                meaning=edition["summary"] if index == 0 else None,
                body=body,
                details=fold if last else [],
                next_action=edition.get("closing") if last else None))
        return messages

    omitted = 0
    messages = pack(omitted)

    def too_big(msgs: List[tg.Message]) -> bool:
        return len(msgs) > max_messages or any(
            len(tg._layout(m, True, None)) > max_chars for m in msgs)

    while too_big(messages):
        if health:
            health.pop()
        elif overflow:
            overflow.pop()
        else:
            for name in DROP_ORDER:
                if sections.get(name):
                    sections[name].pop()
                    omitted += 1
                    break
            else:
                messages = messages[:max_messages]  # nothing left to drop
                break
        messages = pack(omitted)
    return messages


def run_briefing(config: Dict[str, Any], token: str, chat_id: str,
                 connection: sqlite3.Connection,
                 poster: Optional[Callable[..., Tuple[int, str]]] = None,
                 now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Compose and deliver the due edition, if any. One edition per day,
    the weekly replacing the daily on its weekday; a failed delivery
    leaves the watermark unset so the next scan retries."""
    bcfg = config.get("briefing") or {}
    if not bcfg.get("enabled"):
        return {"status": "disabled"}
    now = _utc(now)
    if now.hour < int(bcfg.get("daily_hour_utc", 7)):
        return {"status": "not-due"}
    weekly_day = int(bcfg.get("weekly_weekday", 6))
    kind = EDITION_WEEKLY if now.weekday() == weekly_day else EDITION_DAILY
    stamp = (_iso_week(now) if kind == EDITION_WEEKLY
             else now.date().isoformat())
    if tg.watermark_get(connection, _WM_KEY[kind]) == stamp:
        return {"status": "current", "kind": kind}

    edition = compose(config, connection, kind, now=now)
    messages = _to_messages(edition, config)
    max_chars = int(config.get("message_max_chars", 3500))
    statuses: List[str] = []
    for index, msg in enumerate(messages, start=1):
        event = tg.message_event(
            msg, "briefing:%s:%s:%d" % (kind, stamp, index),
            "pulse-briefing", tg._utc_now(), max_chars, None)
        statuses.append(tg.deliver_event(connection, config, token,
                                         chat_id, event, poster=poster))
    delivered = statuses and all(
        s in (tg.STATUS_DELIVERED, tg.STATUS_SUPPRESSED) for s in statuses)
    if delivered:
        tg.watermark_set(connection, _WM_KEY[kind], stamp)
        _meta_set(connection, "%s:%s" % (_FIGURES_KEY, kind),
                  json.dumps(edition["figures"]))
    return {"status": "sent" if delivered else "failed", "kind": kind,
            "messages": len(messages), "statuses": statuses}
