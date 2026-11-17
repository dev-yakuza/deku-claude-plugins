"""guildcore.checks.netproxy — a host-allowlist HTTP(S) proxy for the engine's deps step.

`sandbox-exec` profiles cannot name domains, so the deps step (pub get, native-assets warm-up,
npm ci) runs with outbound network limited to loopback and `HTTPS_PROXY`/`HTTP_PROXY` pointing
here: CONNECT (and absolute-URI GET) succeed only for allowlisted hosts, everything else gets
403. Every request is logged (host, port, allowed) so the measured need is on record.
"""

import http.server
import json
import select
import socket
import socketserver
import threading
import time
import urllib.parse


class _H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _allowed(self, host, port=443):
        """EXACT host and port 443 only (K2r2-M1: a suffix match let api./uploads./gist.github.com
        and any *.storage.googleapis.com bucket through)."""
        h = (host or "").lower().rstrip(".")
        return port == 443 and h in self.server.allow

    def _log(self, host, port, ok):
        self.server.log.append({"t": time.time(), "host": host, "port": port, "allowed": ok,
                                "method": self.command})

    def do_CONNECT(self):
        host, _, port = self.path.partition(":")
        port = int(port or 443)
        ok = self._allowed(host, port)
        self._log(host, port, ok)
        if not ok:
            self.send_response(403, "host not allowed")
            self.send_header("content-length", "0")
            self.end_headers()
            return
        try:
            up = socket.create_connection((host, port), timeout=30)
        except OSError:
            self.send_response(502)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        conns = [self.connection, up]
        try:
            while True:
                r, _, x = select.select(conns, [], conns, 60)
                if x or not r:
                    break
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    (up if s is self.connection else self.connection).sendall(data)
        finally:
            up.close()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        ok = False                      # plain-HTTP absolute GETs are never proxied
        self._log(u.hostname, u.port or 80, ok)
        self.send_response(403 if not ok else 501)
        self.send_header("content-length", "0")
        self.end_headers()


class _S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class AllowlistProxy(object):
    def __init__(self, allow):
        self.srv = _S(("127.0.0.1", 0), _H)
        self.srv.allow = [a.lower() for a in allow]
        self.srv.log = []
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.th.start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown()

    @property
    def log(self):
        return list(self.srv.log)

    def env(self):
        return {"HTTPS_PROXY": self.url, "HTTP_PROXY": self.url, "https_proxy": self.url,
                "http_proxy": self.url, "NO_PROXY": "localhost,127.0.0.1,::1",
                "no_proxy": "localhost,127.0.0.1,::1"}

    def summary(self):
        out = {}
        for e in self.srv.log:
            k = "%s:%s %s" % (e["host"], e["port"], "allowed" if e["allowed"] else "DENIED")
            out[k] = out.get(k, 0) + 1
        return out
