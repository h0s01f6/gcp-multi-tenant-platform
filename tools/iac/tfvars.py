"""Stage 5 bridge: generated plans (build/*.json, Stages 2-4) -> one tfvars JSON per Terraform stack instance.

Usage:  python3 -m tools.iac.tfvars [-o build/tfvars]      (runs the generators it needs in-process)

Writes build/tfvars/<stack>/<instance>.auto.tfvars.json. Terraform modules are generic; every per-customer value
comes from here, i.e. from the registry. Placeholders that only exist after apply (project numbers) are passed as
{project, format} pairs and resolved inside Terraform with data.google_project.
Status: implemented + locally tested (tests/test_iac_tfvars.py; variables checked against variables.tf by hclcheck).
"""
import argparse
import fnmatch
import json
import pathlib
import re
import sys

from tools.access.matrix import Matrix
from tools.access.privileged import Privileged
from tools.cicd.federation import Federation
from tools.db.grants import build_pool_plans, isotest_impersonation
from tools.monitoring.audit import Audit
from tools.slo.dr import DisasterRecovery
from tools.slo.observability import Observability
from tools.network.edge import Edge
from tools.policy.orgpolicy import OrgPolicies, spec_of
from tools.registry.loader import load_yaml
from tools.security.dataprotection import DataProtection

PH = re.compile(r"\$\{PROJECT_NUMBER:([a-z0-9-]+)\}")
SETTINGS = {"org_id": "${ORG_ID}", "billing_account": "${BILLING_ACCOUNT}", "customer_id": "${CUSTOMER_ID}",
            "domain": "example.com", "region": "asia-south1", "group_domain": "example.com"}


def agent(member):
    """'service-${PROJECT_NUMBER:p}@x' -> {'project': p, 'format': 'service-%s@x'}."""
    m = PH.search(member)
    return {"project": m.group(1), "format": PH.sub("%s", member)} if m else {"project": None, "format": member}


def member_of(principal, domain="example.com"):
    if principal.startswith("sa:"):
        acct, project = principal[3:].split("@")
        return f"serviceAccount:{acct}@{project}.iam.gserviceaccount.com"
    return f"group:{principal}@{domain}"


KMS_RINGS = {"shr-build": "kr-build-as1"}


def scope_parts(scope, region="asia-south1"):
    """Access-matrix scope -> (Terraform scope_type, resource id) understood by modules/iam-bindings."""
    kind, _, name = scope.partition(":")
    if kind == "org":
        return "organization", "${ORG_ID}"
    if kind == "billing":
        return "billing_account", "${BILLING_ACCOUNT}"
    if kind == "folder":
        return "folder", "fldr-" + name.replace("-prd", "/prd").replace("-nonprd", "/nonprd") if "-" in name else "fldr-" + name
    if kind == "project":
        return "project", name
    if kind == "repo":
        return "artifact_repository", f"projects/shr-artifacts/locations/{region}/repositories/{name}"
    if kind == "bucket":
        return "bucket", name
    if kind == "attestor":
        return "project", name.split("/")[0]       # notes.attacher + occurrences.editor on the attestor project
    if kind == "kms":
        project, obj = name.split("/")
        if obj.startswith("kr-"):
            return "kms_keyring", f"projects/{project}/locations/{region}/keyRings/{obj}"
        return "kms_key", f"projects/{project}/locations/{region}/keyRings/{KMS_RINGS[project]}/cryptoKeys/{obj}"
    raise ValueError(f"no Terraform scope for {scope}")


class Bridge:
    def __init__(self, registry="registry", security="security", network="network"):
        self.edge = Edge(registry, network, security)
        self.net = self.edge.net
        self.reg = self.net.reg
        self.plan = self.net.plan
        self.fw = self.edge.fw
        self.matrix = Matrix(registry, security)
        self.stacks = load_yaml(pathlib.Path("terraform") / "stacks.yaml") if pathlib.Path("terraform/stacks.yaml").exists() \
            else load_yaml(pathlib.Path(__file__).resolve().parents[2] / "terraform" / "stacks.yaml")
        self.dp = DataProtection(registry, security).generate()
        self.priv = Privileged(registry, security).render()
        self.fed = Federation(registry, security)
        self.audit = Audit(registry, security).render()
        self.orgp = OrgPolicies(pathlib.Path(security) / "org-policies.yaml")
        self.pools = build_pool_plans(self.plan)
        self.tiers = self.net.ipp.cfg["tiers"]
        self.obs = Observability(registry)
        self.dr = DisasterRecovery(registry, security)

    # ---------------- binding ownership (SK01) ----------------
    def owner(self, scope):
        for prefix, stack in self.stacks["binding_owner"].items():
            if prefix != "default" and scope.startswith(prefix):
                return stack
        return self.stacks["binding_owner"]["default"]

    def iam_bindings(self, stack):
        out = []
        for b in self.matrix.bindings():
            if self.owner(b["scope"]) != stack or b["access"] in ("jit", "breakglass"):
                continue           # jit roles come from PAM grants; break-glass from the group (D7)
            if b["role"].startswith(("k8s/", "mysql/", "cloudidentity/")):
                continue
            kind, name = scope_parts(b["scope"])
            out.append({"scope_type": kind, "scope": name, "role": b["role"], "member": member_of(b["principal"]),
                        "condition": b.get("condition")})
        return out

    # ---------------- stacks ----------------
    def org(self):
        o = self.orgp
        return {**{k: v for k, v in SETTINGS.items() if k != "domain"},
                "folders": [{"name": n, "parent": m["parent"]} for n, m in o.nodes.items() if m["parent"]],
                "org_policies": [{"node": p["node"], "constraint": p["constraint"], **spec_of(p),
                                  "dry_run": bool(p.get("dry_run"))} for p in o.policies],
                "hierarchical_firewall_policies": self.fw.out["hierarchical"],
                "groups": {g: {"category": m["category"], "tier": m["tier"]} for g, m in self.matrix.groups().items()},
                "iam_bindings": self.iam_bindings("org"),
                "group_managers": [{"group": g, "member": member_of(b["principal"])}
                                   for b in self.matrix.bindings() if b["role"] == "cloudidentity/group-manager"
                                   for g in sorted(self.matrix.groups()) if fnmatch.fnmatch(g, b["scope"][len("groups:"):])],
                "pipeline_memberships": [{"group": g, "member": member_of(m)}
                                         for g, ms in self.matrix.matrix.get("pipeline_memberships", {}).items() for m in ms],
                "kms_keyrings": [{"project": "shr-security", "name": f"kr-plt-{t}-as1"} for t in self.tiers] +
                                [{"project": "shr-build", "name": KMS_RINGS["shr-build"]}],
                "pam_entitlements": self.priv,
                "wif": {"pool": self.fed.doc["federation"]["pool"],
                        "providers": {k: v for k, v in self.fed.doc["federation"]["providers"].items() if v["enabled"]},
                        "repository_ids": {k: v["id"] for k, v in self.fed.doc["repositories"].items()},
                        "bindings": [{"service_account": f"{sa[3:].split('@')[0]}@{sa[3:].split('@')[1]}.iam.gserviceaccount.com",
                                      "gates": [{"repo": r, "env": e, "ref": ref} for r, e, ref in self.fed.gates(tpl)]}
                                     for tpl, spec in self.fed.doc["pipeline_identities"].items() if spec["auth"] == "wif"
                                     for sa in self.fed.expand_sa(tpl)]},
                "audit": {k: self.audit[k] for k in ("audit_configs", "log_bucket", "sink", "channels", "alert_policies")},
                "shared_projects": ["shr-build", "shr-artifacts", "shr-cicd-prd", "shr-cicd-nonprd", "shr-security"],
                "host_projects": [t["host_project"] for t in self.tiers.values()],
                "artifact_repositories": ["release", "snapshot"],
                "attestor": self.dp["attestor"]}

    def network(self, tier):
        o, e = self.net.out, self.edge.out
        return {"tier": tier, "region": SETTINGS["region"], "host_project": self.tiers[tier]["host_project"],
                "group_domain": SETTINGS["group_domain"], "vpc": o["vpcs"][tier],
                "subnets": [s for s in o["subnets"] if s["tier"] == tier and s["create"]],
                "psa": next(p for p in o["psa"] if p["tier"] == tier),
                "nat": next(n for n in e["nat"] if n["tier"] == tier),
                "firewall_policy": self.fw.out["network_policies"][f"fwp-{tier}"],
                "secure_tags": self.fw.out["secure_tags"][tier],
                "private_zones": [z for z in e["private_zones"] if z["project"] == self.tiers[tier]["host_project"]],
                "public_zones": {k: z for k, z in e["public_zones"].items() if z["tier"] == tier},
                "subnet_iam": [{"subnet": s["name"], "role": "roles/compute.networkUser",
                                "member": member_of(f"grp-wl-netusers-{tier}")}
                               for s in o["subnets"] if s["tier"] == tier and s["create"]],
                "host_bindings": [{**h, **agent(h["member"])} for h in o["host_bindings"]
                                  if h["host_project"] == self.tiers[tier]["host_project"]]}

    def platform(self, tier):
        o, inv = self.net.out, self.reg.inventory
        pools = {**inv["sql_pools"], **inv.get("product_sql_pools", {})}
        tier_pools = {n: p for n, p in pools.items() if ("prd" if p["env"] == "prd" else "nonprd") == tier}
        keys = {k["sql_instance"]["pool"]: k for k in self.dp["keys"] if k.get("sql_instance")}
        dba = [b for b in self.matrix.bindings() if b["scope"].startswith("mysql:") and not b["principal"].startswith("sa:")]
        import fnmatch
        projects = sorted({c["project"] for c in o["gke_clusters"] if c["tier"] == tier} |
                          {p["project"] for p in tier_pools.values()} | {f"plt-ingress-{tier}"})
        return {"tier": tier, "region": SETTINGS["region"], "host_project": self.tiers[tier]["host_project"],
                "billing_account": SETTINGS["billing_account"],
                "projects": [{"name": p, "folder": f"fldr-platform/{tier}"} for p in projects],
                "gke_cells": [c for c in o["gke_clusters"] if c["tier"] == tier],
                "sql_pools": [{**sp, "env": tier_pools[sp["pool"]]["env"], "edition": "ENTERPRISE_PLUS" if tier == "prd" else "ENTERPRISE",
                               "availability": "REGIONAL" if tier_pools[sp["pool"]]["env"] in ("prd", "uat") else "ZONAL",
                               "database_version": "MYSQL_8_4",
                               "dr": self.dr.replica(sp["pool"], tier_pools[sp["pool"]]["env"]),
                               "backup_location": self.dr.backup_location(tier_pools[sp["pool"]]["env"]),
                               "kms_key": (f"projects/{keys[sp['pool']]['project']}/locations/{keys[sp['pool']]['location']}/"
                                           f"keyRings/{keys[sp['pool']]['key_ring']}/cryptoKeys/{keys[sp['pool']]['key']}")
                               if sp["pool"] in keys else None}
                              for sp in o["cloud_sql"] if sp["tier"] == tier],
                "pool_keys": [{**k, "encrypter_decrypter": [agent(m) for m in k["encrypter_decrypter"]]}
                              for k in self.dp["keys"] if k.get("sql_instance") and k["sql_instance"]["pool"] in tier_pools],
                "dba_group_users": [{"pool": n, "group_email": g} for n, g in
                                    sorted({(n, f"{b['principal']}@example.com") for b in dba for n in tier_pools
                                            if fnmatch.fnmatch(n, b["scope"][len("mysql:"):])})],
                "jobs": [j for j in o["cloud_run"] if j.get("job") and j["tier"] == tier],
                "binauthz_policies": [{**p, "verifier": {**p["verifier"], **agent(p["verifier"]["member"])}}
                                      for p in self.dp["binauthz_policies"]
                                      if p["tier"] == tier and p["project"].startswith("plt-")]}

    def edge_stack(self, tier):
        e = self.edge.out
        return {"tier": tier, "domain": SETTINGS["domain"], "host_project": self.tiers[tier]["host_project"],
                "ingress_project": f"plt-ingress-{tier}",
                "albs": {k: v for k, v in e["albs"].items() if v["project"] == f"plt-ingress-{tier}"},
                "gke_project": f"plt-gke-{tier}",
                "gateway_addresses": {k: {"project": g["project"], "address": g["address"], "certificate": g["certificate"]}
                                      for k, g in e["gateways"].items() if g["project"] == f"plt-gke-{tier}"},
                "certificates": {k: c for k, c in e["certificates"].items() if k.endswith(f"-{tier}")},
                "records": [r for r in e["records"] if r["zone"].endswith(f"-{tier}")],
                "cloud_armor": e["cloud_armor"]["policies"]}

    def cluster_config(self, cell):
        e = self.edge.out
        c = self.reg.inventory["gke_cells"][cell]
        return {"cell": cell, "project": c["project"], "region": SETTINGS["region"],
                "manifests_dir": f"build/k8s/{cell}",
                "gateways": {k: g for k, g in e["gateways"].items() if g["cluster"] == cell}}

    def workloads(self, project):
        """tenant / product stack: everything that lives in one tenant or product project."""
        p, o, dp = self.plan, self.net.out, self.dp
        tier = "nonprd" if project.endswith("nonprd") else "prd"
        sas = [s for s in p["service_accounts"].values() if s["project"] == project]
        emails = {s["email"] for s in sas}
        backends = []
        for um, alb in self.edge.out["albs"].items():
            for hr in alb["host_rules"]:
                if hr["backend_project"] == project and hr["backend_service"] not in {b["name"] for b in backends}:
                    backends.append({"name": hr["backend_service"], "kind": hr["backend_kind"], "product": alb["product"],
                                     "env": alb["env"], "cloud_armor": alb["cloud_armor"]})
        return {"project": project, "tier": tier, "region": SETTINGS["region"],
                "folder": f"fldr-tenants/{tier}" if project.startswith("t-") else f"fldr-platform/{tier}",
                "create_project": project.startswith("t-"),          # product projects come from the platform stack
                "host_project": self.tiers[tier]["host_project"] if project in o["service_projects"][tier] else None,
                "service_accounts": sas,
                "workload_identity_bindings": [w for w in p["workload_identity_bindings"].values()
                                               if w["service_account_email"] in emails],
                "sql_users": [{"pool": u["pool"], "pool_project": u["pool_project"], "user": u["user"],
                               "sa_email": u["sa_email"]} for u in p["cloud_sql_iam_users"].values() if u["sa_email"] in emails],
                "project_iam": [b for b in p["project_iam"].values() if b["project"] == project],
                "resource_iam": [b for b in p["resource_iam"].values() if b["project"] == project],
                "buckets": [b for b in dp["buckets"] if b["project"] == project],
                "secrets": [s for s in dp["secrets"] if s["project"] == project],
                "kms_keys": [{**k, "encrypter_decrypter": [agent(m) for m in k["encrypter_decrypter"]]}
                             for k in dp["keys"] if k["project"] == project],
                "cloud_run_services": [r for r in o["cloud_run"] if r["project"] == project and r.get("service")],
                "migs": [{**m, "metadata": self.mig_metadata(m)} for m in o["mig"] if m["project"] == project],
                "backend_services": backends,
                "binauthz_policy": next(({**b, "verifier": {**b["verifier"], **agent(b["verifier"]["member"])}}
                                         for b in dp["binauthz_policies"] if b["project"] == project), None),
                "isotest_bindings": [b for b in isotest_impersonation(self.pools) if b["resource"] in emails]}

    def mig_metadata(self, mig):
        """Instance metadata read at boot by ansible/roles/app (load-config): identifiers only, never secrets."""
        sa = next(s for s in self.plan["service_accounts"].values() if s["account_id"] == mig["deployment"])
        user = next((u for u in self.plan["cloud_sql_iam_users"].values() if u["sa_email"] == sa["email"]), None)
        pool = next((p for p in self.net.out["cloud_sql"] if user and p["pool"] == user["pool"]), None)
        return {"tenant": sa["tenant"] or "multi", "env": sa["env"],
                "db-connection-name": f"{pool['project']}:{SETTINGS['region']}:{pool['pool']}" if pool else "",
                "db-name": ",".join(user["databases"]) if user else "", "db-user": user["user"] if user else ""}

    def memberships(self, tier):
        out = [{"group": g["group"], "member": f"serviceAccount:{g['member']}", "project": None, "format": None}
               for g in self.plan["group_memberships"].values() if g["group"].endswith(tier) or f"-{tier}-" in g["group"]]
        for grp, members in self.net.out["netusers_members"].items():
            if grp.endswith(f"-{tier}"):
                out += [{"group": grp, "member": None, **agent(m)} for m in members]
        return {"tier": tier, "group_domain": SETTINGS["group_domain"], "memberships": out}

    def observability(self, tier):
        o = self.obs.plan(tier)
        return {"tier": tier, "billing_account": SETTINGS["billing_account"],
                **{k: o[k] for k in ("scoping_projects", "monitored_projects", "channels", "log_metrics", "services",
                                     "slos", "alert_policies", "dashboards")}}

    def all(self):
        res = {("org", "org"): self.org()}
        for tier in self.tiers:
            res[("network", tier)] = self.network(tier)
            res[("platform", tier)] = self.platform(tier)
            res[("edge", tier)] = self.edge_stack(tier)
            res[("memberships", tier)] = self.memberships(tier)
            for project in sorted({s["project"] for s in self.plan["service_accounts"].values()}):
                if project.endswith(f"-{tier}"):
                    kind = "tenant" if project.startswith("t-") else "product"
                    name = project[2:-len(tier) - 1]
                    res[(kind, f"{name}-{tier}")] = {"workloads": self.workloads(project), "region": SETTINGS["region"],
                                                      "host_project": self.tiers[tier]["host_project"],
                                                      "billing_account": SETTINGS["billing_account"]}
                    if kind == "tenant":
                        res[(kind, f"{name}-{tier}")]["uptime_checks"] = self.obs.uptime_checks(name, tier)
            res[("observability", tier)] = self.observability(tier)
        for cell in self.reg.inventory["gke_cells"]:
            res[("cluster-config", cell)] = self.cluster_config(cell)
        return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="build/tfvars")
    a = ap.parse_args(argv)
    b = Bridge()
    res = b.all()
    for (stack, inst), data in res.items():
        d = pathlib.Path(a.out) / stack
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{inst}.auto.tfvars.json").write_text(json.dumps(data, indent=2, default=list) + "\n")
    print(f"{len(res)} tfvars files for {len({s for s, _ in res})} stacks -> {a.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
