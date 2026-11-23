"""Stage 5 – check the Terraform stack catalogue (terraform/stacks.yaml) against the repository and access matrix.

Usage:  python3 -m tools.iac.stacks
Rules
  SK01 every access-matrix binding is applied by exactly one owner (stack or the D4 bootstrap job)
  SK02 every role a stack requires is granted to the stack identity in the access matrix (per tier)
  SK03 the `after` graph references known stacks and has no cycle
  SK04 every catalogued stack has a directory in terraform/stacks and vice versa
  SK05 every stack identity is a D6 pipeline identity (or the bootstrap humans)
Status: implemented + locally tested.
"""
import fnmatch
import pathlib
import sys

from tools.access.matrix import Matrix
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

ROOT = pathlib.Path(__file__).resolve().parents[2]


def covers(granted_scope, required_scope):
    return granted_scope == required_scope or fnmatch.fnmatch(required_scope, granted_scope)


def check(root=ROOT, security="security"):
    cat = load_yaml(root / "terraform" / "stacks.yaml")
    cicd = load_yaml(root / security / "cicd-identities.yaml")
    m = Matrix(root / "registry", root / security)
    binds = m.bindings()
    stacks = cat["stacks"]
    f, P = [], "terraform/stacks.yaml"
    owners = set(stacks) | {"db-bootstrap"}
    for b in binds:
        hits = [s for p, s in cat["binding_owner"].items() if p != "default" and b["scope"].startswith(p)]
        owner = hits[0] if hits else cat["binding_owner"]["default"]
        if len(hits) > 1 or owner not in owners:
            f.append(Finding("SK01", P, f"{b['principal']} {b['role']} on {b['scope']}: owner {hits or owner}"))
    for name, s in stacks.items():
        tiers = ["prd", "nonprd"] if "{tier}" in s["identity"] else [None]
        for t in tiers:
            ident = s["identity"].format(tier=t) if t else s["identity"]
            for r in s.get("requires", []):
                scope = r["scope"].format(tier=t) if t else r["scope"]
                if not any(b["principal"] == ident and b["role"] == r["role"] and covers(b["scope"], scope) for b in binds):
                    f.append(Finding("SK02", P, f"{name}: {ident} lacks {r['role']} on {scope}"))
        for t in tiers:
            ident = s["identity"].format(tier=t) if t else s["identity"]
            if not ident.startswith("human:") and ident not in cicd["pipeline_identities"]:
                f.append(Finding("SK05", P, f"{name}: identity {ident} is not a D6 pipeline identity"))
        for a in s.get("after", []):
            if a not in stacks:
                f.append(Finding("SK03", P, f"{name}: unknown predecessor {a}"))
    state = {}

    def visit(n, path):
        if state.get(n) == 1:
            f.append(Finding("SK03", P, f"cycle: {' -> '.join(path + [n])}"))
            return
        if state.get(n) == 2:
            return
        state[n] = 1
        for a in stacks.get(n, {}).get("after", []):
            visit(a, path + [n])
        state[n] = 2

    for n in stacks:
        visit(n, [])
    dirs = {p.name for p in (root / "terraform" / "stacks").iterdir() if p.is_dir()}
    for n in sorted(set(stacks) ^ dirs):
        f.append(Finding("SK04", P, f"stack {n}: catalogue and directories differ"))
    return f


def order(root=ROOT):
    """Topological apply order (used in docs and the onboarding sequence)."""
    stacks = load_yaml(root / "terraform" / "stacks.yaml")["stacks"]
    out, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for a in stacks[n].get("after", []):
            visit(a)
        out.append(n)

    for n in stacks:
        visit(n)
    return out


def main():
    findings = check()
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"apply order: {' -> '.join(order())}; {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
