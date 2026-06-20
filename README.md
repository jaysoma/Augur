# Augur â€” browser-free, model-driven site mapper & tester

No Chromium. Plain HTTP + raw HTML. A local fast model (Ollama) is the oracle.

## Pipeline
1. `affordances.py` â€” raw HTML â†’ every click/submit as a fireable HTTP request (links=GET, forms=POST w/ fields, CSRF tokens lifted automatically). Deterministic, no model.
2. `model_layer.py` â€” the model layer: `describe_page()` classifies a page; `infer_expected()` predicts a request's expected response (the test oracle). Talks to Ollama; stub fallback offline.
3. `crawl.py` â€” FIRST PASS: model parses each page, crawler follows every internal link â†’ site **tree**.
4. `runner.py` â€” fires each affordance and diffs actual vs the oracle's expectation â†’ pass/fail.
5. `mockshop.py` â€” a tiny multi-page server-rendered site to run against with no Spree.

## Run (live, with your model)
Ollama up + `llama3.2:3b` pulled. Two terminals:

    python mockshop.py                     # terminal 1: target on :3000
    python crawl.py http://localhost:3000  # terminal 2: real model builds the tree

Point `crawl.py` / `runner.py` at any server-rendered site (e.g. your Spree on :3000).

## Config (env)
    TESTER_MODEL    default llama3.2:3b   (try qwen2.5:1.5b / llama3.2:1b for more speed)
    TESTER_OLLAMA   default http://localhost:11434
    TESTER_STUB=1   force the offline deterministic oracle (no model)
