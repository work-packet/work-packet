# Compaction policies for a monolithic dvs-enh session; see dvs-enh-monolithic.md. Run from the repo root.
exec(open("docs/experiments/dvs-enh-monolithic.py").read().split("ws = sum")[0])
from work_packet import stats
st, _ = stats.collect([("dvs-enh", "/home/mballance/projects/packets/dvs-enh")])
item = {"%04d" % s.step: s.item for s in st if not s.failed}
early = {1: "plan", 2: "0a", 3: "0a", 4: "0b", 5: "0b", 6: "0c", 7: "0c", 8: "1a", 9: "1b", 10: "1b",
         11: "1b", 12: "1b", 13: "1b", 14: "2a", 15: "2a", 16: "2a"}
for s in ok:
    s["item"] = item.get(s["name"]) or early[int(s["name"])]
    s["top"] = s["item"][0]
print("items:", [(s["name"][-2:], s["item"]) for s in ok])
def run(T=None, at_item=False, at_step=False, summary=20000, B=base):
    carried, cost, prev, nc, peak = 0, 0.0, None, 0, 0
    tot = 0
    for k, s in enumerate(ok):
        if k and ((at_item and s["item"] != ok[k-1]["item"]) or at_step):
            n = B + carried; tot += n
            cost += n*P["cr"]/1e6 + summary*P["out"]/1e6; carried = summary; prev = None; nc += 1
        f = ctx(s["calls"][0])
        for c in s["calls"]:
            n = B + carried + (ctx(c) - f) + 2000
            if T and n > T:
                tot += n; cost += n*P["cr"]/1e6 + summary*P["out"]/1e6
                carried = summary - (ctx(c) - f); prev = None; nc += 1
                n = B + carried + (ctx(c) - f) + 2000
            new = n - prev if prev and n > prev else n if prev is None else 0
            cost += (n-new)*P["cr"]/1e6 + new*P["cw"]/1e6 + c["out"]*P["out"]/1e6
            prev = n; tot += n; peak = max(peak, n)
        carried += ctx(s["calls"][-1]) - f + 2000
    return "ctx %5.0fM  est $%6.2f  compactions %2d  peak %4dk" % (tot/1e6, cost, nc, peak//1000)

def run2(key, T):
    for s in ok: s["item_"] = s["item"]; s["item"] = s[key]
    r = run(T=T, at_item=True)
    for s in ok: s["item"] = s["item_"]
    return r
print("sub-items:", len(set(s["item"] for s in ok)), " top items:", len(set(s["top"] for s in ok)))
print("auto at 200k only           ", run(T=200_000))
print("each sub-item (0a,0b..), no auto ", run2("item", None))
print("each sub-item + auto 200k       ", run2("item", 200_000))
print("each top item (0..5), no auto   ", run2("top", None))
print("each top item + auto 200k       ", run2("top", 200_000))
print("each step + auto 200k           ", run(T=200_000, at_step=True))
