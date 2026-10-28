import json, os, glob, sys
D = "/home/mballance/projects/packets/dvs-enh/packets/2454b9ba-4aad-42bc-b620-075e0651f652/steps"
def calls(path):
    seen, out = set(), []
    for line in open(path, errors="replace"):
        try: ev = json.loads(line)
        except ValueError: continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("parent_tool_use_id"): continue
        m = ev.get("message") or {}; u = m.get("usage"); mid = m.get("id")
        if not u or mid in seen: continue
        seen.add(mid)
        out.append(dict(inp=u.get("input_tokens") or 0, cr=u.get("cache_read_input_tokens") or 0,
                        cw=u.get("cache_creation_input_tokens") or 0, out=u.get("output_tokens") or 0))
    return out
steps = []
for d in sorted(os.listdir(D)):
    p = os.path.join(D, d, "transcript.jsonl")
    if not os.path.exists(p): continue
    meta = json.load(open(os.path.join(D, d, "meta.json"))) if os.path.exists(os.path.join(D, d, "meta.json")) else {}
    c = calls(p)
    if c: steps.append(dict(name=d, failed="failed" in d, calls=c, cost=meta.get("cost_usd")))
# price ratios (per Mtok, Sonnet-class): input 3, write 3.75, read 0.30, output 15
P = dict(inp=3, cw=3.75, cr=0.30, out=15)
def price(c): return sum(c[k]*P[k] for k in P)/1e6
ctx = lambda c: c["inp"]+c["cr"]+c["cw"]
act = [c for s in steps for c in s["calls"]]
print("transcripts", len(steps), "failed", sum(s["failed"] for s in steps), "calls", len(act))
real = sum(s["cost"] or 0 for s in steps)
print("actual: ctx %.1fM out %.2fM est $%.2f (reported $%.2f over steps with cost)" % (
    sum(map(ctx, act))/1e6, sum(c["out"] for c in act)/1e6, sum(map(price, act)), real))
ok = [s for s in steps if not s["failed"]]
firsts = [ctx(s["calls"][0]) for s in ok]; base = min(firsts)
print("step first ctx: min %d median %d max %d" % (base, sorted(firsts)[len(firsts)//2], max(firsts)))
growth = [ctx(s["calls"][-1]) - ctx(s["calls"][0]) for s in ok]
print("growth/step median %dk total %.0fk" % (sorted(growth)[len(growth)//2]/1e3, sum(growth)/1e3))
def mono(T, summary=20000, steps_=ok, B=base):
    carried, tot_ctx, tot_cost, ncomp, prev = 0, 0, 0.0, 0, None
    for s in steps_:
        f = ctx(s["calls"][0])
        for c in s["calls"]:
            n = B + carried + (ctx(c) - f) + 2000   # 2k: the user turn starting the step
            if n > T:   # compact: one call reads all, writes a summary
                tot_ctx += n; tot_cost += n*P["cr"]/1e6 + summary*P["out"]/1e6
                carried = summary - (ctx(c) - f) ; ncomp += 1; prev = None
                n = B + carried + (ctx(c) - f) + 2000
            # new tokens this call are written to cache, rest is read
            new = n - prev if prev and n > prev else n if prev is None else 0
            rd = n - new
            tot_ctx += n; tot_cost += rd*P["cr"]/1e6 + new*P["cw"]/1e6 + c["out"]*P["out"]/1e6
            prev = n
        carried += ctx(s["calls"][-1]) - f + 2000
    return tot_ctx, tot_cost, ncomp
ws = sum(map(ctx, [c for s in ok for c in s["calls"]])); wc = sum(price(c) for s in ok for c in s["calls"])
print("work-packet, successful steps only: ctx %.1fM est $%.2f" % (ws/1e6, wc))
for T in (160_000, 400_000, 900_000, 10**12):
    t, cst, n = mono(T)
    print("monolithic compact@%s: ctx %.1fM est $%.2f compactions %d  (x%.1f)" % (
        "never" if T > 1e9 else "%dk" % (T//1000), t/1e6, cst, n, cst/wc))


# --- Re-read measurement (the second figure in dvs-enh-monolithic.md) ---
# import json, os
# D = "/home/mballance/projects/packets/dvs-enh/packets/2454b9ba-4aad-42bc-b620-075e0651f652/steps"
# seen_files, tot, reread, n_r, n_rr = set(), 0, 0, 0, 0
# for d in sorted(os.listdir(D)):
#     p = os.path.join(D, d, "transcript.jsonl")
#     if "failed" in d or not os.path.exists(p): continue
#     ids, here = {}, set()
#     for line in open(p, errors="replace"):
#         try: ev = json.loads(line)
#         except ValueError: continue
#         if not isinstance(ev, dict) or ev.get("parent_tool_use_id"): continue
#         for b in ((ev.get("message") or {}).get("content") or []):
#             if not isinstance(b, dict): continue
#             if b.get("type") == "tool_use" and b.get("name") == "Read":
#                 ids[b["id"]] = (b.get("input") or {}).get("file_path")
#             if b.get("type") == "tool_result" and b.get("tool_use_id") in ids:
#                 c = b.get("content"); c = c if isinstance(c, str) else json.dumps(c)
#                 f = ids[b["tool_use_id"]]; t = len(c)/4
#                 tot += t; n_r += 1
#                 if f in seen_files and f not in here: reread += t; n_rr += 1
#                 here.add(f)
#     seen_files |= here
# print("Read results: %d calls, %.0fk tok; re-read of files read in an earlier step: %d calls, %.0fk tok" % (n_r, tot/1e3, n_rr, reread/1e3))
