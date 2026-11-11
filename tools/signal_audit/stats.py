"""Where do CALL/PUT candidates get blocked? Reads session.csv. Read-only."""
import collections, re
import pandas as pd

d = pd.read_csv("session.csv", dtype=str, keep_default_na=False)
d["ts"] = pd.to_datetime(d.time, format="%Y-%m-%d %H:%M:%S", errors="coerce")
s = d[(d.ts.dt.dayofweek < 5) & (d.market_phase != "Pre-Market Analysis")].copy()
print("rows", len(s), "predictions", s.prediction.value_counts().to_dict())
for c in ["vwap_position", "opening_range_position", "regime", "volume_filter", "market_phase", "a_plus_setup"]:
    print(c, s[c].value_counts().to_dict())
s["cand"] = s.reason.str.extract(r"(CALL|PUT) evidence")[0].fillna("")
s["conf"] = pd.to_numeric(s.total_confidence, errors="coerce")
print("direction survives base model:", s.cand.value_counts().to_dict())
reach = s[~s.a_plus_wait_reason.str.contains("no confirmed CALL or PUT candidate")]
for side in ("CALL", "PUT"):
    x = reach[reach.cand == side]
    blockers = collections.Counter(re.sub(r"only \d+ of", "only N of", b) for r in x.a_plus_wait_reason for b in r.split("; "))
    print(side, "reaching A+ filter:", len(x), dict(blockers.most_common(8)))
f = collections.defaultdict(collections.Counter)
for r in s.confluence_factors:
    for kv in r.split("; "):
        if "=" in kv:
            k, v = kv.split("=", 1)
            f[k][v] += 1
for k, v in f.items():
    print("factor", k, dict(v))
print("price unchanged vs previous row %:", round((s.spy_price == s.spy_price.shift()).mean() * 100, 1))
