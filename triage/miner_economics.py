"""Regenerate miner economics in ALPHA. No fiat is stored.

Alpha figures are structural (2952 alpha/day miner pool x incentive share) and
stay correct as markets move. The snapshot alpha price is carried per row so a
reader can convert at display time -- see docs/emission-metrics.md 2.1.

at_uid_cap is NOT a barrier to entry. Registering into a full subnet evicts the
lowest-emission UID and hands over its slot (subtensor registration.rs:27). The
parameters that actually govern entry are immunity_period_blocks (grace window
before you are prunable) and the dynamic burn. See docs/emission-metrics.md 5.
"""
import json, io, csv, statistics as st

MINER_POOL_ALPHA_DAY = 2952.0            # 41% of 7200 alpha/day, verified
NETS = [114,107,91,126,100,8,63,48,124,56,127,15,55,76,70,26,6,43,74,18,2,54,88,83,79,5,41,50,21,13]

raw = json.load(io.open('raw_subnets.json', encoding='utf-8'))
SNAP, BLOCK = raw['fetched_at'], raw['as_of_block']
sub = {s['id']: s for s in raw['payload']['results']}
hyper = json.load(io.open('hyperparams.json', encoding='utf-8'))['data']
repo = {}
for n in range(1, 9):
    for r in json.load(io.open('batch_%d.json' % n, encoding='utf-8')):
        repo[r['netuid']] = r

rows = []
for nid in NETS:
    ns = json.load(io.open('mg/%d.json' % nid, encoding='utf-8'))['neurons']
    s, rp = sub[nid], repo[nid]
    burn = (s.get('emission_miner_burn') or 0) / 100
    price = s.get('price')

    mslots = [n for n in ns if n.get('type') == 'miner']
    inc_m  = sum(n.get('incentive') or 0 for n in mslots)
    gated  = max(sum(n.get('incentive') or 0 for n in ns) - inc_m - burn, 0)

    # alpha via incentive share -- daily_rewards_alpha mixes streams on dual-role UIDs
    alpha = sorted(MINER_POOL_ALPHA_DAY * (n.get('incentive') or 0)
                   for n in mslots if (n.get('incentive') or 0) > 0)
    tot = sum(alpha)
    q = lambda p: round(alpha[int(len(alpha) * p)], 4) if alpha else 0.0
    med = st.median(alpha) if alpha else 0.0
    regc = s.get('registration_cost')
    payback = (round(regc / (med * price), 1)
               if med > 0 and price and isinstance(regc, (int, float)) else 'never')

    rows.append({
        'snapshot_utc': SNAP, 'as_of_block': BLOCK,
        'netuid': nid, 'name': s.get('name'),
        'burn_pct': round(burn * 100, 2),
        'miner_slots': len(mslots), 'earning': len(alpha),
        'earn_rate_pct': round(len(alpha) / len(mslots) * 100, 1) if mslots else 0,
        'miner_accessible_alpha_day': round(MINER_POOL_ALPHA_DAY * (1 - burn), 2),
        'inc_share_non_permit': round(inc_m, 4),
        'inc_share_permit_holders': round(gated, 4),
        'top_alpha_day': round(alpha[-1], 4) if alpha else 0.0,
        'p75_alpha_day': q(0.75),
        'median_alpha_day': round(med, 4),
        'p25_alpha_day': q(0.25),
        'top10_share_pct': round(sum(alpha[-max(1, len(alpha)//10):]) / tot * 100, 1) if tot else 0.0,
        'reg_cost_tao': regc,
        'alpha_price_tao_at_snapshot': price,
        'payback_days_at_snapshot_price': payback,
        'uid_total': len(ns), 'at_uid_cap': len(ns) >= 256,
        'immunity_period_blocks': hyper[str(nid)][0],
        'immunity_days': round(hyper[str(nid)][0] / 7200, 2),
        'registration_allowed': hyper[str(nid)][1],
        'min_burn_tao': hyper[str(nid)][2],
        'burn_increase_mult': hyper[str(nid)][3],
        'setup': rp['setup_complexity'], 'runtime': rp['runtime'],
        'min_compute': rp['min_compute_present'],
        'last_commit': str(rp['last_commit_iso'])[:10],
        'subnet_risk': (s.get('dereg') or {}).get('risk_level'),
    })

rows.sort(key=lambda r: -r['median_alpha_day'])
with io.open('miner_economics.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

print('%-4s %-15s %5s %5s %6s %8s %8s %11s %9s %8s %7s %9s' % (
    'uid','name','slot','earn','earn%','nonPermit','permit','minerPool_a/d','med_a/d','p25_a/d','top10%','immun_d'))
for r in rows:
    print('%-4s %-15s %5s %5s %6.1f %8.4f %8.4f %11.2f %9.4f %8.4f %7.1f %9.2f' % (
        r['netuid'], str(r['name'])[:15], r['miner_slots'], r['earning'], r['earn_rate_pct'],
        r['inc_share_non_permit'], r['inc_share_permit_holders'], r['miner_accessible_alpha_day'],
        r['median_alpha_day'], r['p25_alpha_day'], r['top10_share_pct'],
        r['immunity_days']))
