"""Show expectation checkpoint, call trail and delivered text for (case, harness) pairs.
usage: check.py <scratch> CASE:HARNESS ... [--tail N]"""
import json, sys, re, os
S = sys.argv[1]; pairs = [a for a in sys.argv[2:] if ":" in a]
N = 900
cache = {}
for p in pairs:
    c, h = p.split(":")
    print("#" * 20, c, h)
    e = open(f"{S}/expect/{c}.md").read()
    for m in re.finditer(r"\*\*(预期协同|检查点|数据前置)[^*]*\*\*(.*)", e): print("  ", m.group(1), m.group(2)[:260])
    print("  ", e.split("本批实际问句")[-1].strip()[:300].replace("\n", " "))
    for l in open(f"{S}/digest_xs/{c}/{h}.md"):
        if re.match(r"(### USER|  #\d+.*CALL|    <- )", l): print("  ", l.rstrip()[:220])
    if h not in cache: cache[h] = json.load(open(f"{S}/data/{h}.json"))
    for k in cache[h]["cases"]:
        if k.get("latest") is not False and k["overview"]["case_id"].split("_")[-1] == c:
            for t in k["overview"]["turns"]:
                ft = t.get("final_text") or ""
                print(f"  DELIVERED t{t['index']} ({len(ft)}c) …{ft[-N:]}".replace("\n", " "))
