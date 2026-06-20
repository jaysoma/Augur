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


# â”€â”€ page describe (for the crawl tree) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ analyze_page (crawl: classify + discover every interactive element) â”€â”€â”€â”€â”€â”€â”€
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
