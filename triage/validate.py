import json, io
NETS=[114,107,91,126,100,8,63,48,124,56,127,15,55,76,70,26,6,43,74,18,2,54,88,83,79,5,41,50,21,13]
raw=json.load(io.open('raw_subnets.json',encoding='utf-8'))
sub={s['id']:s for s in raw['payload']['results']}

print("=== A. UID capacity: is every subnet 'full at 256'? ===")
for nid in NETS:
    ns=json.load(io.open('mg/%d.json'%nid,encoding='utf-8'))['neurons']
    from collections import Counter
    c=Counter(n.get('type') for n in ns)
    uids=[n['uid'] for n in ns]
    print('  %-4s total=%-4s maxuid=%-4s miner=%-4s val=%-4s owner=%-3s' % (nid,len(ns),max(uids),c.get('miner',0),c.get('validator',0),c.get('owner',0)))
