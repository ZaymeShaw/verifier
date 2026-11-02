"""Backend interface outcome counts (deduped by tool_call_id). usage: backend_stats.py <data dir>"""
import json,sys,os,re,collections
def status(t):
    s=t.replace(" ","")
    if '"status":"UPSTREAM' in s or '"status":"ERROR"' in s or "UPSTREAM" in s[:300]: return "error"
    if '"status":"AMBIGUOUS"' in s: return "ambiguous"
    if '"status":"EMPTY"' in s or re.search(r'"total":0[,}]',s): return "empty"
    if '"status":"PARTIAL"' in s: return "partial"
    return "ok"
PROD=re.compile(r"保险|平安|鑫瑞|安佑福|守护|e生保|盈添悦|颐享|惠享|险")
st=collections.defaultdict(collections.Counter); pk=collections.Counter(); q417=set(); pairs=collections.defaultdict(set); ex=collections.defaultdict(list)
for h in ["claude","pi","insurance_old","insurance_harness"]:
    D=json.load(open(os.path.join(sys.argv[1],h+".json")))
    for c in D["cases"]:
        if c.get("latest") is False: continue
        cid=c["overview"].get("case_id","").split("_")[-1]
        seen=set(); idq={}
        for k in c["calls"]:
            msgs=k.get("messages") or []
            for m in msgs:
                for tc in m.get("tool_calls") or []:
                    if not isinstance(tc,dict): continue
                    n=tc.get("name") or (tc.get("function") or {}).get("name") or ""
                    a=tc.get("arguments") or (tc.get("function") or {}).get("arguments") or ""
                    if isinstance(a,dict): a=json.dumps(a,ensure_ascii=False)
                    idq[tc.get("id")]=(n,a)
            for m in msgs:
                if m.get("role")!="tool" or m.get("tool_call_id") in seen: continue
                seen.add(m.get("tool_call_id"))
                n,a=idq.get(m.get("tool_call_id"),("",""))
                t=m.get("text") or ""
                try: q=json.loads(a).get("query","")
                except Exception: q=a
                if n.endswith("policy_search"):
                    key="带产品名" if PROD.search(q) else "不带产品名"; s=status(t); st[key][s]+=1; pairs[(key,s)].add(f"{h}:{cid}")
                    if s in("error","empty") and len(ex[(key,s)])<3: ex[(key,s)].append(f"{h}:{cid} {q[:40]} -> {t[:160]}")
                if n.endswith("product_knowledge"): pk[status(t)]+=1
                if n.endswith("customer_search") and re.search(r'"total"\s*:\s*417',t): q417.add(q)
for k,v in st.items(): print("policy_search",k,dict(v),"total",sum(v.values()))
for k,v in sorted(pairs.items()): print("  ",k,"calls in",len(v),"case-harness pairs,",len({x.split(':')[1] for x in v}),"distinct cases")
for k,v in ex.items(): print(k); [print("   ",x.replace("\\n"," ")) for x in v]
print("product_knowledge",dict(pk),"total",sum(pk.values()))
print("customer_search total=417 queries:",sorted(q417))
