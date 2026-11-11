"""Prove which top-level functions changed between the original scanner
(git tag audit-baseline-2026-11-11) and the working copy, by AST comparison
with timestamp-helper calls normalised."""
import ast, subprocess, sys
orig = subprocess.run(["git", "show", "audit-baseline-2026-11-11:spy_options_alert_scanner.py"],
                      capture_output=True, text=True, check=True).stdout
new = open("spy_options_alert_scanner.py", encoding="utf-8").read()

def funcs(src, normalise):
    if normalise:
        src = src.replace('def eastern_strftime(', 'def _eastern_helper(').replace('eastern_strftime(', 'time.strftime(').replace(
            'time.strftime("%Y-%m-%d")', 'datetime.now().strftime("%Y-%m-%d")')
    tree = ast.parse(src)
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}

a, b = funcs(orig, False), funcs(new, True)
changed = sorted(k for k in a if k in b and a[k] != b[k])
added = sorted(set(b) - set(a)); removed = sorted(set(a) - set(b))
print("functions compared:", len(a))
print("changed:", changed or "none")
print("added:", added); print("removed:", removed or "none")
signal_funcs = ["calculate_direction_prediction", "apply_a_plus_setup_filter", "apply_signal_stability",
                "analyze_completed_candles", "classify_market_structure", "build_multi_timeframe_analysis",
                "calculate_support_resistance", "detect_reversal_state", "detect_scanner_regime",
                "get_spy_snapshot", "update_rolling_bid_volume", "track_alert_result", "get_result_label"]
bad = [f for f in signal_funcs if f in changed]
print("signal/result functions changed:", bad or "NONE")
sys.exit(1 if bad or removed else 0)
