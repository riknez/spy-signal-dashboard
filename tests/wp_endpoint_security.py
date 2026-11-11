"""Security checks against a WordPress install running the plugin.
Usage: ARGUS_SPY_INGEST_URL=... ARGUS_SPY_INGEST_SECRET=... WP_BASE=... python tests/wp_endpoint_security.py
Needs users: admin/staging-admin-pass (administrator), viewer/viewer-pass (subscriber)."""
import http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker"))
import wp_push as w

BASE = os.environ["WP_BASE"]; URL = os.environ["ARGUS_SPY_INGEST_URL"]; SECRET = os.environ["ARGUS_SPY_INGEST_SECRET"]
API = BASE + "/wp-json/argus-spy/v1/"
results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, "->", got, "" if ok else f"(expected {want})")


def code(req, opener=None):
    try:
        return (opener or urllib.request.build_opener()).open(req, timeout=15).status
    except urllib.error.HTTPError as e:
        return e.code


def signed(body: bytes, ts=None, secret=SECRET):
    ts = str(ts if ts is not None else int(time.time()))
    return urllib.request.Request(URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Argus-Spy-Timestamp": ts, "X-Argus-Spy-Signature": w.sign(secret, ts, body)})


payload = w.build_payload(); body = json.dumps(payload).encode()
check("valid signed push", code(signed(body)), 200)
check("same push again (idempotent)", code(signed(body)), 200)
check("unsigned push", code(urllib.request.Request(URL, data=body, method="POST", headers={"Content-Type": "application/json"})), 401)
check("wrong secret", code(signed(body, secret="x" * 48)), 401)
check("expired timestamp (-10 min)", code(signed(body, ts=int(time.time()) - 600)), 401)
check("future timestamp (+10 min)", code(signed(body, ts=int(time.time()) + 600)), 401)
ts = str(int(time.time())); sig = w.sign(SECRET, ts, body)
check("tampered body, original signature", code(urllib.request.Request(URL, data=body.replace(b'"WAIT"', b'"CALL"', 1), method="POST", headers={"Content-Type": "application/json", "X-Argus-Spy-Timestamp": ts, "X-Argus-Spy-Signature": sig})), 401)
check("replayed older signed message", code(signed(body, ts=int(time.time()) - 60)), 409)
check("oversized body (600 KB)", code(signed(b'{"schema":1,"pad":"' + b"x" * 600000 + b'"}')), 413)
check("signed but wrong schema", code(signed(json.dumps({"schema": 2}).encode())), 400)
check("GET on ingest", code(urllib.request.Request(URL, method="GET")), 404)

for path in ("status", "sessions", "signals", "journal", "session?date=2026-11-11"):
    check(f"anonymous GET {path}", code(API + path), 401)


def login(user, pw):
    jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(BASE + "/wp-login.php", timeout=15)
    op.open(urllib.request.Request(BASE + "/wp-login.php", data=urllib.parse.urlencode({"log": user, "pwd": pw, "wp-submit": "Log In", "testcookie": "1"}).encode()), timeout=15)
    html = op.open(BASE + "/wp-admin/admin-ajax.php?action=rest-nonce", timeout=15).read().decode()
    return op, html.strip()


op, nonce = login("viewer", "viewer-pass")
check("subscriber GET status without nonce", code(urllib.request.Request(API + "status"), op), 401)
check("subscriber GET status with nonce", code(urllib.request.Request(API + "status", headers={"X-WP-Nonce": nonce}), op), 403)
check("subscriber POST journal with nonce", code(urllib.request.Request(API + "journal", data=b'{"notes":"x"}', method="POST", headers={"X-WP-Nonce": nonce, "Content-Type": "application/json"}), op), 403)
page = op.open(BASE + "/spy/", timeout=15).read().decode()
check("subscriber page shows no data/config", ("argus-spy-app" in page) or ("data-config" in page), False)

op, nonce = login("admin", "staging-admin-pass")
check("admin GET status without nonce (CSRF guard)", code(urllib.request.Request(API + "status"), op), 401)
check("admin GET status with nonce", code(urllib.request.Request(API + "status", headers={"X-WP-Nonce": nonce}), op), 200)
data = json.loads(op.open(urllib.request.Request(API + "status", headers={"X-WP-Nonce": nonce}), timeout=15).read())
check("no secret in status response", SECRET in json.dumps(data), False)
page = op.open(BASE + "/spy/", timeout=15).read().decode()
check("no secret in page HTML", SECRET in page, False)
check("admin cannot delete another user's journal entry", code(urllib.request.Request(API + "journal/999999", method="DELETE", headers={"X-WP-Nonce": nonce}), op), 404)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
