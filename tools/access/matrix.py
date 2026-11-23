"""D3 – expand and check the access-control matrix.

Usage:  python3 -m tools.access.matrix [--registry registry] [--security security]
        writes build/access-bindings.json and security/access-matrix.md (rendered view)
Status: implemented + locally tested (rules AC01-AC12); not applied to any GCP organisation.
"""
import argparse
import fnmatch
import itertools
import json
import pathlib
import re
import sys
from dataclasses import dataclass

from tools.identity.derive import derive
from tools.registry.loader import load_yaml
from tools.registry.validate import validate as validate_registry

ASSIGNMENT_PERSONAS = ["Platform administrators", "DevOps engineers", "Product development teams",
                       "Customer-specific users", "Production support engineers", "Automated deployment pipelines"]
WL_ALLOWED_ROLES = {"roles/cloudsql.client", "roles/cloudsql.instanceUser", "roles/artifactregistry.reader",
                    "roles/compute.networkUser", "roles/compute.networkViewer"}
DBA_GROUPS_PER_INSTANCE_BUDGET = 3          # documented Cloud SQL limit is 200 IAM groups per instance
PRD_JIT_MAX_HOURS = 4


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str

    def __str__(self):
        return f"ERROR {self.rule}: {self.message}"


def scope_tier(scope):
    if "nonprd" in scope:
        return "nonprd"
    if re.search(r"(^|[-:/])prd($|[-*/])", scope):
        return "prd"
    if re.search(r"(gke|sql)-(dev|stg|uat)", scope):
        return "nonprd"
    return "shared"


def _subst(text, env):
    """Replace only known template names; other braces (e.g. CEL extract templates) are kept."""
    if not text:
        return text
    for k, v in env.items():
        text = text.replace("{" + k + "}", v)
    return text


def sa_tier(sa):
    m = re.search(r"-(prd|nonprd)@", sa)
    return m.group(1) if m else "org"


class Matrix:
    def __init__(self, registry_root="registry", security_root="security"):
        sec = pathlib.Path(security_root)
        self.roles = load_yaml(sec / "role-catalog.yaml")
        self.groups_tpl = load_yaml(sec / "groups.yaml")["groups"]
        self.matrix = load_yaml(sec / "access-matrix.yaml")
        self.reg, reg_findings = validate_registry(registry_root)
        if reg_findings:
            raise ValueError("registry invalid: " + "; ".join(map(str, reg_findings)))
        inv = self.reg.inventory
        nns = {"prd": set(), "nonprd": set()}
        for v in inv["sql_pools"].values():
            m = re.fullmatch(r"plt-sql-(prd|nonprd)-(\d{2})", v["project"])
            if m:
                nns[m.group(1)].add(m.group(2))
        self.values = {"tenant": sorted(self.reg.tenants), "product": sorted(self.reg.products),
                       "nn_prd": sorted(nns["prd"]), "nn_nonprd": sorted(nns["nonprd"])}
        self.pools = inv["sql_pools"]

    # ---------------- template expansion ----------------
    def _expand(self, *texts):
        """Yield (bindings dict, expanded texts) for every combination of template values used."""
        joined = " ".join(texts)
        names = sorted(set(re.findall(r"\{(\w+)\}", joined)))
        axes = []
        for n in names:
            if n == "nn":
                tier = "nonprd" if "nonprd-{nn}" in joined else "prd"
                axes.append([(n, v) for v in self.values[f"nn_{tier}"]])
            else:
                axes.append([(n, v) for v in self.values[n]])
        for combo in itertools.product(*axes):
            env = dict(combo)
            yield env, [t.format(**env) if "{" in t else t for t in texts]

    def groups(self):
        out = {}
        for tpl, meta in self.groups_tpl.items():
            for env, (name,) in self._expand(tpl):
                out[name] = {**meta, "template": tpl, "values": env}
        return out

    def bindings(self):
        out = []
        for i, g in enumerate(self.matrix["grants"]):
            for env, (principal, scope, entitlement) in self._expand(g["principal"], g["scope"], g.get("entitlement") or ""):
                for role in g["roles"]:
                    out.append({
                        "principal": principal, "principal_template": g["principal"], "scope": scope,
                        "scope_template": g["scope"], "scope_tier": scope_tier(scope), "role": role,
                        "role_class": (self.roles["roles"].get(role) or {}).get("class"),
                        "access": g["access"], "entitlement": entitlement or None,
                        "max_hours": g.get("max_hours"), "exception": g.get("exception"),
                        "condition": _subst(g.get("condition"), env),
                        "values": env, "grant_index": i})
        return out

    # ---------------- rules ----------------
    def check(self):
        f = []
        groups, binds = self.groups(), self.bindings()
        forbidden = set(self.roles.get("forbidden", []))

        def ptier(p):
            return sa_tier(p) if p.startswith("sa:") else groups.get(p, {}).get("tier", "?")

        for b in binds:
            p, role, cls, scope = b["principal"], b["role"], b["role_class"], b["scope"]
            g = groups.get(p)
            # AC01 / AC02 – role known, no legacy basic roles
            if role in forbidden:
                f.append(Finding("AC02", f"{p} on {scope}: legacy basic role {role} is forbidden"))
            elif cls is None:
                f.append(Finding("AC01", f"{p} on {scope}: role {role} is not in the role catalogue"))
            # AC10 – every principal group exists
            if not p.startswith("sa:") and g is None:
                f.append(Finding("AC10", f"grant references unknown group {p}"))
                continue
            # AC04 – tier boundary
            pt = ptier(p)
            if pt in ("prd", "nonprd") and b["scope_tier"] not in (pt, "shared"):
                f.append(Finding("AC04", f"{p} ({pt}) granted {role} on {scope} ({b['scope_tier']}) – crosses tiers"))
            # AC03 – humans: no standing write/admin/data in prod or at org level
            if g and g["category"] == "hum" and cls in ("write", "admin", "data") \
                    and b["scope_tier"] in ("prd", "shared") and b["access"] == "standing" \
                    and not b["exception"]:
                f.append(Finding("AC03", f"{p}: standing {cls} role {role} on {scope} – use jit/expiring/breakglass"))
            # AC05 – workload groups: connect/pull/subnet only, no k8s or mysql scopes
            if g and g["category"] == "wl":
                if role not in WL_ALLOWED_ROLES or scope.startswith(("k8s:", "mysql:")):
                    f.append(Finding("AC05", f"workload group {p} must not hold {role} on {scope}"))
            # AC06 – MySQL group roles only for human mechanism-2 groups
            if scope.startswith("mysql:") and not p.startswith("sa:"):
                if g["category"] != "hum" or g.get("cloudsql_mechanism") != "sql-group-auth" or g["membership"] == "registry":
                    f.append(Finding("AC06", f"{p}: only human sql-group-auth groups (no SA members) may hold MySQL roles"))
            # AC07 – build identity never on tenant/platform runtime scopes; only builder writes release
            if p == "sa:builder@shr-build" and not scope.startswith(("repo:", "kms:", "attestor:shr-build/")):
                f.append(Finding("AC07", f"build identity must not be granted on {scope}"))
            if role == "roles/artifactregistry.writer" and scope == "repo:release" and p != "sa:builder@shr-build":
                f.append(Finding("AC07", f"only the build identity may write the release repository ({p})"))
            # AC08 – per-customer principals only on that customer's scopes
            if "tenant" in b["values"]:
                t = b["values"]["tenant"]
                if not (f"t-{t}-" in scope or f"/{t}-" in scope):
                    f.append(Finding("AC08", f"{p} granted on {scope}, which is not customer '{t}'"))
            # AC11 – break-glass
            if b["access"] == "breakglass" and (not g or g["membership"] != "manual-breakglass"):
                f.append(Finding("AC11", f"breakglass access only for break-glass groups ({p})"))
            # AC12 – JIT / expiring discipline
            if b["access"] == "jit":
                if not b["entitlement"] or not b["max_hours"] or b["max_hours"] > PRD_JIT_MAX_HOURS:
                    f.append(Finding("AC12", f"{p}: jit grant needs a PAM entitlement and max_hours <= {PRD_JIT_MAX_HOURS}"))
            if b["access"] == "expiring":
                if not g or g["membership"] != "expiring-approval" or (b["max_hours"] or 99) > g.get("max_duration_hours", 0):
                    f.append(Finding("AC12", f"{p}: expiring grant needs an expiring-approval group within its max duration"))

        for name, g in groups.items():
            if g["membership"] == "manual-breakglass" and g.get("default_members", 1) != 0:
                f.append(Finding("AC11", f"{name} must be empty by default"))
            if g.get("cloudsql_mechanism") == "sql-group-auth" and g["category"] != "hum":
                f.append(Finding("AC06", f"{name}: only human groups may use IAM group database authentication"))
        # AC06 – per-instance group budget
        for pool in self.pools:
            n = {b["principal"] for b in binds if b["scope"].startswith("mysql:") and not b["principal"].startswith("sa:")
                 and fnmatch.fnmatch(pool, b["scope"][len("mysql:"):])}
            if len(n) > DBA_GROUPS_PER_INSTANCE_BUDGET:
                f.append(Finding("AC06", f"{pool}: {len(n)} IAM groups as database users > budget {DBA_GROUPS_PER_INSTANCE_BUDGET} (limit 200)"))
        # AC09 – personas
        covered = {p.get("assignment_persona") for p in self.matrix["personas"].values() if p.get("principals")}
        for persona in ASSIGNMENT_PERSONAS:
            if persona not in covered:
                f.append(Finding("AC09", f"assignment persona '{persona}' has no principals"))
        for pid, p in self.matrix["personas"].items():
            for tpl in p["principals"]:
                if not tpl.startswith("sa:") and tpl not in self.groups_tpl:
                    f.append(Finding("AC09", f"persona {pid}: unknown group {tpl}"))
        # AC10 – no orphan groups
        used = {b["principal"] for b in binds} | set(self.matrix.get("pipeline_memberships", {}))
        for name in groups:
            if name not in used:
                f.append(Finding("AC10", f"group {name} is not used by any grant"))
        return f

    # ---------------- outputs ----------------
    def render_markdown(self, plan):
        m, out = self.matrix, []
        out.append("# Access-control matrix (generated)\n")
        out.append("> Generated by `python3 -m tools.access.matrix` from `security/access-matrix.yaml`, "
                   "`security/groups.yaml`, `security/role-catalog.yaml` and the registry. Do not edit by hand.\n"
                   "> Status: **implemented, locally checked (AC01–AC12)**; not applied to a GCP organisation.\n")
        out.append("## Personas\n")
        out.append("| Persona (assignment) | Principals |\n|---|---|")
        for pid, p in m["personas"].items():
            out.append(f"| {p.get('assignment_persona') or pid} | " + ", ".join(f"`{x}`" for x in p["principals"]) + " |")
        out.append("\n## Grants by principal\n")
        out.append("| Principal | Scope | Roles | Access | Tier |\n|---|---|---|---|---|")
        for g in m["grants"]:
            acc = g["access"] + (f" ({g['entitlement']}, ≤{g['max_hours']}h)" if g.get("entitlement")
                                 else f" (≤{g['max_hours']}h)" if g.get("max_hours") else "")
            if g.get("exception"):
                acc += f" – **approved exception:** {g['exception']}"
            out.append(f"| `{g['principal']}` | `{g['scope']}` | " + ", ".join(f"`{r}`" for r in g["roles"])
                       + f" | {acc} | {scope_tier(g['scope'])} |")
        out.append("\n## Workload identities (generated by D2 – per customer-product-environment)\n")
        counts = {}
        for sa in plan["service_accounts"].values():
            k = (sa["deployment_model"], sa["isolation_boundary"])
            counts[k] = counts.get(k, 0) + 1
        out.append("| Deployment model | Isolation boundary | Service accounts |\n|---|---|---|")
        for (model, iso), n in sorted(counts.items()):
            out.append(f"| {model} | {iso} | {n} |")
        out.append("\nWorkload data access (buckets, secrets, MySQL grants) is always granted to the individual SA; "
                   "workload groups hold only connect/pull/subnet roles (AC05). Shared/Cohort identities are "
                   "multi-tenant by design – application-level isolation (ADR-006 rev. 3).\n")
        out.append("## Rules checked\n")
        for line in RULES_DOC:
            out.append(f"- {line}")
        return "\n".join(out) + "\n"


RULES_DOC = [
    "**AC01** every role is in the role catalogue",
    "**AC02** no legacy basic roles (Owner/Editor/Viewer)",
    "**AC03** no standing human write/admin/data access in prod or at organisation level (JIT, expiring or break-glass only), unless the grant carries an explicit, reviewed `exception`",
    "**AC04** no principal crosses the prod / non-prod boundary",
    "**AC05** workload groups hold only connect / artifact-pull / subnet roles – never data, Kubernetes or MySQL grants",
    "**AC06** MySQL group roles only for human `sql-group-auth` groups without SA members; ≤ 3 groups per instance (limit 200)",
    "**AC07** the build identity is never granted on runtime scopes; only it writes the release repository",
    "**AC08** per-customer principals are granted only on that customer's projects / namespaces",
    "**AC09** all six assignment personas are mapped to principals that exist",
    "**AC10** every group exists and is used",
    "**AC11** break-glass access only through an empty-by-default break-glass group",
    "**AC12** JIT grants name a PAM entitlement (≤ 4 h); expiring grants use an expiring-approval group within its maximum",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--output", default="build/access-bindings.json")
    args = ap.parse_args(argv)
    mx = Matrix(args.registry, args.security)
    findings = mx.check()
    for x in findings:
        print(x)
    binds = mx.bindings()
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"bindings": binds, "groups": mx.groups()}, indent=2, sort_keys=True) + "\n")
    plan = derive(mx.reg)
    pathlib.Path(args.security, "access-matrix.md").write_text(mx.render_markdown(plan))
    print(f"{len(mx.groups())} groups, {len(binds)} concrete bindings, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
