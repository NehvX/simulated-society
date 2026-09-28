"""Show every result on localhost automatically.

After a run or a study, Civitas rebuilds out/index.html (a page listing every
dashboard, report and log in the output folder), starts a small local web
server and opens the right page in your browser. Nothing needs typing.
"""
from __future__ import annotations

import functools
import html
import os
import socket
import threading
import time
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SECTIONS = [
    ("Dashboards (one simulation each)", lambda p: p.startswith("civitas_") and p.endswith(".html")),
    ("Study reports", lambda p: p.endswith("_report.html")),
    ("Text reports and logs", lambda p: p.endswith((".txt", ".md"))),
    ("Data", lambda p: p.endswith((".csv", ".json"))),
]


def build_index(out_dir: str) -> str:
    files = []
    for root, _, names in os.walk(out_dir):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), out_dir).replace(os.sep, "/")
            if rel != "index.html" and not rel.endswith(".pkl"):
                files.append((os.path.getmtime(os.path.join(root, name)), rel))
    files.sort(reverse=True)
    blocks = []
    for title, match in SECTIONS:
        rows = [f'<li><a href="{html.escape(rel)}">{html.escape(rel)}</a>'
                f'<span>{datetime.fromtimestamp(t):%d %b %Y, %H:%M}</span></li>'
                for t, rel in files if match(os.path.basename(rel))]
        if rows:
            blocks.append(f"<section><h2>{title}</h2><ul>{''.join(rows)}</ul></section>")
    page = INDEX.replace("__BODY__", "".join(blocks) or "<p>No results yet. Run a simulation first.</p>")
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path


def _free_port(start: int = 8765) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):          # keep the terminal clean
        pass


def serve(out_dir: str = "out", page: str = "index.html", block: bool = True):
    """Serve `out_dir` on localhost and open `page` in the browser. With block,
    keep serving until Enter or Ctrl+C; otherwise return the server (stop it with hold())."""
    os.makedirs(out_dir, exist_ok=True)
    build_index(out_dir)
    handler = functools.partial(_Quiet, directory=os.path.abspath(out_dir))
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    url = f"http://localhost:{server.server_address[1]}/{page.replace(os.sep, '/')}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"\nResults are live at {url}")
    print(f"All results: http://localhost:{server.server_address[1]}/index.html")
    webbrowser.open(url)
    if block:
        hold(server)
    return server


def hold(server) -> None:
    """Keep the local server running until the user presses Enter or Ctrl+C."""
    try:
        input("\nThe results stay on localhost until you press Enter (or Ctrl+C) here...\n")
    except EOFError:                        # no keyboard attached: wait for Ctrl+C
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except KeyboardInterrupt:
        pass
    server.shutdown()


INDEX = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Civitas results</title>
<style>
:root { color-scheme: light; --page:#f3f5f8; --surface:#fcfdfe; --ink:#0f141a; --ink-2:#4a5360; --accent:#1f5fa8; --line:#e1e5ea; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --page:#0d1015; --surface:#151a21; --ink:#f1f4f8;
  --ink-2:#b9c1cc; --accent:#6aa6ea; --line:#262d36; } }
body { margin:0; background:var(--page); color:var(--ink); font:15px/1.5 system-ui, "Segoe UI", sans-serif; padding:0 16px 40px; }
main { max-width: 860px; margin: 0 auto; }
h1 { font-size: 40px; letter-spacing: .08em; margin: 28px 0 4px; }
header p { color: var(--ink-2); margin: 0 0 20px; }
section { background: var(--surface); border: 1px solid var(--line); padding: 14px 18px; margin-bottom: 16px; }
h2 { font-size: 15px; margin: 0 0 8px; }
ul { list-style: none; margin: 0; padding: 0; }
li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-top: 1px solid var(--line); flex-wrap: wrap; }
li:first-child { border-top: 0; }
a { color: var(--accent); word-break: break-all; }
li span { color: var(--ink-2); font-size: 13px; }
</style></head><body><main>
<header><h1>CIVITAS</h1><p>Every result in the output folder, newest first.
Charts load Chart.js from the internet, so stay online.</p></header>
__BODY__
</main></body></html>
"""
