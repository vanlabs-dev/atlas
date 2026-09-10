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

# The six reasons score_subnet can return, as short public phrases. No
# score, no direction cue, no board thesis reaches the page.
WHY_PHRASE = {
    "divergence": "code activity and price are moving apart",
    "emission": "emission routed away from miners",
    "abandon": "repository has gone quiet",
    "fresh": "something changed this pass",
    "opaque": "emission split is not readable from the repository",
    "quiet": "no signal beyond presence",
}


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


def _delta(new: Any, old: Any) -> str:
    """Suffix a figure with its change since the previous shinogi publish.
    Empty on a first edition or when either side is absent."""
    pct = _brief()._delta_pct(new, old)
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
        # Vitals are a daily observation. They carry their date and are not
        # stale for age alone.
        items.append(_fact(
            "TAO at %s USD%s, %s TAO staked, subnets hold %s%% of stake, "
            "%s new accounts, observed %s."
            % (_num(usd, 2), _delta(usd, prev.get("tao_usd")),
               _grouped(staked), _num(share, 2), _grouped(accounts), date)))
    return items, figures


def mover_facts(src: Any, cfg: Dict[str, Any], start: str
                ) -> List[Tuple[str, str]]:
    brief = _brief()
    items: List[Tuple[str, str]] = []
    live = src.live
    if live is None or not brief._table(live, "panel_snapshot"):
        return [_gap("Missing panel snapshots: no movers can be ranked.")]

    for netuid, old, new, ob, nb, pct in brief._movers(
            live, start, "moving_price_tao",
            float(cfg.get("price_move_threshold_pct", 15)), 6):
        items.append(_fact(
            "SN%d alpha price %+.1f%%, from %.5f TAO at block %s to %.5f TAO "
            "at block %s." % (netuid, pct, old, ob, new, nb)))
    for netuid, old, new, ob, nb, pct in brief._movers(
            live, start, "share",
            float(cfg.get("share_move_threshold_pct", 25)), 4):
        items.append(_fact(
            "SN%d demand share %+.1f%%, from %.4f%% at block %s to %.4f%% at "
            "block %s." % (netuid, pct, old * 100, ob, new * 100, nb)))
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
    return items


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

    if not ranked:
        items.append(_gap("Missing a ranked mining head: every observed "
                          "subnet was cut."))
    else:
        head = ranked[0]
        name = head[1]
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
                     "why": WHY_PHRASE.get(item["sc"]["why"])})
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

        for name, builder in (
                ("movers", lambda: mover_facts(src, config, start)),
                ("narrative", lambda: narrative_facts(src, start))):
            try:
                sections[name] = builder()
            except sqlite3.Error as exc:
                sections[name] = [_gap("Missing %s facts: the store is not "
                                       "readable (%s)."
                                       % (name, type(exc).__name__))]

        try:
            rows, gap = attention_rows(src, config, fleet_config)
        except sqlite3.Error as exc:
            rows, gap = [], ("Missing fleet attention facts: the store is "
                             "not readable (%s)." % type(exc).__name__)
        sections["attention"] = rows
        sections["attention_gap"] = gap

        block = asof_block(src)
    finally:
        src.close()

    return {"asof_time": now.strftime("%Y-%m-%d %H:%M UTC"),
            "asof_block": block, "first_edition": first_edition,
            "window_start": start, "sections": sections, "figures": figures}


# ---------------------------------------------------------------------------
# Render. The shell's exact shape and CSS, with the section bodies filled.
# Every interpolated value is escaped.
# ---------------------------------------------------------------------------

_CSS = """
    :root {
      --bg: #0e1114;
      --fg: #e6e8eb;
      --muted: #8b939c;
      --line: #2a3036;
      --accent: #c4b48a;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; background: var(--bg); color: var(--fg); }
    body {
      min-height: 100vh;
      font: 15px/1.45 ui-monospace, "Cascadia Mono", "SF Mono", Menlo, monospace;
      padding: 28px 22px 48px;
    }
    header {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 12px 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: 13px;
      letter-spacing: 0.18em;
      font-weight: 700;
    }
    .tag { color: var(--muted); font-size: 12px; }
    .asof { color: var(--muted); font-size: 12px; margin-left: auto; }
    main { max-width: 52rem; padding-top: 28px; }
    section { margin: 0 0 2em; }
    h2 {
      margin: 0 0 0.55em;
      font-size: 13px;
      letter-spacing: 0.12em;
      font-weight: 700;
    }
    h3 {
      margin: 1.1em 0 0.45em;
      font-size: 12px;
      letter-spacing: 0.08em;
      font-weight: 700;
      color: var(--muted);
    }
    p { margin: 0 0 1em; color: var(--muted); }
    ul { margin: 0 0 1em; padding-left: 1.1em; }
    li { margin: 0 0 0.3em; }
    .gap { margin: 0 0 0.6em; }
    .edition { margin: 0 0 2em; color: var(--accent); }
    .uid { color: var(--fg); }
    .nm { color: var(--accent); }
    footer {
      margin-top: 48px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _body(items: Sequence[Tuple[str, str]]) -> List[str]:
    """Facts render as one list; each gap renders as its own line."""
    out: List[str] = []
    facts = [text for kind, text in items if kind == "fact"]
    gaps = [text for kind, text in items if kind == "gap"]
    if facts:
        out.append("      <ul>")
        out.extend("        <li>%s</li>" % _esc(text) for text in facts)
        out.append("      </ul>")
    for text in gaps:
        out.append('      <p class="gap">%s</p>' % _esc(text))
    if not out:
        out.append('      <p class="gap">Missing every input for this '
                   'section.</p>')
    return out


def _attention_body(rows: Sequence[Dict[str, Any]],
                    gap: Optional[str]) -> List[str]:
    if not rows:
        return ['      <p class="gap">%s</p>'
                % _esc(gap or "Missing fleet attention facts.")]
    out = ["      <ul>"]
    for row in rows:
        name = row.get("name")
        why = row.get("why")
        out.append(
            '        <li><span class="uid">SN%s</span> '
            '<span class="nm">%s</span> %s</li>'
            % (_esc(row["netuid"]),
               _esc(name) if name else "name not recorded",
               _esc(why) if why else "reason not recorded"))
    out.append("      </ul>")
    return out


def render(edition: Dict[str, Any]) -> str:
    sections = edition["sections"]
    block = edition["asof_block"]
    asof = "as of %s · block %s" % (
        edition["asof_time"],
        block if block is not None else "not recorded")

    out: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, '
        'initial-scale=1">',
        "  <title>shinogi</title>",
        '  <meta name="description" content="A lean read on Bittensor '
        'subnets.">',
        "  <style>" + _CSS + "  </style>",
        "</head>",
        "<body>",
        "  <header>",
        "    <h1>SHINOGI</h1>",
        '    <div class="tag">%s</div>' % _esc(TAGLINE),
        '    <div class="asof">%s</div>' % _esc(asof),
        "  </header>",
        "  <main>",
    ]
    if edition["first_edition"]:
        out.append('    <p class="edition">First edition. No previous '
                   'publish to compare against, so no figure shows a '
                   'change.</p>')
    for sid, heading in SECTION_ORDER:
        out.append('    <section id="%s">' % sid)
        out.append("      <h2>%s</h2>" % _esc(heading))
        if sid == "attention":
            out.extend(_attention_body(sections.get("attention") or [],
                                       sections.get("attention_gap")))
        elif sid == "code-narrative":
            out.append("      <h3>Code</h3>")
            out.extend(_body(sections.get("code") or []))
            out.append("      <h3>Narrative</h3>")
            out.extend(_body(sections.get("narrative") or []))
        else:
            key = {"network": "network", "movers": "movers",
                   "mining": "mining"}[sid]
            out.extend(_body(sections.get(key) or []))
        out.append("    </section>")
    out.extend(["  </main>",
                "  <footer>%s</footer>" % _esc(FOOTER),
                "</body>",
                "</html>",
                ""])
    return "\n".join(out)


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
_ASSET_TOKENS: Tuple[str, ...] = (
    "<script", "XMLHttpRequest", "fetch(", "@import", 'rel="stylesheet"',
    "rel='stylesheet'", 'href="http', "href='http", 'src="http', "src='http",
)


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
    for token in _ASSET_TOKENS:
        if token.lower() in lowered:
            found.append("external or scripted asset %r" % token)
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
    code, out, err = _git(checkout, "push", "origin",
                          config.get("branch", "main"))
    if code != 0:
        raise ShinogiError(
            "cannot push to origin/%s: %s. The device holds no write "
            "credential for this remote, so the commit is local and "
            "recoverable; nothing was reset."
            % (config.get("branch", "main"), err.strip() or out.strip()))
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
