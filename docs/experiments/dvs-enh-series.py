# Writes slides/dvs-enh-series.json (chart data for slides/efficiency_deck.js). Run from the repo root.
exec(open("docs/experiments/dvs-enh-monolithic.py").read().split("ws = sum")[0])
import json
def cum_wp():
    out, t = [], 0
    for s in ok:
        t += sum(price(c) for c in s["calls"]); out.append(round(t, 2))
    return out
def cum_mono(T, summary=20000, B=base):
    carried, cost, prev, out = 0, 0.0, None, []
    for s in ok:
        f = ctx(s["calls"][0])
        for c in s["calls"]:
            n = B + carried + (ctx(c) - f) + 2000
            if n > T:
                cost += n*P["cr"]/1e6 + summary*P["out"]/1e6
                carried = summary - (ctx(c) - f); prev = None
                n = B + carried + (ctx(c) - f) + 2000
            new = n - prev if prev and n > prev else n if prev is None else 0
            cost += (n-new)*P["cr"]/1e6 + new*P["cw"]/1e6 + c["out"]*P["out"]/1e6; prev = n
        carried += ctx(s["calls"][-1]) - f + 2000
        out.append(round(cost, 2))
    return out
# per-call context, for a sawtooth chart: sample every call
def wp_ctx(): return [ctx(c) for s in ok for c in s["calls"]]
def mono_ctx(T, summary=20000, B=base):
    carried, out = 0, []
    for s in ok:
        f = ctx(s["calls"][0])
        for c in s["calls"]:
            n = B + carried + (ctx(c) - f) + 2000
            if n > T: carried = summary - (ctx(c) - f); n = B + carried + (ctx(c) - f) + 2000
            out.append(n)
        carried += ctx(s["calls"][-1]) - f + 2000
    return out
json.dump(dict(wp=cum_wp(), m200=cum_mono(200000), m900=cum_mono(900000),
    ctx_wp=wp_ctx(), ctx_m200=mono_ctx(200000), ctx_m900=mono_ctx(900000)), open("slides/dvs-enh-series.json", "w"))
print(cum_wp()[-1], cum_mono(200000)[-1], cum_mono(900000)[-1], len(wp_ctx()))
