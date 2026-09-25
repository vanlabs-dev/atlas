"""Mining screen fixtures (change: mining-board-accuracy).

Two kinds of input, both in the exact shape live-data's
`read_mining_snapshot` returns:

- MEASURED: six subnets read from live Finney at block 9142723
  (2026-09-25) through the real reader. Incentive vectors keep their
  nonzero entries only. `owner_cut` None means SubnetOwnerCut was unset,
  so the runtime default applies.
- `synthetic(...)`: hand-built subnets for edge cases.

`seed_board` runs the REAL writer (run_econ, then run_classify) so every
consumer test reads rows production would write. Importable from the
telegram and subnt suites.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_fleet_mining as mine  # noqa: E402

OWNER_CUT_DEFAULT = 11796

MEASURED = {'block_hash': ('0x319e0bd9561b955401aa2c65fe9491c5'
                            '49ed328d848008763e51988220cf4c1a'),
 'block_number': 9142723,
 'owner_cut': None,
 'subnets': {4: {'Burn': 500000,
                 'ImmunityPeriod': 7520,
                 'MaxAllowedUids': 256,
                 'SubnetAlphaIn': 2517832727587718,
                 'SubnetAlphaOut': 3776963819027628,
                 'SubnetAlphaOutEmission': 1000000000,
                 'SubnetEmissionEnabled': True,
                 'SubnetProtocolAlpha': 323317413062809,
                 'SubnetTAO': 135726766333687,
                 'SubnetworkN': 256,
                 'SwapBalancer': 0.4999999961696292,
                 'incentive': {0: {7: 21161,
                                   28: 1,
                                   32: 5233,
                                   156: 38267,
                                   162: 871}},
                 'incentive_len': {0: 256},
                 'miner_burned': 1.781829632818699e-05,
                 'name': 'Targon',
                 'owner_uids': [28]},
             9: {'Burn': 500000,
                 'ImmunityPeriod': 5000,
                 'MaxAllowedUids': 256,
                 'SubnetAlphaIn': 2148785782103588,
                 'SubnetAlphaOut': 4003981782638530,
                 'SubnetAlphaOutEmission': 1000000000,
                 'SubnetEmissionEnabled': True,
                 'SubnetProtocolAlpha': 263370888062307,
                 'SubnetTAO': 53631722066823,
                 'SubnetworkN': 256,
                 'SwapBalancer': 0.4999999966103741,
                 'incentive': {0: {128: 144, 171: 32773, 209: 32617}},
                 'incentive_len': {0: 256},
                 'miner_burned': 0.49770411662757397,
                 'name': 'iota',
                 'owner_uids': [209]},
             44: {'Burn': 50000000,
                  'ImmunityPeriod': 7500,
                  'MaxAllowedUids': 256,
                  'MechanismCountCurrent': 2,
                  'MechanismEmissionSplit': [0, 65535],
                  'SubnetAlphaIn': 1857035291520231,
                  'SubnetAlphaOut': 4181990856249437,
                  'SubnetAlphaOutEmission': 1000000000,
                  'SubnetEmissionEnabled': True,
                  'SubnetProtocolAlpha': 299994076988081,
                  'SubnetTAO': 65286706802499,
                  'SubnetworkN': 256,
                  'SwapBalancer': 0.49999999251100574,
                  'incentive': {0: {6: 65535},
                                1: {10: 2955,
                                    24: 1641,
                                    29: 3283,
                                    32: 26269,
                                    101: 3283,
                                    132: 3283,
                                    167: 4925,
                                    173: 3283,
                                    179: 15761,
                                    221: 846}},
                  'incentive_len': {0: 256, 1: 256},
                  'miner_burned': 0.0,
                  'name': 'Score',
                  'owner_uids': [6]},
             80: {'Burn': 500000,
                  'ImmunityPeriod': 5000,
                  'MaxAllowedUids': 256,
                  'SubnetAlphaIn': 187846861352756,
                  'SubnetAlphaOut': 2170632547713866,
                  'SubnetAlphaOutEmission': 1000000000,
                  'SubnetEmissionEnabled': True,
                  'SubnetProtocolAlpha': 83524257382101,
                  'SubnetTAO': 4985142451194,
                  'SubnetworkN': 256,
                  'SwapBalancer': 0.4999998404542976,
                  'incentive': {0: {0: 2949, 2: 27852, 21: 27852, 99: 6881}},
                  'incentive_len': {0: 256},
                  'miner_burned': 0.04499999899417162,
                  'name': 'OpenRoboto',
                  'owner_uids': [0]},
             93: {'Burn': 5000000,
                  'ImmunityPeriod': 50400,
                  'MaxAllowedUids': 256,
                  'MechanismCountCurrent': 2,
                  'MechanismEmissionSplit': [1311, 64224],
                  'SubnetAlphaIn': 1269963623511483,
                  'SubnetAlphaOut': 3898146466120447,
                  'SubnetAlphaOutEmission': 1000000000,
                  'SubnetEmissionEnabled': True,
                  'SubnetProtocolAlpha': 152794757213642,
                  'SubnetTAO': 23707402745677,
                  'SubnetworkN': 256,
                  'SwapBalancer': 0.4999999885305448,
                  'incentive': {0: {0: 16837, 152: 389, 153: 48308},
                                1: {157: 65535}},
                  'incentive_len': {0: 256, 1: 256},
                  'miner_burned': 0.005139517365023494,
                  'name': 'Bitcast',
                  'owner_uids': [0]},
             120: {'Burn': 500000000,
                   'ImmunityPeriod': 5000,
                   'MaxAllowedUids': 256,
                   'SubnetAlphaIn': 1653107005508598,
                   'SubnetAlphaOut': 2665007410826066,
                   'SubnetAlphaOutEmission': 1000000000,
                   'SubnetEmissionEnabled': True,
                   'SubnetProtocolAlpha': 324488794429626,
                   'SubnetTAO': 76673020877310,
                   'SubnetworkN': 256,
                   'SwapBalancer': 0.4999999882475417,
                   'incentive': {0: {36: 65535}},
                   'incentive_len': {0: 256},
                   'miner_burned': 0.0,
                   'name': 'Affine',
                   'owner_uids': [0]}}}


def _vector(entries, length):
    vector = [0] * length
    for uid, value in entries.items():
        vector[int(uid)] = int(value)
    return vector


def _values_skeleton():
    return {item: {} for item in (
        "SubnetworkN", "Incentive", "MinerBurned", "CollateralLockShare",
        "SubnetIdentitiesV3", "SubnetEmissionEnabled",
        "SubnetAlphaOutEmission", "OwnerCutEnabled", "MechanismCountCurrent",
        "MechanismEmissionSplit", "SubnetOwner", "SubnetOwnerHotkey",
        "SubnetTAO", "SubnetAlphaIn", "SubnetAlphaOut", "SubnetProtocolAlpha",
        "Burn", "ImmunityPeriod", "MaxAllowedUids", "SwapBalancer")}


def measured_snapshot(netuids=None):
    """The measured subnets as a live-data snapshot."""
    values = _values_skeleton()
    owners = {}
    for netuid, spec in MEASURED["subnets"].items():
        if netuids is not None and netuid not in netuids:
            continue
        for item in values:
            if item in spec:
                values[item][netuid] = spec[item]
        values["SubnetIdentitiesV3"][netuid] = spec["name"]
        values["MinerBurned"][netuid] = spec["miner_burned"]
        for mecid, entries in spec["incentive"].items():
            values["Incentive"][(netuid, mecid)] = _vector(
                entries, spec["incentive_len"][mecid])
        owners[netuid] = {"state": "ok", "uids": list(spec["owner_uids"]),
                          "hotkeys": len(spec["owner_uids"])}
    cut = MEASURED["owner_cut"]
    return {"ok": True, "block_hash": MEASURED["block_hash"],
            "block_number": MEASURED["block_number"], "values": values,
            "failures": {}, "failed_items": {}, "empty_items": [],
            "owner_cut": OWNER_CUT_DEFAULT if cut is None else cut,
            "owner_cut_state": "runtime-default" if cut is None else "set",
            "owners": owners}


def subnet(netuid, incentive=None, owner_uids=(), name=None, burn=None,
           alpha_out=1.0, tao_pool=25_000.0, alpha_pool=3_000_000.0,
           quote=0.5, enabled=True, count=None, split=None, cut_enabled=None,
           network_n=256, max_uids=256, immunity=5000, reg_burn=0.0005):
    """One synthetic subnet. `incentive` maps mecid to a vector (a list)
    or is a single list for mechanism 0. `burn` defaults to the owner share
    the vectors imply, so the fixture reconciles unless told otherwise."""
    if incentive is None:
        incentive = {0: [10, 5]}
    if isinstance(incentive, list):
        incentive = {0: incentive}
    return {"netuid": netuid, "incentive": incentive,
            "owner_uids": list(owner_uids) if owner_uids is not None
            else None,
            "name": "Subnet %d" % netuid if name is None else name,
            "burn": burn, "alpha_out": alpha_out, "tao_pool": tao_pool,
            "alpha_pool": alpha_pool, "quote": quote, "enabled": enabled,
            "count": count, "split": split, "cut_enabled": cut_enabled,
            "network_n": network_n, "max_uids": max_uids,
            "immunity": immunity, "reg_burn": reg_burn}


def _implied_burn(spec):
    count = spec["count"] or len(spec["incentive"]) or 1
    splits = mine.mechanism_split(count, spec["split"])
    owned = set(spec["owner_uids"] or [])
    burn = 0.0
    for mecid, vector in spec["incentive"].items():
        if vector is None:
            continue
        total = sum(vector)
        if total:
            burn += splits[mecid] * sum(
                v for uid, v in enumerate(vector) if uid in owned) / total
    return burn


def synthetic(subnets, block=8789861, owner_cut=OWNER_CUT_DEFAULT,
              failures=None, failed_items=None, identity=True):
    """A snapshot from `subnet(...)` specs. `identity` False leaves the
    identity map empty (unread). An incentive vector of None is recorded as
    an undecodable entry."""
    values = _values_skeleton()
    owners = {}
    failures = {item: dict(entries)
                for item, entries in (failures or {}).items()}
    for spec in subnets:
        n = spec["netuid"]
        values["SubnetworkN"][n] = spec["network_n"]
        values["MaxAllowedUids"][n] = spec["max_uids"]
        values["ImmunityPeriod"][n] = spec["immunity"]
        values["Burn"][n] = int(spec["reg_burn"] * 1e9)
        if identity and spec["name"] is not False:
            values["SubnetIdentitiesV3"][n] = spec["name"]
        if spec["enabled"]:
            values["SubnetEmissionEnabled"][n] = True
        if spec["alpha_out"]:
            values["SubnetAlphaOutEmission"][n] = int(spec["alpha_out"] * 1e9)
        if spec["tao_pool"] is not None:
            values["SubnetTAO"][n] = int(spec["tao_pool"] * 1e9)
        if spec["alpha_pool"] is not None:
            values["SubnetAlphaIn"][n] = int(spec["alpha_pool"] * 1e9)
        values["SubnetAlphaOut"][n] = int(5_000_000 * 1e9)
        if spec["quote"] is not None:
            values["SwapBalancer"][n] = spec["quote"]
        else:
            failures.setdefault("SwapBalancer", {})[n] = "bad payload"
        if spec["count"] is not None:
            values["MechanismCountCurrent"][n] = spec["count"]
        if spec["split"] is not None:
            values["MechanismEmissionSplit"][n] = list(spec["split"])
        if spec["cut_enabled"] is not None:
            values["OwnerCutEnabled"][n] = spec["cut_enabled"]
        for mecid, vector in spec["incentive"].items():
            if vector is None:
                failures.setdefault("Incentive", {})[(n, mecid)] = "bad"
            else:
                values["Incentive"][(n, mecid)] = list(vector)
        values["MinerBurned"][n] = (_implied_burn(spec)
                                    if spec["burn"] is None
                                    else spec["burn"])
        owners[n] = ({"state": "ok", "uids": list(spec["owner_uids"]),
                      "hotkeys": len(spec["owner_uids"])}
                     if spec["owner_uids"] is not None
                     else {"state": "unread", "reason": "cap exceeded"})
    return {"ok": True, "block_hash": "0xabc", "block_number": block,
            "values": values, "failures": failures,
            "failed_items": dict(failed_items or {}), "empty_items": [],
            "owner_cut": owner_cut,
            "owner_cut_state": "runtime-default", "owners": owners}


def seed_board(connection, config, snapshot, now=None):
    """Write one pass exactly as production does: econ, then classify."""
    mine.ensure_schema(connection)
    econ = mine.run_econ(connection, config, now=now, snapshot=snapshot)
    assert econ.get("ok"), econ
    return mine.run_classify(connection, config, econ["ts"])

