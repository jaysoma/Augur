"""serve.py â€” Augur live UI. Serves tree.html and streams the crawl to the browser as
Server-Sent Events: one event per page as it's fetched + classified, so the tree draws
itself a node at a time.

  python serve.py                 # http://localhost:7000  (UI talks only to this server)

Config: AUGUR_UI_PORT (default 7000). Crawl target is chosen in the page (default :3000).
The model/oracle settings come from model_layer.py (TESTER_MODEL / TESTER_OLLAMA / TESTER_STUB).
"""
import os, sys, re, json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import requests
from model_layer import analyze_page, MODEL, STUB

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("AUGUR_UI_PORT", 7000))
ORACLE = "STUB" if STUB else MODEL

# Reverse-proxy the model-generated store (genserver, :3000) under a path, so the whole app is
# reachable through this single server -- e.g. behind one ngrok tunnel. Browse it at /gen/.
GEN_BASE     = os.environ.get("AUGUR_GEN_BASE", "http://localhost:3000").rstrip("/")
PROXY_PREFIX = os.environ.get("AUGUR_GEN_PREFIX", "/gen")


def _log(msg):
    print(msg, file=sys.stderr, flush=True)   # progress to the terminal so you can see liveness


def _node_id(method, url, fields):
    # GET pages key by url; form submits are distinct states, keyed by method+url+fieldset
    if method == "GET":
        return "GET " + url
    return "POST " + url + "#" + "|".join(sorted((fields or {}).keys()))


def crawl_events(base, max_pages=int(os.environ.get("AUGUR_MAX_PAGES", 120))):
    """Agentic BFS: the model trawls each page for interactive elements, then we INTERACT
    with each (follow links, submit forms). The model-backend generates whatever response an
    interaction needs. Parent = first discoverer, so edges form a tree. Ends with 'done'."""
    base = base.rstrip("/") or base
    host = urlparse(base).netloc
    sess = requests.Session()
    seen = set()
    # queue items: (node_id, url, method, fields, parent_id, depth, via)
    root = base
    queue = [(_node_id("GET", root, {}), root, "GET", {}, "", 0, "root")]
    idx = 0
    t_start = time.time()
    _log("crawl start -> %s   (oracle: %s, max %d pages)" % (base, ORACLE, max_pages))
    yield {"event": "start", "target": base, "oracle": ORACLE, "max_pages": max_pages}

    while queue and len(seen) < max_pages:
        nid, url, method, fields, parent, depth, via = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid); idx += 1

        # announce BEFORE the (potentially slow) fetch so the UI/terminal shows what we're waiting on
        _log("[%3d] fetching %-4s %s" % (idx, method, url))
        yield {"event": "log", "msg": "fetching %s %s" % (method, url), "index": idx}

        t0 = time.time()
        try:
            if method == "GET":
                resp = sess.get(url, timeout=120, allow_redirects=True)
            else:
                resp = sess.post(url, data=fields, timeout=120, allow_redirects=True)
            html = resp.text
        except Exception as e:
            _log("[%3d] ERROR    %s   %s" % (idx, url, str(e)[:120]))
            yield {"event": "node", "index": idx, "id": nid, "url": url, "parent": parent,
                   "depth": depth, "via": via, "type": "error", "summary": str(e)[:80],
                   "fetch_ms": 0, "model_ms": 0, "elements": 0}
            continue
        fetch_ms = (time.time() - t0) * 1000

        t1 = time.time()
        a = analyze_page(url, html)        # model: classify + find every interactive element
        model_ms = (time.time() - t1) * 1000
        els = a.get("elements", [])

        els_c = [{"m": e.get("method", "GET"), "k": e.get("kind", "link"),
                  "u": urlparse(e["url"]).path or "/", "l": (e.get("label") or "")[:32]}
                 for e in els][:10]

        yield {"event": "node", "index": idx, "id": nid, "url": url, "parent": parent,
               "depth": depth, "via": via, "method": method,
               "type": a.get("type", "other"), "summary": a.get("summary", ""),
               "fetch_ms": round(fetch_ms), "model_ms": round(model_ms),
               "elements": len(els), "els": els_c}
        _log("[%3d] %-8s %s   fetch %dms  els %d  (queue %d)"
             % (idx, a.get("type", "?"), url, round(fetch_ms), len(els), len(queue)))

        # interact with each element the model found
        for e in els:
            cu = e["url"].split("#")[0].rstrip("/") or base
            if urlparse(cu).netloc and urlparse(cu).netloc != host:
                continue
            m = e.get("method", "GET")
            cid = _node_id(m, cu, e.get("fields"))
            if cid in seen:
                continue
            via_lbl = "link" if m == "GET" else ("submit: " + (e.get("label") or "form"))
            queue.append((cid, cu, m, e.get("fields", {}), nid, depth + 1, via_lbl))

    yield {"event": "done", "pages": len(seen), "seconds": round(time.time() - t_start, 1)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html", "/tree.html"):
            return self._sendfile("tree.html", "text/html")
        if p.path == "/crawl":
            return self._stream(p)
        if p.path == PROXY_PREFIX or p.path.startswith(PROXY_PREFIX + "/"):
            return self._proxy("GET")
        self.send_response(404); self.end_headers()

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == PROXY_PREFIX or p.path.startswith(PROXY_PREFIX + "/"):
            return self._proxy("POST")
        self.send_response(404); self.end_headers()

    def _proxy(self, method):
        # map  /gen/<rest>?<qs>  ->  GEN_BASE/<rest>?<qs>  and relay the response
        rest = self.path[len(PROXY_PREFIX):] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        url = GEN_BASE + rest
        try:
            if method == "GET":
                r = requests.get(url, timeout=180, allow_redirects=False)
            else:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                ct = self.headers.get("Content-Type", "application/x-www-form-urlencoded")
                r = requests.post(url, data=body, headers={"Content-Type": ct},
                                  timeout=180, allow_redirects=False)
        except Exception as e:
            self.send_response(502); self.end_headers()
            self.wfile.write(("proxy error reaching %s: %s" % (url, e)).encode()); return

        ctype = r.headers.get("Content-Type", "text/html; charset=utf-8")
        out = r.content
        if "text/html" in ctype:
            # genserver emits root-relative links; keep navigation inside the proxy prefix
            html = out.decode("utf-8", "ignore")
            html = re.sub(r'(href|action)="/(?!/)', r'\1="' + PROXY_PREFIX + '/', html)
            out = html.encode("utf-8", "ignore")

        self.send_response(r.status_code)
        self.send_header("Content-Type", ctype)
        loc = r.headers.get("Location")
        if loc:                                  # rewrite redirects back under the prefix too
            if loc.startswith(GEN_BASE):
                loc = PROXY_PREFIX + loc[len(GEN_BASE):]
            elif loc.startswith("/"):
                loc = PROXY_PREFIX + loc
            self.send_header("Location", loc)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _stream(self, p):
        q = parse_qs(p.query)
        target = unquote(q.get("target", ["http://localhost:3000"])[0])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for ev in crawl_events(target):
                self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _sendfile(self, name, ctype):
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Augur UI  ->  http://localhost:%d   (oracle: %s)" % (PORT, ORACLE))
    print("  store proxy  %s/  ->  %s   (browse the generated app through this server)" % (PROXY_PREFIX, GEN_BASE))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
