import json, io
NETS=[114,107,91,126,100,8,63,48,124,56,127,15,55,76,70,26,6,43,74,18,2,54,88,83,79,5,41,50,21,13]
raw=json.load(io.open('raw_subnets.json',encoding='utf-8'))
sub={s['id']:s for s in raw['payload']['results']}
print("=== C. Locate the burn UID; was it counted as a 'miner' in my table? ===")
print("%-4s %-15s %6s %6s %-9s %-6s %8s %s" % ('uid','name','burn%','bUID','type','counted','incShare','contaminated?'))
for nid in NETS:
    ns=json.load(io.open('mg/%d.json'%nid,encoding='utf-8'))['neurons']
    s=sub[nid]; burn=(s.get('emission_miner_burn') or 0)/100.0
    if burn<=0.0001:
        print("%-4s %-15s %6.2f %6s %-9s %-6s %8s %s" % (nid,str(s.get('name'))[:15],burn*100,'-','-','-','-','no burn'))
        continue
    cand=[n for n in ns if abs((n.get('incentive') or 0)-burn)<0.02]
    if not cand:
        print("%-4s %-15s %6.2f %6s %-9s %-6s %8s %s" % (nid,str(s.get('name'))[:15],burn*100,'NOT FOUND','?','?','?','*** UNEXPLAINED ***'))
        continue
    b=max(cand,key=lambda n:n.get('incentive') or 0)
    counted = (b.get('type')=='miner') and ((b.get('daily_rewards_usd') or 0)>0)
    print("%-4s %-15s %6.2f %6s %-9s %-6s %8.4f %s" % (
        nid,str(s.get('name'))[:15],burn*100,b['uid'],b.get('type'),str(counted),b.get('incentive') or 0,
        'YES - my top$/median are WRONG' if counted else 'no (excluded)'))
