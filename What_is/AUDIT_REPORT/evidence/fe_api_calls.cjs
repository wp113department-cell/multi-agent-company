// Evidence script (Audit 01/12): use the TypeScript compiler AST to list every
// "/api/..." URL the frontend builds, with the HTTP method from the enclosing
// call's init object (default GET). Run from apps/web:
//   node ../../What_is/AUDIT_REPORT/evidence/fe_api_calls.cjs > /tmp/fe_calls.json
const ts = require("typescript"), fs = require("fs"), path = require("path");
const roots = ["lib", "app", "components", "hooks"].filter(fs.existsSync);
const files = [];
const walk = d => fs.readdirSync(d, { withFileTypes: true }).forEach(e => {
  const p = path.join(d, e.name);
  if (e.isDirectory() && e.name !== "node_modules") walk(p);
  else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\./.test(e.name)) files.push(p);
});
roots.forEach(walk);
const out = [];
for (const f of files) {
  const sf = ts.createSourceFile(f, fs.readFileSync(f, "utf8"), ts.ScriptTarget.Latest, true);
  const visit = n => {
    let url = null;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) url = n.text;
    else if (ts.isTemplateExpression(n)) {
      url = n.head.text + n.templateSpans.map(s => "{x}" + s.literal.text).join("");
    }
    if (url && url.startsWith("/api/")) {
      let method = "GET", p = n.parent;
      while (p && !ts.isCallExpression(p)) p = p.parent;
      if (p && p.arguments.length > 1 && ts.isObjectLiteralExpression(p.arguments[1])) {
        for (const prop of p.arguments[1].properties)
          if (prop.name && prop.name.getText() === "method" && ts.isStringLiteral(prop.initializer))
            method = prop.initializer.text.toUpperCase();
      }
      const { line } = sf.getLineAndCharacterOfPosition(n.getStart());
      out.push({ file: f, line: line + 1, method, url: url.split("?")[0].replace(/\{x\}$/, m => m) });
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
}
console.log(JSON.stringify(out, null, 1));
