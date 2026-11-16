#!/usr/bin/env python3
"""replay.proxy — a logging Anthropic-API proxy / scripted endpoint for the K1 local smoke (§10.2-3b).

The CLI talks to `ANTHROPIC_BASE_URL`; everything the smoke asserts on the CLIENT side (permission
matching, cache_control TTL selection, rate-limit header handling, budget accounting) is
independent of which model produced the tool call. This proxy sits at that URL and:

* logs every request (method, path, headers minus credentials, JSON body) to `<log>/requests.jsonl`
  and every response head to `<log>/responses.jsonl` — the TTL assertion (item 4) reads
  `cache_control` from the logged bodies;
* `forward` mode: streams the request to `--upstream` (the local Ollama) unchanged;
* `script` mode: answers `/v1/messages` itself from a script — a deterministic "model" that issues
  exactly the tool calls the calibration wants (item 2's exact-command assertion holds by
  construction) at seconds per call instead of minutes;
* injection: `--ratelimit rejected:<epoch>` adds `anthropic-ratelimit-unified-*` headers to every
  messages response, `--status429 <n>` answers the n-th main request with HTTP 429 (every one when n < 0) (item 5).

It binds 127.0.0.1 only and never forwards anywhere but `--upstream` (validated to be loopback).

Script file (JSON): {"turns": [<action>, …], "usage": {...}?, "model": "..."?}
  action = {"tool_use": {"name": "Bash", "input": {...}}}           one tool call, stop_reason tool_use
         | {"tool_uses": [{"name":…, "input":…}, …]}                 parallel calls
         | {"text": "…"}                                            final answer, end_turn
The action for a request is chosen by the number of assistant messages already in its
`messages` (so a `--resume`d conversation continues where it left off). Past the end → the last
action if it is text, else a bare "done" text. Requests that carry no `tools` (CLI side calls)
get a short text answer and are logged with `"side": true`.
"""

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request

# loopback only: never route through an http(s)_proxy from the environment
_NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
import uuid

_LOCK = threading.Lock()
_STRIP = ("authorization", "x-api-key")


def _loopback(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")


def _sse(event, data):
    return ("event: %s\ndata: %s\n\n" % (event, json.dumps(data, separators=(",", ":")))).encode("utf-8")


def sse_message(model, blocks, stop_reason, usage):
    """The SSE byte stream of one assistant message (Anthropic streaming format)."""
    mid = "msg_" + uuid.uuid4().hex[:24]
    u0 = dict(usage)
    u0["output_tokens"] = 1
    out = [_sse("message_start", {"type": "message_start", "message": {
        "id": mid, "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": u0}})]
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            out.append(_sse("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "text", "text": ""}}))
            out.append(_sse("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "text_delta", "text": b["text"]}}))
        else:
            out.append(_sse("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "tool_use", "id": b["id"],
                                                                      "name": b["name"], "input": {}}}))
            out.append(_sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(b["input"], ensure_ascii=False)}}))
        out.append(_sse("content_block_stop", {"type": "content_block_stop", "index": i}))
    out.append(_sse("message_delta", {"type": "message_delta",
                                      "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                      "usage": {"output_tokens": usage.get("output_tokens", 10)}}))
    out.append(_sse("message_stop", {"type": "message_stop"}))
    return b"".join(out)


def json_message(model, blocks, stop_reason, usage):
    content = []
    for b in blocks:
        content.append({"type": "text", "text": b["text"]} if b["type"] == "text"
                       else {"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
    return json.dumps({"id": "msg_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant",
                       "model": model, "content": content, "stop_reason": stop_reason,
                       "stop_sequence": None, "usage": usage}).encode("utf-8")


def choose(script, body):
    """(blocks, stop_reason) for one main request."""
    turns = script.get("turns") or []
    n_asst = sum(1 for m in body.get("messages") or [] if m.get("role") == "assistant")
    act = turns[n_asst] if n_asst < len(turns) else (turns[-1] if turns and "text" in turns[-1]
                                                       else {"text": "done"})
    if "text" in act:
        return [{"type": "text", "text": act["text"]}], "end_turn"
    calls = act.get("tool_uses") or [act["tool_use"]]
    blocks = [{"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20], "name": c["name"],
               "input": c.get("input") or {}} for c in calls]
    return blocks, "tool_use"


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "guild-k1-proxy"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _log(self, name, obj):
        with _LOCK:
            with open(os.path.join(self.server.logdir, name), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code, headers, payload):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _rl_headers(self):
        rl = self.server.ratelimit
        if not rl:
            return []
        status, reset = rl
        return [("anthropic-ratelimit-unified-status", status),
                ("anthropic-ratelimit-unified-reset", str(reset)),
                ("anthropic-ratelimit-unified-5h-status", status),
                ("anthropic-ratelimit-unified-5h-reset", str(reset)),
                ("anthropic-ratelimit-unified-representative-claim", "five_hour"),
                ("anthropic-ratelimit-unified-fallback-percentage", "0.5")]

    def do_HEAD(self):
        self._send(200, [], b"")

    def do_GET(self):
        self._log("requests.jsonl", {"t": time.time(), "method": "GET", "path": self.path})
        self._send(200, [("content-type", "application/json")], b"{}")

    def do_POST(self):
        raw = self._body()
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            body = {"_unparsed": raw[:2000].decode("utf-8", "replace")}
        hdrs = {k.lower(): v for k, v in self.headers.items() if k.lower() not in _STRIP}
        is_messages = urllib.parse.urlparse(self.path).path.endswith("/v1/messages")
        side = is_messages and not body.get("tools")
        with _LOCK:
            self.server.n_main += 0 if side or not is_messages else 1
            n_main = self.server.n_main
        self._log("requests.jsonl", {"t": time.time(), "method": "POST", "path": self.path,
                                     "headers": hdrs, "side": side, "n_main": n_main, "body": body})
        if is_messages and not side and self.server.status429 and (
                n_main == self.server.status429 or self.server.status429 < 0):
            payload = json.dumps({"type": "error", "error": {"type": "rate_limit_error",
                                                             "message": "Rate limited (injected)"}}).encode()
            hs = [("content-type", "application/json"), ("retry-after", "1")] + self._rl_headers()
            self._log("responses.jsonl", {"t": time.time(), "code": 429, "headers": hs})
            return self._send(429, hs, payload)
        if self.server.mode == "script" or (side and self.server.mode == "script-side"):
            return self._scripted(body, side, is_messages)
        return self._forward(raw)

    def _scripted(self, body, side, is_messages):
        model = self.server.script.get("model") or body.get("model") or "model"
        usage = dict(self.server.script.get("usage") or {
            "input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0})
        if not is_messages:
            # count_tokens and friends
            return self._send(200, [("content-type", "application/json")],
                              json.dumps({"input_tokens": 100}).encode())
        if side:
            blocks, stop = [{"type": "text", "text": "ok"}], "end_turn"
        else:
            blocks, stop = choose(self.server.script, body)
        hs = [("content-type", "text/event-stream" if body.get("stream") else "application/json"),
              ("request-id", "req_" + uuid.uuid4().hex[:16])] + self._rl_headers()
        payload = (sse_message if body.get("stream") else json_message)(model, blocks, stop, usage)
        self._log("responses.jsonl", {"t": time.time(), "code": 200, "headers": hs, "side": side,
                                      "blocks": blocks, "stop_reason": stop})
        return self._send(200, hs, payload)

    def _forward(self, raw):
        url = self.server.upstream.rstrip("/") + self.path
        req = urllib.request.Request(url, data=raw, method="POST")
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length", "connection", "accept-encoding"):
                req.add_header(k, v)
        try:
            resp = _NOPROXY.open(req, timeout=1800)
            code, rh = resp.status, list(resp.getheaders())
        except urllib.error.HTTPError as e:
            resp, code, rh = e, e.code, list(e.headers.items())
        rh = [(k, v) for k, v in rh if k.lower() not in ("content-length", "transfer-encoding",
                                                         "connection")] + self._rl_headers()
        self._log("responses.jsonl", {"t": time.time(), "code": code, "headers": rh})
        self.send_response(code)
        for k, v in rh:
            self.send_header(k, v)
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        while True:
            chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
            if not chunk:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port, logdir, mode="forward", upstream="http://127.0.0.1:11434", script=None,
                ratelimit=None, status429=0):
    if mode == "forward" and not _loopback(upstream):
        raise SystemExit("proxy: upstream must be a loopback address (%s)" % upstream)
    os.makedirs(logdir, exist_ok=True)
    srv = Server(("127.0.0.1", port), Handler)
    srv.logdir, srv.mode, srv.upstream = logdir, mode, upstream
    srv.script = script or {}
    srv.ratelimit = ratelimit
    srv.status429 = status429
    srv.n_main = 0
    return srv


def serve_background(**kw):
    """Start a proxy on a free port in a daemon thread; returns (server, base_url)."""
    srv = make_server(kw.pop("port", 0), **kw)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--log", required=True)
    ap.add_argument("--mode", choices=("forward", "script", "script-side"), default="forward")
    ap.add_argument("--upstream", default="http://127.0.0.1:11434")
    ap.add_argument("--script")
    ap.add_argument("--ratelimit", help="status:resetEpoch, e.g. rejected:1790000000")
    ap.add_argument("--status429", type=int, default=0)
    a = ap.parse_args(argv)
    script = json.load(open(a.script)) if a.script else None
    rl = None
    if a.ratelimit:
        s, r = a.ratelimit.split(":", 1)
        rl = (s, int(r))
    srv = make_server(a.port, a.log, a.mode, a.upstream, script, rl, a.status429)
    sys.stdout.write("http://127.0.0.1:%d\n" % srv.server_address[1])
    sys.stdout.flush()
    srv.serve_forever()


if __name__ == "__main__":
    main()
