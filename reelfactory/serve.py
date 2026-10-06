"""Minimal HTTP status/dashboard server for a deployed ReelFactory job dir.

Stdlib only. Serves:
  GET /          -> job state JSON
  GET /report    -> report.json
  GET /videos    -> list of rendered final_*.mp4
  GET /video/<n> -> stream a rendered video
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "4050"))
JOB_DIR = os.environ.get("REELFACTORY_DIR", ".")
# Default to loopback-only: this server ships with no TLS and no rate
# limiting. Set REELFACTORY_HOST=0.0.0.0 explicitly to expose it, and set
# REELFACTORY_TOKEN to require a bearer token on every request when you do.
HOST = os.environ.get("REELFACTORY_HOST", "127.0.0.1")
AUTH_TOKEN = os.environ.get("REELFACTORY_TOKEN")


def _rf(*parts):
    return os.path.join(JOB_DIR, *parts)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "reelfactory/0.1"

    def _json(self, obj, code=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._json({"error": "not found"}, 404)

    def _authorized(self):
        if not AUTH_TOKEN:
            return True
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {AUTH_TOKEN}"

    def do_GET(self):
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            state = _read_json(_rf("output", ".reelfactory", "state.json"))
            vids = self._videos()
            self._json({
                "service": "reelfactory",
                "version": "0.1.0",
                "job_dir": os.path.abspath(JOB_DIR),
                "state": state or {"status": "never run"},
                "videos": [v["name"] for v in vids],
            })
        elif path == "/report":
            report = _read_json(_rf("output", ".reelfactory", "report.json"))
            self._json(report) if report else self._not_found()
        elif path == "/videos":
            self._json({"videos": self._videos()})
        elif path.startswith("/video/"):
            name = os.path.basename(path[len("/video/"):])
            fp = _rf("output", name)
            if not os.path.isfile(fp):
                return self._not_found()
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self._not_found()

    def _videos(self):
        out = _rf("output")
        if not os.path.isdir(out):
            return []
        vids = []
        for n in sorted(os.listdir(out)):
            if n.startswith("final_") and n.endswith(".mp4"):
                p = os.path.join(out, n)
                vids.append({"name": n, "size": os.path.getsize(p),
                             "url": f"/video/{n}"})
        return vids

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] " + fmt % args + "\n")


def main():
    os.makedirs(_rf("output"), exist_ok=True)
    if HOST not in ("127.0.0.1", "localhost") and not AUTH_TOKEN:
        print("WARNING: REELFACTORY_HOST is non-local and REELFACTORY_TOKEN is unset; "
              "this server has no authentication. Set REELFACTORY_TOKEN.", file=sys.stderr)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"reelfactory status server on http://{HOST}:{PORT} (dir={os.path.abspath(JOB_DIR)})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
