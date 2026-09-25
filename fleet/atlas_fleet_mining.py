#!/usr/bin/env python3
"""Atlas mining triage — a read-only screen ranking subnets by what a new
independent miner could earn (changes: mining-triage, mining-board-accuracy).

Joins two halves Atlas already holds: chain economics from live-data, and
code feasibility from the fleet clones and their FTS index. Output is a
ranked shortlist where every excluded subnet keeps the reason it was cut, a
LAN-only board page, and a read-only query surface on the atlas-fleet MCP
server.

The model, grounded at subtensor `c004ceb` (spec 471) and Finney blocks
9142678 and 9142723 (`ps/` is `pallets/subtensor/src/`):

- Every input is chain state read at ONE finalized block through live-data.
  No provider panel feeds the screen.
- The alpha distributed to participants per block is `SubnetAlphaOutEmission`.
  It follows the halving curve on each subnet's own alpha issuance
  (`run_coinbase.rs:226-238`), so it is read, never assumed constant.
- The miner share is 0.5 x (1 - owner cut). The owner cut is the global
  `SubnetOwnerCut` over 65535, applied only where `OwnerCutEnabled`; the 0.5
  is the incentive half (`run_coinbase.rs:326-329`) and carries its citation.
- A subnet with several mechanisms divides its miner pool by
  `MechanismEmissionSplit` (even when unset or malformed), and each
  mechanism has its own `Incentive` vector at index mecid * 4096 + netuid.
- Owner capture is removed by excluding owner-controlled UIDs from each
  mechanism's field, resolved as the runtime does (`get_owner_hotkeys`). The
  removed share, weighted by split, must reconcile with chain `MinerBurned`.
- Reward is winner-take-most, so competition is the INDEPENDENT earner count
  and concentration, never a pool divided by registered UIDs.
- Price and exit haircut come from the weighted Balancer pool.

The ladder runs once per pass after feasibility and its result is stored.
Every surface reads the stored result; none re-derives it.

Invariants inherited from the fleet: read-only over clones, never builds or
executes subnet code, additive tables in the shared fleet store, per-subnet
fail-closed, and no network access of its own.

Public surface:

- ensure_schema(conn): create the mine_* tables
- run_econ(conn, config, …): Stage A chain economics
- run_feasibility(conn, config, …): Stage B sha-gated code scan
- run_classify(conn, config, ts): Stage C ladder + rank, stored once
- report(conn, config, …): read the stored result
- run_pass(conn, config, …): econ, feasibility, classify, render
- mining_status(conn): coverage + confidence summary
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

MINING_VERSION = "0.2.0"
# Version of the economics model the stored rows describe. Consumers compare
# it across editions and suppress top-ten deltas when it changes.
MODEL_VERSION = 2

# Bump when the feasibility scanner's LOGIC changes, not when the code moves.
# Feasibility is sha-gated on the scanned commit, so a scanner fix would
# otherwise never re-run against clones that have not moved.
SCAN_VERSION = "3"

BLOCKS_PER_DAY = 7200  # 12s blocks
DAYS_PER_MONTH = 30.0
RAO = 1e9
U16_MAX = 65535

# The incentive half of post-owner-cut alpha. `MINER_SPLIT_SOURCE` must be
# non-empty or no miner-accessible figure is computed at all.
MINER_SPLIT = 0.5
MINER_SPLIT_SOURCE = (
    "RaoFoundation/subtensor c004ceb (spec 471) "
    "pallets/subtensor/src/coinbase/run_coinbase.rs:326-329: "
    "pending_server_alpha = alpha_out_i * 0.5, after the owner cut "
    "(run_coinbase.rs:303-311, SubnetOwnerCut and OwnerCutEnabled at "
    "lib.rs:2254-2265)")

PARITY_MODEL = (
    "MODEL, not an observation: the entrant figure assumes a new miner joins "
    "one mechanism and matches its independent earners, so that mechanism's "
    "independent pool (its miner pool minus the owner share) is shared among "
    "the independent earners + 1. The incumbent figure is what a current "
    "independent earner receives; where it is far larger, entry means "
    "displacing someone, not joining them.")

# Confidence markers. `ok` is the only value that permits a figure.
CONF_OK = "ok"
CONF_INCOMPLETE = "incomplete-inputs"
CONF_OWNERS_UNREAD = "owner-set-unread"
CONF_RECONCILE = "owner-reconcile-failed"

# Unrated reasons that are not confidence markers.
UNRATED_NOT_EMITTING = "not-emitting"
UNRATED_NO_FIGURE = "no-mechanism-figure"

# Cut ladder rungs, in application order.
CUT_GATE = "pool-side-switch-off"
CUT_IDENTITY = "identity-placeholder"
CUT_BURN = "owner-capture"
CUT_NO_EARNER = "no-independent-earner"
CUT_CONCENTRATION = "winner-take-all"
CUT_FEASIBILITY = "not-minable"
CUT_HARDWARE = "above-budget-band"

# Per-mechanism rungs: why a mechanism cannot carry the subnet's rank.
MECH_ZERO_SPLIT = "zero-split"
MECH_EMPTY = "no-independent-earner"
MECH_CONCENTRATED = "winner-take-all"

# On-chain identity states. `unread` is the fail-open value: the map, or
# this netuid's entry, could not be read, which must NOT be read as the
# subnet being unnamed. `absent` means the map read fine and this netuid has
# no entry, which is a real finding about that subnet.
IDENT_NAMED = "named"
IDENT_PLACEHOLDER = "placeholder"
IDENT_ABSENT = "absent"
IDENT_UNREAD = "unread"

# Feasibility verdicts. A closed set, not free strings: `unknown` is a real
# value and is never rendered as feasible. `closed` and `stub` stay in the
# set but need positive cited evidence, and no scanner rule produces them
# yet: no evidence must never become a cut.
VERDICT_POSSIBLE = "possible"
VERDICT_NEEDS_GPU = "needs-gpu"
VERDICT_CLOSED = "closed"
VERDICT_STUB = "stub"
VERDICT_UNKNOWN = "unknown"
VERDICTS = (VERDICT_POSSIBLE, VERDICT_NEEDS_GPU, VERDICT_CLOSED,
            VERDICT_STUB, VERDICT_UNKNOWN)
INFEASIBLE_VERDICTS = (VERDICT_CLOSED, VERDICT_STUB)

# Headline columns copied from the mechanism a subnet is shown on.
_HEADLINE = (
    ("earner_count", "indep_earner_count"),
    ("top1_share_pct", "indep_top1_share_pct"),
    ("top10_share_pct", "indep_top10_share_pct"),
    ("incumbent_alpha_day", "incumbent_alpha_day"),
    ("entrant_alpha_day", "entrant_alpha_day"),
    ("displacement_rank", "displacement_rank"),
    ("haircut_pct", "haircut_pct"),
    ("gross_tao_month", "gross_tao_month"),
    ("net_tao_month", "net_tao_month"),
)

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
    rank INTEGER,
    rank_mecid INTEGER,
    unrated_reason TEXT,
    mechanism_count INTEGER,
    owner_share_pct REAL,
    owner_reconcile_delta REAL,
    balancer_quote REAL,
    immunity_period INTEGER,
    uids_full INTEGER,
    alpha_issuance REAL,
    miner_share REAL,
    PRIMARY KEY (ts, netuid)
);
CREATE INDEX IF NOT EXISTS mine_econ_netuid_ts
    ON mine_econ (netuid, ts DESC);
CREATE TABLE IF NOT EXISTS mine_mechanism (
    ts TEXT NOT NULL,
    netuid INTEGER NOT NULL,
    mecid INTEGER NOT NULL,
    split REAL,
    incentive_read INTEGER NOT NULL,
    earner_count INTEGER,
    owner_share_pct REAL,
    indep_earner_count INTEGER,
    indep_top1_share_pct REAL,
    indep_top10_share_pct REAL,
    miner_alpha_day REAL,
    indep_alpha_day REAL,
    entrant_alpha_day REAL,
    incumbent_alpha_day REAL,
    displacement_rank INTEGER,
    haircut_pct REAL,
    gross_tao_month REAL,
    net_tao_month REAL,
    no_figure_reason TEXT,
    rung TEXT,
    PRIMARY KEY (ts, netuid, mecid)
);
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
    # fleet/config.json is the whole rollback.
    "enabled": False,
    # Owner capture at or above this percent of miner incentive (chain
    # MinerBurned) cuts the subnet. Operator decision, 2026-08-07.
    "burn_ceiling_pct": 99.0,
    # At or above this top-1 share of the INDEPENDENT incentive a mechanism
    # is winner-take-all. Measured on share, not earner count. Operator
    # decision, 2026-08-12.
    "top1_ceiling_pct": 95.0,
    # Largest accepted gap, as a 0-1 fraction, between the owner share
    # removed from the field (weighted by split) and chain MinerBurned.
    "owner_reconcile_tolerance": 0.01,
    # Assumed daily sale of earned alpha, as a fraction of the day's earnings,
    # for the exit haircut.
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
    # concern, matched against the name's normalised FIRST TOKEN. Data to
    # match against, never anything that is executed or followed.
    "identity_placeholders": ["deprecated", "unknown", "pending", "parked",
                              "wait", "tbd", "none", "test", "placeholder"],
    "retention_days": 90,
    "board_limit": 10,
    # Bound on the excluded list a board view returns.
    "cut_limit": 30,
    # The board warns when its economics are older than this. The fleet pass
    # runs every 6h; 18h is three missed passes, the fleet staleness rule.
    "stale_after_hours": 18,
    # Feasibility scan surface.
    "min_compute_names": ["min_compute.yml", "min_compute.yaml"],
    "gpu_tokens": ["torch.cuda", "device=\"cuda\"", "device='cuda'",
                   "cuda:0", "vllm", "bitsandbytes", "nvidia-smi",
                   "nvidia/cuda", "flash_attn"],
    "closed_api_tokens": ["openai", "anthropic", "api_key", "apikey",
                          "bearer "],
    "exclude_path_parts": ["vendor", "node_modules", "test", "tests",
                           "docs", "doc", "examples", "example", ".github"],
    "max_evidence_per_kind": 4,
}

# Keys the screen used before the chain-sourced miner share. A leftover is
# ignored with a note, never used.
RETIRED_CFG_KEYS = ("miner_share", "miner_share_source", "entrypoint_tokens")


def mining_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_MINING_CFG)
    for key, value in (config.get("mining") or {}).items():
        if key == "_comment" or key in RETIRED_CFG_KEYS:
            continue
        merged[key] = value
    return merged


def retired_cfg_notes(config: Dict[str, Any]) -> List[str]:
    present = [key for key in RETIRED_CFG_KEYS
               if key in (config.get("mining") or {})]
    if not present:
        return []
    return ["mining.%s is ignored: the miner share comes from chain "
            "SubnetOwnerCut and OwnerCutEnabled, and entrypoints from the "
            "scanner's pattern set" % ", mining.".join(present)]


def _utc_now() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


# Columns added to mine_econ after the table first shipped. CREATE TABLE IF
# NOT EXISTS is a no-op against a store that already has the old shape, so
# a deployed Pi would keep the old columns and every insert would fail.
_MINE_ECON_ADDED: Tuple[Tuple[str, str], ...] = (
    ("subnet_name", "TEXT"),
    ("identity_state", "TEXT"),
    # change: mining-board-accuracy
    ("rank", "INTEGER"),
    ("rank_mecid", "INTEGER"),
    ("unrated_reason", "TEXT"),
    ("mechanism_count", "INTEGER"),
    ("owner_share_pct", "REAL"),
    ("owner_reconcile_delta", "REAL"),
    ("balancer_quote", "REAL"),
    ("immunity_period", "INTEGER"),
    ("uids_full", "INTEGER"),
    ("alpha_issuance", "REAL"),
    ("miner_share", "REAL"),
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
    """Lazy import of live-data. It owns every chain call; this module never
    opens a socket of its own."""
    global _LIVE
    if _LIVE is None:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "livedata"))
        import atlas_live  # noqa: E402
        _LIVE = atlas_live
    return _LIVE


# ---------------------------------------------------------------------------
# Pure economics — unit-testable, no IO
# ---------------------------------------------------------------------------

def miner_share(owner_cut_raw: int, cut_enabled: bool) -> float:
    """Fraction of distributed alpha that reaches the miner leg:
    0.5 x (1 - owner cut), the cut applying only where enabled."""
    cut = float(owner_cut_raw) / U16_MAX if cut_enabled else 0.0
    return MINER_SPLIT * (1.0 - cut)


def mechanism_split(count: int, raw: Optional[List[int]]) -> List[float]:
    """Per-mechanism fraction of the miner pool, as the runtime divides it
    (`split_emissions`, `ps/subnets/mechanism.rs:233-252`): the stored split
    over 65535 when its length matches the mechanism count, else even."""
    if count <= 0:
        return []
    if raw is not None and len(raw) == count:
        return [int(value) / U16_MAX for value in raw]
    return [1.0 / count] * count


def concentration(incentive: List[int]) -> Dict[str, Any]:
    """Earner count and top-1 / top-10 shares of an incentive vector (or of
    the independent part of one). The count of REGISTERED uids is not the
    competition; the count of earners and how concentrated they are is."""
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


def pool_price(root_in_pool: Optional[float], alpha_in_pool: Optional[float],
               quote: Optional[float]) -> Optional[float]:
    """Spot price of alpha in TAO in a weighted Balancer pool:
    (1 - q) / q x TAO / alpha, with q the quote (TAO) weight. None when a
    reserve or the weight is missing: a price is never assumed."""
    if not root_in_pool or not alpha_in_pool or root_in_pool <= 0 \
            or alpha_in_pool <= 0 or quote is None or not 0.0 < quote < 1.0:
        return None
    return (1.0 - quote) / quote * root_in_pool / alpha_in_pool


def exit_haircut_pct(sale_alpha: float, alpha_in_pool: Optional[float],
                     root_in_pool: Optional[float],
                     quote: Optional[float] = 0.5) -> Optional[float]:
    """Slippage for selling `sale_alpha` into the weighted pool, as a
    percentage of the no-slippage proceeds:
    dTAO = T x (1 - (A / (A + da))^((1 - q) / q)), compared with da x price.
    At q = 0.5 this is x*y=k. None when depth or weight is unknown, because
    a haircut of zero would be a claim, not an absence."""
    spot = pool_price(root_in_pool, alpha_in_pool, quote)
    if spot is None or sale_alpha <= 0:
        return None
    exponent = (1.0 - quote) / quote
    proceeds = root_in_pool * (1.0 - (alpha_in_pool
                                      / (alpha_in_pool + sale_alpha))
                               ** exponent)
    ideal = sale_alpha * spot
    if ideal <= 0:
        return None
    return max(0.0, 100.0 * (1.0 - proceeds / ideal))


def entrant_alpha_per_day(indep_alpha_day: Optional[float],
                          indep_earners: Optional[int]) -> Optional[float]:
    """What a NEW entrant earns under the stated parity assumption: you join
    one mechanism and match its independent earners, so its independent
    pool is shared among `indep_earners + 1`.

    Undefined with no independent earner: dividing a pool by one would rank
    an owner-only or empty field first. It is a model, labelled as one
    wherever it is shown.
    """
    if indep_alpha_day is None or not indep_earners:
        return None
    return float(indep_alpha_day) / (int(indep_earners) + 1)


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


def mechanism_economics(cfg: Dict[str, Any], mecid: int, split: float,
                        vector: Optional[List[int]],
                        owner_uids: Optional[List[int]],
                        miner_alpha_day: Optional[float],
                        price: Optional[float],
                        alpha_in_pool: Optional[float],
                        root_in_pool: Optional[float],
                        quote: Optional[float],
                        rent: Optional[float]) -> Dict[str, Any]:
    """One mechanism's field and entrant figure with the owner removed.

    `vector` None means the mechanism's incentive was not read.
    `owner_uids` None means the owner set was not read; an all-zero vector
    still has no independent earner whoever the owner is.
    """
    mech: Dict[str, Any] = {
        "mecid": mecid, "split": split, "incentive_read": 1,
        "earner_count": None, "owner_share_pct": None,
        "indep_earner_count": None, "indep_top1_share_pct": None,
        "indep_top10_share_pct": None,
        "miner_alpha_day": (None if miner_alpha_day is None
                            else miner_alpha_day * split),
        "indep_alpha_day": None, "entrant_alpha_day": None,
        "incumbent_alpha_day": None, "displacement_rank": None,
        "haircut_pct": None, "gross_tao_month": None,
        "net_tao_month": None, "no_figure_reason": None, "rung": None,
    }
    if vector is None:
        mech["incentive_read"] = 0
        mech["no_figure_reason"] = "incentive-unread"
        return mech

    values = [int(v) for v in vector]
    total = sum(values)
    mech["earner_count"] = sum(1 for v in values if v > 0)
    if total <= 0:
        owner_share, indep = 0.0, []
    elif owner_uids is None:
        mech["no_figure_reason"] = CONF_OWNERS_UNREAD
        return mech
    else:
        owned = set(owner_uids)
        owner_share = sum(v for uid, v in enumerate(values)
                          if uid in owned) / total
        indep = [v for uid, v in enumerate(values)
                 if v > 0 and uid not in owned]
    mech["owner_share_pct"] = 100.0 * owner_share
    stats = concentration(indep)
    mech["indep_earner_count"] = stats["earner_count"]
    mech["indep_top1_share_pct"] = stats["top1_share_pct"]
    mech["indep_top10_share_pct"] = stats["top10_share_pct"]
    if mech["miner_alpha_day"] is not None:
        mech["indep_alpha_day"] = mech["miner_alpha_day"] * (1.0
                                                             - owner_share)
    if not indep:
        mech["no_figure_reason"] = MECH_EMPTY
        return mech
    if mech["indep_alpha_day"] is None:
        mech["no_figure_reason"] = "emission-unread"
        return mech
    indep_total = sum(indep)
    mech["incumbent_alpha_day"] = median_of(
        [mech["indep_alpha_day"] * v / indep_total for v in indep])
    mech["displacement_rank"] = len(indep) + 1
    mech["entrant_alpha_day"] = entrant_alpha_per_day(
        mech["indep_alpha_day"], len(indep))
    if split <= 0:
        mech["no_figure_reason"] = MECH_ZERO_SPLIT
        return mech
    if price is None:
        mech["no_figure_reason"] = "price-unknown"
        return mech
    mech["haircut_pct"] = exit_haircut_pct(
        mech["entrant_alpha_day"] * float(cfg.get("daily_sale_fraction",
                                                  1.0)),
        alpha_in_pool, root_in_pool, quote)
    if mech["haircut_pct"] is None:
        mech["no_figure_reason"] = "haircut-unknown"
        return mech
    gross = (mech["entrant_alpha_day"] * price
             * (1.0 - mech["haircut_pct"] / 100.0) * DAYS_PER_MONTH)
    mech["gross_tao_month"] = gross
    if rent is not None:
        mech["net_tao_month"] = gross - rent
    return mech


def _headline_mechanism(mechs: List[Dict[str, Any]]
                        ) -> Optional[Dict[str, Any]]:
    """The mechanism a subnet is shown on when it has no rank: the largest
    split, ties to the lowest mecid."""
    if not mechs:
        return None
    return sorted(mechs, key=lambda m: (-(m.get("split") or 0.0),
                                        m["mecid"]))[0]


def _copy_headline(row: Dict[str, Any],
                   mech: Optional[Dict[str, Any]]) -> None:
    for column, source in _HEADLINE:
        row[column] = mech.get(source) if mech else None


def subnet_economics(cfg: Dict[str, Any], netuid: int,
                     snapshot: Dict[str, Any], now: str
                     ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """One subnet's economics row and its mechanism rows from a chain
    snapshot. Pure: a malformed value marks this subnet alone."""
    values = snapshot.get("values") or {}
    failures = snapshot.get("failures") or {}
    failed_items = snapshot.get("failed_items") or {}

    def get(item: str, default: Any = None) -> Any:
        return (values.get(item) or {}).get(netuid, default)

    def unread(item: str) -> bool:
        return item in failed_items or netuid in (failures.get(item) or {})

    missing: List[str] = []
    for item in ("SubnetAlphaOutEmission", "MinerBurned", "OwnerCutEnabled",
                 "MechanismCountCurrent", "MechanismEmissionSplit",
                 "SubnetTAO", "SubnetAlphaIn", "SwapBalancer"):
        if unread(item):
            missing.append(item)

    band, rent = _rent_for_band(cfg)
    row: Dict[str, Any] = {
        "ts": now, "netuid": netuid, "confidence": CONF_OK,
        "block_ref": snapshot.get("block_number"), "source_ts": now,
        "rent_band": band, "rent_tao_month": rent,
        "alpha_in_day": None, "baseline_tao_month": None,
        "cut_reason": None, "cut_detail": None, "rank": None,
        "rank_mecid": None, "unrated_reason": None,
    }

    # Pool-side emission switch. Absent is the runtime default (off); an
    # unreadable item or entry is unknown and never cuts.
    if unread("SubnetEmissionEnabled"):
        row["gate_state"] = None
    else:
        row["gate_state"] = ("enabled" if get("SubnetEmissionEnabled")
                             else "disabled")

    identities = values.get("SubnetIdentitiesV3") or {}
    identity_seen = bool(identities) and \
        "SubnetIdentitiesV3" not in failed_items
    if unread("SubnetIdentitiesV3"):
        row["identity_state"], row["subnet_name"] = IDENT_UNREAD, None
    else:
        row["identity_state"], row["subnet_name"] = classify_identity(
            cfg, identities.get(netuid), identity_seen)

    alpha_out_raw = None if unread("SubnetAlphaOutEmission") \
        else get("SubnetAlphaOutEmission", 0)
    row["alpha_out_day"] = (None if alpha_out_raw is None
                            else alpha_out_raw / RAO * BLOCKS_PER_DAY)
    burn = None if unread("MinerBurned") else float(get("MinerBurned", 0.0))
    row["miner_burn_pct"] = None if burn is None else 100.0 * burn

    # Absent OwnerCutEnabled is the runtime default, true.
    cut_enabled = None if unread("OwnerCutEnabled") \
        else bool(get("OwnerCutEnabled", True))
    owner_cut = snapshot.get("owner_cut")
    if owner_cut is None:
        missing.append("SubnetOwnerCut")
    share = (None if cut_enabled is None or owner_cut is None
             or not MINER_SPLIT_SOURCE
             else miner_share(int(owner_cut), cut_enabled))
    row["miner_share"] = share
    row["miner_alpha_day"] = (None if share is None
                              or row["alpha_out_day"] is None
                              else row["alpha_out_day"] * share)

    root_pool = None if unread("SubnetTAO") else get("SubnetTAO", 0) / RAO
    alpha_pool = None if unread("SubnetAlphaIn") \
        else get("SubnetAlphaIn", 0) / RAO
    # Absent weight is the runtime default of 0.5 (`Balancer::default`).
    quote = None if unread("SwapBalancer") else get("SwapBalancer", 0.5)
    row["root_in_pool"], row["alpha_in_pool"] = root_pool, alpha_pool
    row["balancer_quote"] = quote
    row["price_tao"] = pool_price(root_pool, alpha_pool, quote)

    burn_rao = get("Burn")
    row["reg_cost_tao"] = None if burn_rao is None or unread("Burn") \
        else burn_rao / RAO
    row["immunity_period"] = None if unread("ImmunityPeriod") \
        else get("ImmunityPeriod")
    row["subnetwork_n"] = None if unread("SubnetworkN") \
        else get("SubnetworkN")
    max_uids = None if unread("MaxAllowedUids") else get("MaxAllowedUids")
    row["uids_full"] = (None if row["subnetwork_n"] is None
                        or max_uids is None
                        else int(row["subnetwork_n"] >= max_uids))
    issuance_items = ("SubnetAlphaIn", "SubnetAlphaOut",
                      "SubnetProtocolAlpha")
    row["alpha_issuance"] = (None if any(unread(i) for i in issuance_items)
                             else sum(get(i, 0) for i in issuance_items)
                             / RAO)
    # A dormant map reads as its documented zero; an unreadable entry is
    # unknown, never a fabricated zero.
    lock = None if unread("CollateralLockShare") \
        else get("CollateralLockShare", 0)
    row["collateral_lock_pct"] = (None if lock is None
                                  else 100.0 * float(lock) / U16_MAX)

    count = 1 if unread("MechanismCountCurrent") \
        else int(get("MechanismCountCurrent", 1))
    row["mechanism_count"] = count
    splits = mechanism_split(count, None if unread("MechanismEmissionSplit")
                             else get("MechanismEmissionSplit"))

    owners = (snapshot.get("owners") or {}).get(netuid) or {
        "state": "unread", "reason": "no owner resolution"}
    owner_uids = owners.get("uids") if owners.get("state") == "ok" else None

    incentive = values.get("Incentive") or {}
    incentive_failed = failures.get("Incentive") or {}
    incentive_item_failed = "Incentive" in failed_items
    mechs: List[Dict[str, Any]] = []
    blocked = bool(missing)
    for mecid in range(count):
        key = (netuid, mecid)
        if incentive_item_failed or key in incentive_failed:
            vector: Optional[List[int]] = None
            missing.append("Incentive[%d]" % mecid)
        else:
            # Absent is the runtime default: an empty vector.
            vector = incentive.get(key, [])
        mechs.append(mechanism_economics(
            cfg, mecid, splits[mecid], vector, owner_uids,
            None if blocked else row["miner_alpha_day"],
            None if blocked else row["price_tao"],
            alpha_pool, root_pool, quote, rent))

    # Reconciliation: the owner share removed from the field, weighted by
    # split, against the chain's own record of withheld incentive.
    shares = [m["owner_share_pct"] for m in mechs]
    if owners.get("state") == "ok" and burn is not None \
            and all(s is not None for s in shares):
        removed = sum(m["split"] * m["owner_share_pct"] / 100.0
                      for m in mechs)
        row["owner_share_pct"] = 100.0 * removed
        row["owner_reconcile_delta"] = removed - burn
    else:
        row["owner_share_pct"] = None
        row["owner_reconcile_delta"] = None

    emitting = bool(alpha_out_raw)
    if missing:
        row["confidence"] = "%s: %s" % (CONF_INCOMPLETE, ", ".join(missing))
    elif owners.get("state") != "ok":
        row["confidence"] = "%s: %s" % (CONF_OWNERS_UNREAD,
                                        owners.get("reason") or "unread")
    elif emitting and row["owner_reconcile_delta"] is not None and abs(
            row["owner_reconcile_delta"]) > float(
            cfg.get("owner_reconcile_tolerance", 0.01)):
        # A subnet that emits nothing records no MinerBurned, so the check
        # only means something where alpha is distributed.
        row["confidence"] = CONF_RECONCILE

    if row["confidence"] != CONF_OK or not emitting:
        reason = (row["confidence"] if row["confidence"] != CONF_OK
                  else UNRATED_NOT_EMITTING)
        for mech in mechs:
            mech["haircut_pct"] = None
            mech["gross_tao_month"] = mech["net_tao_month"] = None
            if row["confidence"] != CONF_OK:
                mech["entrant_alpha_day"] = None
            if mech["no_figure_reason"] in (None, MECH_ZERO_SPLIT):
                mech["no_figure_reason"] = reason
    if rent is not None and row["confidence"] == CONF_OK and emitting:
        row["baseline_tao_month"] = (
            float(cfg.get("staking_apy_pct", 0.0)) / 100.0 / 12.0 * rent)

    _copy_headline(row, _headline_mechanism(mechs))
    return row, mechs


# ---------------------------------------------------------------------------
# Stage A: economics from one chain snapshot
# ---------------------------------------------------------------------------

def collect_snapshot(config: Dict[str, Any],
                     live: Optional[Any] = None) -> Dict[str, Any]:
    """Read the chain snapshot through live-data, which audits each read in
    its own store, then hand the already-read maps to its watches."""
    live = live or _live()
    live_config = live.load_config()
    connection = live.open_store(live.resolve(live_config["db"]))
    try:
        snapshot = live.read_mining_snapshot(live_config,
                                             connection=connection)
        if snapshot.get("ok"):
            netuids = sorted(snapshot["values"].get("SubnetworkN", {}).keys())
            failed_items = snapshot.get("failed_items") or {}
            for item in ("CollateralLockShare", "SubnetEmissionEnabled"):
                if item in failed_items:
                    continue
                try:
                    live.run_subnet_param_watch(
                        connection, live_config, item, netuids,
                        snapshot["values"].get(item, {}),
                        failures=(snapshot.get("failures") or {}).get(item),
                        block_hash=snapshot.get("block_hash"),
                        block_number=snapshot.get("block_number"))
                except Exception:  # noqa: BLE001 — watch never fails the screen
                    pass
    finally:
        connection.close()
    return snapshot


def build_econ(cfg: Dict[str, Any], snapshot: Dict[str, Any], now: str
               ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Every subnet's rows for one pass, in memory. Root is excluded."""
    netuids = sorted(int(n) for n in
                     (snapshot.get("values") or {}).get("SubnetworkN", {})
                     if int(n) != 0)
    econ: List[Dict[str, Any]] = []
    mechanisms: List[Dict[str, Any]] = []
    for netuid in netuids:
        row, mechs = subnet_economics(cfg, netuid, snapshot, now)
        econ.append(row)
        for mech in mechs:
            mechanisms.append(dict(mech, ts=now, netuid=netuid))
    return econ, mechanisms


def _insert(connection: sqlite3.Connection, table: str,
            row: Dict[str, Any]) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
        % (table, ", ".join(row), ", ".join("?" * len(row))),
        tuple(row.values()))


def run_econ(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stage A: one economics observation per subnet from one chain
    snapshot. A failed snapshot writes nothing and leaves the last complete
    pass current. A pass commits all of its rows or none of them."""
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}
    notes = retired_cfg_notes(config)
    for note in notes:
        print("atlas_fleet_mining: %s" % note, file=sys.stderr)

    if not MINER_SPLIT_SOURCE:
        return {"ok": False, "notes": notes,
                "error": "the incentive/dividend split has no recorded "
                         "citation: no miner-accessible figure is computed"}

    snapshot = snapshot or collect_snapshot(config)
    if not snapshot or not snapshot.get("ok"):
        return {"ok": False, "leg": "chain", "notes": notes,
                "error": (snapshot or {}).get("error") or "chain unavailable",
                "note": "no rows written; the board keeps the last complete "
                        "pass and shows its age"}

    econ, mechanisms = build_econ(cfg, snapshot, now)
    try:
        for row in econ:
            _insert(connection, "mine_econ", row)
        for mech in mechanisms:
            _insert(connection, "mine_mechanism", mech)
        prune = prune_econ(connection, cfg, now=now)
        state_set(connection, "miner_split_source", MINER_SPLIT_SOURCE)
        state_set(connection, "owner_cut", "%s (%s)" % (
            snapshot.get("owner_cut"), snapshot.get("owner_cut_state")))
        state_set(connection, "last_econ_ts", now)
        state_set(connection, "last_econ_block",
                  str(snapshot.get("block_number")))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"ok": True, "observations": len(econ),
            "mechanisms": len(mechanisms),
            "unrated_inputs": sum(1 for r in econ
                                  if r["confidence"] != CONF_OK),
            "block_ref": snapshot.get("block_number"), "pruned": prune,
            "ts": now, "notes": notes}


def prune_econ(connection: sqlite3.Connection, cfg: Dict[str, Any],
               now: Optional[str] = None) -> int:
    """Bound the economics time series. Feasibility is pruned when a slot's
    verdict is superseded, not by time."""
    days = int(cfg.get("retention_days", 90))
    if days <= 0:
        return 0
    cutoff = (_parse_ts(now or _utc_now())
              - datetime.timedelta(days=days)).isoformat()
    cursor = connection.execute("DELETE FROM mine_econ WHERE ts < ?",
                                (cutoff,))
    connection.execute("DELETE FROM mine_mechanism WHERE ts < ?", (cutoff,))
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

# Miner entrypoints, in precedence order, over indexed paths (lowercased).
_ENTRYPOINT_PATTERNS: Tuple["re.Pattern[str]", ...] = (
    re.compile(r"(?:^|/)neurons?/miner[^/]*\.py$"),
    re.compile(r"(?:^|/)miner/(?:__main__|main|cli|run[^/]*)\.py$"),
    re.compile(r"(?:^|/)cmd/miner/main\.go$"),
    re.compile(r"(?:^|/)miner/[^/]+\.go$"),
    re.compile(r"(?:^|/)src/bin/miner[^/]*\.rs$"),
    re.compile(r"(?:^|/)miner/src/main\.rs$"),
    re.compile(r"(?:^|/)miner[^/]*/(?:__init__\.py|(?:src/)?index\.[jt]s)$"),
)
# Directory components that make a miner-named file NOT an entrypoint:
# validator code, API routes, migrations, tests, register and helper
# scripts, docs, examples, and vendored code.
_ENTRYPOINT_EXCLUDED = re.compile(
    r"^(?:validator.*|api|routes|migrations|test.*|scripts|docs|examples|"
    r"vendor|node_modules)$")
SOURCE_EXTENSIONS = (".py", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx",
                     ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".cu",
                     ".sol", ".sh")

# Normalised sha256 of the unedited bittensor subnet template
# `min_compute.yml` (opentensor/bittensor-subnet-template main @ 539b77c,
# fetched 2026-09-25): comments, trailing space and blank lines removed. SN60
# (Bitsec-AI/sandbox) ships it byte for byte. SN33 does NOT match: it adds a
# real `miner-cpu` profile, so it is an edited declaration.
TEMPLATE_MIN_COMPUTE_SHA256 = frozenset({
    "bd51c5e4cf2504cb9dc45cc7a8f2a0739b7f764a6863caac7159633b8cc63e0f",
})


def min_compute_fingerprint(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        if line.strip():
            lines.append(line)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def is_template_min_compute(text: str) -> bool:
    return min_compute_fingerprint(text) in TEMPLATE_MIN_COMPUTE_SHA256


def _miner_section_bounds(text: str) -> Tuple[int, int]:
    """(first, end) line indices of the miner block of a min_compute
    declaration, or the whole file when it does not split by role. This is
    a MINING screen: the validator's requirement describes a machine we are
    not costing."""
    lines = (text or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if _MINER_SECTION_RE.match(line):
            start = index + 1
            break
    if start is None:
        return 0, len(lines)
    for index in range(start, len(lines)):
        if _ROLE_SECTION_RE.match(lines[index]):
            return start, index
    return start, len(lines)


def _miner_section(text: str) -> str:
    first, end = _miner_section_bounds(text)
    return "\n".join((text or "").splitlines()[first:end])


def _excluded(path: str, cfg: Dict[str, Any]) -> bool:
    lowered = path.lower()
    parts = set(lowered.split("/"))
    return any(part in parts for part in cfg.get("exclude_path_parts") or [])


def entrypoint_precedence(path: str) -> Optional[int]:
    """Precedence of `path` as a miner entrypoint (lower wins), or None when
    it is not one. A miner-named file under validator, API, migration, test,
    script, docs, example or vendored paths is never an entrypoint."""
    lowered = path.lower()
    directories = lowered.split("/")[:-1]
    if any(_ENTRYPOINT_EXCLUDED.match(part) for part in directories):
        return None
    for index, pattern in enumerate(_ENTRYPOINT_PATTERNS):
        if pattern.search(lowered):
            return index
    return None


def parse_vram_gb(text: str) -> Tuple[Optional[float], Optional[str],
                                      Optional[int]]:
    """The MINER's declared VRAM floor from a min_compute declaration.

    Returns (gb, basis, line): basis names the key it came from, because
    `min_vram` is a floor and `recommended_vram` is not, and line is the
    1-based line of the kept value, searched in the miner section only.
    Returns (None, None, None) when nothing is declared, never a zero.
    """
    first, end = _miner_section_bounds(text)
    section = "\n".join((text or "").splitlines()[first:end])
    for regex, basis in ((_MIN_VRAM_RE, "min_vram"),
                         (_INLINE_VRAM_RE, "inline"),
                         (_REC_VRAM_RE, "recommended_vram")):
        matches = list(regex.finditer(section))
        if matches:
            best = max(matches, key=lambda m: float(m.group(1)))
            line = first + section.count("\n", 0, best.start()) + 1
            return float(best.group(1)), basis, line
    return None, None, None


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


def _content(connection: sqlite3.Connection, row_id: int) -> str:
    row = connection.execute(
        "SELECT content FROM fleet_files_fts WHERE rowid = ?",
        (row_id,)).fetchone()
    return row[0] if row else ""


def scan_slot(connection: sqlite3.Connection, cfg: Dict[str, Any],
              netuid: int, epoch: int) -> Dict[str, Any]:
    """Read-only feasibility scan of one slot's indexed files.

    Reads the FTS index only. It never touches the working tree, and it
    never builds, installs, tests, or executes subnet code. Absent evidence
    yields `unknown`, which never cuts.
    """
    rows = connection.execute(
        "SELECT id, path FROM fleet_files WHERE netuid = ? AND epoch = ?",
        (netuid, epoch)).fetchall()
    if not rows:
        return {"verdict": VERDICT_UNKNOWN, "evidence": [],
                "reason": "no indexed files for this slot"}

    limit = int(cfg.get("max_evidence_per_kind", 4))
    min_names = [n.lower() for n in cfg.get("min_compute_names") or []]

    evidence: List[Dict[str, Any]] = []
    min_compute_path: Optional[str] = None
    vram_gb: Optional[float] = None
    vram_basis: Optional[str] = None
    gpu_hits: List[Dict[str, Any]] = []
    api_hits: List[Dict[str, Any]] = []
    sources = 0
    entry: Optional[Tuple[int, str, int]] = None
    min_computes: List[Tuple[int, str]] = []

    for row_id, path in rows:
        lowered = path.lower()
        if lowered.rsplit("/", 1)[-1] in min_names:
            min_computes.append((row_id, path))
            continue
        if _excluded(path, cfg):
            continue
        if lowered.endswith(SOURCE_EXTENSIONS):
            sources += 1
        precedence = entrypoint_precedence(path)
        if precedence is not None and (
                entry is None or (precedence, path) < (entry[0], entry[1])):
            entry = (precedence, path, row_id)

    def scan_tokens(content: str, path: str) -> None:
        if len(gpu_hits) < limit:
            gpu_hits.extend(_find_tokens(content, cfg.get("gpu_tokens") or [],
                                         path, limit - len(gpu_hits)))
        if len(api_hits) < limit:
            api_hits.extend(_find_tokens(content,
                                         cfg.get("closed_api_tokens") or [],
                                         path, limit - len(api_hits)))

    for row_id, path in sorted(min_computes, key=lambda item: item[1]):
        content = _content(connection, row_id)
        if min_compute_path is None:
            min_compute_path = path
        if is_template_min_compute(content):
            evidence.append({"kind": "template", "path": path, "line": 1,
                             "note": "unedited subnet template; not a "
                                     "hardware declaration"})
            continue
        parsed, basis, line = parse_vram_gb(content)
        if parsed is not None:
            if vram_gb is None or parsed > vram_gb:
                vram_gb, vram_basis = parsed, basis
            evidence.append({"kind": "vram", "path": path, "line": line,
                             "value": parsed, "basis": basis})
        scan_tokens(content, path)

    entrypoint_path = entry[1] if entry else None
    if entry:
        scan_tokens(_content(connection, entry[2]), entry[1])

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
        verdict = VERDICT_UNKNOWN
        reason = ("no miner entrypoint recognised among %d indexed source "
                  "files; absence is not evidence of a closed subnet"
                  % sources)
    elif gpu_hits or (vram_gb or 0) > 0:
        verdict, reason = VERDICT_NEEDS_GPU, "GPU required"
    else:
        verdict, reason = VERDICT_POSSIBLE, "runnable miner, no GPU tell"

    return {"verdict": verdict, "reason": reason,
            "min_compute_path": min_compute_path,
            "entrypoint_path": entrypoint_path, "vram_gb": vram_gb,
            "vram_basis": vram_basis,
            "closed_api": 1 if api_hits else 0, "evidence": evidence}


def _index_state(connection: sqlite3.Connection
                 ) -> Dict[int, Tuple[int, str]]:
    try:
        rows = connection.execute(
            "SELECT netuid, epoch, indexed_sha FROM index_state").fetchall()
    except sqlite3.Error:
        return {}  # index never built: every slot is unindexed
    return {int(r[0]): (int(r[1]), str(r[2])) for r in rows}


def run_feasibility(connection: sqlite3.Connection, config: Dict[str, Any],
                    netuid: Optional[int] = None,
                    now: Optional[str] = None) -> Dict[str, Any]:
    """Stage B, gated on the commit the index actually holds: a slot is
    rescanned only when its indexed commit moves, and skipped while its
    index is behind its clone. One bad slot is recorded and skipped, never a
    pass failure."""
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    fleet = _fleet()
    slots = ([fleet.get_slot(connection, netuid)] if netuid is not None
             else fleet.all_slots(connection))
    indexed = _index_state(connection)
    scanned = unchanged = skipped = failed = behind = pruned = 0

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
        epoch = int(slot.get("epoch") or 0)
        state = indexed.get(int(slot["netuid"]))
        if state is None or state[0] != epoch:
            skipped += 1  # unindexed, or indexed under another epoch
            continue
        sha = state[1]
        if sha != slot.get("local_sha"):
            behind += 1  # index behind its clone: wait for it to catch up
            continue
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
            result = {"verdict": VERDICT_UNKNOWN,
                      "reason": "scan failed: %s" % str(exc)[:200],
                      "evidence": []}
        # The new verdict supersedes every other one for this slot.
        pruned += connection.execute(
            "DELETE FROM mine_feasibility WHERE netuid = ? AND NOT "
            "(epoch = ? AND sha = ?)", (slot["netuid"], epoch, sha)
        ).rowcount or 0
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
            "skipped": skipped, "index_behind": behind, "failed": failed,
            "superseded_pruned": pruned,
            "invalidated_by_scanner_change": invalidated,
            "scan_version": SCAN_VERSION, "ts": now}


def latest_feasibility(connection: sqlite3.Connection
                       ) -> Dict[int, Dict[str, Any]]:
    """Current verdicts only: those matching the slot's current epoch and
    indexed commit while the slot is active. Anything else is stale or
    unscanned and is not returned."""
    try:
        rows = connection.execute(
            "SELECT f.netuid, f.epoch, f.sha, f.verdict, f.min_compute_path, "
            "f.gpu_floor, f.vram_gb, f.entrypoint_path, f.closed_api, "
            "f.evidence_json, f.scanned_at "
            "FROM mine_feasibility f "
            "JOIN slots s ON s.netuid = f.netuid AND s.epoch = f.epoch "
            "AND s.status = 'active' "
            "JOIN index_state i ON i.netuid = f.netuid "
            "AND i.epoch = f.epoch AND i.indexed_sha = f.sha "
            "ORDER BY f.netuid").fetchall()
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


# ---------------------------------------------------------------------------
# Stage C: the ladder, run once per pass and stored
# ---------------------------------------------------------------------------

def classify_cut(cfg: Dict[str, Any], row: Dict[str, Any],
                 mechanisms: List[Dict[str, Any]],
                 feasibility: Optional[Dict[str, Any]]
                 ) -> Tuple[Optional[str], Optional[str], Dict[int, str]]:
    """Apply the ordered cut ladder. Returns (rung, detail, mechanism
    rungs). A subnet leaves at the FIRST rung it fails and the reason is
    recorded; exclusion is never implemented as omission. The mechanism
    rungs say why a mechanism cannot carry the rank, whether or not the
    subnet is cut."""
    mech_rungs: Dict[int, str] = {}
    ceiling_top1 = cfg.get("top1_ceiling_pct")
    for mech in mechanisms:
        if not (mech.get("split") or 0) > 0:
            mech_rungs[mech["mecid"]] = MECH_ZERO_SPLIT
        elif mech.get("indep_earner_count") == 0:
            mech_rungs[mech["mecid"]] = MECH_EMPTY
        elif mech.get("indep_top1_share_pct") is not None \
                and ceiling_top1 is not None \
                and float(mech["indep_top1_share_pct"]) \
                >= float(ceiling_top1):
            mech_rungs[mech["mecid"]] = MECH_CONCENTRATED

    if row.get("gate_state") == "disabled":
        return (CUT_GATE,
                "pool-side emission switch off: alpha is still distributed "
                "to miners but no TAO inflow backs it, so the alpha price "
                "decays and TAO income tends to zero", mech_rungs)
    identity = row.get("identity_state")
    if identity == IDENT_PLACEHOLDER:
        return (CUT_IDENTITY,
                "on-chain subnet_name is %r: the owner has marked the slot "
                "as not a going concern, so there is nothing to mine into "
                "regardless of what it still pays"
                % (row.get("subnet_name") or ""), mech_rungs)
    if identity == IDENT_ABSENT:
        return (CUT_IDENTITY,
                "no SubnetIdentitiesV3 entry on chain: the slot has never "
                "been named by its owner", mech_rungs)
    burn = row.get("miner_burn_pct")
    ceiling = float(cfg.get("burn_ceiling_pct", 99.0))
    if burn is not None and burn >= ceiling:
        return (CUT_BURN,
                "owner hotkeys captured %.2f%% of miner incentive "
                "(chain MinerBurned; ceiling %.0f%%)" % (burn, ceiling),
                mech_rungs)
    # No independent earner anywhere. Unknown fields (unread vector or
    # owner set) are not empty ones: fail open.
    if mechanisms and all(m.get("indep_earner_count") == 0
                          for m in mechanisms):
        return (CUT_NO_EARNER,
                "no UID outside the owner set earns incentive in any "
                "mechanism: the field has no paying independent miner, and "
                "the parity model would divide the pool by one",
                mech_rungs)
    # Winner-take-all on the INDEPENDENT field, per mechanism. Cut only when
    # every mechanism with a nonzero split is concentrated or empty.
    live = [m for m in mechanisms if (m.get("split") or 0) > 0]
    if live and all(mech_rungs.get(m["mecid"]) in (MECH_EMPTY,
                                                   MECH_CONCENTRATED)
                    for m in live):
        parts = []
        for mech in live:
            if mech_rungs[mech["mecid"]] == MECH_EMPTY:
                parts.append("mechanism %d: no independent earner"
                             % mech["mecid"])
            else:
                parts.append("mechanism %d: independent top-1 takes %.1f%% "
                             "across %s independent earner(s)"
                             % (mech["mecid"],
                                float(mech["indep_top1_share_pct"]),
                                mech.get("indep_earner_count")))
        return (CUT_CONCENTRATION,
                "%s (ceiling %.0f%%): entry means displacing that miner, "
                "not joining a field, and the parity model behind the "
                "headline figure does not describe it"
                % ("; ".join(parts), float(ceiling_top1)), mech_rungs)
    if feasibility and feasibility.get("verdict") in INFEASIBLE_VERDICTS:
        return (CUT_FEASIBILITY,
                "feasibility verdict %s" % feasibility["verdict"],
                mech_rungs)
    band, _ = _rent_for_band(cfg)
    if band and feasibility and feasibility.get("vram_gb"):
        band_vram = float(((cfg.get("rent_bands") or {})
                           .get(band) or {}).get("vram_gb") or 0)
        if float(feasibility["vram_gb"]) > band_vram:
            return (CUT_HARDWARE,
                    "declared floor %.0f GB VRAM exceeds band %s (%.0f GB)"
                    % (float(feasibility["vram_gb"]), band, band_vram),
                    mech_rungs)
    return None, None, mech_rungs


def _figure(entry: Dict[str, Any]) -> Optional[float]:
    value = entry.get("net_tao_month")
    return entry.get("gross_tao_month") if value is None else value


def decide(cfg: Dict[str, Any], rows: List[Dict[str, Any]],
           mechanisms: Dict[int, List[Dict[str, Any]]],
           feasibility: Dict[int, Dict[str, Any]]
           ) -> Tuple[Dict[int, Dict[str, Any]], Dict[Tuple[int, int],
                                                      Optional[str]]]:
    """The ladder and the ranking for one pass. Returns the per-subnet
    result (exactly one of cut, rank or unrated) and each mechanism's rung.
    Pure."""
    results: Dict[int, Dict[str, Any]] = {}
    mech_rungs: Dict[Tuple[int, int], Optional[str]] = {}
    rated: List[Tuple[float, int]] = []
    for row in rows:
        netuid = int(row["netuid"])
        mechs = mechanisms.get(netuid, [])
        rung, detail, rungs = classify_cut(cfg, row, mechs,
                                           feasibility.get(netuid))
        for mech in mechs:
            mech_rungs[(netuid, mech["mecid"])] = rungs.get(mech["mecid"])
        result: Dict[str, Any] = {"cut_reason": rung, "cut_detail": detail,
                                  "rank": None, "rank_mecid": None,
                                  "unrated_reason": None, "headline": None}
        surviving = [m for m in mechs if m["mecid"] not in rungs]
        if rung is None:
            figured = [m for m in surviving if _figure(m) is not None]
            if figured:
                best = sorted(figured, key=lambda m: (-_figure(m),
                                                      m["mecid"]))[0]
                result["rank_mecid"] = best["mecid"]
                result["headline"] = best
                rated.append((_figure(best), netuid))
            else:
                result["unrated_reason"] = (
                    row["confidence"] if row.get("confidence") != CONF_OK
                    else UNRATED_NOT_EMITTING if not row.get("alpha_out_day")
                    else next((m["no_figure_reason"] for m in surviving
                               if m.get("no_figure_reason")),
                              UNRATED_NO_FIGURE))
        results[netuid] = result
    for position, (_value, netuid) in enumerate(
            sorted(rated, key=lambda item: (-item[0], item[1])), start=1):
        results[netuid]["rank"] = position
    return results, mech_rungs


def _econ_rows(connection: sqlite3.Connection,
               ts: str) -> List[Dict[str, Any]]:
    cursor = connection.execute(
        "SELECT * FROM mine_econ WHERE ts = ? ORDER BY netuid", (ts,))
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _mechanism_rows(connection: sqlite3.Connection, ts: str,
                    netuid: Optional[int] = None
                    ) -> Dict[int, List[Dict[str, Any]]]:
    try:
        if netuid is None:
            cursor = connection.execute(
                "SELECT * FROM mine_mechanism WHERE ts = ? "
                "ORDER BY netuid, mecid", (ts,))
        else:
            cursor = connection.execute(
                "SELECT * FROM mine_mechanism WHERE ts = ? AND netuid = ? "
                "ORDER BY mecid", (ts, netuid))
    except sqlite3.Error:
        return {}
    columns = [d[0] for d in cursor.description]
    out: Dict[int, List[Dict[str, Any]]] = {}
    for values in cursor.fetchall():
        mech = dict(zip(columns, values))
        out.setdefault(int(mech["netuid"]), []).append(mech)
    return out


def run_classify(connection: sqlite3.Connection, config: Dict[str, Any],
                 ts: str) -> Dict[str, Any]:
    """Stage C: run the ladder once over the pass at `ts` and store the
    result in one transaction. Idempotent. The caller runs it only when
    econ committed this pass, so it never rewrites a previous pass."""
    cfg = mining_cfg(config)
    rows = _econ_rows(connection, ts)
    if not rows:
        return {"ok": False, "error": "no economics rows at %s" % ts}
    mechanisms = _mechanism_rows(connection, ts)
    feasibility = latest_feasibility(connection)
    results, mech_rungs = decide(cfg, rows, mechanisms, feasibility)

    by_netuid = {int(row["netuid"]): row for row in rows}
    try:
        for netuid, result in results.items():
            headline = result["headline"] or _headline_mechanism(
                mechanisms.get(netuid, []))
            row = dict(by_netuid[netuid])
            _copy_headline(row, headline)
            assignments = {column: row[column] for column, _ in _HEADLINE}
            assignments.update({
                "cut_reason": result["cut_reason"],
                "cut_detail": result["cut_detail"],
                "rank": result["rank"], "rank_mecid": result["rank_mecid"],
                "unrated_reason": result["unrated_reason"]})
            connection.execute(
                "UPDATE mine_econ SET %s WHERE ts = ? AND netuid = ?"
                % ", ".join("%s = ?" % column for column in assignments),
                tuple(assignments.values()) + (ts, netuid))
        for (netuid, mecid), rung in mech_rungs.items():
            connection.execute(
                "UPDATE mine_mechanism SET rung = ? WHERE ts = ? AND "
                "netuid = ? AND mecid = ?", (rung, ts, netuid, mecid))
        state_set(connection, "last_classified_ts", ts)
        state_set(connection, "model_version", str(MODEL_VERSION))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    counts = {"ranked": sum(1 for r in results.values() if r["rank"]),
              "cut": sum(1 for r in results.values() if r["cut_reason"]),
              "unrated": sum(1 for r in results.values()
                             if r["unrated_reason"])}
    return {"ok": True, "ts": ts, "observed": len(rows), **counts,
            "feasibility_joined": len(feasibility)}


# ---------------------------------------------------------------------------
# Read side: every surface reads the stored result
# ---------------------------------------------------------------------------

def classified_ts(connection: sqlite3.Connection) -> Optional[str]:
    """The latest pass whose ladder completed. A pass whose later stage
    failed is never presented."""
    return state_get(connection, "last_classified_ts")


def latest_econ(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    ts = classified_ts(connection)
    return _econ_rows(connection, ts) if ts else []


def _age_hours(ts: Optional[str], now: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    delta = _parse_ts(now or _utc_now()) - _parse_ts(ts)
    return delta.total_seconds() / 3600.0


def report(connection: sqlite3.Connection, config: Dict[str, Any],
           limit: Optional[int] = None, include_cut: bool = False,
           cut_limit: Optional[int] = None,
           now: Optional[str] = None) -> Dict[str, Any]:
    """The stored ranking of the latest classified pass: ranked subnets in
    rank order, unrated subnets apart, and cut subnets with their stored
    rung. Nothing is recomputed.

    Strictly read-only, including no schema creation: the MCP server calls
    this over a `mode=ro` connection where any write attempt would fail.
    """
    cfg = mining_cfg(config)
    rows = latest_econ(connection)
    ts = rows[0]["ts"] if rows else None
    mechanisms = _mechanism_rows(connection, ts) if ts else {}
    feasibility = latest_feasibility(connection)
    limit = int(limit or cfg.get("board_limit", 10))
    cut_limit = int(cut_limit or cfg.get("cut_limit", 30))

    ranked: List[Dict[str, Any]] = []
    cut: List[Dict[str, Any]] = []
    unrated: List[Dict[str, Any]] = []
    joined_scans: List[str] = []
    for row in rows:
        netuid = int(row["netuid"])
        entry = dict(row)
        entry["mechanisms"] = mechanisms.get(netuid, [])
        feature = feasibility.get(netuid)
        if feature and feature.get("scanned_at"):
            joined_scans.append(feature["scanned_at"])
        entry["feasibility"] = feature or {"verdict": VERDICT_UNKNOWN,
                                           "scanned_at": None,
                                           "unscanned": True}
        if row.get("cut_reason"):
            cut.append(entry)
        elif row.get("rank") is not None:
            ranked.append(entry)
        else:
            unrated.append(entry)
    ranked.sort(key=lambda entry: entry["rank"])

    age = _age_hours(ts, now)
    stale_after = float(cfg.get("stale_after_hours", 18))
    result: Dict[str, Any] = {
        "generated_at": _utc_now(),
        "econ_ts": ts,
        "econ_block": rows[0]["block_ref"] if rows else None,
        "econ_age_hours": age,
        "stale": bool(age is not None and age > stale_after),
        "stale_after_hours": stale_after,
        "feasibility_ts": max(joined_scans) if joined_scans else None,
        "model_version": state_get(connection, "model_version"),
        "miner_split_source": state_get(connection, "miner_split_source"),
        "owner_cut": state_get(connection, "owner_cut"),
        "parity_model": PARITY_MODEL,
        "budget_band": cfg.get("budget_band"),
        "counts": {"observed": len(rows), "ranked": len(ranked),
                   "cut": len(cut), "unrated": len(unrated)},
        "cut_summary": _cut_summary(cut),
        "switch_block_ref": rows[0]["block_ref"] if rows else None,
        "ranked": ranked[:limit],
        "unrated": unrated,
    }
    if include_cut:
        result["cut"] = cut[:cut_limit]
        result["cut_omitted"] = max(0, len(cut) - cut_limit)
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
    current = latest_feasibility(connection)
    verdicts: Dict[str, int] = {}
    for feature in current.values():
        verdicts[feature["verdict"]] = verdicts.get(feature["verdict"], 0) + 1
    stored = connection.execute(
        "SELECT COUNT(*) FROM mine_feasibility").fetchone()[0]
    return {"version": MINING_VERSION, "model_version": MODEL_VERSION,
            "econ_rows": econ[0], "last_econ_ts": econ[1],
            "last_classified_ts": classified_ts(connection),
            "confidence": confidence,
            "feasibility_verdicts": verdicts,
            "feasibility_not_current": stored - len(current),
            "last_feasibility_ts": state_get(connection,
                                             "last_feasibility_ts"),
            "miner_split_source": state_get(connection,
                                            "miner_split_source")}


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
    "td.wrap{white-space:normal}"
    "th{color:#8a8f98;font-weight:normal;font-size:12px}"
    ".num{text-align:right}.warn{color:#e0a458}.bad{color:#d05c5c}"
    ".ok{color:#6fbf73}.note{color:#8a8f98;font-size:12px}"
    "code{color:#8ab4f8}a{color:#8ab4f8}"
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


def _name_cell(entry: Dict[str, Any]) -> str:
    name = entry.get("subnet_name")
    return (_esc(name) if name else '<span class="note">%s</span>'
            % _esc(entry.get("identity_state") or "unread"))


def _mechanism_cell(entry: Dict[str, Any]) -> str:
    mecid = entry.get("rank_mecid")
    split = next((m.get("split") for m in entry.get("mechanisms") or []
                  if m.get("mecid") == mecid), None)
    count = entry.get("mechanism_count") or 1
    if count <= 1:
        return "0"
    return "%s of %d (%s split)" % (_esc(mecid), count,
                                    _fmt(None if split is None
                                         else 100.0 * split, 0) + "%")


def _entry_cell(entry: Dict[str, Any]) -> str:
    full = entry.get("uids_full")
    if full is None:
        state = '<span class="note">unknown</span>'
    elif full:
        state = '<span class="warn">full: deregisters a UID</span>'
    else:
        state = "open slot"
    return "%s &middot; immunity %s blk &middot; burn %s TAO" % (
        state, _fmt(entry.get("immunity_period"), 0),
        _fmt(entry.get("reg_cost_tao"), 4))


def _feasibility_cells(entry: Dict[str, Any]) -> Tuple[str, str]:
    feature = entry.get("feasibility") or {}
    floor = feature.get("gpu_floor")
    verdict = feature.get("verdict")
    if floor:
        floor_cell = _esc(floor)
    elif feature.get("unscanned"):
        floor_cell = '<span class="warn">unverified: unscanned</span>'
    elif verdict == VERDICT_UNKNOWN:
        floor_cell = '<span class="warn">unverified</span>'
    else:
        floor_cell = '<span class="note">%s</span>' % _esc(verdict)
    path = feature.get("min_compute_path") or feature.get("entrypoint_path")
    return floor_cell, "<code>%s</code>" % _esc(path or "")


def render_html(view: Dict[str, Any]) -> str:
    rows = []
    for entry in view.get("ranked", []):
        floor_cell, path_cell = _feasibility_cells(entry)
        rows.append(
            "<tr><td class=\"num\">%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class=\"num\">%s</td><td class=\"num warn\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td></tr>"
            % (entry.get("rank"), entry.get("netuid"), _name_cell(entry),
               _mechanism_cell(entry),
               _fmt(_figure(entry), 4),
               _fmt(entry.get("incumbent_alpha_day"), 1),
               _fmt(entry.get("displacement_rank"), 0),
               _fmt(entry.get("price_tao"), 6),
               _fmt(entry.get("owner_share_pct"), 2),
               _fmt(entry.get("earner_count"), 0),
               _fmt(entry.get("top1_share_pct"), 1),
               _entry_cell(entry), floor_cell, path_cell,
               _esc(entry.get("confidence"))))

    unrated = "".join(
        "<tr><td>%s</td><td>%s</td><td class=\"wrap\">%s</td></tr>"
        % (entry.get("netuid"), _name_cell(entry),
           _esc(entry.get("unrated_reason")))
        for entry in view.get("unrated", []))
    cut_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td class=\"wrap\">%s</td>"
        "</tr>" % (entry.get("netuid"), _name_cell(entry),
                   _esc(entry.get("cut_reason")),
                   _esc(entry.get("cut_detail")))
        for entry in view.get("cut", []))
    omitted = view.get("cut_omitted") or 0
    cuts = "".join(
        "<tr><td>%s</td><td class=\"num\">%d</td></tr>" % (_esc(k), v)
        for k, v in sorted(view.get("cut_summary", {}).items()))

    band = view.get("budget_band")
    band_note = ("budget band: %s" % _esc(band) if band else
                 "no budget band chosen yet, so rent is unknown and the "
                 "hardware rung does not cut")
    age = view.get("econ_age_hours")
    age_text = ("age %.1fh" % age) if age is not None else "age unknown"
    stale = ('<div class="bad">STALE: the last complete economics pass is '
             '%s old, over the %.0fh bound. The chain read has been failing; '
             'these figures are not current.</div>'
             % (_esc("%.1fh" % age), float(view.get("stale_after_hours")
                                           or 18))
             if view.get("stale") else "")
    counts = view.get("counts", {})

    return (
        "<html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,"
        "initial-scale=1\">"
        "<title>Atlas mining triage</title><style>%s</style></head><body>"
        "<h1>Mining triage</h1>%s"
        "<div class=\"sub\">economics observed %s at block %s (%s) &middot; "
        "feasibility of joined verdicts scanned %s &middot; %s &middot; "
        "switch at block %s &middot; <a href=\"index.html\">attention "
        "board</a><br>"
        "every figure is chain state at one block: alpha distributed per "
        "block (it halves per subnet), miner share 0.5 &times; (1 &minus; "
        "owner cut), each mechanism's split, owner UIDs removed and "
        "reconciled against MinerBurned, Balancer pool price<br>"
        "<span class=\"warn\">ASSUMPTION:</span> %s</div>"
        "<table><tr><th>rank</th><th>netuid</th><th>on-chain name</th>"
        "<th>ranked on mechanism</th><th>entrant TAO/mo (model)</th>"
        "<th>incumbent &alpha;/day</th><th>enter at rank</th>"
        "<th>alpha price</th><th>owner share %%</th>"
        "<th>indep. earners</th><th>indep. top-1 %%</th>"
        "<th>entry</th><th>hardware floor</th><th>evidence</th>"
        "<th>confidence</th></tr>%s</table>"
        "<h1>Unrated</h1><div class=\"sub\">%d subnet(s) survive the ladder "
        "but have no figure; they are not ranked last, they are unrated"
        "</div><table><tr><th>netuid</th><th>on-chain name</th>"
        "<th>reason</th></tr>%s</table>"
        "<h1>Cut ladder</h1><div class=\"sub\">%d observed, %d ranked, "
        "%d unrated, %d cut</div><table><tr><th>reason</th><th>subnets</th>"
        "</tr>%s</table>"
        "<table><tr><th>netuid</th><th>on-chain name</th><th>rung</th>"
        "<th>stored reason</th></tr>%s</table>%s"
        "<div class=\"note\">%s</div></body></html>"
        % (_CSS, stale,
           _esc(view.get("econ_ts")), _esc(view.get("econ_block")),
           _esc(age_text), _esc(view.get("feasibility_ts") or "n/a"),
           band_note,
           _esc(view.get("switch_block_ref") if view.get("switch_block_ref")
                is not None else "n/a"),
           _esc(view.get("parity_model") or PARITY_MODEL),
           "".join(rows) or "<tr><td colspan=\"15\" class=\"note\">"
                            "no classified pass yet</td></tr>",
           counts.get("unrated", 0),
           unrated or "<tr><td colspan=\"3\" class=\"note\">none</td></tr>",
           counts.get("observed", 0), counts.get("ranked", 0),
           counts.get("unrated", 0), counts.get("cut", 0),
           cuts or "<tr><td colspan=\"2\" class=\"note\">none</td></tr>",
           cut_rows or "<tr><td colspan=\"4\" class=\"note\">none</td></tr>",
           ("<div class=\"note\">%d more cut subnet(s) omitted</div>"
            % omitted) if omitted else "",
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
    view = report(connection, config, include_cut=True,
                  cut_limit=max(int(cfg.get("cut_limit", 30)), 200), now=now)
    page = render_html(view)
    www = (config.get("dashboard") or {}).get("www_dir", "var/fleet/www")
    if not os.path.isabs(www):
        www = os.path.join(_REPO_ROOT, www)
    out = os.path.join(www, "mining.html")
    _atomic_write(out, page)
    return {"path": out, "bytes": len(page),
            "ranked": view.get("counts", {}).get("ranked", 0),
            "unrated": view.get("counts", {}).get("unrated", 0),
            "cut": view.get("counts", {}).get("cut", 0),
            "stale": view.get("stale")}


# ---------------------------------------------------------------------------
# Pass hook + CLI
# ---------------------------------------------------------------------------

def run_pass(connection: sqlite3.Connection, config: Dict[str, Any],
             now: Optional[str] = None,
             snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The mining step, invoked inline after metrics in the fleet pass, in
    the order economics, feasibility, classification, render. Every stage
    is fail-isolated, and classification runs only over a pass whose
    economics committed."""
    cfg = mining_cfg(config)
    now = now or _utc_now()
    ensure_schema(connection)
    if not cfg.get("enabled", True):
        return {"disabled": True}

    summary: Dict[str, Any] = {}

    def stage(name: str, call: Any) -> None:
        try:
            summary[name] = call()
        except Exception as exc:  # noqa: BLE001 — never fails the pass
            connection.rollback()
            summary[name] = {"error": str(exc)[:200]}

    stage("econ", lambda: run_econ(connection, config, now=now,
                                   snapshot=snapshot))
    stage("feasibility", lambda: run_feasibility(connection, config,
                                                 now=now))
    if (summary.get("econ") or {}).get("ok"):
        stage("classify", lambda: run_classify(connection, config, now))
    else:
        summary["classify"] = {"skipped": "economics did not commit this "
                                          "pass"}
    stage("render", lambda: render(connection, config, now=now))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_fleet_mining",
        description="Atlas mining triage: rank subnets by what a new "
                    "independent miner could earn, read-only.")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("econ", help="Stage A chain economics (one snapshot)")
    fe = sub.add_parser("feasibility", help="Stage B sha-gated code scan")
    fe.add_argument("--netuid", type=int, default=None)
    sub.add_parser("classify", help="Stage C over the latest econ pass")
    rp = sub.add_parser("report", help="stored ranking as JSON (read-only)")
    rp.add_argument("--limit", type=int, default=None)
    rp.add_argument("--include-cut", action="store_true")
    sub.add_parser("render", help="write var/fleet/www/mining.html")
    sub.add_parser("pass", help="econ + feasibility + classify + render")
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
            elif args.command == "classify":
                ts = state_get(connection, "last_econ_ts")
                result = (run_classify(connection, config, ts) if ts
                          else {"ok": False, "error": "no economics pass"})
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
