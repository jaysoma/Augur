"""genserver.py â€” a commerce site with NO code and NO database. The model IS the backend.

No seed data. A request for a path arrives; the model GENERATES the full HTML for that page
(a complex Spree-style store) including links to other plausible store paths. The crawler then
hits /, the model invents the landing page + its links, the crawler follows them, and each new
path is generated on demand â€” a website hallucinated into existence as it's explored.

  python genserver.py        # http://localhost:3000

FIRST PASS: pages are generated per request (cached in memory only for within-run consistency).
Persistence is intentionally skipped â€” the next step is to have the model infer a dataset,
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
    "exact page. It must be a LARGE, DEEP store â€” not a handful of pages. Rules:\n"
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
