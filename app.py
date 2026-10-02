"""A page for one database workload: its connection details and its backups.

Served behind the Hubble sign-in, so whoever can open the workload in Hubble can see how to connect to it.
Credentials are read from the database's own volume, where they were generated on first start.
"""
import html
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

ENGINES = {
    "mongodb": {"label": "MongoDB", "scheme": "mongodb"},
    "postgres": {"label": "PostgreSQL", "scheme": "postgresql"},
    "mysql": {"label": "MySQL", "scheme": "mysql"},
    "mariadb": {"label": "MariaDB", "scheme": "mysql"},
    "redis": {"label": "Redis", "scheme": "redis"},
    "qdrant": {"label": "Qdrant", "scheme": "http"},
}

BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def config():
    base = os.environ.get("BASE_PATH", "/").strip("/")
    return {
        "engine": os.environ.get("ENGINE", "mongodb"),
        "workload": os.environ.get("WORKLOAD", ""),
        "host": os.environ.get("HOST", ""),
        "port": os.environ.get("PORT", ""),
        "database": os.environ.get("DATABASE", ""),
        "app_user": os.environ.get("APP_USER", ""),
        "admin_user": os.environ.get("ADMIN_USER", ""),
        "credentials": os.environ.get("CREDENTIALS_DIR", "/store/credentials"),
        "backups": os.environ.get("BACKUPS_DIR", "/store/backups"),
        "base": "/" + base + "/" if base else "/",
    }


def read_secret(directory, name):
    try:
        with open(os.path.join(directory, name)) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def connection_strings(cfg):
    """Return (label, user, password, uri) rows for the engine."""
    engine = cfg["engine"]
    scheme = ENGINES.get(engine, {"scheme": engine})["scheme"]
    host, port, db = cfg["host"], cfg["port"], cfg["database"]
    rows = []
    if engine == "qdrant":
        key = read_secret(cfg["credentials"], "api_key")
        rows.append(("API", "", key, "%s://%s:%s" % (scheme, host, port)))
        return rows
    if engine == "redis":
        pw = read_secret(cfg["credentials"], "root_password")
        rows.append(("Application", "default", pw, "redis://default:%s@%s:%s/0" % (quote(pw, safe=""), host, port)))
        return rows
    app_pw = read_secret(cfg["credentials"], "app_password")
    root_pw = read_secret(cfg["credentials"], "root_password")
    if cfg["app_user"]:
        rows.append(("Application", cfg["app_user"], app_pw,
                     "%s://%s:%s@%s:%s/%s" % (scheme, quote(cfg["app_user"], safe=""), quote(app_pw, safe=""), host, port, db)))
    if cfg["admin_user"]:
        suffix = "/?authSource=admin" if engine == "mongodb" else "/%s" % (db if engine == "postgres" else "")
        rows.append(("Administrator", cfg["admin_user"], root_pw,
                     "%s://%s:%s@%s:%s%s" % (scheme, quote(cfg["admin_user"], safe=""), quote(root_pw, safe=""), host, port, suffix)))
    return rows


def backups(cfg):
    try:
        names = os.listdir(cfg["backups"])
    except OSError:
        return []
    items = []
    for name in names:
        path = os.path.join(cfg["backups"], name)
        if BACKUP_NAME.match(name) and os.path.isfile(path) and not os.path.islink(path):
            stat = os.stat(path)
            items.append((name, stat.st_size, stat.st_mtime))
    return sorted(items, key=lambda item: item[2], reverse=True)


def size(num):
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return "%.0f %s" % (num, unit) if unit == "B" else "%.1f %s" % (num, unit)
        num /= 1024.0


STYLE = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#0f172a;--muted:#5b6474;--line:#e3e6ec;--accent:#0f9f8f}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f17;--panel:#121826;--ink:#e8ecf3;--muted:#98a2b3;--line:#232b3b;--accent:#2dd4bf}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:28px 18px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}.sub{color:var(--muted);margin:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:13px;width:160px}
code,input{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
input{width:100%;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
summary{cursor:pointer;color:var(--accent);font-weight:600}a{color:var(--accent)}
.note{color:var(--muted);font-size:13px}
"""


def page(cfg):
    engine = ENGINES.get(cfg["engine"], {"label": cfg["engine"]})["label"]
    esc = html.escape
    rows = []
    for label, user, password, uri in connection_strings(cfg):
        secret_label = "API key" if cfg["engine"] == "qdrant" else "Password"
        user_row = "<tr><th>User</th><td><code>%s</code></td></tr>" % esc(user) if user else ""
        missing = "" if password else "<p class=\"note\">Not generated yet. The database creates it on first start.</p>"
        rows.append(
            "<div class=\"card\"><h2 style=\"margin-top:0\">%s</h2><table>%s"
            "<tr><th>%s</th><td><details><summary>Show</summary><input readonly value=\"%s\"></details>%s</td></tr>"
            "<tr><th>Connection string</th><td><details><summary>Show</summary><input readonly value=\"%s\"></details></td></tr>"
            "</table></div>" % (esc(label), user_row, secret_label, esc(password), missing, esc(uri)))
    files = backups(cfg)
    if files:
        backup_rows = "".join(
            "<tr><td><a href=\"backups/%s\">%s</a></td><td>%s</td><td>%s</td></tr>"
            % (quote(name), esc(name), size(length), time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(mtime)))
            for name, length, mtime in files)
        backup_html = "<div class=\"card\"><table><tr><th>File</th><th>Size</th><th>Taken</th></tr>%s</table></div>" % backup_rows
    else:
        backup_html = "<div class=\"card\"><p class=\"note\">No backups yet.</p></div>"
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · %s</title><style>%s</style></head><body><div class="wrap">
<h1>%s</h1><p class="sub">%s database</p>
<h2>Connect</h2>
<div class="card"><table><tr><th>Host</th><td><code>%s</code></td></tr><tr><th>Port</th><td><code>%s</code></td></tr>%s</table>
<p class="note">Reachable only from inside the cluster, for example from your apps and sessions in this project. It is never exposed to the internet.</p></div>
%s
<h2>Backups</h2>%s
</div></body></html>""" % (
        esc(cfg["workload"]), esc(engine), STYLE, esc(cfg["workload"]), esc(engine), esc(cfg["host"]), esc(cfg["port"]),
        "<tr><th>Database</th><td><code>%s</code></td></tr>" % esc(cfg["database"]) if cfg["database"] else "",
        "".join(rows), backup_html)


class Handler(BaseHTTPRequestHandler):
    server_version = "db-console"
    sys_version = ""

    def log_message(self, fmt, *args):
        return

    def send(self, status, body, content_type="text/plain; charset=utf-8", extra=None):
        payload = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        for key, value in dict(HEADERS, **(extra or {})).items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def route(self):
        cfg = config()
        path = unquote(self.path.split("?", 1)[0])
        base = cfg["base"]
        if path + "/" == base:
            return self.send(308, "", extra={"Location": base})
        if path.startswith(base):
            path = "/" + path[len(base):]
        if path == "/healthz":
            return self.send(200, "ok\n")
        if path == "/":
            return self.send(200, page(cfg), "text/html; charset=utf-8")
        if path.startswith("/backups/"):
            name = path[len("/backups/"):]
            directory = os.path.realpath(cfg["backups"])
            target = os.path.realpath(os.path.join(directory, name))
            if not BACKUP_NAME.match(name) or os.path.dirname(target) != directory or not os.path.isfile(target):
                return self.send(404, "not found\n")
            with open(target, "rb") as handle:
                data = handle.read()
            return self.send(200, data, "application/octet-stream",
                             {"Content-Disposition": "attachment; filename=\"%s\"" % name})
        return self.send(404, "not found\n")

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def do_POST(self):
        self.send(405, "method not allowed\n", extra={"Allow": "GET, HEAD"})

    do_PUT = do_DELETE = do_PATCH = do_POST


def main():
    port = int(os.environ.get("LISTEN_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
