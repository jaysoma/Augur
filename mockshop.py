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
