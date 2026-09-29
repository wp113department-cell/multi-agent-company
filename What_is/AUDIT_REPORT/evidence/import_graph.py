"""Evidence script (Audit 01/11): build the app/ import graph from the Python AST.
Reports (a) module-level import cycles (top-level imports only; imports inside
functions are deferred and cannot cause import-time cycles), and (b) modules with
zero importers anywhere in app/ (candidates for orphan review).
Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/import_graph.py"""
import ast, os, sys, json
import networkx as nx

ROOT = "app"
mods = {}
for dp, _, fs in os.walk(ROOT):
    for f in fs:
        if f.endswith(".py"):
            p = os.path.join(dp, f)
            m = p[:-3].replace(os.sep, ".")
            if m.endswith(".__init__"): m = m[:-9]
            mods[m] = p

def resolve(cur, node):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    base = node.module or ""
    if node.level:
        parts = cur.split(".")
        pkg = parts if mods.get(cur, "").endswith("__init__.py") else parts[:-1]
        pkg = pkg[: len(pkg) - (node.level - 1)]
        base = ".".join(pkg + ([base] if base else []))
    out = [base]
    for a in node.names:
        out.append(f"{base}.{a.name}")
    return out

top = nx.DiGraph(); anyg = nx.DiGraph()
for m, p in mods.items():
    tree = ast.parse(open(p).read())
    top.add_node(m); anyg.add_node(m)
    toplevel = set(id(n) for n in tree.body)
    # top-level = direct children of module body, plus those under top-level if/try (not TYPE_CHECKING)
    def walk_top(nodes):
        for n in nodes:
            if isinstance(n, (ast.Import, ast.ImportFrom)): yield n
            elif isinstance(n, ast.If):
                t = ast.unparse(n.test)
                if "TYPE_CHECKING" in t: continue
                yield from walk_top(n.body); yield from walk_top(n.orelse)
            elif isinstance(n, ast.Try):
                yield from walk_top(n.body)
    for n in walk_top(tree.body):
        for t in resolve(m, n):
            if t in mods and t != m: top.add_edge(m, t)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for t in resolve(m, n):
                if t in mods and t != m: anyg.add_edge(m, t)

cycles = [c for c in nx.simple_cycles(top) if len(c) > 1]
# importers from tests/ and scripts too
ext_refs = set()
for d in ("tests", "scripts", "migrations"):
    for dp, _, fs in os.walk(d):
        for f in fs:
            if f.endswith(".py"):
                src = open(os.path.join(dp, f), errors="ignore").read()
                for m in mods:
                    if m in src: ext_refs.add(m)
entry = {"app.main", "app", "app.config"}
orphans = sorted(m for m in mods if anyg.in_degree(m) == 0 and m not in entry and not m.endswith("__init__"))
print(json.dumps({
  "modules": len(mods),
  "toplevel_import_cycles": cycles,
  "zero_importer_modules_in_app": orphans,
  "zero_importer_and_not_even_in_tests": [m for m in orphans if m not in ext_refs],
}, indent=1))
