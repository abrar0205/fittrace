"""Serve a built Pages site the way GitHub Pages does: static files, and 404.html (status 404) for unknown paths.

    python scripts/pages_server.py SITE_ROOT [PORT]     # SITE_ROOT contains fittrace/index.html
"""
import http.server
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "site"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9000

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def send_error(self, code, message=None, explain=None):
        if code == 404:
            with open(os.path.join(ROOT, "fittrace", "404.html"), "rb") as f:
                body = f.read()
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().send_error(code, message, explain)
http.server.ThreadingHTTPServer(("", PORT), H).serve_forever()
