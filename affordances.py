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
