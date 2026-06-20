# setup-augur.ps1 - (re)create the entire Augur toolkit with the CURRENT canonical files.
#   cd C:\Projects\GithubRoot\Portfolio\Augur ; powershell -ExecutionPolicy Bypass -File .\setup-augur.ps1

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot ; if (-not $root) { $root = (Get-Location).Path }
New-Item -ItemType Directory -Force -Path $root | Out-Null
Write-Host "Writing Augur files to $root" -ForegroundColor Cyan

# ---- affordances.py ----
Set-Content -LiteralPath (Join-Path $root 'affordances.py') -Encoding UTF8 -Value @'
"""Deterministic half: raw HTML -> every click/submit as a fireable HTTP request spec.
Pure stdlib. No browser, no model, no running app."""
import json, sys
from html.parser import HTMLParser
from urllib.parse import urljoin

class Affordances(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base = base
        self.requests = []
        self.form = None     # current <form> being collected

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.requests.append({
                "kind": "link", "method": "GET",
                "url": urljoin(self.base, a["href"]),
                "fields": {}, "label": None})
        elif tag == "form":
            self.form = {
                "kind": "form",
                "method": (a.get("method") or "GET").upper(),
                "url": urljoin(self.base, a.get("action", "")),
                "fields": {}, "label": a.get("id") or a.get("class")}
        elif tag in ("input", "select", "textarea") and self.form is not None:
            name = a.get("name")
            if name:
                self.form["fields"][name] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.form is not None:
            self.requests.append(self.form); self.form = None

def extract(html, base="http://localhost:3000/"):
    p = Affordances(base); p.feed(html); return p.requests

if __name__ == "__main__":
    html = open(sys.argv[1] if len(sys.argv) > 1 else "landing.html").read()
    reqs = extract(html)
    print(f"{len(reqs)} affordances found on the landing page:\n")
    for r in reqs:
        line = f"  [{r['method']:4}] {r['url']}"
        if r["fields"]:
            line += "   fields=" + ",".join(f"{k}={v!r}" for k,v in r["fields"].items())
        if r.get("label"): line += f"   ({r['label']})"
        print(line)
    print("\n--- as JSON (what the model layer receives) ---")
    print(json.dumps(reqs, indent=2))
'@
Write-Host '  wrote affordances.py'

# ---- model_layer.py ----
Set-Content -LiteralPath (Join-Path $root 'model_layer.py') -Encoding UTF8 -Value @'
"""Model layer: given an affordance (a latent HTTP request), infer the EXPECTED response
= the test oracle. Talks to a local Ollama fast model; falls back to a deterministic stub
so the loop runs with nothing installed.

  TESTER_MODEL   default 'llama3.2:3b'      (fast; try qwen2.5:1.5b / llama3.2:1b)
  TESTER_OLLAMA  default http://localhost:11434
  TESTER_STUB=1  force the offline stub
"""
import os, json, urllib.request, urllib.error

MODEL  = os.environ.get("TESTER_MODEL", "llama3.2:3b")
OLLAMA = os.environ.get("TESTER_OLLAMA", "http://localhost:11434")
STUB   = os.environ.get("TESTER_STUB") == "1"

SYS = (
    "You are an HTTP test oracle. Given one request derived from a web page affordance "
    "(a link or form), predict the response a correct server SHOULD return. "
    "Reply ONLY with JSON: {\"expected_status\":int, \"expected_content_type\":str, "
    "\"expect_contains\":[str,...], \"expect_absent\":[str,...], \"rationale\":str}. "
    "GET links to existing pages -> 200 text/html. A POST that mutates state (add to cart, "
    "subscribe, login) commonly -> 302 redirect to a result page. Keep expect_contains to a "
    "few lowercase substrings you'd expect in the body or redirect target."
)

def _ollama(req_spec):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": json.dumps(req_spec)},
        ],
        "stream": False, "format": "json",
        "options": {"temperature": 0}, "keep_alive": "30m",
    }
    r = urllib.request.Request(OLLAMA.rstrip("/") + "/api/chat",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(json.loads(resp.read())["message"]["content"])

def _stub(req_spec):
    method, url = req_spec["method"], req_spec["url"]
    tail = url.rstrip("/").rsplit("/", 1)[-1] or "home"
    if method == "GET":
        return {"expected_status": 200, "expected_content_type": "text/html",
                "expect_contains": [tail.replace("-", " ")], "expect_absent": ["not found", "error"],
                "rationale": f"GET of an existing page '{tail}' should render 200 HTML."}
    # POST = state mutation -> usually a redirect to a result page
    target = "cart" if "cart" in url else ("login" if "login" in url else tail)
    return {"expected_status": 302, "expected_content_type": "text/html",
            "expect_contains": [target], "expect_absent": ["error", "invalid"],
            "rationale": f"POST to '{tail}' mutates state; expect a 302 redirect toward '{target}'."}

def infer_expected(req_spec):
    if STUB:
        return _stub(req_spec)
    try:
        return _ollama(req_spec)
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        out = _stub(req_spec); out["rationale"] = "[stub: model unreachable] " + out["rationale"]
        return out

if __name__ == "__main__":
    from affordances import extract
    reqs = extract(open("landing.html").read())
    print(f"Oracle ({'STUB' if STUB or True else MODEL}) predictions for {len(reqs)} affordances:\n")
    for r in reqs:
        exp = infer_expected(r)
        print(f"[{r['method']:4}] {r['url']}")
        print(f"      -> {exp['expected_status']} {exp['expected_content_type']}  "
              f"contains={exp['expect_contains']}")


# ── page describe (for the crawl tree) ───────────────────────────────────────
PAGE_SYS = ("Classify a web page from its URL and a snippet of HTML. Reply ONLY JSON: "
            "{\"type\":\"home|listing|product|cart|checkout|auth|other\",\"summary\":\"<=8 words\"}.")

def describe_page(url, html):
    if STUB:
        return _describe_stub(url)
    try:
        body = {"model": MODEL, "stream": False, "format": "json",
                "options": {"temperature": 0}, "keep_alive": "30m",
                "messages": [{"role": "system", "content": PAGE_SYS},
                             {"role": "user", "content": f"URL: {url}\nHTML: {html[:1200]}"}]}
        import urllib.request as _u
        r = _u.Request(OLLAMA.rstrip("/") + "/api/chat",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with _u.urlopen(r, timeout=60) as resp:
            return json.loads(json.loads(resp.read())["message"]["content"])
    except Exception:
        return _describe_stub(url)

def _describe_stub(url):
    p = url.rstrip("/").rsplit("/", 1)[-1] or "home"
    t = ("home" if url.rstrip("/").endswith(":3000") or p == "home" else
         "product" if "products/" in url else "listing" if p == "products" else
         "cart" if p == "cart" else "checkout" if p == "checkout" else
         "auth" if "login" in url else "other")
    return {"type": t, "summary": f"{t} page ({p})"}


# ── analyze_page (crawl: classify + discover every interactive element) ───────
CLASSIFY = os.environ.get("AUGUR_CLASSIFY", "off")

def analyze_page(url, html):
    """Classify the page AND discover every interactive element on it.
    Classification is a fast URL heuristic by default; set AUGUR_CLASSIFY=model to use the
    (slower) model labels. Elements come from the deterministic full-HTML affordance parse
    (links=GET, forms=POST with fields/CSRF lifted), deduped. Shape matches what serve.py /
    crawl consume: {type, summary, elements:[{kind, method, url, fields, label}, ...]}."""
    desc = describe_page(url, html) if CLASSIFY == "model" else _describe_stub(url)

    from affordances import extract
    base = url.rstrip("/") + "/"
    try:
        els = extract(html, base)
    except Exception:
        els = []

    seen, uniq = set(), []
    for e in els:
        key = (e.get("method", "GET"), e.get("url"),
               tuple(sorted((e.get("fields") or {}).keys())))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    return {"type": desc.get("type", "other"),
            "summary": desc.get("summary", ""),
            "elements": uniq}
'@
Write-Host '  wrote model_layer.py'

# ---- serve.py ----
Set-Content -LiteralPath (Join-Path $root 'serve.py') -Encoding UTF8 -Value @'
"""serve.py — Augur live UI. Serves tree.html and streams the crawl to the browser as
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
'@
Write-Host '  wrote serve.py'

# ---- genserver.py ----
Set-Content -LiteralPath (Join-Path $root 'genserver.py') -Encoding UTF8 -Value @'
"""genserver.py — a commerce site with NO code and NO database. The model IS the backend.

No seed data. A request for a path arrives; the model GENERATES the full HTML for that page
(a complex Spree-style store) including links to other plausible store paths. The crawler then
hits /, the model invents the landing page + its links, the crawler follows them, and each new
path is generated on demand — a website hallucinated into existence as it's explored.

  python genserver.py        # http://localhost:3000

FIRST PASS: pages are generated per request (cached in memory only for within-run consistency).
Persistence is intentionally skipped — the next step is to have the model infer a dataset,
generate it, and store it in local Mongo, then serve from there.

Config: GENSERVER_PORT (3000), GENSERVER_MODEL / TESTER_MODEL (llama3.2:3b),
TESTER_OLLAMA (http://localhost:11434), GENSERVER_STORE (the store description / prompt).
"""
import os, json, re, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

OLLAMA = os.environ.get("TESTER_OLLAMA", "http://localhost:11434")
MODEL  = os.environ.get("GENSERVER_MODEL", os.environ.get("TESTER_MODEL", "llama3.2:3b"))
PORT   = int(os.environ.get("GENSERVER_PORT", 3000))

STORE = os.environ.get("GENSERVER_STORE",
    "a large, complex Spree-style online store named 'Aurora Outfitters' selling outdoor "
    "apparel and gear, with deep category taxonomies, many products with variants, plus cart, "
    "checkout, and account pages")

SYS = (
    "You ARE the server-side backend of " + STORE + ". "
    "You receive one HTTP path and must return the FULL HTML the store would render for that "
    "exact page. It must be a LARGE, DEEP store — not a handful of pages. Rules:\n"
    "- a small header nav (Home, a few top categories, Cart, Account);\n"
    "- THEN content specific to this path, with MANY page-specific links that are UNIQUE and "
    "DEEPER than the nav (do not just repeat the nav):\n"
    "   '/' -> 6-10 top categories at /t/<cat> AND 8-12 featured products at /products/<unique-slug>;\n"
    "   a category path /t/<cat> -> 4-6 SUBcategories at /t/<cat>/<sub>, 10-16 product links with "
    "DISTINCT realistic slugs, and pagination links (/t/<cat>?page=2 ...);\n"
    "   a subcategory path -> more products + deeper subcategories;\n"
    "   a product path /products/<slug> -> a breadcrumb category link, a price, variants, an "
    "<form action='/cart/add' method='post'> with hidden product_id/variant_id, and 4-6 'related "
    "product' links with DISTINCT slugs;\n"
    "   /cart -> line items + a <form action='/checkout'>; /checkout, /account/* -> their forms.\n"
    "- Invent varied, realistic, UNIQUE slugs every time (e.g. /products/summit-down-parka-mens, "
    "/products/tarn-12l-daypack) so the store keeps branching. Use root-relative URLs only.\n"
    "Aim for 12-24 links per page. Keep under ~1600 tokens. Output ONLY raw HTML beginning with "
    "<html>. No markdown, no prose."
)

CACHE = {}


def _strip_fences(s):
    s = s.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def generate(path, note=""):
    key = path + note
    if key in CACHE:
        return CACHE[key]
    user = "GET " + path if not note else "GET " + path + "  -- " + note
    body = {"model": MODEL, "stream": False, "keep_alive": "30m",
            "options": {"temperature": 0.4},
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(OLLAMA.rstrip("/") + "/api/chat",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            html = json.loads(r.read())["message"]["content"]
        html = _strip_fences(html)
        if "<html" not in html.lower():
            html = "<html><body>" + html + "</body></html>"
    except Exception as e:
        html = "<html><body><h1>generation error</h1><p>%s</p></body></html>" % e
    CACHE[key] = html
    return html


class Handler(BaseHTTPRequestHandler):
    def _send(self, html):
        body = html.encode("utf-8", "ignore")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(404); self.end_headers(); return
        self._send(generate(path))

    def do_POST(self):
        path = urlparse(self.path).path
        self._send(generate(path, "this is the result page AFTER submitting the form"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("genserver (model %s) -> http://localhost:%d   [%s]" % (MODEL, PORT, STORE[:48] + "..."))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
'@
Write-Host '  wrote genserver.py'

# ---- mockshop.py ----
Set-Content -LiteralPath (Join-Path $root 'mockshop.py') -Encoding UTF8 -Value @'
"""Multi-page server-rendered mock site so the crawler has a real tree to discover.
  python mockshop.py   -> http://localhost:3000"""
import http.server, urllib.parse

# path -> internal links it exposes
SITE = {
    "/":                  ["/products", "/products/red-shoe", "/cart", "/account/login"],
    "/products":          ["/products/red-shoe", "/products/blue-hat", "/"],
    "/products/red-shoe": ["/cart", "/products"],
    "/products/blue-hat": ["/cart", "/products"],
    "/cart":              ["/checkout", "/"],
    "/checkout":          ["/"],
    "/account/login":     ["/"],
}
FORMS = ('<form action="/search" method="get"><input name="q"></form>'
         '<form action="/cart/add" method="post"><input type="hidden" name="product_id" value="42">'
         '<input type="hidden" name="csrf_token" value="abc123"><input name="quantity" value="1"></form>')

class H(http.server.BaseHTTPRequestHandler):
    def _html(self, code, body):
        self.send_response(code); self.send_header("Content-Type","text/html"); self.end_headers()
        self.wfile.write(f"<html><body>{body}</body></html>".encode())
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in SITE:
            links = "".join(f'<a href="{h}">{h}</a> ' for h in SITE[path])
            extra = FORMS if path == "/" else ""
            return self._html(200, f"<h1>{path}</h1>{links}{extra}")
        return self._html(404, "Not Found")
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/cart/add": 
            self.send_response(302); self.send_header("Location","/cart"); self.end_headers(); return
        return self._html(404, "Not Found")
    def log_message(self, *a): pass

if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", 3000), H).serve_forever()
'@
Write-Host '  wrote mockshop.py'

# ---- crawl.py ----
Set-Content -LiteralPath (Join-Path $root 'crawl.py') -Encoding UTF8 -Value @'
"""First pass: model parses each page, crawler follows every internal link -> site tree.
  python crawl.py [base_url]      default http://localhost:3000 ;  TESTER_STUB=1 for offline.
Progress is printed live to stderr as it crawls; the tree + JSON go to stdout."""
import sys, json, time, requests
from urllib.parse import urlparse
from affordances import extract
from model_layer import describe_page, MODEL, STUB

ORACLE = "STUB" if STUB else MODEL


def _log(msg):
    print(msg, file=sys.stderr, flush=True)   # progress on stderr; tree/JSON stay on stdout


def crawl(base, max_pages=50):
    host = urlparse(base).netloc
    sess = requests.Session()
    seen, nodes = set(), {}
    order = [0]
    t_start = time.time()
    _log("crawling " + base + "  (oracle: " + ORACLE + ", max " + str(max_pages) + " pages)\n")

    def visit(url, depth=0):
        url = url.split("#")[0].rstrip("/") or base
        if url in seen or len(seen) >= max_pages:
            return nodes.get(url)
        seen.add(url)
        order[0] += 1
        indent = "  " * depth

        t0 = time.time()
        try:
            html = sess.get(url, timeout=10).text
        except Exception as e:
            _log("[%3d] %s! %s  fetch error: %s" % (order[0], indent, url, e))
            nodes[url] = {"url": url, "type": "error", "summary": str(e), "children": []}
            return nodes[url]
        t_fetch = (time.time() - t0) * 1000

        t1 = time.time()
        desc = describe_page(url, html)
        t_model = (time.time() - t1) * 1000

        node = {"url": url, "type": desc["type"], "summary": desc["summary"], "children": []}
        nodes[url] = node

        # navigate: internal GET links only (POSTs are state changes, not navigation)
        child_urls = []
        for a in extract(html, url + "/"):
            if a["method"] == "GET" and a["kind"] == "link":
                cu = a["url"].split("#")[0].rstrip("/") or base
                if urlparse(cu).netloc == host and cu not in child_urls:
                    child_urls.append(cu)
        new_links = sum(1 for cu in child_urls if cu not in seen)

        _log("[%3d] %s%s  fetch %4.0fms  model %5.0fms  -> [%s] %s  (+%d new)"
             % (order[0], indent, url, t_fetch, t_model, desc["type"], desc["summary"], new_links))

        for cu in child_urls:
            child = visit(cu, depth + 1)
            if child and child["url"
'@
Write-Host '  wrote crawl.py'

# ---- tree.html ----
Set-Content -LiteralPath (Join-Path $root 'tree.html') -Encoding UTF8 -Value @'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Augur — a site that maps itself</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>
  :root{
    --ink:#0a0d12; --panel:#0e1219; --panel2:#11161f;
    --amber:#f0b54a; --amber-dim:#b9863a; --dim:#3a4150;
    --text:#c7cdd6; --muted:#6b7480; --line:rgba(255,255,255,.07);
    --line-amber:rgba(240,181,74,.18);
    --home:#f0b54a; --listing:#76c7ff; --product:#ffd470; --cart:#c79bff;
    --checkout:#6fe0a6; --auth:#ff9d6b; --other:#9fb0c0; --error:#e05a5a;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0; background:var(--ink); color:var(--text);
    font-family:'Space Grotesk',system-ui,sans-serif; line-height:1.5; -webkit-font-smoothing:antialiased;}
  .wrap{max-width:1180px; margin:0 auto; padding:34px 28px 60px; display:flex; flex-direction:column; min-height:100%;}
  h1{font-weight:700; font-size:clamp(30px,5vw,46px); line-height:1.02; margin:0 0 4px; letter-spacing:-.02em;}
  h1 em{font-style:normal; color:var(--amber)}
  .tagline{font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--muted); margin-bottom:22px; letter-spacing:.02em;}

  .setup{display:flex; gap:12px; align-items:center; margin-bottom:18px; flex-wrap:wrap;}
  .setup input{flex:1; min-width:220px; background:var(--ink); color:var(--text); border:1px solid var(--line);
    border-radius:4px; padding:11px 13px; font-family:'IBM Plex Mono',monospace; font-size:13px;}
  .setup input:focus{outline:2px solid var(--amber); outline-offset:1px; border-color:transparent;}
  .go{padding:11px 26px; border:none; border-radius:4px; cursor:pointer; background:var(--amber); color:#0a0d12;
    font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:14px; letter-spacing:.01em; transition:filter .15s,opacity .15s;}
  .go:hover{filter:brightness(1.08)} .go:disabled{opacity:.4; cursor:not-allowed}
  .clock{font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--amber-dim); font-variant-numeric:tabular-nums; min-width:46px;}

  .pane{background:var(--panel); border:1px solid var(--line); border-radius:6px; overflow:hidden; display:flex; flex-direction:column;}
  .pane-header{padding:11px 16px; border-bottom:1px solid var(--line); font-family:'IBM Plex Mono',monospace;
    font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--amber-dim);
    display:flex; align-items:center; gap:8px;}
  .pane-header .hdot{width:6px; height:6px; border-radius:50%; background:var(--amber); animation:dotPulse 1.8s ease-in-out infinite;}
  .pane-header .hdot.idle{background:var(--muted); animation:none;}
  .pane-header .right{margin-left:auto; color:var(--muted); letter-spacing:.06em;}

  /* console — streams the model's voice as it crawls */
  .console{margin-bottom:18px;}
  .console .body{height:240px; overflow-y:auto; padding:16px; white-space:pre-wrap; scroll-behavior:smooth;
    font-family:'IBM Plex Mono',monospace; font-size:12.5px; line-height:1.6; color:var(--amber-dim);}
  .console .body .ph{color:var(--dim); font-style:italic;}
  .cursor{display:inline-block; width:7px; height:1.05em; background:var(--amber); margin-left:1px;
    vertical-align:text-bottom; animation:blink .8s step-end infinite;}

  /* tree */
  .tree{flex:1;}
  .tree .body{position:relative; overflow:auto; height:clamp(440px,62vh,920px);}
  svg.canvas{display:block;}
  .link{fill:none; stroke:var(--line-amber); stroke-width:1.4px;}
  .node rect{fill:var(--panel2); stroke-width:1.5px;}
  .node .label{font-family:'IBM Plex Mono',monospace; font-size:11px; fill:var(--text); dominant-baseline:middle;}
  .node.new rect{stroke:var(--amber)!important; stroke-width:2.5px;}
  .legend{display:flex; flex-wrap:wrap; gap:6px 14px; padding:9px 14px; border-top:1px solid var(--line); background:rgba(10,13,18,.5);}
  .legend span{font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.05em; color:var(--muted); display:inline-flex; align-items:center; gap:6px;}
  .legend i{width:9px; height:9px; border-radius:50%; display:inline-block;}

  @keyframes blink{0%,100%{opacity:1} 50%{opacity:0}}
  @keyframes dotPulse{0%,100%{opacity:1} 50%{opacity:.3}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Aug<em>u</em>r</h1>
  <div class="tagline">a store with no code and no database — the model generates each page, and the map draws itself as it's explored.</div>

  <div class="setup">
    <input id="target" value="http://localhost:3000" spellcheck="false">
    <button class="go" id="go">Crawl</button>
    <span class="clock" id="clock"></span>
  </div>

  <div class="pane console">
    <div class="pane-header"><span class="hdot idle" id="cdot"></span> Model <span class="right" id="cstatus">idle</span></div>
    <div class="body" id="console"><span class="ph">Set a target and hit Crawl. The model will generate each page, read it for interactive elements, and act on them — narrating here as the tree grows below.</span></div>
  </div>

  <div class="pane tree">
    <div class="pane-header"><span class="hdot idle" id="tdot"></span> Site tree <span class="right" id="tcount">0 pages</span></div>
    <div class="body"><svg class="canvas"></svg></div>
    <div class="legend" id="legend"></div>
  </div>
</div>

<script>
const TYPES=["home","listing","product","cart","checkout","auth","other","error"];
const color=t=>getComputedStyle(document.documentElement).getPropertyValue("--"+(TYPES.includes(t)?t:"other")).trim();

const legend=document.getElementById("legend");
TYPES.forEach(t=>{const s=document.createElement("span"); s.innerHTML='<i style="background:'+color(t)+'"></i>'+t; legend.appendChild(s);});

const svg=d3.select("svg.canvas");
const gZoom=svg.append("g");
const gLink=gZoom.append("g");
const gNode=gZoom.append("g");
// The panel (.tree .body) scrolls natively; the SVG is sized to the tree's content on each
// render, so a scrollbar appears whenever the tree exceeds the panel's height/width.

let nodesById={}, es=null;

function pathOf(url){ try{const u=new URL(url); const p=u.pathname.replace(/\/$/,""); return p===""?"/":p;}catch(_){ const p=(url.split("#")[0]).replace(/\/$/,""); return p===""?"/":p; } }
function chipLabel(d){ const l=d.data.label; return l.length>30 ? l.slice(0,29)+"…" : l; }
function chipW(d){ return Math.min(250, chipLabel(d).length*6.7 + 42); }

/* ---------- streaming console (typewriter) ---------- */
let buf="", shown=0, typing=false;
const consoleEl=document.getElementById("console");
function pushText(t){ if(consoleEl.querySelector(".ph")) consoleEl.textContent=""; buf+=t; if(!typing) tick(); }
function tick(){
  typing=true;
  if(shown>=buf.length){ typing=false; render_cursor(); return; }
  const backlog=buf.length-shown;
  shown += Math.max(1, Math.floor(backlog/40));   // catch up if we fall behind
  consoleEl.textContent=buf.slice(0,shown);
  render_cursor();
  consoleEl.scrollTop=consoleEl.scrollHeight;
  setTimeout(tick,16);
}
function render_cursor(){
  const c=document.createElement("span"); c.className="cursor"; consoleEl.appendChild(c);
}
function narrate(ev){
  if(ev.type==="error") return "\n"+String(ev.index).padStart(2,"0")+"  "+(ev.method||"GET")+" "+pathOf(ev.url)+"\n   x  "+ev.summary+"\n";
  let t="\n"+String(ev.index).padStart(2,"0")+"  "+(ev.method||"GET")+" "+pathOf(ev.url)+"\n";
  t+="   → ["+ev.type+"]  "+(ev.summary||"")+"   ("+ev.fetch_ms+"ms gen · "+ev.model_ms+"ms read)\n";
  if(ev.els && ev.els.length){
    t+="   found "+ev.elements+" element"+(ev.elements===1?"":"s")+":\n";
    ev.els.forEach(e=>{ t+="     · "+(e.m||"GET")+" "+e.u+(e.l?"  «"+e.l+"»":"")+"\n"; });
    t+="   ↳ interacting…\n";
  }
  return t;
}

/* ---------- horizontal tree (left -> right) ---------- */
function addNode(ev){
  if(nodesById[ev.id]) return;
  const isSubmit = ev.via && ev.via.indexOf("submit")===0;
  nodesById[ev.id]={ id:ev.id, parentId:ev.parent||"", type:ev.type, summary:ev.summary,
                     url:ev.url, label:(isSubmit?"+ ":"")+pathOf(ev.url) };
  render(ev.id);
  document.getElementById("tcount").textContent=Object.keys(nodesById).length+" pages";
}
function render(newId){
  const data=Object.values(nodesById); if(!data.length) return;
  let root;
  try{ root=d3.stratify().id(d=>d.id).parentId(d=>d.parentId)(data); }catch(_){ return; }
  // Windows-Explorer style: indented tree. Each node gets its own row (pre-order):
  // depth -> horizontal indent, row order -> vertical position. Root sits at top-left.
  const INDENT=30, ROW=34;
  let _row=0;
  root.eachBefore(d=>{ d.dx=d.depth*INDENT; d.dy=(_row++)*ROW; });   // dx=indent (screen x), dy=row (screen y)
  const nodes=root.descendants(), links=root.links();
  const px=d=>d.dx+chipW(d)/2;   // translate-x so the chip's LEFT edge lands on the indent
  const py=d=>d.dy;

  // right-angle (elbow) connectors, like a file tree: down the parent's gutter, then across
  const linkPath=d=>{ const gx=d.source.dx+12,gy=d.source.dy+13,cy=d.target.dy,cx=d.target.dx;
    return `M${gx},${gy} V${cy} H${cx}`; };
  const link=gLink.selectAll("path.link").data(links,d=>d.target.id);
  link.exit().remove();
  link.enter().append("path").attr("class","link").attr("opacity",0)
    .merge(link).transition().duration(500).attr("opacity",1).attr("d",linkPath);

  const node=gNode.selectAll("g.node").data(nodes,d=>d.id);
  node.exit().remove();
  const ent=node.enter().append("g").attr("class","node")
      .attr("transform",d=>"translate("+(d.parent?px(d.parent):px(d))+","+(d.parent?py(d.parent):py(d))+")")
      .attr("opacity",0);
  ent.append("title").text(d=> pathOf(d.data.url||d.id)+"  ·  ["+d.data.type+"]  "+(d.data.summary||""));
  ent.append("rect").attr("height",26).attr("rx",6).attr("ry",6)
      .attr("width",chipW).attr("x",d=>-chipW(d)/2).attr("y",-13)
      .attr("stroke",d=>color(d.data.type));
  ent.append("circle").attr("r",3.6).attr("cy",0).attr("cx",d=>-chipW(d)/2+13).attr("fill",d=>color(d.data.type));
  ent.append("text").attr("class","label").attr("x",d=>-chipW(d)/2+24).attr("y",1).text(chipLabel);
  ent.merge(node).classed("new",d=>d.id===newId)
    .transition().duration(500)
      .attr("transform",d=>"translate("+px(d)+","+py(d)+")").attr("opacity",1);

  fit(nodes,newId);
}
function fit(nodes,newId){
  const PAD=40;
  const w=Math.max(...nodes.map(n=>n.dx+chipW(n)))+PAD*2;
  const h=Math.max(...nodes.map(n=>n.dy))+PAD*2;
  // size the SVG to the tree so the panel (.tree .body{overflow:auto}) gets a scrollbar
  svg.attr("width",w).attr("height",h).style("width",w+"px").style("height",h+"px");
  gZoom.attr("transform","translate("+PAD+","+PAD+")");
  // keep the newest node in view as the crawl streams in
  const body=svg.node().parentNode, n=nodes.find(d=>d.id===newId);
  if(n){
    const top=PAD+n.dy-22, bot=PAD+n.dy+22;
    if(bot>body.scrollTop+body.clientHeight) body.scrollTop=bot-body.clientHeight;
    else if(top<body.scrollTop) body.scrollTop=top;
  }
}

/* ---------- run ---------- */
let t0=0, clockTimer=null;
function setStatus(s){ document.getElementById("cstatus").textContent=s; }
function setLive(on){
  document.getElementById("cdot").className="hdot"+(on?"":" idle");
  document.getElementById("tdot").className="hdot"+(on?"":" idle");
}
function startClock(){ t0=Date.now(); clearInterval(clockTimer);
  clockTimer=setInterval(()=>{ const s=Math.floor((Date.now()-t0)/1000);
    document.getElementById("clock").textContent=Math.floor(s/60)+":"+String(s%60).padStart(2,"0"); },1000); }

function start(){
  if(es) es.close();
  nodesById={}; gLink.selectAll("*").remove(); gNode.selectAll("*").remove();
  buf=""; shown=0; consoleEl.textContent=""; document.getElementById("tcount").textContent="0 pages";
  const target=document.getElementById("target").value.trim();
  document.getElementById("go").disabled=true; setLive(true); startClock(); setStatus("crawling "+target);
  pushText("> crawling "+target+"\n");
  es=new EventSource("/crawl?target="+encodeURIComponent(target));
  es.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.event==="node"){ addNode(ev); pushText(narrate(ev)); setStatus("discovered "+ev.index+" pages"); }
    else if(ev.event==="start"){ pushText("> oracle: "+ev.oracle+"  (max "+ev.max_pages+" pages)\n"); setStatus("crawling "+ev.target); }
    else if(ev.event==="log"){ pushText("  "+ev.msg+" ...\n"); setStatus(ev.msg); }
    else if(ev.event==="done"){ es.close(); document.getElementById("go").disabled=false; setLive(false);
      clearInterval(clockTimer); setStatus("done"); pushText("\n> done — "+ev.pages+" pages in "+ev.seconds+"s\n"); }
  };
  es.onerror=()=>{ setStatus("stream error (serve.py running? target up?)");
    document.getElementById("go").disabled=false; setLive(false); clearInterval(clockTimer); if(es) es.close(); };
}
document.getElementById("go").addEventListener("click",start);
document.getElementById("target").addEventListener("keydown",e=>{ if(e.key==="Enter") start(); });
</script>
</body>
</html>
'@
Write-Host '  wrote tree.html'

# ---- preview.html ----
Set-Content -LiteralPath (Join-Path $root 'preview.html') -Encoding UTF8 -Value @'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Augur — tree preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>
  :root{
    --ink:#0a0d12; --panel:#0e1219; --panel2:#11161f;
    --amber:#f0b54a; --amber-dim:#b9863a; --dim:#3a4150;
    --text:#c7cdd6; --muted:#6b7480; --line:rgba(255,255,255,.07); --line-amber:rgba(240,181,74,.18);
    --home:#f0b54a; --listing:#76c7ff; --product:#ffd470; --cart:#c79bff;
    --checkout:#6fe0a6; --auth:#ff9d6b; --other:#9fb0c0; --error:#e05a5a;
  }
  *{box-sizing:border-box} html,body{height:100%}
  body{margin:0; background:var(--ink); color:var(--text); font-family:'Space Grotesk',system-ui,sans-serif;}
  .wrap{max-width:1180px; margin:0 auto; padding:30px 28px; display:flex; flex-direction:column; min-height:100%;}
  h1{font-weight:700; font-size:36px; margin:0 0 2px; letter-spacing:-.02em;} h1 em{font-style:normal; color:var(--amber)}
  .tagline{font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--muted); margin-bottom:18px;}
  .pane{background:var(--panel); border:1px solid var(--line); border-radius:6px; overflow:hidden; display:flex; flex-direction:column; flex:1;}
  .pane-header{padding:11px 16px; border-bottom:1px solid var(--line); font-family:'IBM Plex Mono',monospace;
    font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--amber-dim); display:flex; align-items:center; gap:8px;}
  .pane-header .right{margin-left:auto; color:var(--muted);}
  .body{position:relative; overflow:hidden; height:clamp(460px,68vh,960px);}
  svg.canvas{width:100%; height:100%; display:block;}
  .link{fill:none; stroke:var(--line-amber); stroke-width:1.4px;}
  .node rect{fill:var(--panel2); stroke-width:1.5px;}
  .node .label{font-family:'IBM Plex Mono',monospace; font-size:11px; fill:var(--text); dominant-baseline:middle;}
  .node.new rect{stroke:var(--amber)!important; stroke-width:2.5px;}
  .legend{display:flex; flex-wrap:wrap; gap:6px 14px; padding:9px 14px; border-top:1px solid var(--line); background:rgba(10,13,18,.5);}
  .legend span{font-family:'IBM Plex Mono',monospace; font-size:10px; letter-spacing:.05em; color:var(--muted); display:inline-flex; align-items:center; gap:6px;}
  .legend i{width:9px; height:9px; border-radius:50%;}
</style>
</head>
<body>
<div class="wrap">
  <h1>Aug<em>u</em>r</h1>
  <div class="tagline">tree preview — baked sample store, real styling (no server needed)</div>
  <div class="pane">
    <div class="pane-header">Site tree <span class="right" id="count"></span></div>
    <div class="body"><svg class="canvas"></svg></div>
    <div class="legend" id="legend"></div>
  </div>
</div>

<script>
// A rich, realistic store tree (parent-first order) to judge node + font presentation.
const DATA=[
  ["/","",                         "home","Aurora Outfitters"],
  ["/t/mens","/",                  "listing","Men's"],
  ["/t/womens","/",                "listing","Women's"],
  ["/t/gear","/",                  "listing","Gear"],
  ["/t/sale","/",                  "listing","Sale"],
  ["/cart","/",                    "cart","Cart (2)"],
  ["/account/login","/",           "auth","Sign in"],

  ["/t/mens/jackets","/t/mens",        "listing","Men's jackets"],
  ["/t/mens/footwear","/t/mens",       "listing","Men's footwear"],
  ["/t/mens/baselayers","/t/mens",     "listing","Base layers"],
  ["/t/mens?page=2","/t/mens",         "listing","Men's · page 2"],

  ["/products/summit-down-parka","/t/mens/jackets",  "product","Summit Down Parka"],
  ["/products/alpine-3l-shell","/t/mens/jackets",    "product","Alpine 3L Shell"],
  ["/products/storm-anorak","/t/mens/jackets",       "product","Storm Anorak"],
  ["/products/trail-runner-gtx","/t/mens/footwear",  "product","Trail Runner GTX"],
  ["/products/summit-boot","/t/mens/footwear",       "product","Summit Boot"],
  ["/products/merino-crew","/t/mens/baselayers",     "product","Merino Crew"],

  ["/t/womens/jackets","/t/womens",    "listing","Women's jackets"],
  ["/t/womens/packs","/t/womens",      "listing","Women's packs"],
  ["/products/aurora-parka","/t/womens/jackets",   "product","Aurora Parka"],
  ["/products/mistral-windbreaker","/t/womens/jackets","product","Mistral Windbreaker"],
  ["/products/tarn-12l-daypack","/t/womens/packs", "product","Tarn 12L Daypack"],
  ["/products/summit-45-pack","/t/womens/packs",   "product","Summit 45 Pack"],

  ["/t/gear/tents","/t/gear",          "listing","Tents"],
  ["/t/gear/sleep","/t/gear",          "listing","Sleep"],
  ["/t/gear/cooking","/t/gear",        "listing","Cooking"],
  ["/products/cirrus-2p-tent","/t/gear/tents",   "product","Cirrus 2P Tent"],
  ["/products/basecamp-4p","/t/gear/tents",      "product","Basecamp 4P"],
  ["/products/down-bag-0f","/t/gear/sleep",      "product","Down Bag 0°F"],
  ["/products/featherlite-pad","/t/gear/sleep",  "product","Featherlite Pad"],
  ["/products/trail-stove","/t/gear/cooking",    "product","Trail Stove"],

  ["/products/aurora-parka#cart","/products/aurora-parka", "cart","Added to cart"],
  ["/checkout","/cart",                "checkout","Checkout"],
  ["/checkout/shipping","/checkout",   "checkout","Shipping"],
  ["/checkout/payment","/checkout",    "checkout","Payment"],
  ["/account/register","/account/login","auth","Create account"],
  ["/account/orders","/account/login", "auth","Orders"],
].map(d=>({id:d[0],parentId:d[1],type:d[2],summary:d[3]}));

const TYPES=["home","listing","product","cart","checkout","auth","other","error"];
const color=t=>getComputedStyle(document.documentElement).getPropertyValue("--"+(TYPES.includes(t)?t:"other")).trim();
const legend=document.getElementById("legend");
TYPES.forEach(t=>{const s=document.createElement("span"); s.innerHTML='<i style="background:'+color(t)+'"></i>'+t; legend.appendChild(s);});

const svg=d3.select("svg.canvas");
const gZoom=svg.append("g"), gLink=gZoom.append("g"), gNode=gZoom.append("g");
const zoom=d3.zoom().scaleExtent([0.1,2.5]).on("zoom",e=>gZoom.attr("transform",e.transform));
svg.call(zoom);

function pathOf(url){ const p=(url.split("#")[0]).replace(/\/$/,""); return p===""?"/":p; }
function chipLabel(d){ const l=pathOf(d.id); return l.length>30 ? l.slice(0,29)+"…" : l; }
function chipW(d){ return Math.min(250, chipLabel(d).length*6.7 + 42); }

let shown=[];
function render(newId){
  const root=d3.stratify().id(d=>d.id).parentId(d=>d.parentId)(shown);
  // Windows-Explorer style: indented tree. Each node gets its own row (pre-order):
  // depth -> horizontal indent, row order -> vertical position. Root sits at top-left.
  const INDENT=30, ROW=34;
  let _row=0;
  root.eachBefore(d=>{ d.dx=d.depth*INDENT; d.dy=(_row++)*ROW; });   // dx=indent (screen x), dy=row (screen y)
  const nodes=root.descendants(), links=root.links();
  document.getElementById("count").textContent=nodes.length+" pages";
  const px=d=>d.dx+chipW(d)/2;   // translate-x so the chip's LEFT edge lands on the indent
  const py=d=>d.dy;

  // right-angle (elbow) connectors, like a file tree: down the parent's gutter, then across
  const linkPath=d=>{ const gx=d.source.dx+12,gy=d.source.dy+13,cy=d.target.dy,cx=d.target.dx;
    return `M${gx},${gy} V${cy} H${cx}`; };
  const link=gLink.selectAll("path.link").data(links,d=>d.target.id);
  link.exit().remove();
  link.enter().append("path").attr("class","link").attr("opacity",0)
    .merge(link).transition().duration(450).attr("opacity",1).attr("d",linkPath);

  const node=gNode.selectAll("g.node").data(nodes,d=>d.id);
  node.exit().remove();
  const ent=node.enter().append("g").attr("class","node")
      .attr("transform",d=>"translate("+(d.parent?px(d.parent):px(d))+","+(d.parent?py(d.parent):py(d))+")")
      .attr("opacity",0);
  ent.append("title").text(d=>pathOf(d.id)+"  ·  ["+d.data.type+"]  "+(d.data.summary||""));
  ent.append("rect").attr("height",26).attr("rx",6).attr("ry",6)
      .attr("width",chipW).attr("x",d=>-chipW(d)/2).attr("y",-13)
      .attr("stroke",d=>color(d.data.type));
  ent.append("circle").attr("r",3.6).attr("cy",0).attr("cx",d=>-chipW(d)/2+13).attr("fill",d=>color(d.data.type));
  ent.append("text").attr("class","label").attr("x",d=>-chipW(d)/2+24).attr("y",1).text(chipLabel);
  ent.merge(node).classed("new",d=>d.id===newId)
    .transition().duration(450).attr("transform",d=>"translate("+px(d)+","+py(d)+")").attr("opacity",1);

  fit(nodes);
}
function fit(nodes){
  const minX=Math.min(...nodes.map(n=>n.dx)), maxX=Math.max(...nodes.map(n=>n.dx+chipW(n)));
  const minY=Math.min(...nodes.map(n=>n.dy)), maxY=Math.max(...nodes.map(n=>n.dy));
  const b=svg.node().getBoundingClientRect(); let w=b.width||980,h=b.height||560;
  const bw=(maxX-minX)+120,bh=(maxY-minY)+120;
  let k=Math.min(1.05,0.92*Math.min(w/bw,h/bh)); if(!isFinite(k)||k<=0) k=0.8;
  const tx=40-k*minX, ty=40-k*minY;
  svg.transition().duration(450).call(zoom.transform,d3.zoomIdentity.translate(tx,ty).scale(k));
}

// staggered reveal — mimics the live build
let i=0;
(function step(){ if(i>=DATA.length) return; shown.push(DATA[i]); render(DATA[i].id); i++; setTimeout(step,140); })();
</script>
</body>
</html>
'@
Write-Host '  wrote preview.html'

# ---- README.md ----
Set-Content -LiteralPath (Join-Path $root 'README.md') -Encoding UTF8 -Value @'
# Augur — browser-free, model-driven site mapper & tester

No Chromium. Plain HTTP + raw HTML. A local fast model (Ollama) is the oracle.

## Pipeline
1. `affordances.py` — raw HTML → every click/submit as a fireable HTTP request (links=GET, forms=POST w/ fields, CSRF tokens lifted automatically). Deterministic, no model.
2. `model_layer.py` — the model layer: `describe_page()` classifies a page; `infer_expected()` predicts a request's expected response (the test oracle). Talks to Ollama; stub fallback offline.
3. `crawl.py` — FIRST PASS: model parses each page, crawler follows every internal link → site **tree**.
4. `runner.py` — fires each affordance and diffs actual vs the oracle's expectation → pass/fail.
5. `mockshop.py` — a tiny multi-page server-rendered site to run against with no Spree.

## Run (live, with your model)
Ollama up + `llama3.2:3b` pulled. Two terminals:

    python mockshop.py                     # terminal 1: target on :3000
    python crawl.py http://localhost:3000  # terminal 2: real model builds the tree

Point `crawl.py` / `runner.py` at any server-rendered site (e.g. your Spree on :3000).

## Config (env)
    TESTER_MODEL    default llama3.2:3b   (try qwen2.5:1.5b / llama3.2:1b for more speed)
    TESTER_OLLAMA   default http://localhost:11434
    TESTER_STUB=1   force the offline deterministic oracle (no model)
'@
Write-Host '  wrote README.md'

# ---- HANDOFF.md ----
Set-Content -LiteralPath (Join-Path $root 'HANDOFF.md') -Encoding UTF8 -Value @'
# Augur — Handoff

A commerce site with **no code and no database**: a local model *is* the backend and
**generates every page on request**. An agentic crawler then trawls each generated page
for interactive elements, **interacts** with them (follows links, submits forms), and
**builds a tree of the site as it's explored** — all over plain HTTP, **no browser/Chromium**.
The live UI is skinned like StoryWriter: a streaming "Model" console on top, a vertical
tree of chip-nodes building below.

Location: `C:\Projects\GithubRoot\Portfolio\Augur`

## The idea, in one line

The model invents the store page-by-page; Augur navigates what the model invents and draws
the map. "The most complex commerce app" is just the **prompt** — there's no Spree running.

## Pipeline

```
GET /                      genserver.py  -> the MODEL generates the landing-page HTML (+links)
  -> serve.py crawl        for each page:
       analyze_page()        classify (fast URL heuristic) + find EVERY interactive element
                             (deterministic full HTML parse, unioned with the model's findings)
       interact              follow links (GET) AND submit forms (POST) — each becomes a node
                             (form result pages are generated by the model too)
  -> SSE events            streamed to tree.html: a 'node' per discovered page
  -> tree.html             vertical tree draws itself; the console narrates in the model's voice
```

One model call per page now (the page **generation**). Classification is a fast heuristic by
default — set `AUGUR_CLASSIFY=model` to bring the (slower) model labels back.

## Files

| File | Role |
|------|------|
| `genserver.py` | The model-as-backend. `GET /<path>` -> model-generated HTML (deep store: taxonomies, unique product slugs, pagination). Serves :3000. |
| `serve.py` | UI server (:7000). Serves `tree.html` and streams the agentic crawl as Server-Sent Events. |
| `model_layer.py` | `analyze_page()` (classify + interactive-element discovery), plus `infer_expected()` / `describe_page()` from earlier passes. Talks to Ollama; deterministic fallbacks. |
| `affordances.py` | Deterministic HTML -> every link/form as a fireable request spec (the complete element parse). |
| `tree.html` | The live UI: streaming model console + vertical chip-node tree (D3). |
| `preview.html` | Standalone, baked rich sample tree — open directly to judge node/font presentation, no server. |
| `mockshop.py` | A tiny hand-coded multi-page site (fallback target; not the model-backed one). |
| `crawl.py` | CLI crawler -> prints the tree + JSON (no UI). |
| `view-augur.ps1` | One command: start genserver (:3000) + UI (:7000) + open browser. |
| `run-augur.ps1` | CLI crawl runner (mock or external target). |
| `setup-augur.ps1` | Re-creates ALL files above from canonical copies. Run to kill stale-version drift. |

## Ports

| Port | Process | Role |
|------|---------|------|
| 3000 | `genserver.py` | model-generated store (the crawl target) |
| 7000 | `serve.py` | Augur UI + SSE crawl stream |
| 11434 | Ollama | local model (`llama3.2:3b` default) |

## Run

Prereqs: Python with `requests` (`pip install requests`), Ollama up with `llama3.2:3b`
(`ollama pull llama3.2:3b`).

```powershell
cd C:\Projects\GithubRoot\Portfolio\Augur
powershell -ExecutionPolicy Bypass -File .\setup-augur.ps1   # ensure current files (no drift)
.\view-augur.ps1                                              # genserver + UI + browser
# in the page: target = http://localhost:3000, hit Crawl
```

Just the visuals, no model: open `preview.html`.
CLI tree (no UI): `.\run-augur.ps1` or `python crawl.py http://localhost:3000`.

## Config (env vars)

| Var | Default | Effect |
|-----|---------|--------|
| `TESTER_MODEL` / `GENSERVER_MODEL` | `llama3.2:3b` | model tag (try `qwen2.5:1.5b`, `llama3.2:1b` for speed) |
| `TESTER_OLLAMA` | `http://localhost:11434` | Ollama endpoint |
| `GENSERVER_STORE` | Aurora Outfitters … | the store the model emulates (change for more/less depth) |
| `AUGUR_MAX_PAGES` | `120` | crawl cap |
| `AUGUR_CLASSIFY` | `off` | set `model` to use the model (slower) for node labels |
| `AUGUR_UI_PORT` / `GENSERVER_PORT` | `7000` / `3000` | ports |
| `TESTER_STUB` | unset | `1` = fully offline deterministic oracle (no model) |

## Status

Done: model-backed generation, agentic crawl (links + form submits), deterministic complete
element discovery, SSE streaming UI, StoryWriter skin, vertical chip-node tree, one-call-per-page
speedup, setup script.

**Deferred — the next pass:** persistence. Have the model **infer a dataset once**
(categories, products with variants/prices), **store it in local Mongo**, and serve consistent
pages from Mongo instead of regenerating per request. That makes the store stable across runs
and lets the tree (and later a fire->compare test pass) be reproducible. Mongo is already running
on :27017; reuse the `pymongo` pattern from the StoryWriter backend.

## Notes / speed levers

- Slowest part is the model generating each page. Levers: lower `AUGUR_MAX_PAGES`, use a smaller
  model, or cap generation length (`num_predict`) in `genserver.py`.
- The sandbox the assistant runs in is Python 3.10 and can't reach your Ollama, so changes were
  written to disk and verified by you locally — `setup-augur.ps1` is the source of truth.
'@
Write-Host '  wrote HANDOFF.md'

# ---- run-augur.ps1 ----
Set-Content -LiteralPath (Join-Path $root 'run-augur.ps1') -Encoding UTF8 -Value @'
# run-augur.ps1 — start the mock shop, crawl it with the model, then stop the mock.
#
#   .\run-augur.ps1                         # spins up mockshop.py and crawls it
#   .\run-augur.ps1 http://localhost:3000   # crawl a site you already have running (e.g. Spree)
#   $env:TESTER_STUB=1 ; .\run-augur.ps1    # offline: deterministic oracle, no model
#
param([string]$Target)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot          # always run from the Augur folder = no stale paths

if ($Target) {
    # crawl an already-running site; don't touch the mock
    python crawl.py $Target
}
else {
    Write-Host "Starting mock shop on :3000..." -ForegroundColor Cyan
    $mock = Start-Process python -ArgumentList "mockshop.py" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 1
    try {
        python crawl.py http://localhost:3000
    }
    finally {
        Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue
        Write-Host "`nMock shop stopped." -ForegroundColor Cyan
    }
}
'@
Write-Host '  wrote run-augur.ps1'

# ---- view-augur.ps1 ----
Set-Content -LiteralPath (Join-Path $root 'view-augur.ps1') -Encoding UTF8 -Value @'
# view-augur.ps1 — launch the live animated crawl over a MODEL-GENERATED store.
#
#   .\view-augur.ps1              # starts genserver.py (model is the backend, :3000) + UI (:7000) + browser
#   .\view-augur.ps1 -NoBackend   # UI only — point it at a site you're already running
#
# In the page, target = http://localhost:3000, hit Crawl. The model hallucinates each page as
# the crawler reaches it. Press Enter in this window to stop the servers.
param([switch]$NoBackend)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$backend = $null
if (-not $NoBackend) {
    Write-Host "Starting model-backed store (genserver.py) on :3000..." -ForegroundColor Cyan
    $backend = Start-Process python -ArgumentList "genserver.py" -PassThru -WindowStyle Hidden
}

Write-Host "Starting Augur UI on :7000..." -ForegroundColor Cyan
$srv = Start-Process python -ArgumentList "serve.py" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1
Start-Process "http://localhost:7000"

Write-Host "`nAugur UI: http://localhost:7000   (the store is being generated by the model)" -ForegroundColor Green
Read-Host "Press Enter to stop the servers"

if ($srv)     { Stop-Process -Id $srv.Id     -Force -ErrorAction SilentlyContinue }
if ($backend) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
Write-Host "Stopped." -ForegroundColor Cyan
'@
Write-Host '  wrote view-augur.ps1'

Write-Host 'Done. 12 files written.' -ForegroundColor Green