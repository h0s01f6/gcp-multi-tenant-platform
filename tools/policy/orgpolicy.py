"""D5 – check the organisation / folder policy set (security/org-policies.yaml).

Usage:  python3 -m tools.policy.orgpolicy [security/org-policies.yaml] [-o build/org-policy-effective.json]

Rules
  OP01 constraint is in the catalogue and the policy shape matches its type (boolean: enforce; list: allow|deny|deny_all)
  OP02 node exists; one policy per (node, constraint)
  OP03 every baseline / mandatory constraint is set at the organisation node
  OP04 prod is at least as strict as non-prod (effective policy, per folder pair); for tier_scoped constraints
       each tier's values must name only its own tier
  OP05 a child that relaxes its parent's effective policy needs an `exception` (reason, approved_by, review_by)
  OP06 high-impact constraints start in dry-run and name their validation item
  OP07 mandatory constraints are never relaxed below the organisation, exception or not
  OP08 no value is left as an unknown placeholder (only ${ORG_ID}, ${CUSTOMER_ID}, ${BB_WORKSPACE} are allowed)
Status: implemented + locally tested. Policies are PROPOSED; nothing applied (T-O1..T-O6).
"""
import argparse
import json
import pathlib
import re
import sys

from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

KNOWN_PLACEHOLDERS = {"ORG_ID", "CUSTOMER_ID", "BB_WORKSPACE"}
TIER_PAIRS = [("fldr-tenants/prd", "fldr-tenants/nonprd"), ("fldr-platform/prd", "fldr-platform/nonprd")]
UNSET = {"kind": "unset"}


def spec_of(p):
    if "enforce" in p:
        return {"kind": "boolean", "enforce": bool(p["enforce"])}
    if p.get("deny_all"):
        return {"kind": "deny_all"}
    if "allow" in p:
        return {"kind": "allow", "values": sorted(p["allow"])}
    if "deny" in p:
        return {"kind": "deny", "values": sorted(p["deny"])}
    return {"kind": "invalid"}


def at_least_as_strict(a, b):
    """True if effective spec `a` restricts at least as much as `b`."""
    if b["kind"] == "unset" or a == b:
        return True
    if a["kind"] == "unset":
        return False
    if a["kind"] == "boolean" and b["kind"] == "boolean":
        return a["enforce"] or not b["enforce"]
    if a["kind"] == "deny_all":
        return True
    if b["kind"] == "deny_all":
        return False
    if a["kind"] == "allow" and b["kind"] == "allow":
        return set(a["values"]) <= set(b["values"])
    if a["kind"] == "deny" and b["kind"] == "deny":
        return set(a["values"]) >= set(b["values"])
    return False      # mixed allow/deny – treat as not comparable => needs review


class OrgPolicies:
    def __init__(self, path="security/org-policies.yaml"):
        self.path = str(path)
        self.doc = load_yaml(path)
        self.nodes = self.doc["nodes"]
        self.catalog = self.doc["constraints"]
        self.policies = self.doc["policies"]

    def ancestors(self, node):
        chain = []
        while node is not None:
            chain.append(node)
            node = self.nodes[node]["parent"]
        return chain           # self first, org last

    def own(self, node, constraint):
        return next((p for p in self.policies if p["node"] == node and p["constraint"] == constraint), None)

    def effective(self, node, constraint, include_dry_run=True):
        for n in self.ancestors(node):
            p = self.own(n, constraint)
            if p and (include_dry_run or not p.get("dry_run")):
                return {**spec_of(p), "set_at": n, "dry_run": bool(p.get("dry_run"))}
        return dict(UNSET)

    @staticmethod
    def _cmp(e):
        return {k: v for k, v in e.items() if k not in ("set_at", "dry_run")}

    def check(self):
        f, P = [], self.path
        seen = set()
        for p in self.policies:
            c, n = p.get("constraint"), p.get("node")
            meta = self.catalog.get(c)
            if meta is None:
                f.append(Finding("OP01", P, f"unknown constraint {c}"))
                continue
            kind = spec_of(p)["kind"]
            if kind == "invalid" or (meta["type"] == "boolean") != (kind == "boolean"):
                f.append(Finding("OP01", P, f"{c} on {n}: shape '{kind}' does not match type {meta['type']}"))
            if n not in self.nodes:
                f.append(Finding("OP02", P, f"{c}: unknown node {n}"))
                continue
            if (n, c) in seen:
                f.append(Finding("OP02", P, f"{c} set twice on {n}"))
            seen.add((n, c))
            if meta.get("impact") == "high" and not (p.get("dry_run") and p.get("validation")):
                f.append(Finding("OP06", P, f"{c} on {n}: high-impact constraint must start dry_run with a validation item"))
            for v in p.get("allow", []) + p.get("deny", []):
                for ph in re.findall(r"\$\{(\w+)\}", v):
                    if ph not in KNOWN_PLACEHOLDERS:
                        f.append(Finding("OP08", P, f"{c} on {n}: unknown placeholder ${{{ph}}}"))
        for c, meta in self.catalog.items():
            if (meta.get("baseline") or meta.get("mandatory")) and not self.own("org", c):
                f.append(Finding("OP03", P, f"baseline/mandatory constraint {c} is not set at the organisation"))
        for c in self.catalog:
            for prd, nonprd in TIER_PAIRS:
                if self.catalog[c].get("tier_scoped"):
                    for node, tier, other in ((prd, "prd", "nonprd"), (nonprd, "nonprd", "prd")):
                        e = self.effective(node, c)
                        vals = e.get("values", [])
                        if e["kind"] != "allow" or not vals or any(
                                f"-{other}" in v or f"-{tier}" not in v for v in vals):
                            f.append(Finding("OP04", P, f"{c} on {node}: tier-scoped values must name only {tier}"))
                    continue
                if not at_least_as_strict(self.effective(prd, c), self.effective(nonprd, c)):
                    f.append(Finding("OP04", P, f"{c}: {prd} is less strict than {nonprd}"))
            for n, meta in self.nodes.items():
                if meta["parent"] is None or self.catalog[c].get("tier_scoped"):
                    continue
                mine, parent = self.effective(n, c), self.effective(meta["parent"], c)
                if at_least_as_strict(mine, parent):
                    continue
                own = self.own(n, c) or {}
                if self.catalog[c].get("mandatory"):
                    f.append(Finding("OP07", P, f"mandatory {c} relaxed on {n}"))
                exc = own.get("exception") or {}
                if not all(exc.get(k) for k in ("reason", "approved_by", "review_by")):
                    f.append(Finding("OP05", P, f"{c} relaxed on {n} without a complete exception"))
        return f

    def effective_table(self):
        return {n: {c: self.effective(n, c) for c in sorted(self.catalog)} for n in self.nodes}

    def render_markdown(self):
        leaves = ["fldr-tenants/prd", "fldr-tenants/nonprd", "fldr-platform/prd", "fldr-platform/nonprd",
                  "fldr-shared", "fldr-network", "fldr-bootstrap"]

        def cell(e):
            k = e["kind"]
            s = {"unset": "–", "deny_all": "deny all"}.get(k) or \
                ("enforced" if k == "boolean" and e["enforce"] else "not enforced" if k == "boolean" else
                 f"{k}: " + ", ".join(e["values"]))
            return s + (" (dry-run)" if e.get("dry_run") else "")

        out = ["# Organisation policy – effective values (generated)", "",
               "Generated by `python3 -m tools.policy.orgpolicy`; source `security/org-policies.yaml`. "
               "**Proposed – not applied.** dry-run = Org Policy dry-run spec only (violations logged, not blocked).", "",
               "| Constraint | Set at org | " + " | ".join(leaves) + " | Why |",
               "|---|---|" + "---|" * len(leaves) + "---|"]
        for c, meta in sorted(self.catalog.items()):
            org = cell(self.effective("org", c))
            row = [cell(self.effective(n, c)) for n in leaves]
            row = ["=" if r == org else r for r in row]
            mark = " **(mandatory)**" if meta.get("mandatory") else ""
            out.append(f"| `{c}`{mark} | {org} | " + " | ".join(row) + f" | {meta['why']} |")
        out += ["", "`=` same as the organisation value (inherited)."]
        return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policies", nargs="?", default="security/org-policies.yaml")
    ap.add_argument("-o", "--out", default="build/org-policy-effective.json")
    ap.add_argument("--markdown", default="security/org-policies.md")
    a = ap.parse_args(argv)
    op = OrgPolicies(a.policies)
    findings = op.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(op.effective_table(), indent=1, sort_keys=True) + "\n")
    if a.markdown:
        pathlib.Path(a.markdown).write_text(op.render_markdown())
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(op.policies)} policies, {len(op.catalog)} constraints, {len(op.nodes)} nodes, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
