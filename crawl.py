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
