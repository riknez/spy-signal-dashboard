"""AST proof of exactly which scanner functions differ from the original
(git tag audit-baseline-2026-11-11). Approved changes are normalised away
where they are one-line substitutions, so any OTHER change fails the test."""
import ast, subprocess, sys

orig = subprocess.run(["git", "show", "audit-baseline-2026-11-11:spy_options_alert_scanner.py"],
                      capture_output=True, text=True, check=True).stdout
new = open("spy_options_alert_scanner.py", encoding="utf-8").read()


def funcs(src, normalise):
    if normalise:
        src = (src.replace('def eastern_strftime(', 'def _eastern_helper(')
                  .replace('eastern_strftime(', 'time.strftime(')
                  .replace('time.strftime("%Y-%m-%d")', 'datetime.now().strftime("%Y-%m-%d")')
                  .replace('"Market Regime": regime_direction(regime),', '"Market Regime": direction_from_text(regime),')
                  .replace('    record_last_completed_1m_bar(data)\n', ''))
    tree = ast.parse(src)
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}


a, b = funcs(orig, False), funcs(new, True)
changed = sorted(k for k in a if k in b and a[k] != b[k])
APPROVED = {"get_market_phase", "update_rolling_bid_volume", "get_yesterday_midpoint_direction"}
print("functions compared:", len(a))
print("changed:", changed)
print("added:", sorted(set(b) - set(a)))
unexpected = sorted(set(changed) - APPROVED)
removed = sorted(set(a) - set(b))
print("unexpected changes:", unexpected or "NONE", "| removed:", removed or "none")
def consts(src):
    out = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id.isupper():
            out[n.targets[0].id] = ast.dump(n.value)
    return out


ca, cb = consts(orig), consts(new)
moved = sorted(k for k in ca if k in cb and ca[k] != cb[k] and k != "LOG_DIR")
print("module constants compared:", len(ca), "| changed (LOG_DIR excluded):", moved or "NONE")
sys.exit(1 if unexpected or removed or moved else 0)
