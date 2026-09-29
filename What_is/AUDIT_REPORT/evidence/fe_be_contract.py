"""Evidence script (Audit 01/12): match each frontend API call (from
fe_api_calls.cjs) to a backend OpenAPI operation (method + path template).
Usage: python fe_be_contract.py <fe_calls.json> <openapi.json>"""
import json, re, sys
calls = json.load(open(sys.argv[1])); spec = json.load(open(sys.argv[2]))
ops = [(m.upper(), p) for p, v in spec["paths"].items() for m in v]
def rx(p): return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(p)) + "$")
compiled = [(m, p, rx(p)) for m, p in ops]
miss = []
for c in calls:
    url = c["url"].replace("{x}", "X").rstrip("/") or "/"
    hits = [(m, p) for m, p, r in compiled if r.match(url)]
    meth = [h for h in hits if h[0] == c["method"]]
    if not meth:
        miss.append({**c, "path_exists_other_methods": sorted({m for m, _ in hits})})
used = set()
for c in calls:
    url = c["url"].replace("{x}", "X").rstrip("/")
    for m, p, r in compiled:
        if r.match(url) and m == c["method"]: used.add((m, p))
print(json.dumps({"frontend_calls": len(calls), "unmatched": miss,
  "backend_ops": len(ops), "backend_ops_with_no_frontend_caller": len(set(ops) - used)}, indent=1))
