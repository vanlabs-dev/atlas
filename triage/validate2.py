import json, io
NETS=[114,107,91,126,100,8,63,48,124,56,127,15,55,76,70,26,6,43,74,18,2,54,88,83,79,5,41,50,21,13]
raw=json.load(io.open('raw_subnets.json',encoding='utf-8'))
sub={s['id']:s for s in raw['payload']['results']}
print("=== B. Does the incentive stream equal 2952a (gross) or 2952a*(1-burn) (net)? ===")
print("%-4s %-15s %6s %11s %11s %11s  %s" % ('uid','name','burn%','inc_alpha/d','gross2952','net_2952','verdict'))
bad=[]
for nid in NETS:
    ns=json.load(io.open('mg/%d.json'%nid,encoding='utf-8'))['neurons']
    s=sub[nid]; burn=s.get('emission_miner_burn') or 0
    inc=[n for n in ns if (n.get('incentive') or 0)>0]
    a=sum(n.get('daily_rewards_alpha') or 0 for n in inc)
    gross=2952.0; net=2952.0*(1-burn/100)
    v='GROSS' if abs(a-gross)<gross*0.03 else ('NET' if abs(a-net)<max(net*0.05,1) else '???')
    if v!='GROSS': bad.append(nid)
    print("%-4s %-15s %6.2f %11.1f %11.1f %11.1f  %s" % (nid,str(s.get('name'))[:15],burn,a,gross,net,v))
print()
print("non-GROSS:",bad)
