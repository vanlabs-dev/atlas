#!/usr/bin/env python3
"""Atlas mining triage — a read-only screen ranking subnets by what a new
independent miner could earn (change: mining-triage).

Joins two halves Atlas already holds and never connected: chain and panel
economics from live-data, and code feasibility from the fleet clones and
their FTS index. Output is a ranked shortlist where every excluded subnet
keeps the reason it was cut, a LAN-only board page, and a read-only query
surface on the existing atlas-fleet MCP server.

What the economics actually turn on, verified on-device 2026-08-07:

- The alpha DISTRIBUTED to participants is `alpha_out_emission`, a protocol
  constant of one alpha per block on every subnet. `alpha_in_emission` is
  the capped TAO-side pool injection and is NOT miner income. Because the
  distributed quantity is constant, quantity carries no ranking information:
  what separates subnets is the TAO value of that alpha and how few people
  share it.
- `MinerBurned` is not an owner knob. `run_coinbase.rs` computes it as the
  proportion of each tempo's miner incentive that landed on owner or
  owner-associated immune hotkeys and was burned or recycled. It withholds
  from the miner leg at distribution AND penalises the subnet's price share
  afterwards. The share penalty is already inside the observed emission, so
  the burn factor is applied exactly once here.
- Reward is winner-take-most. `SubnetworkN` is 256 nearly everywhere while
  only single digits of UIDs earn anything, so a pool-divided-by-field
  average is meaningless and is never produced. Concentration is reported
  instead.
- A gate-disabled subnet still pays its miners alpha; it loses the TAO
  inflow backing it. Cut for a decaying price, not for absent payment.

Invariants inherited from the fleet: read-only over clones, never builds or
executes subnet code, additive tables in the shared fleet store, per-subnet
fail-closed, and no network access of its own — every provider and chain
call goes through live-data so it lands in that component's validation,
retry, quota and audit path.

Public surface:

- ensure_schema(conn)                  — create the mine_* tables
- run_econ(conn, config, …)            — Stage A economics screen
- run_feasibility(conn, config, …)     — Stage B sha-gated code scan
- report(conn, config, …)              — Stage C ranked view + cut ladder
- run_pass(conn, config, …)            — econ + feasibility + render
- mining_status(conn)                  — coverage + confidence summary
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

MINING_VERSION = "0.1.0"

# Bump when the feasibility scanner's LOGIC changes, not when the code moves.
# Feasibility is sha-gated on the scanned commit, so a scanner fix would
# otherwise never re-run against clones that have not moved, and the old
# verdicts would sit there looking current. Learned the hard way: the first
# VRAM parser matched no real min_compute.yml and its empty results were
# already persisted.
SCAN_VERSION = "2"

BLOCKS_PER_DAY = 7200  # 12s blocks
DAYS_PER_MONTH = 30.0

# Confidence markers. `ok` is the only value that permits a net figure.
CONF_OK = "ok"
CONF_CHAIN_UNAVAILABLE = "chain-unavailable"
CONF_INCOMPLETE = "incomplete-inputs"

# Cut ladder rungs, in application order.
CUT_GATE = "gate-disabled"
CUT_IDENTITY = "identity-placeholder"
CUT_BURN = "owner-capture"
CUT_CONCENTRATION = "winner-take-all"
CUT_FEASIBILITY = "not-minable"
CUT_HARDWARE = "above-budget-band"

# On-chain identity states. `unread` is the fail-open value: it means the
# whole SubnetIdentitiesV3 map was unavailable, which must NOT be read as
# every subnet being unnamed. `absent` means the map read fine and this
# netuid has no entry, which is a real finding about that subnet.
IDENT_NAMED = "named"
IDENT_PLACEHOLDER = "placeholder"
IDENT_ABSENT = "absent"
IDENT_UNREAD = "unread"

# Feasibility verdicts. A closed set, not free strings: `unknown` is a real
# value and is never rendered as feasible.
VERDICT_POSSIBLE = "possible"
VERDICT_NEEDS_GPU = "needs-gpu"
VERDICT_CLOSED = "closed"
VERDICT_STUB = "stub"
VERDICT_UNKNOWN = "unknown"
VERDICTS = (VERDICT_POSSIBLE, VERDICT_NEEDS_GPU, VERDICT_CLOSED,
            VERDICT_STUB, VERDICT_UNKNOWN)
INFEASIBLE_VERDICTS = (VERDICT_CLOSED, VERDICT_STUB)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mine_econ (
    ts TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    gate_state TEXT,
    alpha_out_day REAL,
    alpha_in_day REAL,
    miner_burn_pct REAL,
    miner_alpha_day REAL,
    subnetwork_n INTEGER,
    earner_count INTEGER,
    top1_share_pct REAL,
    top10_share_pct REAL,
    incumbent_alpha_day REAL,
    entrant_alpha_day REAL,
    displacement_rank INTEGER,
    price_tao REAL,
    alpha_in_pool REAL,
    root_in_pool REAL,
    haircut_pct REAL,
    reg_cost_tao REAL,
    collateral_lock_pct REAL,
    subnet_name TEXT,
    identity_state TEXT,
    rent_band TEXT,
    rent_tao_month REAL,
    gross_tao_month REAL,
    net_tao_month REAL,
    baseline_tao_month REAL,
    cut_reason TEXT,
    cut_detail TEXT,
    confidence TEXT NOT NULL,
    block_ref INTEGER,
    source_ts TEXT,
    PRIMARY KEY (ts, netuid)
);
CREATE INDEX IF NOT EXISTS mine_econ_netuid_ts
    ON mine_econ (netuid, ts DESC);
CREATE TABLE IF NOT EXISTS mine_feasibility (
    netuid INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    sha TEXT NOT NULL,
    verdict TEXT NOT NULL,
    min_compute_path TEXT,
    gpu_floor TEXT,
    vram_gb REAL,
    entrypoint_path TEXT,
    closed_api INTEGER,
    evidence_json TEXT,
    scanned_at TEXT NOT NULL,
    PRIMARY KEY (netuid, epoch, sha)
);
CREATE TABLE IF NOT EXISTS mine_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Config — code defaults merged under fleet/config.json's `mining` block.
# ---------------------------------------------------------------------------

DEFAULT_MINING_CFG: Dict[str, Any] = {
    # DEFAULTS OFF, like the emission-gate signal. Flipping this in
    # fleet/config.json is the whole rollback, and it means the screen is
    # the only part of the fleet pass that reaches a provider: a caller that
    # has not opted in never triggers a network call from a reconcile.
    "enabled": False,
    # The protocol miner share of distributed alpha. NOT hardcoded silently:
    # `miner_share_source` must be present or the screen refuses to compute a
    # miner-accessible figure at all. Sourced 2026-08-07 from the knowledge
    # base and corroborated by the live panel's owner_emission_share of 0.18.
    "miner_share": 0.41,
    "miner_share_source":
        "atlas-kb ground-truth.md::Emissions and Halving lines 58-65 "
        "(confirmed, coverage 2026-08-06): 18% owner / 41% miners / "
        "41% validators, fixed at protocol level",
    # Owner capture at or above this percent means a new miner is competing
    # for a remainder that rounds to nothing, and the subnet's price share is
    # multiplied by (1 - burn) on top. Operator decision, 2026-08-07.
    "burn_ceiling_pct": 99.0,
    # Incumbent capture. At or above this top-1 share of the incentive
    # vector the field is winner-take-all: entry means displacing the single
    # earner, not joining a field, and the parity model that drives the
    # headline figure is at its least honest. Measured on the top-1 SHARE
    # rather than the earner count, because a subnet can pay ten UIDs and
    # still round to 100 percent for the top one (netuid 63 does exactly
    # that, and 101 keeps 90 percent on one UID across a 249-earner field).
    # Operator decision, 2026-08-12.
    "top1_ceiling_pct": 95.0,
    # Assumed daily sale of earned alpha, as a fraction of the day's earnings,
    # for the constant-product exit haircut.
    "daily_sale_fraction": 1.0,
    # Do-nothing baseline: staking the same capital rather than mining it.
    "staking_apy_pct": 0.0,
    # Hardware bands. `rent_tao_month` is hand-set, never scraped.
    "rent_bands": {
        "cpu": {"vram_gb": 0, "rent_tao_month": 0.0},
        "consumer-gpu": {"vram_gb": 24, "rent_tao_month": 2.0},
        "datacenter-gpu": {"vram_gb": 80, "rent_tao_month": 6.0},
    },
    # None means no band chosen yet (D2 deferred): the hardware rung does not
    # cut, and rent is reported as unknown rather than assumed zero.
    "budget_band": None,
    # On-chain SubnetIdentitiesV3 names that mean the slot is not a going
    # concern. Matched against the name's normalised FIRST TOKEN, so
    # `pending...`, `Parked` and `wait (reproduce paper)` all resolve without
    # needing an entry each. Observed on live Finney 2026-08-12: deprecated
    # (3, 39, 81), unknown (16, 42), pending (94), parked (73), wait (47).
    # Owner-written free text, so this list is expected to grow; it is data
    # to match against, never anything that is executed or followed.
    "identity_placeholders": ["deprecated", "unknown", "pending", "parked",
                              "wait", "tbd", "none", "test", "placeholder"],
    "retention_days": 90,
    "board_limit": 10,
    # Feasibility scan surface.
    "min_compute_names": ["min_compute.yml", "min_compute.yaml"],
    "entrypoint_tokens": ["neurons/miner.py", "neuron/miner.py",
                          "miner.py", "template/miner"],
    "gpu_tokens": ["torch.cuda", "device=\"cuda\"", "device='cuda'",
                   "cuda:0", "vllm", "bitsandbytes", "nvidia-smi",
                   "nvidia/cuda", "flash_attn"],
    "closed_api_tokens": ["openai", "anthropic", "api_key", "apikey",
                          "bearer "],
    "exclude_path_parts": ["vendor", "node_modules", "test", "tests",
                           "docs", "doc", "examples", "example", ".github"],
    "max_evidence_per_kind": 4,
}


def mining_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_MINING_CFG)
    for key, value in (config.get("mining") or {}).items():
        if key == "_comment":
            continue
        merged[key] = value
    return merged


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


# Columns added to mine_econ after the table first shipped. CREATE TABLE IF
# NOT EXISTS is a no-op against a store that already has the old shape, so
# a deployed Pi would keep the old columns and every insert would fail.
_MINE_ECON_ADDED: Tuple[Tuple[str, str], ...] = (
    ("subnet_name", "TEXT"),
    ("identity_state", "TEXT"),
)


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the mining tables if absent, and add columns a deployed store
    predates. Owns only its own tables; additive only, never destructive."""
    connection.executescript(SCHEMA_SQL)
    have = {row[1] for row in connection.execute(
        "PRAGMA table_info(mine_econ)")}
    for column, decl in _MINE_ECON_ADDED:
        if column not in have:
            connection.execute(
                "ALTER TABLE mine_econ ADD COLUMN %s %s" % (column, decl))


def state_get(connection: sqlite3.Connection, key: str) -> Optional[str]:
    try:
        row = connection.execute(
            "SELECT value FROM mine_state WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None  # read path over a store that has never been written
    return row[0] if row else None


def state_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO mine_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


_FLEET: Any = None
_LIVE: Any = None


def _fleet() -> Any:
    global _FLEET
    if _FLEET is None:
        sys.path.insert(0, _MODULE_DIR)
        import atlas_fleet  # noqa: E402
        _FLEET = atlas_fleet
    return _FLEET


def _live() -> Any:
    """Lazy import of live-data. It owns every provider and chain call; this
    module never opens a socket of its own."""
    global _LIVE
    if _LIVE is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
        import atlas_live  # noqa: E402
        _LIVE = atlas_live
    return _LIVE


# ---------------------------------------------------------------------------
# Pure economics — unit-testable, no IO
# ---------------------------------------------------------------------------

def miner_alpha_per_day(alpha_out_per_block: float, miner_share: float,
                        burn_pct: float) -> float:
    """Alpha reaching independent miners per day.

    `alpha_out_per_block` is the participant distribution, NOT the pool
    injection. The burn is applied exactly once: the subnet-share penalty it
    also causes is already inside the observed emission.
    """
    burn_fraction = max(0.0, min(1.0, float(burn_pct) / 100.0))
    return (float(alpha_out_per_block) * BLOCKS_PER_DAY * float(miner_share)
            * (1.0 - burn_fraction))


def concentration(incentive: List[int]) -> Dict[str, Any]:
    """Earner count and top-1 / top-10 shares from a chain incentive vector.

    Reward is winner-take-most, so the count of REGISTERED uids is not the
    competition; the count of earners and how concentrated they are is.
    """
    values = [int(v) for v in incentive or []]
    total = sum(values)
    earners = [v for v in values if v > 0]
    if total <= 0:
        return {"earner_count": len(earners), "top1_share_pct": None,
                "top10_share_pct": None}
    ranked = sorted(values, reverse=True)
    return {
        "earner_count": len(earners),
        "top1_share_pct": 100.0 * ranked[0] / total,
        "top10_share_pct": 100.0 * sum(ranked[:10]) / total,
    }


def exit_haircut_pct(sale_alpha: float, alpha_in_pool: Optional[float],
                     root_in_pool: Optional[float]) -> Optional[float]:
    """Constant-product slippage for selling `sale_alpha` into the pool,
    as a percentage of the no-slippage proceeds. None when pool depth is
    unknown, because a haircut of zero would be a claim, not an absence."""
    if not alpha_in_pool or not root_in_pool or alpha_in_pool <= 0 \
            or root_in_pool <= 0 or sale_alpha <= 0:
        return None
    spot = root_in_pool / alpha_in_pool
    # x*y=k: selling `sale_alpha` alpha returns this much root.
    proceeds = root_in_pool - (root_in_pool * alpha_in_pool
                               / (alpha_in_pool + sale_alpha))
    ideal = sale_alpha * spot
    if ideal <= 0:
        return None
    return max(0.0, 100.0 * (1.0 - proceeds / ideal))


def entrant_alpha_per_day(miner_alpha_day: Optional[float],
                          earner_count: Optional[int]) -> Optional[float]:
    """What a NEW entrant earns under the stated parity assumption: you join
    the field and match the existing earners, so the miner pool is shared
    among `earner_count + 1`.

    This is a model, and it is labelled as one wherever it is shown. It
    exists because the alternative is worse: ranking on what the incumbents
    currently earn puts the most concentrated, least enterable subnets at
    the top of the board, which reads as opportunity and is the opposite.
    """
    if miner_alpha_day is None or earner_count is None:
        return None
    return float(miner_alpha_day) / (int(earner_count) + 1)


def median_of(values: List[float]) -> Optional[float]:
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _rent_for_band(cfg: Dict[str, Any]) -> Tuple[Optional[str],
                                                 Optional[float]]:
    band = cfg.get("budget_band")
    if not band:
        return None, None
    spec = (cfg.get("rent_bands") or {}).get(band)
    if not spec:
        return band, None
    return band, float(spec.get("rent_tao_month") or 0.0)


def _first_token(name: str) -> str:
    """Normalise a free-text subnet name to its first word, lowercased and
    stripped of surrounding punctuation, so `pending...` and
    `wait (reproduce paper)` reduce to `pending` and `wait`."""
    cleaned = re.split(r"[^0-9A-Za-z]+", name.strip().lower())
    return next((part for part in cleaned if part), "")


def classify_identity(cfg: Dict[str, Any], name: Optional[str],
                      seen: bool) -> Tuple[str, Optional[str]]:
    """Classify one subnet's on-chain identity. Returns (state, name).

    `seen` is whether the SubnetIdentitiesV3 map itself was readable. When it
    was not, every subnet is `unread` and the rung stays inert: a renamed or
    unreachable storage item must never cut the whole board.
    """
    if not seen:
        return IDENT_UNREAD, name
    if name is None:
        return IDENT_ABSENT, None
    token = _first_token(name)
    placeholders = {str(p).strip().lower()
                    for p in (cfg.get("identity_placeholders") or [])}
    if not token or token in placeholders:
        return IDENT_PLACEHOLDER, name
    return IDENT_NAMED, name


def classify_cut(cfg: Dict[str, Any], row: Dict[str, Any],
                 feasibility: Optional[Dict[str, Any]]
                 ) -> Tuple[Optional[str], Optional[str]]:
    """Apply the ordered cut ladder. Returns (rung, detail) or (None, None).

    A subnet leaves at the FIRST rung it fails and the reason is recorded;
    exclusion is never implemented as omission.
    """
    if row.get("gate_state") == "disabled":
        return (CUT_GATE,
                "emission gate disabled: alpha is still distributed to "
                "miners but no TAO inflow backs it, so the alpha price "
                "decays and TAO income tends to zero")
    identity = row.get("identity_state")
    if identity == IDENT_PLACEHOLDER:
        return (CUT_IDENTITY,
                "on-chain subnet_name is %r: the owner has marked the slot "
                "as not a going concern, so there is nothing to mine into "
                "regardless of what it still pays"
                % (row.get("subnet_name") or ""))
    if identity == IDENT_ABSENT:
        return (CUT_IDENTITY,
                "no SubnetIdentitiesV3 entry on chain: the slot has never "
                "been named by its owner")
    burn = row.get("miner_burn_pct")
    ceiling = float(cfg.get("burn_ceiling_pct", 99.0))
    if burn is not None and burn >= ceiling:
        return (CUT_BURN,
                "owner hotkeys captured %.2f%% of miner incentive "
                "(ceiling %.0f%%)" % (burn, ceiling))
    # Incumbent capture. Null means the incentive vector was never read, and
    # an unread field is not a concentrated one: fail open, as at every
    # other rung whose input can be absent.
    top1 = row.get("top1_share_pct")
    top1_ceiling = cfg.get("top1_ceiling_pct")
    if top1 is not None and top1_ceiling is not None \
            and float(top1) >= float(top1_ceiling):
        earners = row.get("earner_count")
        return (CUT_CONCENTRATION,
                "top earner takes %.1f%% of the incentive vector across %s "
                "earner(s) (ceiling %.0f%%): entry means displacing that "
                "miner, not joining a field, and the parity model behind the "
                "headline figure does not describe it"
                % (float(top1),
                   "unknown" if earners is None else earners,
                   float(top1_ceiling)))
    if feasibility and feasibility.get("verdict") in INFEASIBLE_VERDICTS:
        return (CUT_FEASIBILITY,
                "feasibility verdict %s" % feasibility["verdict"])
    band, _ = _rent_for_band(cfg)
    if band and feasibility and feasibility.get("vram_gb"):
        band_vram = float(((cfg.get("rent_bands") or {})
                           .get(band) or {}).get("vram_gb") or 0)
        if float(feasibility["vram_gb"]) > band_vram:
            return (CUT_HARDWARE,
                    "declared floor %.0f GB VRAM exceeds band %s (%.0f GB)"
                    % (float(feasibility["vram_gb"]), band, band_vram))
    return None, None


# ---------------------------------------------------------------------------
# Stage A — economics screen
# ---------------------------------------------------------------------------

def _gate_states(live: Any, live_conn: Any) -> Dict[int, str]:
    """Per-netuid gate side from live-data's own gate tracking, when it has
    any. Absent tracking is not an error: `emission_is_enabled` from the
    panel is the primary signal."""
    try:
        rows = live_conn.execute(
            "SELECT netuid, side FROM gate_sides").fetchall()
    except sqlite3.Error:
        return {}
    return {int(r[0]): str(r[1]) for r in rows}


def collect_inputs(config: Dict[str, Any], live: Optional[Any] = None,
                   panel: Optional[Dict[str, Any]] = None,
                   chain: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """Gather the panel and chain legs through live-data.

    Both legs fail independently. `panel` and `chain` may be injected for
    tests; when injected no live-data call is made at all.
    """
    if panel is not None and chain is not None:
        return {"panel": panel, "chain": chain, "gate_sides": {}}

    live = live or _live()
    live_config = live.load_config()
    env = live.load_env()
    connection = live.open_store(live.resolve(live_config["db"]))
    try:
        ledger = live.QuotaLedger(connection, live_config)
        if panel is None:
            panel = live.run_operation(connection, live_config, ledger,
                                       "subnets_taoswap", interactive=False,
                                       env=env)
        if chain is None:
            chain = live.read_subnet_maps(live_config)
        gate_sides = _gate_states(live, connection)

        # Hand the already-read collateral map to the watch. No extra call.
        if chain.get("ok"):
            netuids = sorted(chain["values"].get("SubnetworkN", {}).keys())
            try:
                live.run_subnet_param_watch(
                    connection, live_config, "CollateralLockShare", netuids,
                    chain["values"].get("CollateralLockShare", {}),
                    failures=(chain.get("failures") or {}).get(
                        "CollateralLockShare"),
                    block_hash=chain.get("block_hash"),
                    block_number=chain.get("block_number"))
            except Exception:  # noqa: BLE001 — watch never fails the screen
                pass
    finally:
        connection.close()
    return {"panel": panel, "chain": chain, "gate_sides": gate_sides}


def run_econ(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stage A: one economics observation per subnet.

    Fail-closed in three distinct ways, because they mean different things:
    a dead panel leaves prior rows untouched, a dead chain records rows with
    no net figure, and a single bad subnet is marked unknown alone.
    """
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    if not cfg.get("miner_share_source"):
        return {"ok": False,
                "error": "mining.miner_share_source is unset: the protocol "
                         "miner share must carry a recorded citation before "
                         "any miner-accessible figure is computed"}
    state_set(connection, "miner_share_source",
              str(cfg["miner_share_source"]))

    inputs = inputs or collect_inputs(config)
    panel, chain = inputs["panel"], inputs["chain"]

    if not panel or panel.get("status") != "ok":
        connection.commit()
        return {"ok": False, "leg": "panel",
                "error": (panel or {}).get("error", {}).get("category")
                or "panel unavailable",
                "note": "prior observations left intact; the board renders "
                        "last-known rows with their age"}

    chain_ok = bool(chain and chain.get("ok"))
    chain_values = (chain or {}).get("values") or {}
    chain_failures = (chain or {}).get("failures") or {}
    block_ref = (chain or {}).get("block_number")

    subnets = [s for s in panel["values"]["subnets"]
               if s.get("netuid") is not None and s.get("netuid") != 0]
    # An identity map that enumerated empty is indistinguishable from a
    # renamed storage item, so it is treated as unread and the rung stays
    # inert rather than cutting all 128 subnets at once.
    identities = chain_values.get("SubnetIdentitiesV3") or {}
    identity_seen = bool(chain_ok and identities)
    band, rent = _rent_for_band(cfg)
    share = float(cfg.get("miner_share", 0.41))
    written = 0
    unknown = 0

    for item in subnets:
        netuid = int(item["netuid"])
        row: Dict[str, Any] = {
            "ts": now, "netuid": netuid,
            "gate_state": ("enabled" if item.get("emission_is_enabled")
                           else "disabled"
                           if item.get("emission_is_enabled") is False
                           else None),
            "alpha_out_day": None, "alpha_in_day": None,
            "miner_burn_pct": item.get("emission_miner_burn"),
            "miner_alpha_day": None,
            "subnetwork_n": None, "earner_count": None,
            "top1_share_pct": None, "top10_share_pct": None,
            "incumbent_alpha_day": None, "entrant_alpha_day": None,
            "displacement_rank": None,
            "price_tao": item.get("alpha_price_tao"),
            "alpha_in_pool": item.get("alpha_in_pool"),
            "root_in_pool": item.get("root_in_pool"),
            "haircut_pct": None,
            "reg_cost_tao": item.get("registration_cost"),
            "collateral_lock_pct": None,
            "subnet_name": None, "identity_state": IDENT_UNREAD,
            "rent_band": band, "rent_tao_month": rent,
            "gross_tao_month": None, "net_tao_month": None,
            "baseline_tao_month": None,
            "cut_reason": None, "cut_detail": None,
            "confidence": CONF_OK, "block_ref": block_ref,
            "source_ts": (panel.get("request_completed")
                          or panel.get("upstream_timestamp")),
        }

        alpha_out = item.get("alpha_out_emission")
        alpha_in = item.get("alpha_in_emission")
        if alpha_out is not None:
            row["alpha_out_day"] = float(alpha_out) * BLOCKS_PER_DAY
        if alpha_in is not None:
            row["alpha_in_day"] = float(alpha_in) * BLOCKS_PER_DAY

        burn = row["miner_burn_pct"]
        if alpha_out is not None and burn is not None:
            row["miner_alpha_day"] = miner_alpha_per_day(
                float(alpha_out), share, float(burn))

        row["identity_state"], row["subnet_name"] = classify_identity(
            cfg, identities.get(netuid), identity_seen)

        if not chain_ok:
            row["confidence"] = CONF_CHAIN_UNAVAILABLE
        else:
            if netuid in (chain_failures.get("Incentive") or {}) \
                    or netuid in (chain_failures.get("SubnetworkN") or {}):
                row["confidence"] = CONF_INCOMPLETE
                unknown += 1
            row["subnetwork_n"] = chain_values.get(
                "SubnetworkN", {}).get(netuid)
            lock = chain_values.get("CollateralLockShare", {}).get(netuid)
            if lock is not None:
                row["collateral_lock_pct"] = 100.0 * float(lock) / 65535.0
            else:
                row["collateral_lock_pct"] = 0.0
            vector = chain_values.get("Incentive", {}).get(netuid)
            if vector is not None:
                stats = concentration(vector)
                row["earner_count"] = stats["earner_count"]
                row["top1_share_pct"] = stats["top1_share_pct"]
                row["top10_share_pct"] = stats["top10_share_pct"]
                if row["miner_alpha_day"] is not None \
                        and stats["earner_count"]:
                    total = sum(int(v) for v in vector) or 1
                    per_uid = [row["miner_alpha_day"] * int(v) / total
                               for v in vector if int(v) > 0]
                    row["incumbent_alpha_day"] = median_of(per_uid)
                    # Entry position under the parity assumption.
                    row["displacement_rank"] = stats["earner_count"] + 1
                row["entrant_alpha_day"] = entrant_alpha_per_day(
                    row["miner_alpha_day"], stats["earner_count"])
            elif row["confidence"] == CONF_OK:
                row["confidence"] = CONF_INCOMPLETE
                unknown += 1

        if row["entrant_alpha_day"] is not None:
            row["haircut_pct"] = exit_haircut_pct(
                row["entrant_alpha_day"] * float(
                    cfg.get("daily_sale_fraction", 1.0)),
                row["alpha_in_pool"], row["root_in_pool"])

        # A net figure requires a complete read, and it is an ENTRANT figure
        # under the parity assumption. Ranking on incumbent income would put
        # the most concentrated, least enterable subnets at the top.
        if row["confidence"] == CONF_OK \
                and row["entrant_alpha_day"] is not None \
                and row["price_tao"] is not None:
            haircut = row["haircut_pct"] or 0.0
            gross = (row["entrant_alpha_day"] * float(row["price_tao"])
                     * (1.0 - haircut / 100.0) * DAYS_PER_MONTH)
            row["gross_tao_month"] = gross
            if rent is not None:
                row["net_tao_month"] = gross - rent
            row["baseline_tao_month"] = (
                float(cfg.get("staking_apy_pct", 0.0)) / 100.0 / 12.0
                * (rent or 0.0))

        connection.execute(
            "INSERT OR REPLACE INTO mine_econ (%s) VALUES (%s)"
            % (", ".join(row), ", ".join("?" * len(row))),
            tuple(row.values()))
        written += 1

    prune = prune_econ(connection, cfg, now=now)
    state_set(connection, "last_econ_ts", now)
    connection.commit()
    return {"ok": True, "observations": written, "unknown": unknown,
            "chain": "ok" if chain_ok else CONF_CHAIN_UNAVAILABLE,
            "block_ref": block_ref, "pruned": prune, "ts": now}


def prune_econ(connection: sqlite3.Connection, cfg: Dict[str, Any],
               now: Optional[str] = None) -> int:
    """Bound the economics time series. Feasibility is sha-keyed and is not
    pruned by time."""
    days = int(cfg.get("retention_days", 90))
    if days <= 0:
        return 0
    parsed = datetime.datetime.fromisoformat(
        (now or _utc_now()).replace("Z", "+00:00"))
    cutoff = (parsed - datetime.timedelta(days=days)).isoformat()
    cursor = connection.execute("DELETE FROM mine_econ WHERE ts < ?",
                                (cutoff,))
    return cursor.rowcount or 0


# ---------------------------------------------------------------------------
# Stage B — feasibility over the existing index (never executes subnet code)
# ---------------------------------------------------------------------------

# Real min_compute.yml files (bittensor subnet template) write the value as a
# bare YAML number with the unit in a trailing comment:
#     min_vram: 24                    # Minimum GPU VRAM (GB)
# The unit is therefore NOT adjacent to the number and must not be required.
_MIN_VRAM_RE = re.compile(r"\bmin_vram\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_REC_VRAM_RE = re.compile(r"\brecommended_vram\s*:\s*(\d+(?:\.\d+)?)",
                          re.IGNORECASE)
# Fallback for files that write a unit inline rather than a template key.
_INLINE_VRAM_RE = re.compile(
    r"\bvram\b\D{0,24}?(\d+(?:\.\d+)?)\s*(?:gb|gib)", re.IGNORECASE)
_MINER_SECTION_RE = re.compile(r"^\s*miner\s*:\s*$", re.IGNORECASE)
_ROLE_SECTION_RE = re.compile(r"^\s*(miner|validator)\s*:\s*$", re.IGNORECASE)


def _miner_section(text: str) -> str:
    """The miner block of a min_compute declaration, when the file splits by
    role. This is a MINING screen: reading the validator's requirement would
    describe a machine we are not costing."""
    lines = (text or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if _MINER_SECTION_RE.match(line):
            start = index + 1
            break
    if start is None:
        return text or ""
    for index in range(start, len(lines)):
        if _ROLE_SECTION_RE.match(lines[index]):
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def _excluded(path: str, cfg: Dict[str, Any]) -> bool:
    lowered = path.lower()
    parts = set(lowered.split("/"))
    return any(part in parts for part in cfg.get("exclude_path_parts") or [])


def parse_vram_gb(text: str) -> Tuple[Optional[float], Optional[str]]:
    """The MINER's declared VRAM floor from a min_compute declaration.

    Returns (gb, basis) where basis names which key it came from, because
    `min_vram` is a floor and `recommended_vram` is not, and a board column
    labelled "hardware floor" must not silently show the recommended tier.
    Returns (None, None) when nothing is declared — never a fabricated zero.
    """
    section = _miner_section(text)
    minimums = [float(m.group(1)) for m in _MIN_VRAM_RE.finditer(section)]
    if minimums:
        return max(minimums), "min_vram"
    inline = [float(m.group(1)) for m in _INLINE_VRAM_RE.finditer(section)]
    if inline:
        return max(inline), "inline"
    recommended = [float(m.group(1)) for m in _REC_VRAM_RE.finditer(section)]
    if recommended:
        return max(recommended), "recommended_vram"
    return None, None


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _find_tokens(content: str, tokens: List[str], path: str,
                 limit: int) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    lowered = content.lower()
    for token in tokens:
        position = lowered.find(token.lower())
        if position < 0:
            continue
        hits.append({"token": token, "path": path,
                     "line": _line_of(content, position)})
        if len(hits) >= limit:
            break
    return hits


def scan_slot(connection: sqlite3.Connection, cfg: Dict[str, Any],
              netuid: int, epoch: int) -> Dict[str, Any]:
    """Read-only feasibility scan of one slot's indexed files.

    Reads the FTS index only. It never touches the working tree, and it
    never builds, installs, tests, or executes subnet code.
    """
    rows = connection.execute(
        "SELECT id, path FROM fleet_files WHERE netuid = ? AND epoch = ?",
        (netuid, epoch)).fetchall()
    if not rows:
        return {"verdict": VERDICT_UNKNOWN, "evidence": [],
                "reason": "no indexed files for this slot"}

    limit = int(cfg.get("max_evidence_per_kind", 4))
    min_names = [n.lower() for n in cfg.get("min_compute_names") or []]
    entry_tokens = [t.lower() for t in cfg.get("entrypoint_tokens") or []]

    evidence: List[Dict[str, Any]] = []
    min_compute_path: Optional[str] = None
    entrypoint_path: Optional[str] = None
    vram_gb: Optional[float] = None
    vram_basis: Optional[str] = None
    gpu_hits: List[Dict[str, Any]] = []
    api_hits: List[Dict[str, Any]] = []
    considered = 0

    for row_id, path in rows:
        lowered = path.lower()
        base = lowered.rsplit("/", 1)[-1]
        is_min_compute = base in min_names
        is_entry = any(lowered.endswith(t) or ("/" + t) in lowered
                       for t in entry_tokens)
        if not is_min_compute and _excluded(path, cfg):
            continue
        considered += 1
        if is_min_compute and min_compute_path is None:
            min_compute_path = path
        if is_entry and entrypoint_path is None:
            entrypoint_path = path
        if not (is_min_compute or is_entry):
            continue
        content_row = connection.execute(
            "SELECT content FROM fleet_files_fts WHERE rowid = ?",
            (row_id,)).fetchone()
        content = content_row[0] if content_row else ""
        if is_min_compute:
            parsed, basis = parse_vram_gb(content)
            if parsed is not None:
                vram_gb = max(vram_gb or 0.0, parsed)
                vram_basis = basis
                match = (_MIN_VRAM_RE.search(content)
                         or _INLINE_VRAM_RE.search(content)
                         or _REC_VRAM_RE.search(content))
                evidence.append({"kind": "vram", "path": path,
                                 "line": _line_of(content, match.start())
                                 if match else 1,
                                 "value": parsed, "basis": basis})
        if len(gpu_hits) < limit:
            gpu_hits.extend(_find_tokens(content, cfg.get("gpu_tokens") or [],
                                         path, limit - len(gpu_hits)))
        if len(api_hits) < limit:
            api_hits.extend(_find_tokens(content,
                                         cfg.get("closed_api_tokens") or [],
                                         path, limit - len(api_hits)))

    for hit in gpu_hits:
        evidence.append(dict(hit, kind="gpu"))
    for hit in api_hits:
        evidence.append(dict(hit, kind="hosted-api"))
    if min_compute_path:
        evidence.append({"kind": "min-compute", "path": min_compute_path,
                         "line": 1})
    if entrypoint_path:
        evidence.append({"kind": "entrypoint", "path": entrypoint_path,
                         "line": 1})

    if entrypoint_path is None:
        # A real project that ships no runnable miner versus a placeholder.
        verdict = (VERDICT_CLOSED if considered >= 20 else VERDICT_STUB)
        reason = ("no miner entrypoint among %d indexed files" % considered)
    elif gpu_hits or (vram_gb or 0) > 0:
        verdict, reason = VERDICT_NEEDS_GPU, "GPU required"
    else:
        verdict, reason = VERDICT_POSSIBLE, "runnable miner, no GPU tell"

    return {"verdict": verdict, "reason": reason,
            "min_compute_path": min_compute_path,
            "entrypoint_path": entrypoint_path, "vram_gb": vram_gb,
            "vram_basis": vram_basis,
            "closed_api": 1 if api_hits else 0, "evidence": evidence}


def run_feasibility(connection: sqlite3.Connection, config: Dict[str, Any],
                    netuid: Optional[int] = None,
                    now: Optional[str] = None) -> Dict[str, Any]:
    """Stage B, sha-gated: rescan a slot only when its commit has moved.
    One bad slot is recorded and skipped, never a pass failure."""
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    fleet = _fleet()
    slots = ([fleet.get_slot(connection, netuid)] if netuid is not None
             else fleet.all_slots(connection))
    scanned = unchanged = skipped = failed = 0

    # A scanner-logic change invalidates every stored verdict, because
    # sha-gating alone would keep serving results the old scanner produced.
    invalidated = 0
    if state_get(connection, "scan_version") != SCAN_VERSION:
        invalidated = connection.execute(
            "DELETE FROM mine_feasibility").rowcount or 0
        state_set(connection, "scan_version", SCAN_VERSION)
        connection.commit()

    for slot in slots:
        if not slot or slot.get("status") != "active":
            skipped += 1
            continue
        sha = slot.get("local_sha")
        if not sha:
            skipped += 1
            continue
        epoch = int(slot.get("epoch") or 0)
        existing = connection.execute(
            "SELECT 1 FROM mine_feasibility WHERE netuid = ? AND epoch = ? "
            "AND sha = ?", (slot["netuid"], epoch, sha)).fetchone()
        if existing:
            unchanged += 1
            continue
        try:
            result = scan_slot(connection, cfg, int(slot["netuid"]), epoch)
        except Exception as exc:  # noqa: BLE001 — one slot never fails a pass
            failed += 1
            connection.execute(
                "INSERT OR REPLACE INTO mine_feasibility (netuid, epoch, "
                "sha, verdict, evidence_json, scanned_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (slot["netuid"], epoch, sha, VERDICT_UNKNOWN,
                 json.dumps({"error": str(exc)[:200]}), now))
            continue
        connection.execute(
            "INSERT OR REPLACE INTO mine_feasibility (netuid, epoch, sha, "
            "verdict, min_compute_path, gpu_floor, vram_gb, entrypoint_path, "
            "closed_api, evidence_json, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slot["netuid"], epoch, sha, result["verdict"],
             result.get("min_compute_path"),
             ("%.0f GB VRAM (%s)" % (result["vram_gb"],
                                     result.get("vram_basis") or "declared"))
             if result.get("vram_gb") is not None else None,
             result.get("vram_gb"), result.get("entrypoint_path"),
             result.get("closed_api"),
             json.dumps({"reason": result.get("reason"),
                         "evidence": result.get("evidence", [])}), now))
        scanned += 1

    state_set(connection, "last_feasibility_ts", now)
    connection.commit()
    return {"ok": True, "scanned": scanned, "unchanged": unchanged,
            "skipped": skipped, "failed": failed,
            "invalidated_by_scanner_change": invalidated,
            "scan_version": SCAN_VERSION, "ts": now}


# ---------------------------------------------------------------------------
# Stage C — join, cut ladder, ranked report
# ---------------------------------------------------------------------------

def latest_feasibility(connection: sqlite3.Connection
                       ) -> Dict[int, Dict[str, Any]]:
    try:
        rows = connection.execute(
            "SELECT netuid, epoch, sha, verdict, min_compute_path, "
            "gpu_floor, vram_gb, entrypoint_path, closed_api, "
            "evidence_json, scanned_at "
            "FROM mine_feasibility ORDER BY netuid, scanned_at").fetchall()
    except sqlite3.Error:
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        out[int(row[0])] = {
            "netuid": int(row[0]), "epoch": row[1], "sha": row[2],
            "verdict": row[3], "min_compute_path": row[4],
            "gpu_floor": row[5], "vram_gb": row[6],
            "entrypoint_path": row[7], "closed_api": bool(row[8]),
            "evidence": json.loads(row[9] or "{}"), "scanned_at": row[10]}
    return out


def latest_econ(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    latest = connection.execute(
        "SELECT MAX(ts) FROM mine_econ").fetchone()[0]
    if not latest:
        return []
    cursor = connection.execute(
        "SELECT * FROM mine_econ WHERE ts = ? ORDER BY netuid", (latest,))
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def report(connection: sqlite3.Connection, config: Dict[str, Any],
           limit: Optional[int] = None,
           include_cut: bool = False) -> Dict[str, Any]:
    """Stage C: ranked survivors plus the full cut ladder.

    Strictly read-only, including no schema creation: the MCP server calls
    this over a `mode=ro` connection where any write attempt would fail.
    """
    cfg = mining_cfg(config)
    rows = latest_econ(connection)
    feasibility = latest_feasibility(connection)
    limit = int(limit or cfg.get("board_limit", 10))

    ranked: List[Dict[str, Any]] = []
    cut: List[Dict[str, Any]] = []
    for row in rows:
        feature = feasibility.get(int(row["netuid"]))
        rung, detail = classify_cut(cfg, row, feature)
        entry = dict(row)
        entry["feasibility"] = feature or {"verdict": VERDICT_UNKNOWN,
                                           "scanned_at": None,
                                           "unscanned": True}
        if rung:
            entry["cut_reason"], entry["cut_detail"] = rung, detail
            cut.append(entry)
        else:
            ranked.append(entry)

    def sort_key(entry: Dict[str, Any]) -> Tuple[int, float]:
        value = entry.get("net_tao_month")
        if value is None:
            value = entry.get("gross_tao_month")
        return (0, -float(value)) if value is not None else (1, 0.0)

    ranked.sort(key=sort_key)
    result: Dict[str, Any] = {
        "generated_at": _utc_now(),
        "econ_ts": rows[0]["ts"] if rows else None,
        "feasibility_ts": state_get(connection, "last_feasibility_ts"),
        "miner_share_source": state_get(connection, "miner_share_source"),
        "budget_band": cfg.get("budget_band"),
        "counts": {"observed": len(rows), "ranked": len(ranked),
                   "cut": len(cut)},
        "cut_summary": _cut_summary(cut),
        "ranked": ranked[:limit],
    }
    if include_cut:
        result["cut"] = cut
    return result


def _cut_summary(cut: List[Dict[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for entry in cut:
        summary[entry["cut_reason"]] = summary.get(entry["cut_reason"], 0) + 1
    return summary


def mining_status(connection: sqlite3.Connection) -> Dict[str, Any]:
    econ = connection.execute(
        "SELECT COUNT(*), MAX(ts) FROM mine_econ").fetchone()
    confidence = dict(connection.execute(
        "SELECT confidence, COUNT(*) FROM mine_econ WHERE ts = "
        "(SELECT MAX(ts) FROM mine_econ) GROUP BY confidence").fetchall())
    verdicts = dict(connection.execute(
        "SELECT verdict, COUNT(*) FROM mine_feasibility "
        "GROUP BY verdict").fetchall())
    return {"version": MINING_VERSION,
            "econ_rows": econ[0], "last_econ_ts": econ[1],
            "confidence": confidence,
            "feasibility_verdicts": verdicts,
            "last_feasibility_ts": state_get(connection,
                                             "last_feasibility_ts"),
            "miner_share_source": state_get(connection,
                                            "miner_share_source")}


# ---------------------------------------------------------------------------
# Board render — LAN-only static page, no external asset, no secret
# ---------------------------------------------------------------------------

_CSS = (
    "body{background:#0f1115;color:#e6e6e6;font:14px/1.5 ui-monospace,"
    "SFMono-Regular,Menlo,monospace;margin:0;padding:24px}"
    "h1{font-size:18px;margin:0 0 4px}"
    ".sub{color:#8a8f98;font-size:12px;margin-bottom:18px}"
    "table{border-collapse:collapse;width:100%;margin-bottom:24px}"
    "th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #232733;"
    "white-space:nowrap}"
    "th{color:#8a8f98;font-weight:normal;font-size:12px}"
    ".num{text-align:right}.warn{color:#e0a458}.bad{color:#d05c5c}"
    ".ok{color:#6fbf73}.note{color:#8a8f98;font-size:12px}"
    "code{color:#8ab4f8}"
)


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _fmt(value: Any, digits: int = 2, dash: str = "unknown") -> str:
    if value is None:
        return '<span class="note">%s</span>' % dash
    try:
        return ("%%.%df" % digits) % float(value)
    except (TypeError, ValueError):
        return _esc(value)


def render_html(view: Dict[str, Any]) -> str:
    rows = []
    for entry in view.get("ranked", []):
        feature = entry.get("feasibility") or {}
        floor = feature.get("gpu_floor")
        floor_cell = _esc(floor) if floor else (
            '<span class="note">unscanned</span>'
            if feature.get("unscanned")
            else '<span class="note">%s</span>' % _esc(feature.get("verdict")))
        path = (feature.get("min_compute_path")
                or feature.get("entrypoint_path"))
        headline = entry.get("net_tao_month")
        if headline is None:
            headline = entry.get("gross_tao_month")
        name = entry.get("subnet_name")
        name_cell = (_esc(name) if name else
                     '<span class="note">%s</span>'
                     % _esc(entry.get("identity_state") or "unread"))
        rows.append(
            "<tr><td>%s</td><td>%s</td><td class=\"num\">%s</td>"
            "<td class=\"num warn\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td>"
            "<td>%s</td><td><code>%s</code></td><td>%s</td></tr>"
            % (entry.get("netuid"),
               name_cell,
               _fmt(headline, 4),
               _fmt(entry.get("incumbent_alpha_day"), 1),
               _fmt(entry.get("displacement_rank"), 0),
               _fmt(entry.get("price_tao"), 6),
               _fmt(entry.get("miner_burn_pct"), 2),
               _fmt(entry.get("earner_count"), 0),
               _fmt(entry.get("top10_share_pct"), 1),
               floor_cell, _esc(path or ""),
               _esc(entry.get("confidence"))))

    cuts = "".join(
        "<tr><td>%s</td><td class=\"num\">%d</td></tr>" % (_esc(k), v)
        for k, v in sorted(view.get("cut_summary", {}).items()))

    band = view.get("budget_band")
    band_note = ("budget band: %s" % _esc(band) if band else
                 "no budget band chosen yet, so rent is unknown and the "
                 "hardware rung does not cut")

    return (
        "<html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,"
        "initial-scale=1\">"
        "<title>Atlas mining triage</title><style>%s</style></head><body>"
        "<h1>Mining triage</h1>"
        "<div class=\"sub\">economics observed %s &middot; feasibility "
        "scanned %s &middot; %s<br>%s<br>"
        "alpha distributed per block is a protocol constant, so ranking is "
        "driven by price, owner capture, and concentration, never by "
        "emission quantity<br>"
        "<span class=\"warn\">ASSUMPTION:</span> the TAO/mo column is what a "
        "NEW ENTRANT earns at parity, the miner pool shared among "
        "earners + 1. It is a model, not an observation. The incumbent "
        "column is what a current earner actually receives; where that is "
        "far larger, the field is concentrated and entry means displacing "
        "someone, not joining them.</div>"
        "<table><tr><th>netuid</th><th>on-chain name</th>"
        "<th>entrant TAO/mo</th>"
        "<th>incumbent &alpha;/day</th><th>enter at rank</th>"
        "<th>alpha price</th>"
        "<th>burn %%</th><th>earners</th><th>top10 %%</th>"
        "<th>hardware floor</th><th>evidence</th><th>confidence</th></tr>"
        "%s</table>"
        "<h1>Cut ladder</h1><div class=\"sub\">%d observed, %d ranked, "
        "%d cut</div><table><tr><th>reason</th><th>subnets</th></tr>%s"
        "</table>"
        "<div class=\"note\">%s</div></body></html>"
        % (_CSS,
           _esc(view.get("econ_ts")), _esc(view.get("feasibility_ts")),
           band_note, _esc(view.get("miner_share_source") or ""),
           "".join(rows) or "<tr><td colspan=\"12\" class=\"note\">"
                            "no observations yet</td></tr>",
           view.get("counts", {}).get("observed", 0),
           view.get("counts", {}).get("ranked", 0),
           view.get("counts", {}).get("cut", 0),
           cuts or "<tr><td colspan=\"2\" class=\"note\">none</td></tr>",
           "ranks evidence, recommends nothing; holds no keys and takes no "
           "action"))


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def render(connection: sqlite3.Connection, config: Dict[str, Any],
           now: Optional[str] = None) -> Dict[str, Any]:
    """Write one self-contained mining.html atomically into the www dir the
    LAN dashboard service already serves. Never raises on an empty store."""
    cfg = mining_cfg(config)
    view = report(connection, config)
    page = render_html(view)
    www = (config.get("dashboard") or {}).get("www_dir", "var/fleet/www")
    if not os.path.isabs(www):
        www = os.path.join(_REPO_ROOT, www)
    out = os.path.join(www, "mining.html")
    _atomic_write(out, page)
    return {"path": out, "bytes": len(page),
            "ranked": len(view.get("ranked", [])),
            "cut": view.get("counts", {}).get("cut", 0)}


# ---------------------------------------------------------------------------
# Pass hook + CLI
# ---------------------------------------------------------------------------

def run_pass(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The mining step, invoked inline after metrics in the fleet pass.
    Every stage is fail-isolated: nothing here fails the enclosing pass."""
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    summary: Dict[str, Any] = {}
    for name, call in (
            ("econ", lambda: run_econ(connection, config, now=now,
                                      inputs=inputs)),
            ("feasibility", lambda: run_feasibility(connection, config,
                                                    now=now)),
            ("render", lambda: render(connection, config, now=now))):
        try:
            summary[name] = call()
        except Exception as exc:  # noqa: BLE001 — never fails the pass
            summary[name] = {"error": str(exc)[:200]}
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet_mining",
        description="Atlas mining triage: rank subnets by what a new "
                    "independent miner could earn, read-only.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("econ", help="Stage A economics screen (one panel call)")
    fe = sub.add_parser("feasibility", help="Stage B sha-gated code scan")
    fe.add_argument("--netuid", type=int, default=None)
    rp = sub.add_parser("report", help="Stage C ranked JSON (read-only)")
    rp.add_argument("--limit", type=int, default=None)
    rp.add_argument("--include-cut", action="store_true")
    sub.add_parser("render", help="write var/fleet/www/mining.html")
    sub.add_parser("pass", help="econ + feasibility + render")
    args = parser.parse_args(argv)

    fleet = _fleet()
    try:
        config = fleet.load_config(args.config or fleet.CONFIG_FILE)
        connection = fleet.open_store(config["db"])
        try:
            ensure_schema(connection)
            if args.command == "status":
                result: Dict[str, Any] = mining_status(connection)
            elif args.command == "econ":
                result = run_econ(connection, config)
            elif args.command == "feasibility":
                result = run_feasibility(connection, config,
                                         netuid=args.netuid)
            elif args.command == "report":
                result = report(connection, config, limit=args.limit,
                                include_cut=args.include_cut)
            elif args.command == "render":
                result = render(connection, config)
            elif args.command == "pass":
                result = run_pass(connection, config)
            else:
                return 2
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        finally:
            connection.close()
        return 0
    except fleet.FleetError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

