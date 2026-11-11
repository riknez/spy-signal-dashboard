import os, subprocess, sys, time, urllib.request, urllib.error, socket, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def start(env_extra):
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "spy_dashboard.py"), tmp)   # no .env next to it
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {k: v for k, v in os.environ.items() if k not in ("SPY_DASHBOARD_PASSWORD", "DASHBOARD_UPDATE_TOKEN")}
    env.update(PORT=str(port), DASHBOARD_HOST="127.0.0.1", **env_extra)
    p = subprocess.Popen([sys.executable, "spy_dashboard.py"], cwd=tmp, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1); break
        except Exception:
            time.sleep(0.1)
    return p, port


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


def post(port, path, data, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers or {}, method="POST")
    try:
        return urllib.request.build_opener(NoRedirect).open(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_login_and_push_rules():
    for pw, expect in [("", 503), ("scanner2026", 503), ("short", 503), ("a-strong-new-pass-2026", 303)]:
        p, port = start({"SPY_DASHBOARD_PASSWORD": pw} if pw else {})
        try:
            assert post(port, "/login", f"password={pw}".encode()) == expect, pw
            if expect == 303:
                assert post(port, "/login", b"password=wrong-guess-123") == 401
            assert post(port, "/api/push-status", b"{}", {"Content-Type": "application/json"}) == 503
        finally:
            p.terminate(); p.wait()
    p, port = start({"DASHBOARD_UPDATE_TOKEN": "tok-123456789"})
    try:
        assert post(port, "/api/push-status", b"{}", {"X-Dashboard-Token": "nope"}) == 401
    finally:
        p.terminate(); p.wait()
