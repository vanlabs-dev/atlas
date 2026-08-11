import json, io, re, datetime

FETCHED_AT = "2026-08-11T04:30:02Z"
body = json.load(io.open('raw_subnets_body.json', encoding='utf-8'))
results = body['results']
as_of_block = None
for s in results:
    c = s.get('conviction') or {}
    if c.get('as_of_block'):
        as_of_block = c['as_of_block']; break

wrapped = {
    "fetched_at": FETCHED_AT,
    "source_url": "https://api.taoswap.org/v2/subnets/",
    "http_status": 200,
    "as_of_block": as_of_block,
    "current_block": (body.get('dereg_context') or {}).get('current_block'),
    "emission_miner_burn_unit": "percent_0_100",
    "subnet_count": len(results),
    "payload": body,
}
with io.open('raw_subnets.json','w',encoding='utf-8') as f:
    json.dump(wrapped, f, ensure_ascii=False, indent=1)

GH = re.compile(r'https?://(?:www\.)?github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)', re.I)

def gh_url(identity):
    if not isinstance(identity, dict): return None
    for key in ('github','url','description','name'):
        v = identity.get(key)
        if isinstance(v,str):
            m = GH.search(v)
            if m:
                owner, repo = m.group(1), m.group(2).rstrip('.git').rstrip('/')
                if owner.lower() in ('orgs','settings','features','about'): continue
                return "https://github.com/%s/%s" % (owner, repo)
    return None

ledger, survivors = [], []
def excl(nid, rule, value):
    ledger.append({"netuid": nid, "rule": rule, "value": value, "stage": "stage0"})

for s in results:
    nid = s['id']
    burn = s.get('emission_miner_burn')
    ident = s.get('identity')
    owner = s.get('owner')
    if not isinstance(burn,(int,float)):
        excl(nid, "burn_not_numeric", burn); continue
    if burn >= 90.0:
        excl(nid, "burn_ge_90pct", burn); continue
    if not ident or not isinstance(ident,dict) or not any(
            isinstance(ident.get(k),str) and ident.get(k).strip() for k in ('name','url','github','description')):
        excl(nid, "identity_missing_or_empty", ident); continue
    if not owner or not str(owner).strip():
        excl(nid, "owner_missing", owner); continue
    g = gh_url(ident)
    if not g:
        excl(nid, "no_github_url_in_identity", ident.get('github') or ident.get('url')); continue
    survivors.append({
        "netuid": nid,
        "name": s.get('name'),
        "burn_pct": burn,
        "registration_cost": s.get('registration_cost'),
        "active_miners": s.get('active_miners'),
        "prune_rank": (s.get('dereg') or {}).get('prune_rank'),
        "repo_url": g,
    })

with io.open('ledger.jsonl','w',encoding='utf-8') as f:
    for e in ledger:
        f.write(json.dumps(e, ensure_ascii=False)+"\n")
with io.open('survivors.json','w',encoding='utf-8') as f:
    json.dump(survivors, f, ensure_ascii=False, indent=1)

from collections import Counter
print("as_of_block:", as_of_block, "current_block:", wrapped['current_block'])
print("total:", len(results), "excluded:", len(ledger), "SURVIVORS:", len(survivors))
print("exclusions by rule:", dict(Counter(e['rule'] for e in ledger)))
print("survivor netuids:", [x['netuid'] for x in survivors])
