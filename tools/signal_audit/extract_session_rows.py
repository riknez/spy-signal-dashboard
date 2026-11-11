import csv, sys, time
csv.field_size_limit(10**9)
P, start, end, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
keep = ["time","spy_price","prediction","confidence","reason","trend_score","momentum_score","engine_score","breadth_score","volume_activity_score","candle_indecision","regime","vwap_position","opening_range_position","market_structure","current_advantage","mtf_overall_signal","volume_filter","activity_filter","market_phase","a_plus_setup","a_plus_wait_reason","mode_stability","last_3_candle_reading","confluence_score","bullish_confluence_score","bearish_confluence_score","confluence_factors","total_confidence","vwap_confirmation","previous_prediction"]
t=time.time()
with open(P,"rb") as fh:
    header = fh.readline().decode("utf-8-sig").strip("\r\n")
    cols = next(csv.reader([header])); idx=[cols.index(k) for k in keep]
    fh.seek(start)
    if start>0: fh.readline()
    w=csv.writer(open(out,"w",newline="")); w.writerow(keep); n=0
    while fh.tell() < end:
        line = fh.readline()
        if not line: break
        try: row = next(csv.reader([line.decode("utf-8","replace")]))
        except Exception: continue
        if len(row) < len(cols): continue
        if row[cols.index("market_phase")] in ("Market Closed",): continue
        w.writerow([row[i] for i in idx]); n+=1
print(n, round(time.time()-t,1))
