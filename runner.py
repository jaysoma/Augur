"""Closes the loop: GET landing page -> affordances -> oracle (model) -> FIRE -> compare.
  python runner.py [base_url]      default http://localhost:3000
Real model: ensure Ollama is up; runs llama3.2:3b. Offline demo: TESTER_STUB=1."""
import sys, requests
from affordances import extract
from model_layer import infer_expected, MODEL, STUB

def fire(sess, req):
    url, m, fields = req["url"], req["method"], req["fields"]
    if m == "GET":
        # don't actually submit the empty search form with junk; GET its action plainly
        return sess.get(url, allow_redirects=False, timeout=10)
    return sess.post(url, data=fields, allow_redirects=False, timeout=10)

def check(exp, resp):
    reasons = []
    if resp.status_code != exp["expected_status"]:
        reasons.append(f"status {resp.status_code}!={exp['expected_status']}")
    hay = (resp.text + " " + resp.headers.get("Location","")).lower()
    for s in exp.get("expect_contains", []):
        if s and s.lower() not in hay:
            reasons.append(f"missing '{s}'")
    for s in exp.get("expect_absent", []):
        if s and s.lower() in resp.text.lower():
            reasons.append(f"unexpected '{s}'")
    return reasons

def main(base="http://localhost:3000"):
    sess = requests.Session()
    html = sess.get(base, timeout=10).text
    reqs = extract(html, base + "/")
    print(f"Oracle: {'STUB' if STUB else MODEL}   target: {base}   ({len(reqs)} affordances)\n")
    npass = 0
    for r in reqs:
        exp = infer_expected(r)
        try:
            resp = fire(sess, r)
        except Exception as e:
            print(f"FAIL [{r['method']:4}] {r['url']}  -> request error: {e}"); continue
        reasons = check(exp, resp)
        if reasons:
            print(f"FAIL [{r['method']:4}] {r['url']}")
            print(f"       expected {exp['expected_status']} contains {exp.get('expect_contains')}; "
                  f"got {resp.status_code}. issues: {', '.join(reasons)}")
        else:
            npass += 1
            print(f"PASS [{r['method']:4}] {r['url']}  ({resp.status_code})")
    print(f"\n{npass}/{len(reqs)} passed.")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000")
