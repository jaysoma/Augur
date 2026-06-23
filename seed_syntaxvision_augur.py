#!/usr/bin/env python3
"""
seed_syntaxvision_augur.py — Claude's analysis of the Augur pipeline files.
Writes Annotations and ControlFlow docs to the SyntaxVision MongoDB database.
Run once; upserts safely on re-run.
"""
import os, sys, datetime
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB        = "SyntaxVision"
APP       = "Augur"
MODEL     = "claude"
HERE      = os.path.dirname(os.path.abspath(__file__))

def db():
    cli = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    cli.admin.command("ping")
    return cli[DB]

def line_count(filename):
    with open(os.path.join(HERE, filename), encoding="utf-8") as f:
        return sum(1 for _ in f)

def upsert_annotations(database, filename, by_line):
    n = line_count(filename)
    entries = [
        {"line_number": i, "claude_annotation": by_line.get(i), "ollama_annotation": None}
        for i in range(1, n + 1)
    ]
    database["Annotations"].replace_one(
        {"app": APP, "file": filename},
        {"app": APP, "file": filename, "annotations": entries},
        upsert=True
    )
    annotated = sum(1 for e in entries if e["claude_annotation"])
    print(f"  Annotations: {filename} — {n} lines, {annotated} annotated")

def upsert_control_flow(database, filename, tree):
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    database["ControlFlow"].replace_one(
        {"app": APP, "file": filename, "model": MODEL},
        {"app": APP, "file": filename, "model": MODEL,
         "execution": {"timestamp": now, "status": "success"},
         "tree": tree},
        upsert=True
    )
    print(f"  ControlFlow:  {filename} (model={MODEL})")


# ── affordances.py ────────────────────────────────────────────────────────────

AFFORDANCES_ANNOTATIONS = {
    1:  "Module docstring — describes this file as the deterministic half of Augur: pure stdlib HTML parser that turns any page into a list of fireable HTTP request specs, with no browser, no model, and no running app required.",
    3:  "Import json for CLI output, sys for reading stdin args, HTMLParser for DOM walking, and urljoin to resolve relative URLs against the page base.",
    7:  "Affordances — an HTMLParser subclass that accumulates every link and form on a page as a structured request spec.",
    8:  "Initialize the base URL (used to resolve relative hrefs/actions) and the requests list; set form to None to indicate no form is currently open.",
    13: "handle_starttag() — called by HTMLParser for every opening tag; dispatches on tag name to collect links and form elements.",
    14: "Convert the attrs list of tuples to a dict for convenient key access.",
    15: "Is this an <a> tag with an href? → YES — record a GET link request spec / NO — check for form tags.",
    20: "Is this a <form> tag? → YES — open a new form context with its method (defaulting to GET) and action URL / NO — check for input tags.",
    26: "Is this an input, select, or textarea inside an open form? → YES — add its name/value pair to the form's fields dict / NO — ignore.",
    31: "handle_endtag() — called for every closing tag; when </form> is seen, finalize and record the accumulated form spec.",
    32: "Is this a closing </form> and is a form currently open? → YES — append it to requests and reset form to None / NO — do nothing.",
    35: "extract() — public API: instantiate an Affordances parser, feed it the HTML, and return the list of request specs.",
    38: "CLI entry point — read an HTML file (or landing.html by default), extract affordances, and print them in a human-readable format followed by full JSON.",
}

AFFORDANCES_TREE = {
    "name": "affordances.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 5,
            "annotation": "Module docstring and imports — json, sys, HTMLParser, urljoin. No third-party deps; this file is intentionally pure stdlib.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "Affordances",
            "type": "function",
            "line_start": 7, "line_end": 33,
            "annotation": "HTMLParser subclass that walks an HTML document and emits every link and form as a structured {kind, method, url, fields, label} request spec — the input feed for both the model layer and the runner.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "link_collection",
                    "type": "if",
                    "line_start": 15, "line_end": 19,
                    "annotation": "Is this tag an <a> with an href? → YES — append a GET link spec with the resolved URL / NO — check for form tags.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "form_open",
                    "type": "if",
                    "line_start": 20, "line_end": 25,
                    "annotation": "Is this a <form> tag? → YES — open a new form context (method defaults to GET, action resolved via urljoin) / NO — check for input-type tags.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "field_collection",
                    "type": "if",
                    "line_start": 26, "line_end": 29,
                    "annotation": "Is this an input/select/textarea with a name attribute inside an open form? → YES — record its name/value pair in the form's fields dict / NO — ignore.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "form_close",
                    "type": "if",
                    "line_start": 32, "line_end": 33,
                    "annotation": "Is this a closing </form> with a form open? → YES — finalize the form spec and reset self.form to None / NO — do nothing.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "extract",
            "type": "function",
            "line_start": 35, "line_end": 36,
            "annotation": "Public API — instantiate Affordances with the base URL, feed it the HTML, and return the accumulated request specs list.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "cli_entrypoint",
            "type": "block",
            "line_start": 38, "line_end": 49,
            "annotation": "CLI mode — read an HTML file, extract affordances, print each one in a human-readable line, then dump the full list as JSON so it can be piped to the model layer.",
            "on_happy_path": True, "captured": None, "children": []
        }
    ]
}


# ── crawl.py ──────────────────────────────────────────────────────────────────

CRAWL_ANNOTATIONS = {
    1:  "Module docstring — describes this as the first-pass crawler: the model parses each page and the crawler follows every internal GET link, building a site tree. Offline mode available via TESTER_STUB=1.",
    3:  "Import sys and json for output, time for timing, requests for HTTP, urlparse for host filtering, and the two local modules: affordances for link extraction, model_layer for page description.",
    9:  "ORACLE — display string indicating whether the model or the offline stub is answering; shown in the crawl header.",
    12: "log() — write a progress message to stderr so crawl tree output on stdout stays clean.",
    16: "crawl() — depth-first recursive crawler: fetches each page, asks the model to describe it, records it as a node, then recurses into every internal GET link.",
    17: "Parse the base URL to extract the host for same-origin filtering.",
    18: "sess — a persistent requests.Session for connection reuse; seen — visited URL set; nodes — url-keyed result dict; order — mutable int for sequential node numbering.",
    24: "visit() — inner recursive function: normalize the URL, guard against revisits and the page cap, fetch, describe, record, and recurse.",
    25: "Normalize the URL — strip fragment, trailing slash, and fall back to base for empty strings.",
    26: "Has this URL already been visited or have we hit the page cap? → YES — return the existing node or None / NO — continue.",
    33: "Fetch the page HTML; on any error record an error node and return without recursing.",
    35: "fetch error handler — record an error node with the exception message so the tree shows the failure point.",
    41: "Call describe_page() to classify the URL and summarize the page content in ≤8 words.",
    45: "Build the node dict and register it in the nodes map.",
    49: "Extract all affordances from the page, but filter to internal GET links only — POST form submits are state changes, not navigation to follow.",
    55: "Count newly-discovered links (not yet in seen) for the log line.",
    60: "Recurse into each child URL and append the returned node to this node's children list.",
    62: "Is the child node non-None and not already a child of this node (by URL)? → YES — append it / NO — skip.",
}

CRAWL_TREE = {
    "name": "crawl.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 9,
            "annotation": "Module docstring, imports, and the ORACLE display string — sets up sys, json, time, requests, urlparse, and the two local modules (affordances, model_layer).",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_log",
            "type": "function",
            "line_start": 12, "line_end": 13,
            "annotation": "Write a progress line to stderr — keeps the crawl tree + JSON output on stdout clean for piping.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "crawl",
            "type": "function",
            "line_start": 16, "line_end": 62,
            "annotation": "Depth-first recursive site crawler — fetches each page, classifies it via the model layer, records it as a tree node, then follows all internal GET links up to max_pages.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "visit",
                    "type": "function",
                    "line_start": 24, "line_end": 62,
                    "annotation": "Inner recursive visit function — normalize URL, guard revisits, fetch HTML, describe with model, build node, filter to same-origin GET links, recurse.",
                    "on_happy_path": True, "captured": None,
                    "children": [
                        {
                            "name": "already_seen_guard",
                            "type": "if",
                            "line_start": 26, "line_end": 27,
                            "annotation": "Has this URL been visited or is the page cap reached? → YES — short-circuit and return the cached node or None / NO — continue.",
                            "on_happy_path": False, "captured": None, "children": []
                        },
                        {
                            "name": "fetch_error_handler",
                            "type": "except",
                            "line_start": 35, "line_end": 37,
                            "annotation": "Did the HTTP fetch raise? → YES — record an error node with the exception message and return without recursing.",
                            "on_happy_path": False, "captured": None, "children": []
                        },
                        {
                            "name": "get_links_only_filter",
                            "type": "block",
                            "line_start": 49, "line_end": 54,
                            "annotation": "Filter affordances to same-origin GET links only — POST form submits are state mutations, not navigable pages to recurse into.",
                            "on_happy_path": True, "captured": None, "children": []
                        },
                        {
                            "name": "recurse_children",
                            "type": "block",
                            "line_start": 60, "line_end": 62,
                            "annotation": "Recurse into each child URL and append the returned node to this node's children list if valid and not a duplicate.",
                            "on_happy_path": True, "captured": None, "children": []
                        }
                    ]
                }
            ]
        }
    ]
}


# ── genserver.py ──────────────────────────────────────────────────────────────

GENSERVER_ANNOTATIONS = {
    1:  "Module docstring — describes the core concept: a commerce site with no code and no database. The Ollama model IS the backend; every page is generated on demand from a single system prompt describing the store.",
    17: "Import os for environment variables, json and re for request/response handling, urllib.request for the Ollama API call, and the stdlib HTTP server classes.",
    21: "OLLAMA — the Ollama server base URL, configurable via environment variable.",
    22: "MODEL — the Ollama model tag to use for page generation; defaults to qwen2.5:3b, overridable via GENSERVER_MODEL or TESTER_MODEL.",
    23: "PORT — the port genserver listens on; defaults to 3000.",
    25: "STORE — the plain-English description of the store the model is asked to emulate; fully configurable via GENSERVER_STORE env var.",
    30: "SYS — the system prompt that turns the model into a store backend: rules for page structure, link density, slug variety, and output format (raw HTML only, no markdown).",
    51: "CACHE — in-memory dict keying generated HTML by path+note so repeated requests for the same page return the same markup within a single run.",
    54: "_strip_fences() — remove markdown code fences that small models sometimes wrap their HTML output in.",
    61: "generate() — the core function: check the cache, build the Ollama chat request, call the model, strip fences, wrap bare content in html/body if needed, cache and return.",
    63: "Is this path+note already in CACHE? → YES — return the cached HTML immediately / NO — call the model.",
    65: "Build the user message — the HTTP path, optionally annotated with a note for POST result pages.",
    66: "Build the Ollama request body — model, no streaming, keep_alive to hold the model resident between requests, temperature 0.4 for varied but coherent slugs.",
    72: "Make the POST request to Ollama's /api/chat endpoint with a 2-minute timeout.",
    74: "Extract the generated HTML from the response; strip any markdown fences the model added.",
    76: "Is <html> missing from the output? → YES — wrap the content in minimal html/body tags / NO — use as-is.",
    78: "generation error handler — if Ollama fails or times out, return a minimal error HTML page so the crawler records an error node instead of crashing.",
    84: "Handler — HTTP request handler for the genserver; routes all GETs and POSTs through generate().",
    85: "_send() — encode the HTML body as UTF-8 and write a 200 response with Content-Type and Content-Length headers.",
    93: "do_GET() — parse the request path, skip favicon.ico (returns 404), and call generate() for all other paths.",
    99: "do_POST() — call generate() with a note indicating this is a POST result page, so the model produces a confirmation/redirect-style response.",
    103: "log_message() — suppress the default per-request log line.",
    107: "Entry point — print startup info and start a ThreadingHTTPServer on localhost so multiple crawler threads can request pages concurrently.",
}

GENSERVER_TREE = {
    "name": "genserver.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 23,
            "annotation": "Module docstring, imports, and configuration constants — OLLAMA endpoint, MODEL tag, PORT, STORE description, and the SYS prompt that makes the model behave as a store backend.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "store_system_prompt",
            "type": "block",
            "line_start": 25, "line_end": 51,
            "annotation": "STORE and SYS — the two strings that define the entire store: STORE names what it is, SYS gives the model its page-generation rules (nav structure, link density, slug variety, output format). Changing STORE or SYS is how you swap one store for another.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_strip_fences",
            "type": "function",
            "line_start": 54, "line_end": 58,
            "annotation": "Strip markdown code fences from model output — small models sometimes wrap HTML in ```html...``` blocks despite being told not to.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "generate",
            "type": "function",
            "line_start": 61, "line_end": 81,
            "annotation": "Core generation function — cache lookup, Ollama chat call, fence stripping, html/body wrapping, error fallback, and cache write. Every page in the store passes through here.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "cache_hit",
                    "type": "if",
                    "line_start": 63, "line_end": 64,
                    "annotation": "Is this path already cached from this run? → YES — return immediately / NO — call the model.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "missing_html_wrapper",
                    "type": "if",
                    "line_start": 76, "line_end": 77,
                    "annotation": "Did the model return content without an <html> tag? → YES — wrap it in minimal html/body so the HTML parser doesn't choke / NO — use as-is.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "generation_error_handler",
                    "type": "except",
                    "line_start": 78, "line_end": 79,
                    "annotation": "Did the Ollama call fail (timeout, connection error, bad JSON)? → YES — return a minimal error HTML page so the crawler can record the failure without crashing.",
                    "on_happy_path": False, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "Handler",
            "type": "function",
            "line_start": 84, "line_end": 104,
            "annotation": "HTTP request handler — all GETs and POSTs route through generate(); favicon returns 404; log_message suppressed.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "favicon_skip",
                    "type": "if",
                    "line_start": 95, "line_end": 96,
                    "annotation": "Is this a favicon.ico request? → YES — return 404 immediately; browsers always ask for it and the model shouldn't waste a generation slot on it.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "do_POST_note",
                    "type": "block",
                    "line_start": 99, "line_end": 101,
                    "annotation": "POST handler — passes a note to generate() so the model knows to produce a form-submission result page (confirmation, redirect content) rather than a navigation page.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "server_entrypoint",
            "type": "block",
            "line_start": 107, "line_end": 109,
            "annotation": "Entry point — print startup info and start a ThreadingHTTPServer on localhost:3000 so concurrent crawler requests are handled without queuing.",
            "on_happy_path": True, "captured": None, "children": []
        }
    ]
}


# ── mockshop.py ───────────────────────────────────────────────────────────────

MOCKSHOP_ANNOTATIONS = {
    1:  "Module docstring — describes this as a hand-coded multi-page mock site for testing the crawler when the model-generated genserver is not needed.",
    3:  "Import http.server for the BaseHTTPRequestHandler and HTTPServer, urllib.parse for URL parsing.",
    6:  "SITE — static dict mapping each path to its list of internal links; defines the complete fixed topology of the mock store.",
    15: "FORMS — two hardcoded form HTML strings to inject on the landing page: a search GET form and an add-to-cart POST form with a CSRF token field.",
    19: "H — the request handler; _html() sends a minimal HTML response with the given status code.",
    23: "do_GET() — parse the path; if it's in SITE render links + optional forms; otherwise return 404.",
    25: "Is this path in the SITE map? → YES — render its links as <a> tags plus the forms if this is the root / NO — return 404.",
    30: "do_POST() — only /cart/add is handled; it issues a 302 redirect to /cart to simulate a real add-to-cart flow.",
    32: "Is this POST to /cart/add? → YES — redirect to /cart / NO — return 404.",
    35: "log_message() — suppress request logging.",
    37: "Entry point — start a plain (single-threaded) HTTPServer on localhost:3000.",
}

MOCKSHOP_TREE = {
    "name": "mockshop.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 17,
            "annotation": "Module docstring, imports, the SITE topology dict, and the FORMS HTML string — everything that defines the mock store's structure lives here as static data.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "H",
            "type": "function",
            "line_start": 19, "line_end": 35,
            "annotation": "Request handler — do_GET renders link pages from SITE or 404s; do_POST handles only /cart/add with a 302 redirect.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "known_path",
                    "type": "if",
                    "line_start": 25, "line_end": 28,
                    "annotation": "Is this path in SITE? → YES — render its links as anchor tags, adding forms on the root page / NO — return 404.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "cart_add_redirect",
                    "type": "if",
                    "line_start": 32, "line_end": 33,
                    "annotation": "Is this POST to /cart/add? → YES — issue a 302 to /cart (simulates a real cart mutation) / NO — return 404.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "server_entrypoint",
            "type": "block",
            "line_start": 37, "line_end": 38,
            "annotation": "Entry point — start a single-threaded HTTPServer on localhost:3000; single-threaded is fine since the mock serves static data instantly.",
            "on_happy_path": True, "captured": None, "children": []
        }
    ]
}


# ── model_layer.py ────────────────────────────────────────────────────────────

MODEL_LAYER_ANNOTATIONS = {
    1:  "Module docstring — describes this as the model layer: given an affordance (a latent HTTP request spec), infer the expected response as a test oracle. Falls back to a deterministic stub if Ollama is unavailable.",
    9:  "Import os for env vars, json for request/response encoding, urllib.request and urllib.error for the Ollama HTTP call.",
    11: "MODEL — the Ollama model tag; defaults to llama3.2:3b (fast, for oracle use).",
    12: "OLLAMA — the Ollama server base URL.",
    13: "STUB — if TESTER_STUB=1, all oracle calls are answered by the deterministic stub regardless of model availability.",
    15: "SYS — the oracle system prompt: given a request spec, predict the expected HTTP response as JSON with status, content-type, expect_contains, expect_absent, and rationale.",
    25: "_ollama() — call the Ollama model with the request spec and return the parsed oracle prediction JSON.",
    35: "Build and send the Ollama chat request — JSON format enforced, temperature 0 for deterministic oracle answers, keep_alive to hold the model resident.",
    40: "_stub() — deterministic offline oracle: GET → 200 HTML; POST → 302 redirect. Uses the URL tail as the expected content hint.",
    43: "Is this a GET? → YES — predict a 200 HTML response containing the path tail / NO — predict a 302 redirect (POST = state mutation).",
    53: "infer_expected() — public API: route to stub if STUB=1, otherwise call Ollama and fall back to the stub on any error.",
    54: "Is STUB mode on? → YES — return the deterministic stub prediction / NO — try the model.",
    56: "Try the Ollama oracle; on any network, parse, or key error fall back to the stub and prefix the rationale with '[stub: model unreachable]'.",
    62: "CLI entry point — extract affordances from landing.html and print oracle predictions for each.",
    73: "PAGE_SYS — system prompt for page classification: given a URL and HTML snippet, return a JSON {type, summary} label.",
    77: "describe_page() — classify a page by URL and HTML. Uses model if STUB is off; falls back to _describe_stub() on any error.",
    78: "Is STUB mode on? → YES — use the heuristic stub / NO — call the model.",
    90: "describe_page error handler — on any exception from the model call, fall back to the deterministic stub.",
    93: "_describe_stub() — heuristic page classifier: infers type from the URL path tail (home, product, listing, cart, checkout, auth, other).",
    102: "analyze_page() — combined page analysis used by the live crawl in serve.py: classify the page AND extract every interactive element from it.",
    111: "Is AUGUR_CLASSIFY=model? → YES — use the model for classification / NO — use the fast URL heuristic.",
    113: "Extract all affordances from the page HTML; on any parse error return an empty list.",
    120: "Deduplicate elements by (method, url, fields-keyset) so the same link appearing multiple times in nav/body only fires once.",
    129: "Return the combined result: page type, summary, and deduplicated elements list.",
}

MODEL_LAYER_TREE = {
    "name": "model_layer.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 23,
            "annotation": "Module docstring, imports, configuration constants (MODEL, OLLAMA, STUB), and SYS — the oracle system prompt that defines what infer_expected() asks the model to predict.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_ollama",
            "type": "function",
            "line_start": 25, "line_end": 38,
            "annotation": "Call the Ollama model with a request spec and return the parsed oracle prediction — JSON format enforced, temperature 0 for deterministic answers.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_stub",
            "type": "function",
            "line_start": 40, "line_end": 51,
            "annotation": "Deterministic offline oracle — GET links predict 200 HTML; POST forms predict 302 redirects. No model needed; used when TESTER_STUB=1 or Ollama is unreachable.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "get_vs_post_branch",
                    "type": "if",
                    "line_start": 43, "line_end": 51,
                    "annotation": "Is this a GET? → YES — predict 200 HTML with the path tail as expected content / NO — predict a 302 redirect as POST = state mutation.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "infer_expected",
            "type": "function",
            "line_start": 53, "line_end": 60,
            "annotation": "Public oracle API — route to the stub if STUB=1, otherwise call Ollama and fall back to the stub with a warning prefix on any error.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "stub_mode",
                    "type": "if",
                    "line_start": 54, "line_end": 55,
                    "annotation": "Is TESTER_STUB=1? → YES — return the deterministic stub answer immediately / NO — try the model.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "ollama_fallback",
                    "type": "except",
                    "line_start": 58, "line_end": 60,
                    "annotation": "Did the Ollama call fail? → YES — fall back to _stub() and prefix the rationale with '[stub: model unreachable]' so the caller knows the oracle degraded.",
                    "on_happy_path": False, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "describe_page",
            "type": "function",
            "line_start": 77, "line_end": 91,
            "annotation": "Classify a page by URL and HTML snippet — calls the model for a {type, summary} label, or falls back to the heuristic stub on STUB mode or any error.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "describe_stub_mode",
                    "type": "if",
                    "line_start": 78, "line_end": 79,
                    "annotation": "Is STUB mode on? → YES — use the URL heuristic immediately / NO — call the model.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "describe_error_handler",
                    "type": "except",
                    "line_start": 90, "line_end": 91,
                    "annotation": "Did the model call raise for any reason? → YES — fall back to the deterministic stub silently.",
                    "on_happy_path": False, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "_describe_stub",
            "type": "function",
            "line_start": 93, "line_end": 99,
            "annotation": "Heuristic page classifier — infers page type from URL path structure (home, product, listing, cart, checkout, auth, other) with no model call.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "analyze_page",
            "type": "function",
            "line_start": 105, "line_end": 131,
            "annotation": "Combined analysis for the live crawl — classify the page AND extract every interactive element, deduplicated by (method, url, fields-keyset). This is what serve.py calls per page during the agentic crawl.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "classification_branch",
                    "type": "if",
                    "line_start": 111, "line_end": 111,
                    "annotation": "Is AUGUR_CLASSIFY=model? → YES — use the model for a richer label / NO — use the fast URL heuristic (the default, to keep the crawl fast).",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "affordance_parse_error",
                    "type": "except",
                    "line_start": 117, "line_end": 118,
                    "annotation": "Did the HTML affordance parse raise? → YES — return an empty elements list and continue; a malformed page shouldn't stop the crawl.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "deduplication_loop",
                    "type": "block",
                    "line_start": 120, "line_end": 127,
                    "annotation": "Deduplicate elements by (method, url, sorted-fields-keys) so nav links repeated in header/footer/body only generate one crawl edge.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        }
    ]
}


# ── runner.py ─────────────────────────────────────────────────────────────────

RUNNER_ANNOTATIONS = {
    1:  "Module docstring — describes the full oracle loop: GET landing page, extract affordances, ask the model to predict expected responses, fire each request, compare actual vs expected.",
    3:  "Import sys for CLI args, requests for HTTP, affordances.extract for link/form discovery, and model_layer for the oracle and configuration constants.",
    8:  "fire() — execute one affordance: GET links with allow_redirects=False so we can check 302s; POST forms with their field dict.",
    11: "Is this a GET? → YES — send a GET request (no redirects) / NO — send a POST with the form fields.",
    15: "check() — compare the actual response against the oracle's prediction; return a list of failure reasons (empty = pass).",
    16: "Collect failure reasons: wrong status code, missing expected substrings in the body or Location header, unexpected substrings in the body.",
    28: "main() — the full loop: fetch the landing page, extract affordances, get oracle predictions, fire each, check each, print PASS/FAIL, print totals.",
    29: "Create a session and fetch the landing page HTML.",
    30: "Extract affordances from the landing page.",
    35: "For each affordance: get the oracle prediction, fire the request, check the result, print PASS or FAIL with details.",
    37: "Did the HTTP request raise? → YES — print FAIL with the error and continue to the next affordance / NO — compare the response.",
    40: "Did check() return any failure reasons? → YES — print FAIL with expected vs actual detail / NO — increment npass and print PASS.",
}

RUNNER_TREE = {
    "name": "runner.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 6,
            "annotation": "Module docstring and imports — sys, requests, affordances.extract, and model_layer (infer_expected, MODEL, STUB).",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "fire",
            "type": "function",
            "line_start": 8, "line_end": 13,
            "annotation": "Execute one affordance — GET links use allow_redirects=False so 302s are visible for checking; POST forms send the field dict.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "get_vs_post",
                    "type": "if",
                    "line_start": 11, "line_end": 13,
                    "annotation": "Is this a GET? → YES — plain GET with no redirect following / NO — POST with the form fields dict.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "check",
            "type": "function",
            "line_start": 15, "line_end": 26,
            "annotation": "Compare actual response against oracle prediction — checks status code, expect_contains substrings (in body + Location header), and expect_absent substrings. Returns a list of failure reasons; empty = pass.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "main",
            "type": "function",
            "line_start": 28, "line_end": 48,
            "annotation": "Full oracle loop — fetch landing page, extract affordances, for each: get prediction, fire request, check result, print PASS/FAIL. Prints totals at the end.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "request_error_handler",
                    "type": "except",
                    "line_start": 38, "line_end": 39,
                    "annotation": "Did the HTTP request raise (connection error, timeout)? → YES — print FAIL with the error message and continue to the next affordance.",
                    "on_happy_path": False, "captured": None, "children": []
                },
                {
                    "name": "fail_branch",
                    "type": "if",
                    "line_start": 40, "line_end": 44,
                    "annotation": "Did check() return any failure reasons? → YES — print FAIL with expected vs actual detail / NO — increment pass count and print PASS.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "cli_entrypoint",
            "type": "block",
            "line_start": 50, "line_end": 51,
            "annotation": "Entry point — call main() with the CLI base URL argument or the default localhost:3000.",
            "on_happy_path": True, "captured": None, "children": []
        }
    ]
}


# ── serve.py ──────────────────────────────────────────────────────────────────

SERVE_ANNOTATIONS = {
    1:  "Module docstring — describes serve.py as the Augur live UI server: serves tree.html and streams the agentic crawl to the browser as Server-Sent Events, one event per page.",
    10: "Import os, sys, re, json, time for utilities; ThreadingHTTPServer for concurrent connections; urlparse, parse_qs, unquote for URL handling; requests for the crawl HTTP calls; and model_layer for page analysis.",
    16: "HERE — absolute path of serve.py's directory, used to locate tree.html.",
    17: "PORT — the UI server port; defaults to 7000.",
    18: "ORACLE — display string shown in the UI header and startup message.",
    21: "GEN_BASE and PROXY_PREFIX — the reverse-proxy configuration: all requests under /gen/ are forwarded to genserver on :3000, so the entire app is reachable through one tunnel.",
    26: "_log() — write a progress line to stderr for terminal liveness monitoring.",
    30: "_node_id() — generate a stable, unique ID for each crawl node: GET pages key by URL; form submits key by method+url+field-names so different forms to the same action are distinct nodes.",
    37: "crawl_events() — the agentic BFS crawler: starts from the given base URL, calls analyze_page() on each response to find every interactive element, then enqueues every element as a next interaction. Yields SSE event dicts throughout.",
    41: "Initialize the crawl state: base URL, host for origin filtering, a requests.Session, a seen set, and the BFS queue seeded with the root GET.",
    51: "Yield a 'start' event immediately so the UI can show the crawl target and oracle before the first fetch.",
    53: "BFS loop — pop the front of the queue; skip if already seen; mark seen; fetch; analyze; yield 'node'; enqueue new interactions.",
    58: "Announce the fetch BEFORE making it so the terminal and UI show what we're waiting on (fetches can take seconds).",
    63: "Fetch the page — GET or POST depending on the element type; 2-minute timeout to accommodate slow model-generated pages.",
    70: "fetch error handler — yield an error node event and continue to the next queue item.",
    77: "Call analyze_page() to classify the page and extract every interactive element.",
    83: "Build the abbreviated elements list (capped at 10) for the SSE payload — keeps the event small.",
    87: "Yield the 'node' SSE event with full crawl metadata: index, id, url, parent, depth, via, type, summary, timings, and elements.",
    95: "Interact with each element found on this page — enqueue every unseen link and form submit as a new BFS node.",
    98: "Is this element from a different host? → YES — skip it (stay same-origin) / NO — continue.",
    103: "Build via_lbl — human-readable description of how this node was reached (link or form submit label).",
    107: "Yield the 'done' event with total page count and elapsed seconds.",
    110: "Handler — HTTP request handler for the UI server.",
    111: "do_GET() — route / and tree.html to _sendfile, /crawl to _stream, /gen/* to _proxy, everything else 404.",
    113: "Is this / or /tree.html? → YES — serve tree.html / NO — check /crawl.",
    115: "Is this /crawl? → YES — start the SSE stream / NO — check the proxy prefix.",
    117: "Is this under the /gen/ proxy prefix? → YES — forward to genserver / NO — return 404.",
    121: "do_POST() — only proxy POST requests under /gen/ are handled; everything else 404.",
    127: "_proxy() — reverse-proxy a request to genserver: rewrite root-relative links in the response HTML to stay under /gen/ so the browser navigates through this server.",
    148: "Is the response HTML? → YES — rewrite href/action attributes from '/' to '/gen/' so all navigation stays proxied / NO — pass through as-is.",
    154: "Rewrite Location redirect headers back under the /gen/ prefix so POST→redirect flows stay inside the proxy.",
    167: "_stream() — parse the target URL from the query string and stream crawl_events() as SSE.",
    183: "_sendfile() — read a local file and send it with the given content-type; 404 if not found.",
    195: "log_message() — suppress the default per-request log line.",
    199: "Entry point — print startup info including the proxy mapping and start a ThreadingHTTPServer.",
}

SERVE_TREE = {
    "name": "serve.py",
    "type": "file",
    "children": [
        {
            "name": "module_header",
            "type": "block",
            "line_start": 1, "line_end": 23,
            "annotation": "Module docstring, imports, and configuration: HERE path, PORT, ORACLE label, GEN_BASE and PROXY_PREFIX for the reverse proxy to genserver.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_log",
            "type": "function",
            "line_start": 26, "line_end": 27,
            "annotation": "Write a progress line to stderr for terminal liveness — the SSE stream and HTTP responses use the socket, not stdout.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "_node_id",
            "type": "function",
            "line_start": 30, "line_end": 34,
            "annotation": "Generate a stable unique node ID — GET pages key by URL; form submits key by method+url+sorted-field-names so two different forms to the same action are distinct crawl nodes.",
            "on_happy_path": True, "captured": None, "children": []
        },
        {
            "name": "crawl_events",
            "type": "function",
            "line_start": 37, "line_end": 107,
            "annotation": "Agentic BFS crawler — the heart of Augur. Starts from base, fetches each page, calls analyze_page() to find every interactive element, enqueues each as a new interaction, and yields SSE event dicts throughout.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "crawl_init",
                    "type": "block",
                    "line_start": 41, "line_end": 51,
                    "annotation": "Initialize BFS state: base URL, host, session, seen set, and the queue seeded with the root GET. Yield the 'start' event immediately.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "bfs_loop",
                    "type": "block",
                    "line_start": 53, "line_end": 106,
                    "annotation": "BFS loop — pop queue front, skip if seen, mark seen, announce, fetch, analyze, yield 'node' event, enqueue new interactions.",
                    "on_happy_path": True, "captured": None,
                    "children": [
                        {
                            "name": "already_seen_skip",
                            "type": "if",
                            "line_start": 55, "line_end": 56,
                            "annotation": "Is this node already seen? → YES — skip it / NO — mark seen and continue.",
                            "on_happy_path": False, "captured": None, "children": []
                        },
                        {
                            "name": "fetch_error_handler",
                            "type": "except",
                            "line_start": 70, "line_end": 75,
                            "annotation": "Did the HTTP fetch raise? → YES — yield an error node event and continue to the next queue item without recursing.",
                            "on_happy_path": False, "captured": None, "children": []
                        },
                        {
                            "name": "enqueue_interactions",
                            "type": "block",
                            "line_start": 95, "line_end": 105,
                            "annotation": "For each element found on this page — skip off-host URLs, build the node ID, skip already-seen, label the via edge, and append to the BFS queue.",
                            "on_happy_path": True, "captured": None,
                            "children": [
                                {
                                    "name": "off_host_skip",
                                    "type": "if",
                                    "line_start": 98, "line_end": 99,
                                    "annotation": "Is this element's URL on a different host? → YES — skip it to keep the crawl same-origin / NO — enqueue it.",
                                    "on_happy_path": False, "captured": None, "children": []
                                }
                            ]
                        }
                    ]
                },
                {
                    "name": "done_event",
                    "type": "block",
                    "line_start": 107, "line_end": 107,
                    "annotation": "Yield the 'done' SSE event with total pages visited and elapsed seconds — signals the UI that the crawl is complete.",
                    "on_happy_path": True, "captured": None, "children": []
                }
            ]
        },
        {
            "name": "Handler",
            "type": "function",
            "line_start": 110, "line_end": 196,
            "annotation": "HTTP request handler — routes GET to tree.html, /crawl SSE stream, or /gen/ proxy; routes POST to /gen/ proxy only.",
            "on_happy_path": True, "captured": None,
            "children": [
                {
                    "name": "do_GET_routing",
                    "type": "block",
                    "line_start": 111, "line_end": 119,
                    "annotation": "Route GET requests: / or /tree.html → serve tree.html; /crawl → SSE stream; /gen/* → reverse proxy to genserver; else → 404.",
                    "on_happy_path": True, "captured": None, "children": []
                },
                {
                    "name": "_proxy",
                    "type": "function",
                    "line_start": 127, "line_end": 165,
                    "annotation": "Reverse-proxy a request to genserver — rewrites root-relative href/action attributes in HTML responses to stay under /gen/, and rewrites Location redirect headers too.",
                    "on_happy_path": True, "captured": None,
                    "children": [
                        {
                            "name": "proxy_error_handler",
                            "type": "except",
                            "line_start": 142, "line_end": 144,
                            "annotation": "Did the proxied request fail (genserver down or unreachable)? → YES — return 502 with the error message.",
                            "on_happy_path": False, "captured": None, "children": []
                        },
                        {
                            "name": "html_link_rewrite",
                            "type": "if",
                            "line_start": 148, "line_end": 152,
                            "annotation": "Is the response HTML? → YES — rewrite href/action from '/' to '/gen/' so all in-page navigation stays inside the proxy / NO — pass bytes through unchanged.",
                            "on_happy_path": True, "captured": None, "children": []
                        },
                        {
                            "name": "redirect_rewrite",
                            "type": "if",
                            "line_start": 156, "line_end": 162,
                            "annotation": "Is there a Location header? → YES — rewrite it back under /gen/ so POST→redirect flows remain inside the proxy.",
                            "on_happy_path": True, "captured": None, "children": []
                        }
                    ]
                },
                {
                    "name": "_stream",
                    "type": "function",
                    "line_start": 167, "line_end": 181,
                    "annotation": "SSE endpoint — parse the target URL from the query string, send SSE headers, then stream crawl_events() as newline-delimited 'data:' frames until done or the client disconnects.",
                    "on_happy_path": True, "captured": None,
                    "children": [
                        {
                            "name": "client_disconnect_handler",
                            "type": "except",
                            "line_start": 180, "line_end": 181,
                            "annotation": "Did the client disconnect mid-stream (BrokenPipeError or ConnectionResetError)? → YES — exit the stream loop silently.",
                            "on_happy_path": False, "captured": None, "children": []
                        }
                    ]
                },
                {
                    "name": "_sendfile",
                    "type": "function",
                    "line_start": 183, "line_end": 193,
                    "annotation": "Read a local file and send it with the given content-type. Returns 404 if the file is not found.",
                    "on_happy_path": True, "captured": None,
                    "children": [
                        {
                            "name": "file_not_found",
                            "type": "except",
                            "line_start": 187, "line_end": 188,
                            "annotation": "Is the requested file missing? → YES — return 404.",
                            "on_happy_path": False, "captured": None, "children": []
                        }
                    ]
                }
            ]
        },
        {
            "name": "server_entrypoint",
            "type": "block",
            "line_start": 199, "line_end": 202,
            "annotation": "Entry point — print startup info (port, oracle, proxy mapping) and start a ThreadingHTTPServer so multiple browser tabs and crawl connections are handled concurrently.",
            "on_happy_path": True, "captured": None, "children": []
        }
    ]
}


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="only seed this file (basename)")
    ap.add_argument("--drop", action="store_true", help="drop Augur entries from Annotations and ControlFlow first")
    args = ap.parse_args()

    print(f"Connecting to {MONGO_URI} -> {DB}")
    database = db()

    if args.drop:
        database["Annotations"].delete_many({"app": APP})
        database["ControlFlow"].delete_many({"app": APP})
        print(f"Dropped all {APP} entries from Annotations and ControlFlow.")

    files = [
        ("affordances.py",  AFFORDANCES_ANNOTATIONS,  AFFORDANCES_TREE),
        ("crawl.py",        CRAWL_ANNOTATIONS,         CRAWL_TREE),
        ("genserver.py",    GENSERVER_ANNOTATIONS,     GENSERVER_TREE),
        ("mockshop.py",     MOCKSHOP_ANNOTATIONS,      MOCKSHOP_TREE),
        ("model_layer.py",  MODEL_LAYER_ANNOTATIONS,   MODEL_LAYER_TREE),
        ("runner.py",       RUNNER_ANNOTATIONS,        RUNNER_TREE),
        ("serve.py",        SERVE_ANNOTATIONS,         SERVE_TREE),
    ]

    for filename, annotations, tree in files:
        if args.file and args.file != filename:
            continue
        print(f"\n{filename}")
        upsert_annotations(database, filename, annotations)
        upsert_control_flow(database, filename, tree)

    print("\nDone.")

if __name__ == "__main__":
    main()
