"""Replay the A+ filter on logged rows with hypothetical fixes and measure
SPY's forward move after each hypothetical signal. Read-only."""
import numpy as np
import pandas as pd

d = pd.read_csv("session.csv", dtype=str, keep_default_na=False)
d["ts"] = pd.to_datetime(d.time, format="%Y-%m-%d %H:%M:%S", errors="coerce")
d["px"] = pd.to_numeric(d.spy_price, errors="coerce")
d = d.dropna(subset=["ts", "px"]).sort_values("ts")
s = d[(d.ts.dt.dayofweek < 5) & (d.market_phase != "Pre-Market Analysis")].copy()
s["cand"] = s.reason.str.extract(r"(CALL|PUT) evidence")[0]
s = s[s.cand.notna() & ~s.a_plus_wait_reason.str.contains("no confirmed CALL or PUT candidate")].copy()
s["conf"] = pd.to_numeric(s.total_confidence, errors="coerce")
s["F"] = s.confluence_factors.map(lambda r: dict(kv.split("=", 1) for kv in r.split("; ") if "=" in kv))
px = d.set_index("ts").px


def fwd(t, mins):
    j = px.index.searchsorted(t + pd.Timedelta(minutes=mins))
    if j >= len(px) or px.index[j].date() != t.date():
        return np.nan
    return px.iloc[j]


def run(name, allow_midday, conf_min, need):
    keep = []
    for _, r in s.iterrows():
        c = r.cand
        f = dict(r.F)
        f["Market Regime"] = {"TRENDING UP": "CALL", "TRENDING DOWN": "PUT"}.get(r.regime, "NEUTRAL")
        f["Volume/RVOL"] = c  # upper bound: volume always confirms
        tod = r.ts.hour * 60 + r.ts.minute
        nt = r.regime == "CHOPPY" or r.mode_stability == "LOW" or tod >= 945 or (r.market_phase == "Midday Chop" and not allow_midday)
        f["Time of Day Risk"] = c if (not nt and r.market_phase != "Caution Window") else "NEUTRAL"
        sc = sum(v == c for v in f.values())
        if (nt or r.conf < conf_min or r.vwap_confirmation != "PASS" or f.get("VWAP") != c
                or f.get("Trend Box") not in (c, "NEUTRAL") or f.get("Market Breadth") not in (c, "NEUTRAL") or sc < need):
            continue
        keep.append(r)
    k = pd.DataFrame(keep)
    if k.empty:
        print(name, "none")
        return
    k["m"] = k.ts.dt.floor("min")
    k = k.drop_duplicates("m")
    out, last = [], None
    for _, r in k.iterrows():  # one signal per 4 minutes, like the live alert spacing
        if last is None or (r.ts - last).total_seconds() >= 240:
            out.append(r)
            last = r.ts
    k = pd.DataFrame(out)
    sign = np.where(k.cand == "CALL", 1, -1)
    res = {"signals": len(k), "CALL": int((k.cand == "CALL").sum()), "PUT": int((k.cand == "PUT").sum())}
    for m in (2, 5, 15):
        mv = (k.ts.map(lambda t: fwd(t, m)) - k.px) * sign
        res[f"{m}m_avg$"] = round(mv.mean(), 3)
        res[f"{m}m_hit%"] = round((mv > 0).mean() * 100, 1)
    print(name, res)


run("A regime+volume (current thresholds)", False, 80, 8)
run("B +midday allowed", True, 80, 8)
run("C +conf>=70, 7/11", True, 70, 7)
