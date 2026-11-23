"""Stage 5 – static checks for the Terraform code (no terraform binary is available here).

Usage:  python3 -m tools.iac.hclcheck [terraform] [--tfvars build/tfvars]

Rules
  HC01 every file scans cleanly: balanced braces / brackets / parentheses, terminated strings (incl. interpolation)
  HC02 every var.X used is declared, every declared variable is used; every variable and output has a description
  HC03 module calls: source exists; arguments are variables of the target; all required target variables are passed
  HC04 module.X.Y and terraform_remote_state outputs referenced exist; local.X referenced is declared
  HC05 every module and stack has versions.tf with required_version and a version constraint for every provider;
       every stack except bootstrap has a gcs backend
  HC06 generated tfvars for every stack instance match the stack's variables (no unknown key, every required one
       present, except values the pipeline provides: org_state_bucket, github_org_id, github_org)
  HC07 forbidden content: secret versions (values in state), legacy basic roles, literal passwords / private keys
Status: implemented + locally tested. Not a substitute for `terraform validate` / `plan` (T-TF1, T-TF2).
"""
import argparse
import json
import pathlib
import re
import sys

from tools.registry.validate import Finding

META = {"source", "count", "for_each", "depends_on", "providers", "version"}
PIPELINE_VARS = {"org_state_bucket", "github_org_id", "github_org"}


class ScanError(Exception):
    pass


def strip_and_check(text):
    """Remove comments, neutralise brackets inside strings (interpolations stay code); raise ScanError if unbalanced."""
    out, i, n = [], 0, len(text)
    stack = []                      # brace kinds; "I" = interpolation inside a string
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == "$" and text[i + 1:i + 2] == "{" and text[i - 1:i] != "$":
                stack.append("I")
                in_str = False
                out.append(" ")
                i += 2
                continue
            if c == '"':
                in_str = False
                out.append('"')
            else:
                out.append(" " if c in "{}[]()" else c)   # keep text (labels, sources), neutralise brackets
            i += 1
            continue
        if c == "#" or (c == "/" and text[i + 1:i + 2] == "/"):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and text[i + 1:i + 2] == "*":
            j = text.find("*/", i + 2)
            if j < 0:
                raise ScanError("unterminated block comment")
            i = j + 2
            continue
        if c == '"':
            in_str = True
            out.append('"')
            i += 1
            continue
        if c in "{[(":
            stack.append(c)
        elif c in "}])":
            if not stack:
                raise ScanError(f"unbalanced '{c}' at offset {i}")
            top = stack.pop()
            if top == "I":
                if c != "}":
                    raise ScanError(f"bad interpolation close at {i}")
                in_str = True
                out.append(" ")
                i += 1
                continue
            if "{[(".index(top) != "}])".index(c):
                raise ScanError(f"mismatched '{top}' / '{c}' at offset {i}")
        out.append(c)
        i += 1
    if in_str or stack:
        raise ScanError("unterminated string or block")
    return "".join(out)


def blocks(code):
    """Top-level blocks: (type, labels, body) using brace matching on comment/string-free code."""
    res = []
    for m in re.finditer(r'^(variable|output|module|resource|data|locals|provider|terraform)((?:\s+"[^"]*")*)\s*\{', code, re.M):
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(code[j], 0)
            j += 1
        res.append((m.group(1), re.findall(r'"([^"]*)"', m.group(2)), code[m.end():j - 1]))
    return res


def top_attrs(body):
    """Attribute names at nesting depth 0 of a block body."""
    names, depth = [], 0
    for line in body.split("\n"):
        s = line.strip()
        if depth == 0:
            m = re.match(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=", s)
            if m:
                names.append(m.group(1))
        depth += s.count("{") + s.count("[") + s.count("(") - s.count("}") - s.count("]") - s.count(")")
    return names


class Dir:
    def __init__(self, path, raw_texts):
        self.path = path
        self.files = {}
        self.errors = []
        for f, t in raw_texts.items():
            try:
                self.files[f] = strip_and_check(t)
            except ScanError as e:
                self.errors.append(f"{f}: {e}")
        self.raw = raw_texts
        self.blocks = [b for code in self.files.values() for b in blocks(code)]
        self.vars = {b[1][0]: b[2] for b in self.blocks if b[0] == "variable"}
        self.outputs = {b[1][0]: b[2] for b in self.blocks if b[0] == "output"}
        self.modules = {b[1][0]: b[2] for b in self.blocks if b[0] == "module"}
        self.locals = {a for b in self.blocks if b[0] == "locals" for a in top_attrs(b[2])}
        self.code = "\n".join(self.files.values())

    def required_vars(self):
        return {k for k, body in self.vars.items() if "default" not in top_attrs(body)}


def load_dir(p):
    return Dir(p, {f.name: f.read_text() for f in sorted(p.glob("*.tf"))})


def check(tf_root="terraform", tfvars_root=None):
    tf_root = pathlib.Path(tf_root)
    f = []
    dirs = {p: load_dir(p) for p in sorted(list((tf_root / "modules").iterdir()) + list((tf_root / "stacks").iterdir()))
            if p.is_dir()}
    for p, d in dirs.items():
        P = str(p.relative_to(tf_root))
        for e in d.errors:
            f.append(Finding("HC01", P, e))
        used = set(re.findall(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)", d.code))
        for v in sorted(used - set(d.vars)):
            f.append(Finding("HC02", P, f"var.{v} used but not declared"))
        for v in sorted(set(d.vars) - used):
            f.append(Finding("HC02", P, f"variable {v} declared but not used"))
        for kind, decls in (("variable", d.vars), ("output", d.outputs)):
            for name, body in decls.items():
                if "description" not in top_attrs(body):
                    f.append(Finding("HC02", P, f"{kind} {name} has no description"))
        for name, body in d.modules.items():
            src = re.search(r'source\s*=\s*"([^"]*)"', body)
            target = (p / src.group(1)).resolve() if src else None
            if not target or target not in {x.resolve() for x in dirs}:
                f.append(Finding("HC03", P, f"module {name}: source not found"))
                continue
            t = dirs[next(x for x in dirs if x.resolve() == target)]
            args = set(top_attrs(body)) - META
            for a in sorted(args - set(t.vars)):
                f.append(Finding("HC03", P, f"module {name}: argument {a} is not a variable of {target.name}"))
            for a in sorted(t.required_vars() - args):
                f.append(Finding("HC03", P, f"module {name}: required variable {a} of {target.name} not passed"))
            for out in set(re.findall(rf"\bmodule\.{re.escape(name)}(?:\[[^\]]*\])?\.([A-Za-z_][A-Za-z0-9_]*)", d.code)):
                if out not in t.outputs:
                    f.append(Finding("HC04", P, f"module.{name}.{out}: no such output in {target.name}"))
        for m in set(re.findall(r"\bmodule\.([A-Za-z_][A-Za-z0-9_]*)", d.code)) - set(d.modules):
            f.append(Finding("HC04", P, f"module.{m} referenced but not declared"))
        for l in sorted(set(re.findall(r"\blocal\.([A-Za-z_][A-Za-z0-9_]*)", d.code)) - d.locals):
            f.append(Finding("HC04", P, f"local.{l} referenced but not declared"))
        for out in set(re.findall(r"terraform_remote_state\.org\.outputs\.([A-Za-z_]+)", d.code)):
            if out not in dirs[tf_root / "stacks" / "org"].outputs:
                f.append(Finding("HC04", P, f"org remote-state output {out} does not exist"))
        v = d.raw.get("versions.tf", "")
        if "required_version" not in v:
            f.append(Finding("HC05", P, "versions.tf with required_version missing"))
        for prov in re.findall(r"(\w+)\s*=\s*\{\s*source", v):
            if not re.search(rf"{prov}\s*=\s*\{{[^}}]*version\s*=", v, re.S):
                f.append(Finding("HC05", P, f"provider {prov} has no version constraint"))
        if p.parent.name == "stacks" and p.name != "bootstrap" and 'backend "gcs"' not in v:
            f.append(Finding("HC05", P, "stack without gcs backend"))
        raw = "\n".join(d.raw.values())
        if "google_secret_manager_secret_version" in d.code:
            f.append(Finding("HC07", P, "secret versions would put values in Terraform state"))
        if re.search(r'"roles/(owner|editor|viewer)"', raw) and p.name != "iam-bindings":
            f.append(Finding("HC07", P, "legacy basic role"))
        if re.search(r'(password|private_key)\s*=\s*"[^"$]', raw, re.I):
            f.append(Finding("HC07", P, "literal password / private key"))
    if tfvars_root and pathlib.Path(tfvars_root).exists():
        for sd in sorted(pathlib.Path(tfvars_root).iterdir()):
            stack = dirs.get(tf_root / "stacks" / sd.name)
            if stack is None:
                f.append(Finding("HC06", str(sd), "tfvars for an unknown stack"))
                continue
            for tv in sorted(sd.glob("*.json")):
                keys = set(json.loads(tv.read_text()))
                for k in sorted(keys - set(stack.vars)):
                    f.append(Finding("HC06", str(tv), f"unknown variable {k}"))
                for k in sorted(stack.required_vars() - keys - PIPELINE_VARS):
                    f.append(Finding("HC06", str(tv), f"required variable {k} missing"))
    return f, dirs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("terraform", nargs="?", default="terraform")
    ap.add_argument("--tfvars", default="build/tfvars")
    a = ap.parse_args(argv)
    findings, dirs = check(a.terraform, a.tfvars)
    for x in findings:
        print(f"{x.rule} {x.path}: {x.message}")
    res = sum(len([b for b in d.blocks if b[0] in ("resource", "data")]) for d in dirs.values())
    print(f"{len(dirs)} module/stack directories, {res} resources/data sources, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
