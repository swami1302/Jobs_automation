"""Web control panel for the job-swipe pipeline.

    .venv/bin/python -m scripts.panel
    -> open http://localhost:8000  (also reachable from your phone on the same wifi)

Buttons run the pipeline steps; live log streams below; DB counts + top matches
shown at the top. The bot can be started/stopped from here too.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template_string, request

from src import config, models, store

app = Flask(__name__)

_STARTED = time.monotonic()  # for the /health uptime field

# one shared state: the current one-shot action + its log, plus the bot process
_state: dict = {"action": None, "log": "", "proc": None, "bot": None}
_lock = threading.Lock()

ACTIONS = {
    "build_profile": "scripts.build_profile",
    "scrape": "scripts.scrape_jobs",
    "match": "scripts.match_jobs",
    "reset": "scripts.reset_jobs",
}


def _stream(name: str, module: str, extra: list[str]) -> None:
    cmd = [sys.executable, "-m", module, *extra]
    with _lock:
        _state["action"] = name
        _state["log"] = f"$ {' '.join(cmd)}\n"
    proc = subprocess.Popen(
        cmd, cwd=str(config.ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    _state["proc"] = proc
    for line in proc.stdout:
        with _lock:
            _state["log"] += line
    proc.wait()
    with _lock:
        _state["log"] += f"\n--- done (exit {proc.returncode}) ---\n"
        _state["action"] = None
        _state["proc"] = None


def _bot_running() -> bool:
    bot = _state.get("bot")
    return bool(bot and bot.poll() is None)


PAGE = """
<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Job Swipe — Control Panel</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:18px}
 h1{font-size:18px;margin:0 0 12px}
 .cards{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
 .card{background:#1b1f27;border:1px solid #2a2f3a;border-radius:10px;padding:10px 14px;min-width:90px}
 .card b{font-size:22px;display:block}
 .card span{color:#9aa3b2;font-size:12px}
 .btns{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
 button{background:#2a6df4;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-size:14px;cursor:pointer}
 button:disabled{opacity:.5;cursor:not-allowed}
 button.warn{background:#b4452f} button.ok{background:#2f9e57} button.gray{background:#3a4150}
 pre{background:#000;border:1px solid #2a2f3a;border-radius:10px;padding:12px;height:46vh;overflow:auto;white-space:pre-wrap;font-size:12px}
 table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:14px}
 td,th{border-bottom:1px solid #2a2f3a;padding:6px 8px;text-align:left}
 .status{color:#9aa3b2;font-size:13px;margin-left:8px}
</style></head><body>
<h1>🧭 Job Swipe — Control Panel <span class=status id=backend></span></h1>
<div class=cards id=cards></div>
<div class=btns>
 <button onclick="run('build_profile')">📄 Build Profile</button>
 <button onclick="run('scrape')">🔎 Scrape Jobs</button>
 <button onclick="run('match')">🎯 Match &amp; Score</button>
 <button class=warn onclick="if(confirm('Delete ALL jobs?'))run('reset',['--yes'])">🗑 Reset DB</button>
 <button class=ok id=botstart onclick="bot('start')">▶️ Start Bot</button>
 <button class=gray id=botstop onclick="bot('stop')">⏹ Stop Bot</button>
 <span class=status id=running></span>
</div>
<h1 style="font-size:14px">Top matches</h1>
<table id=top><thead><tr><th>Score</th><th>Title</th><th>Company</th><th>Status</th></tr></thead><tbody></tbody></table>
<pre id=log>Ready.</pre>
<script>
async function run(a, extra){ await fetch('/action/'+a,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({extra:extra||[]})}); }
async function bot(x){ await fetch('/bot/'+x,{method:'POST'}); }
async function tick(){
 const s = await (await fetch('/status')).json();
 document.getElementById('backend').textContent = '· '+s.backend;
 document.getElementById('cards').innerHTML = Object.entries(s.counts).map(([k,v])=>`<div class=card><b>${v}</b><span>${k}</span></div>`).join('') || '<div class=card><b>0</b><span>jobs</span></div>';
 document.getElementById('running').textContent = s.action ? ('▶ running: '+s.action) : (s.bot ? '🤖 bot running' : 'idle');
 document.querySelectorAll('.btns button').forEach(b=>{ if(!b.id) b.disabled = !!s.action; });
 document.getElementById('botstart').disabled = s.bot; document.getElementById('botstop').disabled = !s.bot;
 document.querySelector('#top tbody').innerHTML = s.top.map(r=>`<tr><td>${r.match_score??'-'}</td><td>${r.title||''}</td><td>${r.company||''}</td><td>${r.status}</td></tr>`).join('');
 const log = await (await fetch('/log')).text();
 const pre = document.getElementById('log'); const atBottom = pre.scrollTop+pre.clientHeight >= pre.scrollHeight-30;
 pre.textContent = log; if(atBottom) pre.scrollTop = pre.scrollHeight;
}
setInterval(tick, 1200); tick();
</script></body></html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/health")
def health():
    """Liveness probe for uptime pingers (UptimeRobot) + Render's Health Check Path.

    Cheap by default — NO database hit — so a 5-minute keep-alive ping doesn't
    wake Neon or burn its compute. Add ?deep=1 to also verify the DB connection
    (returns 503 if the DB is unreachable).
    """
    payload = {
        "status": "ok",
        "uptime_seconds": round(time.monotonic() - _STARTED, 1),
        "bot": _bot_running(),
    }
    if request.args.get("deep"):
        try:
            payload["backend"] = store.backend()
            payload["jobs"] = sum(store.counts().values())
            payload["db"] = "ok"
        except Exception as e:  # noqa: BLE001
            payload["db"] = f"error: {str(e)[:120]}"
            return jsonify(payload), 503
    return jsonify(payload), 200


@app.get("/status")
def status():
    with _lock:
        action = _state["action"]
    return jsonify(
        backend=store.backend(),
        counts=store.counts(),
        action=action,
        bot=_bot_running(),
        top=[
            {"match_score": r["match_score"], "title": r["title"],
             "company": r["company"], "status": r["status"]}
            for r in store.top_matches(limit=10)
        ],
    )


@app.get("/log")
def log():
    with _lock:
        return _state["log"], 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.post("/action/<name>")
def action(name: str):
    if name not in ACTIONS:
        return jsonify(error="unknown action"), 400
    with _lock:
        if _state["action"]:
            return jsonify(error="busy"), 409
    extra = (request.get_json(silent=True) or {}).get("extra", [])
    threading.Thread(
        target=_stream, args=(name, ACTIONS[name], extra), daemon=True
    ).start()
    return jsonify(ok=True)


@app.post("/bot/start")
def bot_start():
    if _bot_running():
        return jsonify(error="already running"), 409
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.run_bot"], cwd=str(config.ROOT)
    )
    _state["bot"] = proc
    return jsonify(ok=True)


@app.post("/bot/stop")
def bot_stop():
    bot = _state.get("bot")
    if bot and bot.poll() is None:
        bot.terminate()
        try:
            bot.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot.kill()
    _state["bot"] = None
    return jsonify(ok=True)


def main() -> None:
    # Render (and most PaaS) inject $PORT — bind it if present, else local default.
    port = int(config.get("PORT") or config.get("PANEL_PORT", "8000"))
    print(f"Control panel: http://localhost:{port}  (Ctrl-C to stop)")
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
