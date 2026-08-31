#!/usr/bin/env python3
"""Atlas pulse briefing (change: pulse-briefing).

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

Sections render in fixed order (network, subnets, code, narrative, mining,
atlas). When the composed edition exceeds the message bound, whole lines
drop from the lowest-priority section upward (narrative first, then code,
mining, atlas, subnets); the network section is never truncated and the
omission count is stated. The final line is the next action when one
exists, otherwise the LAN board link.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

import atlas_telegram as tg

EDITION_DAILY = "daily"
EDITION_WEEKLY = "weekly"

# Fixed render order. Truncation drops from the lowest-priority section
# upward; "network" is deliberately absent from the drop order.
SECTION_ORDER = ("network", "subnets", "code", "narrative", "mining",
                 "atlas")
DROP_ORDER = ("narrative", "code", "mining", "atlas", "subnets")

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


# ---------------------------------------------------------------------------
# Sections. Each returns (lines, figures). Every line is a recorded fact or
# a comparison of two recorded facts; absent inputs say so or omit the line.
# ---------------------------------------------------------------------------

def _network_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                     prev: Dict[str, Any]) -> Tuple[List[str],
                                                    Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is None:
        return ["live store: unavailable"], figures

    spec = _one(live, "SELECT value FROM meta WHERE key = 'last_live_spec'")
    if spec is not None:
        line = "runtime spec %s" % spec
        release = tg._release_for_upgrade(
            bcfg.get("repo_db", "var/repotrack/repotrack.db"), int(spec))
        if release is not None:
            line += " · %s" % release["subject"]
        lines.append(line)
        figures["spec"] = int(spec)

    if _table(live, "chain_param_events"):
        for item, prev_v, new_v in live.execute(
                "SELECT item, prev_value, new_value FROM chain_param_events "
                "WHERE observed_at > ? ORDER BY id", (start,)):
            lines.append("rule change: %s %s to %s" % (item, prev_v, new_v))

    row = live.execute(
        "SELECT theta, rank, above_count, observed_at FROM gate_state "
        "WHERE gate_active = 1 ORDER BY id DESC LIMIT 1").fetchone() \
        if _table(live, "gate_state") else None
    if row is not None:
        theta, rank, above, observed_at = row
        stale_hours = float(bcfg.get("stale_hours", 26))
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=stale_hours)).isoformat()
        if observed_at < cutoff:
            lines.append("bar: stale (last observed %s)" % observed_at[:16])
        else:
            figures["theta"] = theta
            delta = _delta_pct(theta, prev.get("theta"))
            lines.append(
                "bar %.5f%s · rank %s · %s above"
                % (theta, " · %s vs last edition" % delta if delta else "",
                   _fmt(rank), _fmt(above)))
        if _table(live, "gate_events"):
            moves = _one(live, "SELECT COUNT(*) FROM gate_events "
                               "WHERE observed_at > ?", (start,))
            lines.append("side changes in window: %s" % moves)
            figures["side_changes"] = moves

    if _table(live, "network_vitals"):
        vit = live.execute(
            "SELECT date, tao_usd, total_staked_tao, subnets_share_pct, "
            "new_accounts_today FROM network_vitals "
            "ORDER BY date DESC LIMIT 1").fetchone()
        if vit is not None:
            date, usd, staked, share, accounts = vit
            figures["tao_usd"] = usd
            delta = _delta_pct(usd, prev.get("tao_usd"))
            lines.append("TAO %s USD%s · staked %s · subnet share %s%% · "
                         "new accounts %s · dated %s"
                         % (_fmt(usd, 2),
                            " (%s)" % delta if delta else "",
                            _fmt(staked, 0), _fmt(share, 2),
                            _fmt(accounts), date))
        else:
            lines.append("network vitals: none recorded yet")
    else:
        lines.append("network vitals: none recorded yet")
    return lines, figures


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


def _subnets_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                     prev: Dict[str, Any]) -> Tuple[List[str],
                                                    Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is None or not _table(live, "panel_snapshot"):
        return ["panel snapshot: none recorded yet"], figures
    threshold = float(bcfg.get("price_move_threshold_pct", 15))
    for netuid, old, new, ob, nb, pct in _movers(
            live, start, "moving_price_tao", threshold, 6):
        lines.append("SN%d price %+.1f%% · %.5f at block %s to %.5f at "
                     "block %s" % (netuid, pct, old, ob, new, nb))
    for netuid, old, new, ob, nb, pct in _movers(
            live, start, "share", float(
                bcfg.get("share_move_threshold_pct", 25)), 4):
        lines.append("SN%d demand share %+.1f%% · %.4f%% at block %s to "
                     "%.4f%% at block %s"
                     % (netuid, pct, old * 100, ob, new * 100, nb))
    risk = [str(r[0]) for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND dereg_risk_level = 'high' ORDER BY netuid")]
    if risk:
        lines.append("dereg risk high: SN%s" % ", SN".join(risk[:8]))
    contested = [str(r[0]) for r in live.execute(
        "SELECT DISTINCT netuid FROM panel_snapshot WHERE id IN "
        "(SELECT MAX(id) FROM panel_snapshot GROUP BY netuid) "
        "AND (conviction_is_contested = 1 OR takeover_eligible = 1) "
        "ORDER BY netuid")]
    if contested:
        lines.append("ownership contested or takeover-eligible: SN%s"
                     % ", SN".join(contested[:8]))
    if _table(live, "gate_sides"):
        hover = [str(r[0]) for r in live.execute(
            "SELECT netuid FROM gate_sides WHERE hovering = 1 "
            "ORDER BY netuid")]
        if hover:
            lines.append("hovering at the bar (%d): SN%s"
                         % (len(hover), ", SN".join(hover)))
    if not lines:
        lines.append("no subnet movers beyond thresholds this window")
    return lines, figures


def _code_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                  prev: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None:
        return ["fleet store: unavailable"], figures
    if _table(fleet, "metric_activity"):
        latest = _one(fleet, "SELECT MAX(pass_ts) FROM metric_activity")
        if latest:
            pushed, total = fleet.execute(
                "SELECT SUM(c7 > 0), COUNT(*) FROM metric_activity "
                "WHERE pass_ts = ?", (latest,)).fetchone()
            lines.append("%s of %s tracked subnets pushed in 7d"
                         % (_fmt(pushed), _fmt(total)))
    if _table(fleet, "signal_econ_verdicts"):
        highs = fleet.execute(
            "SELECT netuid, what_changed, new_sha FROM signal_econ_verdicts "
            "WHERE created_at > ? AND significance = 'high' "
            "ORDER BY created_at DESC LIMIT 5", (start,)).fetchall()
        for netuid, what, sha in highs:
            lines.append("SN%d high · %s · %s"
                         % (netuid, (what or "")[:90], (sha or "")[:12]))
        med = _one(fleet, "SELECT COUNT(*) FROM signal_econ_verdicts "
                          "WHERE created_at > ? AND significance = 'med'",
                   (start,))
        figures["high_count"] = len(highs)
        figures["med_count"] = med
        lines.append("incentive-code verdicts: %d high · %s med"
                     % (len(highs), _fmt(med)))
    if _table(fleet, "epochs"):
        repoints = fleet.execute(
            "SELECT netuid, epoch FROM epochs WHERE opened_at > ? "
            "AND epoch > 1 ORDER BY opened_at DESC LIMIT 5",
            (start,)).fetchall()
        for netuid, epoch in repoints:
            lines.append("SN%d repo re-pointed (epoch %d)" % (netuid, epoch))
    return lines or ["no code activity recorded this window"], figures


def _narrative_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                       prev: Dict[str, Any]) -> Tuple[List[str],
                                                      Dict[str, Any]]:
    lines: List[str] = []
    fleet = src.fleet
    if fleet is None or not _table(fleet, "signal_adoptions"):
        return ["adoption ledger: unavailable"], {}
    # Model identifiers only: dependency terms are fleet-search material,
    # not narrative (pytest and numpy adoptions say nothing).
    rows = fleet.execute(
        "SELECT term, GROUP_CONCAT(DISTINCT netuid) FROM signal_adoptions "
        "WHERE kind = 'model-id' AND seeded = 0 AND adopted_at > ? "
        "GROUP BY term ORDER BY COUNT(*) DESC LIMIT 6",
        (start,)).fetchall()
    for term, netuids in rows:
        lines.append("model %s · SN%s" % (term,
                                          netuids.replace(",", ", SN")))
    if _table(fleet, "signal_events"):
        clusters = fleet.execute(
            "SELECT term FROM signal_events WHERE class = "
            "'narrative-cluster' AND created_at > ?", (start,)).fetchall()
        for (term,) in clusters:
            lines.append("cluster formed · %s" % term)
    return lines or ["no model-id adoptions this window"], {}


def _mining_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                    prev: Dict[str, Any]) -> Tuple[List[str],
                                                   Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    fleet = src.fleet
    if fleet is None or not _table(fleet, "mine_econ"):
        return ["mining screen: unavailable"], figures
    latest = _one(fleet, "SELECT MAX(ts) FROM mine_econ")
    if not latest:
        return ["mining screen: no economics recorded yet"], figures
    rows = fleet.execute(
        "SELECT netuid, subnet_name, cut_reason, net_tao_month, "
        "gross_tao_month, rent_band FROM mine_econ WHERE ts = ?",
        (latest,)).fetchall()
    ranked = [r for r in rows if r[2] is None]
    ranked.sort(key=lambda r: (0, -(r[3] if r[3] is not None else
                                    (r[4] or 0.0))) if (r[3] is not None or
                                                        r[4] is not None)
                else (1, 0.0))
    top = [int(r[0]) for r in ranked[:10]]
    figures["mining_top10"] = top
    if ranked:
        head = ranked[0]
        lines.append("board head: SN%d %s" % (head[0], head[1] or ""))
    lines.append("%d ranked · %d cut · %d observed"
                 % (len(ranked), len(rows) - len(ranked), len(rows)))
    prev_top = prev.get("mining_top10") or []
    entered = [n for n in top if n not in prev_top]
    left = [n for n in prev_top if n not in top]
    if prev_top and (entered or left):
        if entered:
            lines.append("entered top ten: SN%s"
                         % ", SN".join(str(n) for n in entered))
        if left:
            lines.append("left top ten: SN%s"
                         % ", SN".join(str(n) for n in left))
    elif prev_top:
        lines.append("top ten unchanged")
    if ranked and all(r[5] is None for r in ranked):
        lines.append("budget band unset · rent unknown · hardware rung "
                     "inert")
    return lines, figures


def _atlas_section(src: _Sources, bcfg: Dict[str, Any], start: str,
                   prev: Dict[str, Any], config: Dict[str, Any],
                   connection: sqlite3.Connection
                   ) -> Tuple[List[str], Dict[str, Any]]:
    lines: List[str] = []
    figures: Dict[str, Any] = {}
    live = src.live
    if live is not None and _table(live, "integration_health"):
        fails = live.execute(
            "SELECT provider, COUNT(*) FROM integration_health "
            "WHERE timestamp > ? GROUP BY provider ORDER BY 2 DESC",
            (start,)).fetchall()
        if fails:
            lines.append("provider events: %s" % " · ".join(
                "%s %d" % (p, n) for p, n in fails[:4]))
        else:
            lines.append("providers: quiet")
    if live is not None and _table(live, "gate_state"):
        dist = live.execute(
            "SELECT above_count, COUNT(*) FROM gate_state "
            "WHERE observed_at > ? AND above_count IS NOT NULL "
            "GROUP BY above_count ORDER BY above_count", (start,)).fetchall()
        if dist:
            lines.append("above-bar counts: %s" % " · ".join(
                "%s on %d polls" % (c, n) for c, n in dist))
    if live is not None and _table(live, "calls"):
        month_start = datetime.datetime.now(
            datetime.timezone.utc).replace(day=1, hour=0, minute=0,
                                           second=0, microsecond=0)
        used = _one(live, "SELECT COUNT(*) FROM calls WHERE provider = "
                          "'taostats' AND ts >= ?",
                    (month_start.timestamp(),))
        cap = int(bcfg.get("taostats_monthly_cap", 10000))
        lines.append("TaoStats quota: %s of %d this month" % (used, cap))
    if src.knowledge is not None and _table(src.knowledge, "intake_runs"):
        last = _one(src.knowledge, "SELECT MAX(run_id) FROM intake_runs")
        if last:
            lines.append("last knowledge ingest: %s" % str(last)[:8])
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
            lines.append("class %s: watermark stalled since %s"
                         % (name, row[0][:16]))
    return lines or ["no atlas records this window"], figures


# ---------------------------------------------------------------------------
# Composition and delivery
# ---------------------------------------------------------------------------

def compose(config: Dict[str, Any], connection: sqlite3.Connection,
            kind: str, now: Optional[datetime.datetime] = None
            ) -> Dict[str, Any]:
    """Build the edition: sections, figures, and the closing line. Pure
    read; delivery and watermarks belong to run_briefing."""
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
    try:
        for name, builder in (
                ("network", _network_section), ("subnets", _subnets_section),
                ("code", _code_section), ("narrative", _narrative_section),
                ("mining", _mining_section)):
            try:
                lines, figs = builder(src, bcfg, start, prev)
            except sqlite3.Error as exc:
                lines, figs = ["%s: unreadable (%s)"
                               % (name, type(exc).__name__)], {}
            sections[name] = lines
            figures.update(figs)
        try:
            lines, figs = _atlas_section(src, bcfg, start, prev, config,
                                         connection)
        except sqlite3.Error as exc:
            lines, figs = ["atlas: unreadable (%s)" % type(exc).__name__], {}
        sections["atlas"] = lines
        figures.update(figs)
    finally:
        src.close()

    next_action = None
    if any("budget band unset" in line for line in sections["mining"]):
        next_action = ("next: pick mining.budget_band, or disable the "
                       "mining screen")
    closing = next_action or ("board: %s" % bcfg.get(
        "board_url", "http://192.168.0.150:8480/"))
    return {"kind": kind, "sections": sections, "figures": figures,
            "first_edition": first_edition, "closing": closing,
            "window_start": start}


def _to_messages(edition: Dict[str, Any], config: Dict[str, Any]
                 ) -> List[Tuple[str, List[str]]]:
    """(headline, lines) per message. Lines drop from the lowest-priority
    section upward until the edition fits the configured message count;
    the network section is never cut, and the omission count is stated."""
    bcfg = config.get("briefing") or {}
    max_messages = int(bcfg.get(
        "max_messages_weekly" if edition["kind"] == EDITION_WEEKLY
        else "max_messages_daily", 2))
    max_chars = int(config.get("message_max_chars", 3500))
    per_message = max_chars - 400  # markup + headline headroom
    sections = {name: list(lines)
                for name, lines in edition["sections"].items()}
    date = _utc(None).date().isoformat()
    head = "Atlas · %s pulse · %s" % (edition["kind"], date)

    def pack() -> List[Tuple[str, List[str]]]:
        blocks: List[List[str]] = []
        if edition["first_edition"]:
            blocks.append(["first edition · deltas begin next time"])
        for name in SECTION_ORDER:
            if sections[name]:
                blocks.append(
                    ["%s%s%s" % (tg._BOLD_OPEN, name, tg._BOLD_CLOSE)]
                    + sections[name])
        messages: List[Tuple[str, List[str]]] = []
        current: List[str] = []
        size = 0
        for block in blocks:
            block_len = sum(len(line) + 1 for line in block) + 1
            if current and size + block_len > per_message:
                messages.append((head if not messages else
                                 "%s · %d" % (head, len(messages) + 1),
                                 current))
                current, size = [], 0
            current.extend(block + [""])
            size += block_len
        if current:
            messages.append((head if not messages else
                             "%s · %d" % (head, len(messages) + 1),
                             current))
        return messages

    omitted = 0
    messages = pack()
    while len(messages) > max_messages:
        for name in DROP_ORDER:
            if sections[name]:
                sections[name].pop()
                omitted += 1
                break
        else:
            messages = messages[:max_messages]  # nothing left to drop
            break
        messages = pack()
    if messages:
        headline, lines = messages[-1]
        tail = (["%d line(s) omitted for size" % omitted] if omitted
                else []) + [edition["closing"]]
        messages[-1] = (headline, lines + tail)
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
    _lexicon, glosses = tg.voice_maps(config)
    statuses: List[str] = []
    for index, (headline, lines) in enumerate(messages, start=1):
        event = {
            "event_id": "briefing:%s:%s:%d" % (kind, stamp, index),
            "event_class": "pulse-briefing", "created_at": tg._utc_now(),
            "text": tg.render_plain(headline, lines, "", None, max_chars,
                                    glosses=glosses),
            "html": tg.render_html(headline, lines, "", None, max_chars,
                                   glosses=glosses),
        }
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
