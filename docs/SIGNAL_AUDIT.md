# Why the scanner almost never signals (audit, 2026-11-11)

Data: `spy_direction_predictions.csv` on the PC (1.16 GB, 428,990 rows, Jun 30 – Sep 25 2026).
Analysed: 126,319 weekday rows in market phases (pre-market and weekends excluded).
Scripts: `tools/signal_audit/`.

## Where signals die

| Stage | Rows with a CALL/PUT candidate |
|---|---|
| `calculate_direction_prediction` (direction survives its own checks) | 9,429 (6,099 CALL / 3,330 PUT) |
| … and strength ≥ 55 | 7,851 (5,162 CALL / 2,689 PUT) |
| reach the A+ filter after stability checks | 5,630 (4,395 CALL / 1,235 PUT) |
| **pass the A+ filter (logged as CALL/PUT)** | **19 (19 CALL / 0 PUT)** |

The bearish path is symmetric in code and does produce PUT candidates; nearly all
candidates are removed by `apply_a_plus_setup_filter`, which every logged prediction must pass.

## Causes, by type

**Implementation defects (not threshold choices)**
1. **Volume is almost never measured.** `last_1m_bid_total` is 0 in 83% of session rows
   (sample of 20,486). `update_rolling_bid_volume` counts the in-progress yfinance bar's
   volume at first sight (≈0) and never sees the finished bar. SPY trades millions of shares
   a minute, so the 200-share threshold can't be the issue. Result: `volume_filter=FAIL` in
   86% of rows, "volume/RVOL below average" blocks 81% of CALL and 86% of PUT candidates,
   and the Volume factor almost never counts.
2. **"Market Regime" factor can never agree.** Regime values are `TRENDING UP`,
   `TRENDING DOWN`, `CHOPPY`, `REVERSAL RISK`; the keyword matcher looks for
   BULLISH/HIGHER/ABOVE/…, so this factor is NEUTRAL in 100% of rows. A+ needs 8 of 11, so
   effectively 8 of the remaining 10.
3. **Weekend rows:** `get_market_phase` doesn't check the weekday — 26,886 rows were logged on
   Saturdays/Sundays as if the market were open.
4. **Yesterday Midpoint** reads the whole 1.16 GB file once a day and uses all rows of the prior
   calendar date (including overnight/weekend rows), not the prior NYSE regular session.
5. **Price freshness:** the price was unchanged from the previous row in 78% of rows (yfinance
   1-minute data). The 2/10/30-second momentum windows mostly see no movement.

**Deliberate strictness (threshold choices — your call)**
- Trade risk "NO TRADE" during *Midday Chop* (11:30–15:00) and after 15:45: blocks 88% of
  CALL and 86% of PUT candidates. Only ~2.3 hours a day are eligible.
- A+ requires strength ≥ 80 (vs 55 in the base model) and 8 of 11 factors.

**Market context:** SPY rose 740 → 772 over the period; price was above VWAP in 63% of rows,
so more CALL than PUT candidates is expected.

## Counter-factual replay (no code changed)

Replaying the A+ filter on the logged rows (the replay reproduces today's 19 rows exactly):

| Scenario | Signals (≥4 min apart) | CALL / PUT |
|---|---|---|
| Current rules | 4 minutes, 2 days | 4 / 0 |
| Fix regime factor only | same | 4 / 0 |
| Fix regime + volume counted* | 11 | 9 / 2 |
| + allow midday | 25 | 20 / 5 |
| + strength ≥ 70, 7 of 11 | 38 | 30 / 8 |

\*Upper bound: assumes volume would confirm whenever measured correctly.

Forward SPY move after those hypothetical signals (same logs, same day):

| Scenario | 5-min hit rate | 5-min avg move | 15-min hit rate | 15-min avg move |
|---|---|---|---|---|
| regime + volume | 55% | +$0.02 | 36% | −$0.06 |
| + midday | 48% | −$0.03 | 36% | −$0.11 |
| + 70 / 7-of-11 | 61% | +$0.04 | 40% | −$0.05 |

Samples are tiny (11–38 signals) and the price data is coarse. **There is no evidence that
loosening thresholds creates an edge.** The evidence supports fixing the measurement defects
first and collecting clean data before touching thresholds.

## Corrections — approved and applied 2026-11-11 (thresholds unchanged)

1. Measure volume from the last *completed* 1-minute bar (and a rolling average for RVOL).
2. Map regime to direction (`TRENDING UP`→CALL, `TRENDING DOWN`→PUT, others neutral).
3. Skip non-trading days in `get_market_phase` (the supervisor already stops the scanner then).
4. Compute Yesterday Midpoint from the previous NYSE regular session only, cached.
Thresholds (55 / 80 / 8-of-11 / midday block) unchanged until ~4 weeks of clean data exist.

Status: items 1–4 implemented on branch `migration/wordpress-pc` (functions
`update_rolling_bid_volume` + `record_last_completed_1m_bar`, `regime_direction`,
`get_market_phase`, `get_yesterday_midpoint_direction`). `tests/logic_unchanged.py`
proves no other function and no threshold constant changed.

Note for a future decision (not changed): with volume now measured correctly, the
existing 200-share minimum will almost always pass for SPY, so the volume check will
rarely block. Requiring above-average (RVOL) volume would be a new threshold and needs
your approval.
