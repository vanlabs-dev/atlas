#!/usr/bin/env python3
"""Atlas fleet-rotation-metrics dashboard — the ranked "attention board"
(change: fleet-rotation-metrics).

Turns the read-only rotation report into a single, explicitly-scored list
of subnets ordered from "look here now" to "safely ignore this hour", and
renders it as one self-contained static HTML page (inline CSS/JS, no
external asset, no secret) written atomically into a dedicated www dir the
Pi serves LAN-only.

The attention score (operator-approved ranking rules v2) is explicit and
shown per row:
  - fresh events rank highest — an economics-code change or a branch-pulse
    spike since the last snapshot can reach the top regardless of standing
    signal;
  - then divergence magnitude (repo-activity percentile vs price-momentum
    percentile, either direction, tagged promising/dangerous);
  - then emission severity (share routed off-miners; newly-changed counts
    as fresh);
  - then abandonment (cold repo, weighted up when price is elevated).
Opacity is a modifier, not a headline: a purely-opaque-no-other-signal
subnet collapses into one grouped line instead of hogging the head tier.

All inputs are the real fleet store via `atlas_fleet_metrics.report()` —
there is no placeholder data anywhere; an empty store renders an honest
empty board.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DASHBOARD_CFG: Dict[str, Any] = {
    "enabled": True,
    "www_dir": "var/fleet/www",
    "head_count": 10,          # max rows in the LOOK-HERE tier
    "mid_count": 24,           # max rows in the SKIM tier
    "head_min_score": 28,      # score floor to reach the head tier
    "mid_min_score": 12,       # score floor to reach the mid tier
    "pulse_spike": 5,          # changed branch tips that counts as a spike
    "fresh_hours": 2,          # econ-code event age that still counts fresh
}

# Score component weights (documented so the ranking stays legible). Tuned
# so a ~47-pctile-point divergence, a ~30%+ off-miner redirect, or any fresh
# change each independently clears the head floor (head_min_score).
_W_DIVERGENCE = 0.6            # per percentile-point of |activity - momentum|
_W_EMISSION = 90.0            # per unit of off-miner redirect fraction
_ABANDON_ELEVATED = 25.0       # cold repo whose price is still high
_ABANDON_PLAIN = 10.0          # cold repo otherwise
_FRESH_BOOST = 42.0            # a change since last snapshot (floats to top)
_OPAQUE_MOD = 14.0             # opacity only counts paired with another signal


def dashboard_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_DASHBOARD_CFG)
    for key, value in (config.get("dashboard") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    return merged


_MET: Any = None
_FLEET: Any = None


def _met() -> Any:
    global _MET
    if _MET is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet_metrics  # noqa: E402
        _MET = atlas_fleet_metrics
    return _MET


def _fleet() -> Any:
    global _FLEET
    if _FLEET is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet  # noqa: E402
        _FLEET = atlas_fleet
    return _FLEET


# ---------------------------------------------------------------------------
# Freshness — an economics-code change since the last snapshot (real data
# from the signals event queue; absent table degrades to "not fresh").
# ---------------------------------------------------------------------------


def _recent_econ_netuids(connection: sqlite3.Connection, now: str,
                         hours: float) -> set:
    cutoff = (_met()._parse_iso(now)
              - datetime.timedelta(hours=hours)).isoformat()
    try:
        rows = connection.execute(
            "SELECT DISTINCT netuid FROM signal_events WHERE class = "
            "'econ-code' AND created_at >= ?", (cutoff,)).fetchall()
    except sqlite3.Error:
        return set()
    return {row[0] for row in rows if row[0] is not None}


# ---------------------------------------------------------------------------
# Scoring — one explicit attention score per subnet, with a dominant reason
# ---------------------------------------------------------------------------


def _pct(value: Optional[float]) -> Optional[int]:
    return None if value is None else int(round(value * 100))


def score_subnet(row: Dict[str, Any], fresh: bool, cfg: Dict[str, Any]
                 ) -> Dict[str, Any]:
    """Return the attention score plus the dominant reason, direction cue,
    and whether the row is a pure-opaque (headline-suppressed) case."""
    act = row.get("activity_pct")
    mom = row.get("momentum_pct")
    redirect = row.get("redirect_fraction_upper_bound") or 0.0
    opaque = bool(row.get("emission_opaque"))
    changed = row.get("changed_tips") or 0
    days = row.get("days_since")
    cls = row.get("activity_class")
    cold = cls in ("fade-eligible", "idle") or (days is not None and days > 90)
    pulse_spike = changed >= cfg["pulse_spike"]

    components: List[Tuple[str, float]] = []
    # Divergence (either direction).
    div_signed = None
    if act is not None and mom is not None:
        div_signed = int(round((act - mom) * 100))
        components.append(("divergence", abs(div_signed) * _W_DIVERGENCE))
    # Emission redirect off miners.
    if redirect > 0:
        components.append(("emission", redirect * _W_EMISSION))
    # Abandonment, weighted up when the token price is still elevated.
    if cold:
        elevated = mom is not None and mom >= 0.6
        components.append(("abandon",
                           _ABANDON_ELEVATED if elevated else _ABANDON_PLAIN))
    # Freshness — a change since last snapshot floats to the top.
    if fresh or pulse_spike:
        components.append(("fresh", _FRESH_BOOST))
    # Opacity is a modifier, only meaningful paired with another *real*
    # signal (a zero-magnitude divergence does not count as pairing).
    paired = any(weight > 0 for _n, weight in components)
    if opaque and paired:
        components.append(("opaque", _OPAQUE_MOD))

    score = int(round(min(100.0, sum(weight for _n, weight in components))))
    dominant = max(components, key=lambda c: c[1])[0] if components else "quiet"

    # Direction cue: promising (accumulate) vs dangerous (fade/extraction)
    # vs watch (fresh/neutral until inspected).
    if dominant == "divergence":
        promising = div_signed is not None and div_signed >= 0
        cue = ("up", "▲") if promising else ("dn", "▼")
    elif dominant in ("emission", "abandon", "opaque"):
        cue = ("dn", "▼")
    elif dominant == "fresh":
        cue = ("amb", "◆")
    else:
        cue = ("tx3", "◆")

    pure_opaque = (opaque and not paired) or (
        opaque and dominant == "opaque" and redirect < 0.1
        and (div_signed is None or abs(div_signed) < 20) and not cold
        and not (fresh or pulse_spike))

    return {"score": score, "why": dominant, "cue_kind": cue[0],
            "cue": cue[1], "div_signed": div_signed, "cold": cold,
            "pulse_spike": pulse_spike, "econ_fresh": bool(fresh),
            "fresh": fresh or pulse_spike, "pure_opaque": pure_opaque}


# ---------------------------------------------------------------------------
# Narrative — plain-English thesis + badges, deterministic from real numbers
# ---------------------------------------------------------------------------


def _mom_txt(mom7: Optional[float]) -> str:
    return "no data yet" if mom7 is None else "%+.0f%%" % mom7


def build_thesis(row: Dict[str, Any], sc: Dict[str, Any],
                 emission: Dict[str, Any], org_multi: Optional[int]) -> str:
    act_p, mom_p = _pct(row.get("activity_pct")), _pct(row.get("momentum_pct"))
    c30, a30 = row.get("c30") or 0, row.get("a30") or 0
    days = row.get("days_since")
    mom7 = row.get("momentum_7d")
    redirect = row.get("redirect_fraction_upper_bound") or 0.0
    rpct = int(round(redirect * 100))
    changed = row.get("changed_tips") or 0
    why = sc["why"]

    dom_route = _dominant_route(emission)
    if why == "fresh":
        # Prefer the econ-code-change story when we have one; otherwise the
        # branch-pulse spike story. Both are "something moved this snapshot".
        if sc.get("econ_fresh") and dom_route:
            return "Emission routing changed recently: %s." % dom_route
        if sc.get("econ_fresh"):
            return ("Economics-code changed recently — reward/weight logic "
                    "touched this snapshot.")
        return ("Branch-pulse spike: %d branch tips moved since last snapshot "
                "while the default branch %s."
                % (changed, "sleeps" if c30 == 0 else "ships"))
    if why == "divergence" and sc["cue_kind"] == "up":
        if mom_p is None:
            return ("Top-%s%% dev activity, price history not yet accrued — "
                    "ranked on activity%s alone."
                    % (100 - (act_p or 0),
                       (" + %d%% %s" % (rpct, _dominant_kind(emission)))
                       if redirect else ""))
        return ("Repo top-%s%% active, token bottom-%s%% — market hasn't "
                "priced %d commits/30d from %d devs."
                % (100 - (act_p or 0), mom_p, c30, a30))
    if why == "divergence" and sc["cue_kind"] == "dn":
        if days is not None and mom7 is not None and mom7 > 0:
            return ("Price %s 7d on a repo dead %dd — momentum with nothing "
                    "behind it." % (_mom_txt(mom7), days))
        return ("Token top-%s%% momentum on a repo cooled to %d commits/30d."
                % (100 - (mom_p or 0), c30))
    if why == "abandon":
        if org_multi:
            return ("Org runs %d subnets and one just went cold — %dd "
                    "silent, price unmoved." % (org_multi, days or 0))
        return ("Price %s while the repo has been dead %dd."
                % (_mom_txt(mom7), days or 0))
    if why in ("emission", "opaque"):
        if row.get("emission_opaque"):
            tail = ("" if mom_p is None
                    else " while price rides top-%s%%." % (100 - mom_p))
            return ("Economics loaded from a remote server — unknowable "
                    "from code%s" % (tail or "."))
        return ("%d%% of emission routed off-miners — %s."
                % (rpct, _route_summary(emission)))
    # Fallback (rare): state the strongest available fact.
    return ("%d commits/30d, %d devs, last commit %s."
            % (c30, a30, ("%dd ago" % days) if days is not None else "unknown"))


def _dominant_route(emission: Dict[str, Any]) -> Optional[str]:
    routes = (emission or {}).get("routes") or []
    best = None
    for route in routes:
        frac = route.get("fraction")
        if frac is None or frac <= 0:
            continue  # a 0%/absent fraction is not a meaningful redirect
        if best is None or frac > best.get("fraction", 0):
            best = route
    if not best:
        return None
    dest = best.get("dest_hotkey")
    return ("%d%% routes to a %s wallet (%s:%s)"
            % (round(best["fraction"] * 100), best["kind"],
               best.get("file", "?"), best.get("line", "?")))


def _dominant_kind(emission: Dict[str, Any]) -> str:
    """The dominant OFF-MINER redirect kind (burn is excluded — it is
    destroyed emission, not a redirect, and is not counted in the off-miner
    fraction). Prefers the highest-fraction non-burn route."""
    routes = [r for r in (emission or {}).get("routes") or []
              if r.get("kind") != "burn"]
    for route in sorted(routes, key=lambda r: -(r.get("fraction") or 0)):
        return route.get("kind", "treasury")
    return "treasury"


def _route_summary(emission: Dict[str, Any]) -> str:
    kinds: List[str] = []
    for route in (emission or {}).get("routes") or []:
        if route.get("kind") and route["kind"] != "burn" and (
                route["kind"] not in kinds):
            kinds.append(route["kind"])
    return " + ".join(kinds[:3]) if kinds else "routing in code"


def build_badges(row: Dict[str, Any], sc: Dict[str, Any],
                 emission: Dict[str, Any]) -> List[Dict[str, str]]:
    badges: List[Dict[str, str]] = []
    div = sc.get("div_signed")
    if div is not None and abs(div) >= 15:
        badges.append({"t": "DIV %+d" % div,
                       "color": "var(--up)" if div >= 0 else "var(--dn)"})
    if sc["cold"] and row.get("days_since") is not None:
        badges.append({"t": "COLD %dd" % row["days_since"],
                       "color": "var(--dn)"})
    redirect = row.get("redirect_fraction_upper_bound") or 0.0
    if redirect >= 0.1:
        kind = _dominant_kind(emission).upper()
        badges.append({"t": "%d%%-%s" % (round(redirect * 100), kind),
                       "color": "var(--dn)"})
    if row.get("emission_opaque"):
        badges.append({"t": "OPAQUE", "color": "var(--amb)"})
    if sc["fresh"] and not sc["pulse_spike"]:
        badges.append({"t": "△ ECON", "color": "var(--amb)"})
    if sc["pulse_spike"]:
        badges.append({"t": "PULSE %d" % (row.get("changed_tips") or 0),
                       "color": "var(--amb)"})
    if row.get("momentum_7d") is None and row.get("momentum_30d") is None:
        badges.append({"t": "NO PX DATA", "color": "var(--tx3)"})
    return badges


def _evid_line(row: Dict[str, Any]) -> str:
    redirect = row.get("redirect_fraction_upper_bound") or 0.0
    days = row.get("days_since")
    return ("%d/%d/%dc · %d devs · last %s · pulse %d · "
            "px7 %s · %d%% routed away"
            % (row.get("c7") or 0, row.get("c30") or 0, row.get("c90") or 0,
               row.get("a30") or 0,
               ("%dd" % days) if days is not None else "?",
               row.get("changed_tips") or 0, _mom_txt(row.get("momentum_7d")),
               round(redirect * 100)))


# ---------------------------------------------------------------------------
# Assemble the ranked board from the real report
# ---------------------------------------------------------------------------

_KIND_COLOR = {"burn": "var(--amb)", "treasury": "var(--dn)",
               "partner": "var(--dn)", "owner": "var(--dn)",
               "royalty": "var(--dn)"}


def _drawer_detail(row: Dict[str, Any], sc: Dict[str, Any],
                   emission: Dict[str, Any], thesis: str,
                   baseline: Dict[str, Any],
                   concentration: List[Dict[str, Any]]) -> Dict[str, Any]:
    days = row.get("days_since")
    dev_block = (
        "%d commits 7d · %d 30d · %d 90d\n%d authors 30d\n"
        "last commit %s · %d branch tips moved\nclass: %s"
        % (row.get("c7") or 0, row.get("c30") or 0, row.get("c90") or 0,
           row.get("a30") or 0,
           ("%dd ago" % days) if days is not None else "unknown",
           row.get("changed_tips") or 0, row.get("activity_class") or "?"))
    b7 = baseline.get("7")
    px_block = (
        "Δ7  %s   (fleet %s)\nΔ30 %s   (fleet %s)"
        % (_mom_txt(row.get("momentum_7d")),
           _mom_txt(b7) if b7 is not None else "n/a",
           _mom_txt(row.get("momentum_30d")),
           _mom_txt(baseline.get("30")) if baseline.get("30") is not None
           else "n/a"))
    emissions = [
        {"kind": r["kind"], "color": _KIND_COLOR.get(r["kind"], "var(--tx2)"),
         "frac": ("%d%%" % round(r["fraction"] * 100)
                  if r.get("fraction") is not None else "?"),
         "dest": ("→ %s" % r["dest_hotkey"]) if r.get("dest_hotkey")
                 else "",
         "cite": "%s:%s" % (r.get("file", "?"), r.get("line", "?"))}
        for r in (emission or {}).get("routes") or []]
    redirect = row.get("redirect_fraction_upper_bound") or 0.0
    away_line = ("≈ ≥%d%% of emission routed away from miners"
                 % round(redirect * 100)) if redirect > 0 else (
                 "no off-miner routing detected in code")
    team_note = None
    org = row.get("org")
    for group in concentration:
        if group["org"] == org:
            others = [n for n in group["netuids"] if n != row.get("netuid")]
            team_note = ("%s runs %d subnets — SN%s"
                         % (org, group["count"],
                            ", SN".join(str(n) for n in group["netuids"])))
            break
    dir_label = {"up": "PROMISING — substance ahead of price",
                 "dn": "DANGEROUS — price ahead of substance",
                 "amb": "WATCH — something just moved",
                 "tx3": "QUIET"}.get(sc["cue_kind"], "")
    opaque_note = ("Economics load from a remote server at runtime — the "
                   "real split is unknowable from the repository."
                   if row.get("emission_opaque") else None)
    lifetime = ("lifetime %s commits · %s authors (includes inherited "
                "fork history — context only)"
                % (row.get("total_commits_context") or 0,
                   row.get("total_authors_context") or 0))
    return {"netuid": row.get("netuid"), "org": org or "", "cue": sc["cue"],
            "cue_kind": sc["cue_kind"], "thesis": thesis,
            "dir_label": dir_label, "dev_block": dev_block,
            "px_block": px_block, "emissions": emissions,
            "away_line": away_line, "team_note": team_note,
            "opaque_note": opaque_note, "lifetime": lifetime}


def build_board(connection: sqlite3.Connection, config: Dict[str, Any],
                now: Optional[str] = None) -> Dict[str, Any]:
    """The real ranked board: score every active subnet, tier it, and
    assemble head/mid/quiet/invisible plus per-subnet drawer detail. All
    data comes from the metrics report — never a placeholder."""
    cfg = dashboard_cfg(config)
    now = now or _met()._utc_now()
    rep = _met().report(connection, config)
    fresh_netuids = _recent_econ_netuids(connection, now, cfg["fresh_hours"])
    concentration = rep["team_concentration"]
    org_multi = {g["org"]: g["count"] for g in concentration}
    emission_detail = rep["emission_detail"]
    baseline = rep["momentum_baseline"]

    scored: List[Dict[str, Any]] = []
    for row in rep["subnets"]:
        nid = row["netuid"]
        emission = emission_detail.get(nid) or emission_detail.get(str(nid)) or {}
        sc = score_subnet(row, nid in fresh_netuids, cfg)
        thesis = build_thesis(row, sc, emission,
                              org_multi.get(row.get("org")) if row.get("org")
                              and org_multi.get(row.get("org"), 0) > 1
                              else None)
        detail = _drawer_detail(row, sc, emission, thesis, baseline,
                                concentration)
        scored.append({"row": row, "sc": sc, "thesis": thesis,
                       "emission": emission, "detail": detail,
                       "badges": build_badges(row, sc, emission),
                       "evid": _evid_line(row)})
    scored.sort(key=lambda s: -s["sc"]["score"])

    head: List[Dict[str, Any]] = []
    mid: List[Dict[str, Any]] = []
    quiet: List[Dict[str, Any]] = []
    opaque_group: List[int] = []
    for item in scored:
        score = item["sc"]["score"]
        if item["sc"]["pure_opaque"]:
            opaque_group.append(item["row"]["netuid"])
            continue
        if len(head) < cfg["head_count"] and score >= cfg["head_min_score"]:
            head.append(item)
        elif len(mid) < cfg["mid_count"] and score >= cfg["mid_min_score"]:
            mid.append(item)
        else:
            quiet.append(item)

    diverging = sum(1 for s in scored
                    if s["sc"]["div_signed"] is not None
                    and abs(s["sc"]["div_signed"]) >= 40)
    emission_flags = sum(1 for s in scored
                         if (s["row"].get("redirect_fraction_upper_bound") or 0)
                         >= 0.1 or s["row"].get("emission_opaque"))
    cold = sum(1 for s in scored if s["sc"]["cold"])
    return {"generated_at": rep["generated_at"], "head": head, "mid": mid,
            "quiet": quiet, "opaque_group": opaque_group,
            "invisible": rep["invisible_fleet"],
            "price_history_present": rep["price_history_present"],
            "counts": {"diverging": diverging, "emission": emission_flags,
                       "cold": cold, "quiet": len(quiet),
                       "invisible": len(rep["invisible_fleet"])}}


# ---------------------------------------------------------------------------
# Render — one self-contained static page, exact reference structure
# ---------------------------------------------------------------------------

_CSS = """
html,body{margin:0;padding:0;height:100%;overflow:hidden}
body{background:var(--bg);color:var(--tx);font-family:'Space Grotesk',system-ui,sans-serif}
*{box-sizing:border-box}
[data-theme="dark"]{--bg:#0e1014;--panel:#151920;--panel2:#1b202a;--tx:#e7eaf2;--tx2:#98a0b3;--tx3:#5b6373;--line:rgba(255,255,255,.08);--up:oklch(0.76 0.15 155);--dn:oklch(0.72 0.17 27);--amb:oklch(0.8 0.13 85);--chip:rgba(255,255,255,.05);--track:rgba(255,255,255,.09);--shade:rgba(0,0,0,.6)}
[data-theme="light"]{--bg:#f3f2ee;--panel:#ffffff;--panel2:#eceae4;--tx:#191b20;--tx2:#5d6472;--tx3:#9aa0ac;--line:rgba(20,24,32,.1);--up:oklch(0.52 0.15 155);--dn:oklch(0.52 0.17 27);--amb:oklch(0.58 0.13 78);--chip:rgba(20,24,32,.05);--track:rgba(20,24,32,.1);--shade:rgba(20,22,28,.35)}
.mono{font-family:'JetBrains Mono','SFMono-Regular',ui-monospace,Menlo,monospace}
.hrow:hover{background:var(--panel)}
.mrow:hover{color:var(--tx)!important}
.chip:hover{color:var(--tx2)!important}
button{cursor:pointer}
"""

_JS = """
(function(){
  var root=document.getElementById('root');
  function setTheme(t){root.setAttribute('data-theme',t);
    document.getElementById('themebtn').textContent=t==='dark'?'LIGHT':'DARK';
    try{localStorage.setItem('atlas_theme',t)}catch(e){}}
  var saved;try{saved=localStorage.getItem('atlas_theme')}catch(e){}
  if(saved)setTheme(saved);
  document.getElementById('themebtn').addEventListener('click',function(){
    setTheme(root.getAttribute('data-theme')==='dark'?'light':'dark')});
  var filter='all';
  function applyFilter(f){filter=f;
    document.querySelectorAll('[data-fb]').forEach(function(b){
      b.style.opacity=(b.getAttribute('data-fb')===f)?'1':'.5'});
    document.querySelectorAll('.hrow').forEach(function(r){
      var show=f==='all'||r.getAttribute('data-tags').indexOf('|'+f+'|')>=0;
      r.style.display=show?'grid':'none'})}
  document.querySelectorAll('[data-fb]').forEach(function(b){
    b.addEventListener('click',function(){applyFilter(b.getAttribute('data-fb'))})});
  var DETAIL=JSON.parse(document.getElementById('detaildata').textContent);
  var drawer=document.getElementById('drawer'),shade=document.getElementById('shade');
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
  function open(uid){var s=DETAIL[uid];if(!s)return;
    var cc='var(--'+s.cue_kind+')';
    var em=s.emissions.map(function(e){return '<div style="display:flex;align-items:baseline;gap:8px;font:400 11px monospace;margin-bottom:4px"><span style="font-weight:700;color:'+e.color+';min-width:64px;text-transform:uppercase">'+esc(e.kind)+'</span><span style="color:var(--tx)">'+esc(e.frac)+'</span><span style="color:var(--tx3);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(e.dest)+'</span><span style="color:var(--tx3)">'+esc(e.cite)+'</span></div>'}).join('');
    var opaque=s.opaque_note?'<div style="font:500 11px monospace;color:var(--amb);margin-bottom:6px">'+esc(s.opaque_note)+'</div>':'';
    var team=s.team_note?'<div><div class="mono" style="font:700 10px monospace;letter-spacing:.15em;color:var(--tx3);margin-bottom:6px">TEAM CONCENTRATION</div><div class="mono" style="font-size:11.5px;line-height:1.6;color:var(--tx2)">'+esc(s.team_note)+'</div></div>':'';
    drawer.innerHTML='<div style="display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)"><span class="mono" style="font-weight:700;font-size:15px;color:'+cc+'">'+esc(s.cue)+'</span><span class="mono" style="font-weight:700;font-size:15px">SN'+esc(s.netuid)+'</span><span class="mono" style="font-size:11px;color:var(--tx3)">'+esc(s.org)+'</span><span style="flex:1"></span><button id="closebtn" class="mono" style="font-weight:700;font-size:12px;border:1px solid var(--line);background:none;color:var(--tx2);border-radius:6px;padding:3px 9px">ESC</button></div>'+
      '<div style="flex:1;overflow:auto;padding:16px 18px;display:flex;flex-direction:column;gap:16px">'+
      '<div style="font:500 15px/1.4 sans-serif">'+esc(s.thesis)+'</div>'+
      '<div class="mono" style="font:500 10px monospace;letter-spacing:.12em;color:'+cc+'">'+esc(s.dir_label)+'</div>'+
      '<div><div class="mono" style="font:700 10px monospace;letter-spacing:.15em;color:var(--tx3);margin-bottom:6px">DEV ACTIVITY</div><div class="mono" style="font-size:11.5px;line-height:1.8;color:var(--tx2);white-space:pre-line">'+esc(s.dev_block)+'</div></div>'+
      '<div><div class="mono" style="font:700 10px monospace;letter-spacing:.15em;color:var(--tx3);margin-bottom:6px">PRICE MOMENTUM vs FLEET</div><div class="mono" style="font-size:11.5px;line-height:1.8;color:var(--tx2);white-space:pre-line">'+esc(s.px_block)+'</div></div>'+
      '<div><div class="mono" style="font:700 10px monospace;letter-spacing:.15em;color:var(--tx3);margin-bottom:6px">EMISSION MAP</div>'+opaque+em+'<div class="mono" style="font-size:11px;color:var(--tx2);margin-top:8px">'+esc(s.away_line)+'</div></div>'+
      team+
      '<div class="mono" style="font-size:10px;color:var(--tx3)">'+esc(s.lifetime)+'</div></div>';
    drawer.style.display='flex';shade.style.display='block';
    document.getElementById('closebtn').addEventListener('click',close);}
  function close(){drawer.style.display='none';shade.style.display='none';}
  shade.addEventListener('click',close);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')close()});
  document.querySelectorAll('[data-uid]').forEach(function(el){
    el.addEventListener('click',function(){open(el.getAttribute('data-uid'))})});
})();
"""


def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _bar(pct: Optional[int], color: str) -> str:
    width = "0%%" if pct is None else "%d%%" % max(0, min(100, pct))
    label = "n/a" if pct is None else str(pct)
    return ('<span style="flex:1;height:5px;background:var(--track);'
            'border-radius:3px;overflow:hidden;display:block">'
            '<span style="display:block;height:100%%;width:%s;background:%s">'
            '</span></span><span class="mono" style="font-size:9px;'
            'color:var(--tx2);width:26px;text-align:right">%s</span>'
            % (width, color, label))


def _head_row(rank: int, item: Dict[str, Any]) -> str:
    row, sc = item["row"], item["sc"]
    cue_color = "var(--%s)" % sc["cue_kind"]
    act_p, mom_p = _pct(row.get("activity_pct")), _pct(row.get("momentum_pct"))
    b7 = None  # px bar color: red if negative momentum else green
    mom7 = row.get("momentum_7d")
    px_color = ("var(--up)" if (mom7 is not None and mom7 >= 0)
                else "var(--dn)" if mom7 is not None else "var(--track)")
    tags = ["|all|"]
    if sc["cue_kind"] == "up":
        tags.append("|promising|")
    if sc["cue_kind"] == "dn":
        tags.append("|dangerous|")
    if sc["div_signed"] is not None and abs(sc["div_signed"]) >= 40:
        tags.append("|diverged|")
    if (row.get("redirect_fraction_upper_bound") or 0) >= 0.1 or row.get(
            "emission_opaque"):
        tags.append("|emission|")
    badges = "".join(
        '<span class="mono" style="font:700 8.5px monospace;letter-spacing:'
        '.06em;color:%s;border:1px solid %s;border-radius:3px;padding:1px 5px;'
        'white-space:nowrap">%s</span>' % (b["color"], b["color"], _esc(b["t"]))
        for b in item["badges"])
    return (
        '<div class="hrow mono" data-uid="%d" data-tags="%s" style="min-height:'
        '48px;display:grid;grid-template-columns:56px 18px minmax(0,1fr) 176px;'
        'gap:14px;align-items:center;padding:6px 18px;border-bottom:1px solid '
        'var(--line);cursor:pointer;border-left:3px solid %s">'
        '<div style="text-align:right"><div style="font-weight:700;font-size:'
        '13px;color:var(--tx3)">%02d</div><div style="font-weight:700;'
        'font-size:11px;color:var(--tx)">%d</div><div style="font-weight:500;'
        'font-size:8px;letter-spacing:.03em;color:var(--tx3);text-transform:'
        'uppercase">%s</div></div>'
        '<div style="font-weight:700;font-size:14px;color:%s">%s</div>'
        '<div style="min-width:0"><div style="display:flex;align-items:'
        'baseline;gap:10px;min-width:0"><span style="font-weight:700;font-size:'
        '13px;white-space:nowrap">SN%d</span><span style="font-size:11px;'
        'color:var(--tx3);white-space:nowrap">%s</span><span style="font-'
        'family:sans-serif;font-weight:500;font-size:14px;overflow:hidden;'
        'text-overflow:ellipsis;white-space:nowrap">%s</span></div>'
        '<div style="display:flex;align-items:center;gap:6px;margin-top:3px;'
        'min-width:0">%s<span style="font-size:10.5px;color:var(--tx2);'
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">%s</span>'
        '</div></div>'
        '<div style="display:flex;flex-direction:column;gap:3px">'
        '<div style="display:flex;align-items:center;gap:6px"><span '
        'style="font-size:9px;color:var(--tx3);width:24px">DEV</span>%s</div>'
        '<div style="display:flex;align-items:center;gap:6px"><span '
        'style="font-size:9px;color:var(--tx3);width:24px">PX</span>%s</div>'
        '</div></div>'
        % (row["netuid"], "".join(tags), cue_color, rank, sc["score"],
           _esc(sc["why"]), cue_color, _esc(sc["cue"]), row["netuid"],
           _esc(row.get("org") or ""), _esc(item["thesis"]), badges,
           _esc(item["evid"]), _bar(act_p, "var(--up)"),
           _bar(mom_p, px_color)))


def _mid_row(item: Dict[str, Any]) -> str:
    row, sc = item["row"], item["sc"]
    badge = item["badges"][0]["t"] if item["badges"] else ""
    badge_color = item["badges"][0]["color"] if item["badges"] else "var(--tx3)"
    thesis = item["thesis"]
    return (
        '<div class="mrow mono" data-uid="%d" style="display:flex;align-items:'
        'baseline;gap:7px;font-size:11px;color:var(--tx2);cursor:pointer;'
        'padding:2px 0;min-width:0"><span style="color:var(--%s);font-weight:'
        '700">%s</span><span style="font-weight:700;color:var(--tx)">SN%d'
        '</span><span style="font:700 8.5px monospace;color:%s;white-space:'
        'nowrap">%s</span><span style="overflow:hidden;text-overflow:ellipsis;'
        'white-space:nowrap">%s</span></div>'
        % (row["netuid"], sc["cue_kind"], _esc(sc["cue"]), row["netuid"],
           badge_color, _esc(badge), _esc(thesis)))


def render_html(board: Dict[str, Any], theme: str = "dark") -> str:
    counts = board["counts"]
    summary = ("%d diverging hard · %d emission flags · %d cold "
               "repos · %d quiet · %d invisible"
               % (counts["diverging"], counts["emission"], counts["cold"],
                  counts["quiet"], counts["invisible"]))
    generated = _esc(board["generated_at"][:16].replace("T", " ") + " UTC")

    filters = [("all", "ALL"), ("promising", "▲ PROMISING"),
               ("dangerous", "▼ DANGEROUS"), ("diverged", "⚖ "
               "DIVERGED"), ("emission", "⚑ EMISSION")]
    fbtns = "".join(
        '<button class="mono" data-fb="%s" style="font:500 10px monospace;'
        'padding:4px 9px;border-radius:99px;border:1px solid var(--line);'
        'background:none;color:var(--tx2);opacity:%s">%s</button>'
        % (key, "1" if key == "all" else ".5", _esc(label))
        for key, label in filters)

    head_html = "".join(_head_row(i + 1, it)
                        for i, it in enumerate(board["head"])) or (
        '<div class="mono" style="padding:20px 18px;color:var(--tx3)">'
        'No subnets cross the attention threshold this snapshot.</div>')
    mid_html = "".join(_mid_row(it) for it in board["mid"])
    opaque_line = ""
    if board["opaque_group"]:
        opaque_line = (
            '<div class="mono" style="font-size:10.5px;color:var(--tx3);'
            'padding:2px 18px 7px"><span style="color:var(--amb);font-weight:'
            '700">⚠</span> %d subnets: economics opaque, no other signal '
            '— SN%s</div>'
            % (len(board["opaque_group"]),
               ", SN".join(str(n) for n in board["opaque_group"])))
    quiet_chips = "".join(
        '<span class="chip mono" data-uid="%d" title="score %d" style="font-'
        'size:9.5px;color:var(--tx3);background:var(--chip);border-radius:4px;'
        'padding:2px 7px;cursor:pointer">%d</span>'
        % (it["row"]["netuid"], it["sc"]["score"], it["row"]["netuid"])
        for it in board["quiet"])
    invis_chips = "".join(
        '<span class="mono" title="%s" style="font-size:9px;color:var(--tx3);'
        'border:1px dashed var(--line);border-radius:4px;padding:1px 6px;'
        'opacity:.55">%s</span>'
        % (_esc(v.get("reason") or v.get("status") or ""), _esc(v["netuid"]))
        for v in board["invisible"])

    detail = {str(it["row"]["netuid"]): it["detail"]
              for it in board["head"] + board["mid"] + board["quiet"]}
    detail_json = _esc(json.dumps(detail))

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Subnet Attention</title><style>%s</style></head><body>'
        '<div id="root" data-theme="%s" style="height:100vh;display:grid;'
        'grid-template-rows:auto 1fr auto auto auto;background:var(--bg);'
        'color:var(--tx);overflow:hidden">'
        # header
        '<header style="display:flex;align-items:center;gap:16px;flex-wrap:'
        'wrap;padding:10px 18px;border-bottom:1px solid var(--line)">'
        '<div class="mono" style="font-weight:700;font-size:13px;letter-'
        'spacing:.12em">SUBNET ATTENTION</div>'
        '<div class="mono" style="font-size:11px;color:var(--tx2)">%s</div>'
        '<div style="flex:1"></div><div style="display:flex;gap:6px">%s</div>'
        '<button id="themebtn" class="mono" style="font:500 10px monospace;'
        'padding:4px 9px;border-radius:99px;border:1px solid var(--line);'
        'background:none;color:var(--tx2)">LIGHT</button>'
        '<div class="mono" style="font-size:10px;color:var(--tx3)">%s</div>'
        '</header>'
        # head section
        '<section style="min-height:0;display:flex;flex-direction:column;'
        'overflow:hidden"><div style="display:flex;align-items:center;gap:10px;'
        'padding:7px 18px 4px"><span class="mono" style="font-weight:700;'
        'font-size:10px;letter-spacing:.15em;color:var(--tx2)">HEAD — LOOK '
        'HERE</span><span style="flex:1;height:1px;background:var(--line)">'
        '</span><span class="mono" style="font-size:9px;color:var(--tx3)">'
        'SCORE = attention · DEV = repo-activity pctile · PX = price-'
        'momentum pctile · the gap between the bars is the divergence'
        '</span></div><div style="flex:1;min-height:0;overflow:auto">%s</div>'
        '</section>'
        # mid section
        '<section style="border-top:2px solid var(--line)"><div style="display:'
        'flex;align-items:center;gap:10px;padding:6px 18px 4px"><span '
        'class="mono" style="font-weight:700;font-size:10px;letter-spacing:'
        '.15em;color:var(--tx3)">MID — SKIM</span><span style="flex:1;'
        'height:1px;background:var(--line)"></span></div><div style="display:'
        'grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));'
        'gap:1px 20px;padding:2px 18px 8px;max-height:24vh;overflow:auto">%s'
        '</div>%s</section>'
        # quiet section
        '<section style="border-top:1px solid var(--line);background:'
        'var(--panel2)"><div style="display:flex;align-items:center;gap:10px;'
        'padding:6px 18px 3px"><span class="mono" style="font-weight:700;'
        'font-size:9px;letter-spacing:.15em;color:var(--tx3)">QUIET — %d '
        'UNREMARKABLE THIS HOUR</span><span style="flex:1;height:1px;'
        'background:var(--line)"></span></div><div style="display:flex;flex-'
        'wrap:wrap;gap:4px;padding:3px 18px 8px;max-height:16vh;overflow:auto">'
        '%s</div></section>'
        # invisible section
        '<section style="border-top:1px solid var(--line);background:'
        'var(--panel2)"><div style="display:flex;align-items:center;flex-wrap:'
        'wrap;gap:4px 10px;padding:5px 18px 7px"><span class="mono" '
        'style="font-weight:700;font-size:9px;letter-spacing:.15em;color:'
        'var(--tx3)">INVISIBLE — %d NO REACHABLE REPO</span>%s</div>'
        '</section>'
        # drawer + shade + data
        '<div id="shade" style="display:none;position:fixed;inset:0;background:'
        'var(--shade);z-index:9"></div>'
        '<div id="drawer" style="display:none;position:fixed;top:0;right:0;'
        'height:100vh;width:min(460px,100vw);background:var(--panel);border-'
        'left:1px solid var(--line);z-index:10;flex-direction:column;box-'
        'shadow:-12px 0 40px rgba(0,0,0,.3)"></div>'
        '</div>'
        '<script type="application/json" id="detaildata">%s</script>'
        '<script>%s</script></body></html>'
        % (_CSS, _esc(theme), _esc(summary), fbtns, generated, head_html,
           mid_html, opaque_line, counts["quiet"], quiet_chips,
           counts["invisible"], invis_chips, detail_json, _JS))


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def render(connection: sqlite3.Connection, config: Dict[str, Any],
           now: Optional[str] = None) -> Dict[str, Any]:
    """Build the ranked board from the real store and write one self-
    contained index.html atomically into the www dir. Returns a small
    summary; never raises for an empty store (renders an honest empty
    board)."""
    cfg = dashboard_cfg(config)
    board = build_board(connection, config, now=now)
    page = render_html(board)
    www = cfg["www_dir"]
    if not os.path.isabs(www):
        www = os.path.join(_fleet()._REPO_ROOT, www)
    out = os.path.join(www, "index.html")
    _atomic_write(out, page)
    return {"path": out, "bytes": len(page), "head": len(board["head"]),
            "mid": len(board["mid"]), "quiet": len(board["quiet"]),
            "invisible": len(board["invisible"]),
            "opaque_grouped": len(board["opaque_group"])}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet_dashboard",
        description="Atlas rotation cockpit: render the ranked subnet-"
                    "attention board from the real fleet store.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render", help="write var/fleet/www/index.html")
    sub.add_parser("board", help="print the ranked board as JSON (no render)")
    args = parser.parse_args(argv)

    fleet = _fleet()
    try:
        config = fleet.load_config(args.config or fleet.CONFIG_FILE)
        connection = fleet.open_store(config["db"])
        try:
            _met().ensure_schema(connection)
            if args.command == "render":
                result: Dict[str, Any] = render(connection, config)
            else:
                board = build_board(connection, config)
                result = {"counts": board["counts"],
                          "head": [{"rank": i + 1, "netuid": it["row"]["netuid"],
                                    "score": it["sc"]["score"],
                                    "why": it["sc"]["why"],
                                    "thesis": it["thesis"]}
                                   for i, it in enumerate(board["head"])]}
            print(json.dumps(result, indent=2, sort_keys=True))
        finally:
            connection.close()
        return 0
    except fleet.FleetError as exc:
        print("fatal: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
