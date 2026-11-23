"""N2 – VPCs, subnets, Shared VPC attachments and runtime network settings, generated and checked.

Usage:  python3 -m tools.network.vpc [--registry registry] [--network network] [--security security]
                                     [-o build/network-plan.json]
Rules
  NW01 every GKE cell has its subnet with node, Pod and Service ranges from its IP-plan slot; <= 30 secondary ranges
  NW02 every service project is attached to exactly one host project – the one of its tier; only projects that run
       VPC workloads are attached (tenants with Cloud Run / MIG, product projects, GKE, SQL pools, CI jobs)
  NW03 every runtime (Cloud Run service/job, MIG, GKE cell, SQL pool) uses a subnet / range of its own tier
  NW04 Private Google Access on every created subnet; Cloud SQL private IP only, connectors enforced; MIGs no external IP
  NW05 consistency with D5: subnet constraint allows the tier's host project for every attached project's folder;
       no external IPs; Cloud SQL public IP restricted; Cloud Run egress allowed by run.allowedVPCEgress
  NW06 Network User on host subnets only via grp-wl-netusers-<tier> on that tier's subnets (no project-level grant)
  NW07 no peering between the tier VPCs
Status: implemented + locally tested; nothing created in GCP (T-N1, T-N3..T-N6).
"""
import argparse
import fnmatch
import json
import pathlib
import sys

from tools.access.matrix import Matrix
from tools.identity.derive import derive
from tools.network.ipam import IPPlan, tier_of_env
from tools.policy.orgpolicy import OrgPolicies
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding


def folder_of(project):
    tier = "nonprd" if project.endswith("nonprd") or "-nonprd-" in project else "prd"
    if project.startswith("t-"):
        return f"fldr-tenants/{tier}"
    if project.startswith(("p-", "plt-")):
        return f"fldr-platform/{tier}"
    return "fldr-shared"


class NetworkPlan:
    def __init__(self, registry_root="registry", network_root="network", security_root="security"):
        self.path = str(pathlib.Path(network_root) / "vpc.yaml")
        self.cfg = load_yaml(self.path)
        self.ipp = IPPlan(registry_root, network_root)
        self.reg = self.ipp.reg
        self.plan = derive(self.reg)
        self.matrix = Matrix(registry_root, security_root)
        self.org = OrgPolicies(pathlib.Path(security_root) / "org-policies.yaml")
        self.out = self.generate()

    def region(self):
        return next((r, v["short"]) for r, v in self.ipp.cfg["regions"].items() if v["status"] == "active")

    def generate(self):
        c, ipc = self.cfg, self.ipp.plan
        region, short = self.region()
        out = {"vpcs": {}, "subnets": [], "psa": [], "service_projects": {}, "gke_clusters": [], "cloud_run": [],
               "mig": [], "cloud_sql": [], "netusers_members": {}, "host_bindings": []}
        for tier, t in self.ipp.cfg["tiers"].items():
            blocks = ipc["tiers"][tier]["regions"][region]["blocks"]
            out["vpcs"][tier] = {"name": t["vpc"], "host_project": t["host_project"], **c["vpc"]}
            for key, s in c["subnets"].items():
                out["subnets"].append({"name": s["name"].format(tier=tier, short=short), "tier": tier,
                                       "host_project": t["host_project"], "region": region, "kind": key,
                                       "cidr": blocks[s["block"]]["cidr"], "secondary": [],
                                       "private_google_access": s.get("private_google_access", False),
                                       "create": s.get("create", True)})
            out["psa"].append({"tier": tier, "host_project": t["host_project"], "network": t["vpc"],
                               "range_name": c["psa"]["range_name"].format(tier=tier),
                               "cidr": blocks["psa"]["cidr"], "service": c["psa"]["service"],
                               "export_custom_routes": c["psa"]["export_custom_routes"]})
            out["service_projects"][tier] = set()
        for cell, v in ipc["cells"].items():
            t = self.ipp.cfg["tiers"][v["tier"]]
            sec = [{"range_name": v["pods_range_name"], "cidr": v["pods"]},
                   {"range_name": v["services_range_name"], "cidr": v["services"]}]
            if c["gke_subnet"]["create_pods_reserve_range"]:
                sec.append({"range_name": v["pods_reserve_range_name"], "cidr": v["pods_reserve"]})
            out["subnets"].append({"name": v["subnet"], "tier": v["tier"], "host_project": t["host_project"],
                                   "region": region, "kind": "gke", "cell": cell, "cidr": v["nodes"],
                                   "secondary": sec, "reserved_pod_range": v["pods_reserve"],
                                   "private_google_access": c["gke_subnet"]["private_google_access"], "create": True})
            proj = self.reg.inventory["gke_cells"][cell]["project"]
            out["gke_clusters"].append({"cluster": cell, "project": proj, "tier": v["tier"], "network": t["vpc"],
                                        "subnet": v["subnet"], "pods_range": v["pods_range_name"],
                                        "services_range": v["services_range_name"], **c["gke"]})
            out["service_projects"][v["tier"]].add(proj)
        sn = {(s["tier"], s["kind"]): s["name"] for s in out["subnets"] if s["kind"] in ("run", "mig")}
        agents = {}

        def agent(project, kind):
            agents.setdefault(project, set()).add(kind)

        for sa in self.plan["service_accounts"].values():
            if sa["purpose"] != "app":
                continue
            tier = sa["env_tier"]
            if sa["runtime"] == "cloudrun":
                out["cloud_run"].append({"service": f"{sa['product']}-{sa['env']}" if sa["tenant_scope"] == "multi"
                                         else f"{sa['tenant']}-{sa['product']}-{sa['env']}",
                                         "project": sa["project"], "tier": tier, "network": self.ipp.cfg["tiers"][tier]["vpc"],
                                         "subnet": sn[(tier, "run")], "egress": c["cloud_run"]["egress"],
                                         "ingress": c["cloud_run"]["ingress"],
                                         "network_tags": [x.format(tier=tier, product=sa["product"]) for x in c["cloud_run"]["network_tags"]]})
                out["service_projects"][tier].add(sa["project"])
                agent(sa["project"], "cloudrun")
            elif sa["runtime"] == "mig":
                out["mig"].append({"deployment": sa["account_id"], "project": sa["project"], "tier": tier,
                                   "subnet": sn[(tier, "mig")], "external_ip": c["mig"]["external_ip"],
                                   "secure_tags": [x.format(tier=tier, product=sa["product"]) for x in c["mig"]["secure_tags"]]})
                out["service_projects"][tier].add(sa["project"])
                agent(sa["project"], "apis")
        pools = {**self.reg.inventory["sql_pools"], **self.reg.inventory.get("product_sql_pools", {})}
        for name, pool in sorted(pools.items()):
            tier = tier_of_env(pool["env"])
            psa = next(p for p in out["psa"] if p["tier"] == tier)
            out["cloud_sql"].append({"pool": name, "project": pool["project"], "tier": tier,
                                     "private_network": psa["network"], "allocated_ip_range": psa["range_name"],
                                     **c["cloud_sql"]})
            out["service_projects"][tier].add(pool["project"])
            if pool["project"].startswith("plt-sql-"):
                agent(pool["project"], "cloudrun")           # db-bootstrap job
        for tier in self.ipp.cfg["tiers"]:
            for j in c["cloud_run"]["jobs"]:
                projects = sorted({p["project"] for p in pools.values() if tier_of_env(p["env"]) == tier
                                   and p["project"].startswith("plt-sql-")}) if "{nn}" in j["project"] \
                    else [j["project"].format(tier=tier)]
                for proj in projects:
                    out["cloud_run"].append({"job": j["name"], "project": proj, "tier": tier,
                                             "network": self.ipp.cfg["tiers"][tier]["vpc"], "subnet": sn[(tier, "run")],
                                             "egress": c["cloud_run"]["egress"],
                                             "network_tags": [x.format(tier=tier) for x in j["tags"]]})
                    out["service_projects"][tier].add(proj)
                    agent(proj, "cloudrun")
        for cl in out["gke_clusters"]:
            agent(cl["project"], "gke")
            agent(cl["project"], "apis")
        for project, kinds in sorted(agents.items()):
            tier = "nonprd" if "nonprd" in project else "prd"
            grp = f"grp-wl-netusers-{tier}"
            for k in sorted(kinds):
                out["netusers_members"].setdefault(grp, []).append(c["service_agents"][k].replace("{project}", project))
            if "gke" in kinds:
                out["host_bindings"].append({"host_project": self.ipp.cfg["tiers"][tier]["host_project"],
                                             "role": "roles/container.hostServiceAgentUser",
                                             "member": c["service_agents"]["gke"].replace("{project}", project)})
        out["service_projects"] = {t: sorted(v) for t, v in out["service_projects"].items()}
        return out

    def check(self):
        f, P, o, c = [], self.path, self.out, self.cfg
        cells = self.ipp.plan["cells"]
        subs = {s["name"]: s for s in o["subnets"]}
        for cell, v in cells.items():
            s = subs.get(v["subnet"])
            if not s or s["cidr"] != v["nodes"] or {r["cidr"] for r in s["secondary"]} < {v["pods"], v["services"]}:
                f.append(Finding("NW01", P, f"{cell}: subnet or ranges differ from the IP plan"))
        for s in o["subnets"]:
            if len(s["secondary"]) > c["limits"]["secondary_ranges_per_subnet"]:
                f.append(Finding("NW01", P, f"{s['name']}: too many secondary ranges"))

        seen = {}
        for tier, projects in o["service_projects"].items():
            for p in projects:
                seen.setdefault(p, []).append(tier)
                ptier = "nonprd" if p.endswith("nonprd") or "-nonprd-" in p else "prd"
                if ptier != tier:
                    f.append(Finding("NW02", P, f"{p} attached to the {tier} host project"))
        for p, tiers in seen.items():
            if len(tiers) > 1:
                f.append(Finding("NW02", P, f"{p} attached to {len(tiers)} host projects"))
        workload_projects = {r["project"] for k in ("cloud_run", "mig", "gke_clusters", "cloud_sql") for r in o[k]}
        for p in sorted(set(seen) - workload_projects):
            f.append(Finding("NW02", P, f"{p} attached without a VPC workload"))

        for kind in ("cloud_run", "mig", "gke_clusters"):
            for r in o[kind]:
                s = subs.get(r["subnet"])
                if not s or s["tier"] != r["tier"]:
                    f.append(Finding("NW03", P, f"{kind} {r.get('service') or r.get('job') or r.get('deployment') or r.get('cluster')}: subnet of another tier"))
        for r in o["cloud_sql"]:
            psa = next(p for p in o["psa"] if p["range_name"] == r["allocated_ip_range"])
            if psa["tier"] != r["tier"]:
                f.append(Finding("NW03", P, f"pool {r['pool']}: PSA range of another tier"))

        for s in o["subnets"]:
            if s["create"] and not s["private_google_access"]:
                f.append(Finding("NW04", P, f"{s['name']}: Private Google Access off"))
        for r in o["cloud_sql"]:
            if r["ipv4_enabled"] or r["connector_enforcement"] != "REQUIRED":
                f.append(Finding("NW04", P, f"pool {r['pool']}: public IP or connectors not enforced"))
        for r in o["mig"]:
            if r["external_ip"]:
                f.append(Finding("NW04", P, f"MIG {r['deployment']}: external IP"))

        for tier, projects in o["service_projects"].items():
            host = self.ipp.cfg["tiers"][tier]["host_project"]
            for p in projects:
                e = self.org.effective(folder_of(p), "compute.restrictSharedVpcSubnetworks")
                if e["kind"] == "allow" and f"under:projects/{host}" not in e["values"]:
                    f.append(Finding("NW05", P, f"{p}: D5 subnet constraint does not allow {host}"))
        if self.org.effective("fldr-tenants/prd", "compute.vmExternalIpAccess")["kind"] != "deny_all":
            f.append(Finding("NW05", P, "D5 must deny VM external IPs"))
        for r in o["cloud_run"]:
            e = self.org.effective(folder_of(r["project"]), "run.allowedVPCEgress")
            if e["kind"] == "allow" and r["egress"] not in e["values"]:
                f.append(Finding("NW05", P, f"{r['project']}: Cloud Run egress {r['egress']} not allowed by D5"))

        for b in self.matrix.bindings():
            if b["role"] != "roles/compute.networkUser":
                continue
            if b["scope"].startswith("project:net-host"):
                f.append(Finding("NW06", P, f"{b['principal']}: project-level Network User on {b['scope']}"))
            if b["scope"].startswith("subnet:"):
                tier = "nonprd" if "nonprd" in b["scope"] else "prd"
                if b["principal"] != f"grp-wl-netusers-{tier}":
                    f.append(Finding("NW06", P, f"{b['principal']}: Network User on {b['scope']}"))
        for s in o["subnets"]:
            if not s["create"] or s["kind"] == "proxy_only":
                continue
            grants = [b for b in self.matrix.bindings() if b["role"] == "roles/compute.networkUser"
                      and b["scope"].startswith("subnet:") and fnmatch.fnmatch(s["name"], b["scope"][len("subnet:"):])]
            if [g["principal"] for g in grants] != [f"grp-wl-netusers-{s['tier']}"]:
                f.append(Finding("NW06", P, f"{s['name']}: Network User must be granted to grp-wl-netusers-{s['tier']} only"))

        if c["vpc"].get("peering") != "none":
            f.append(Finding("NW07", P, "tier VPCs must not be peered"))
        return f

    def quota_report(self):
        """Service projects per host at the capacity-model upper bound (500 customers), for T-N1 / Q20."""
        lim = self.cfg["limits"]["shared_vpc_service_projects_per_host"]
        now = {t: len(v) for t, v in self.out["service_projects"].items()}
        return {"attached_now": now, "upper_bound_per_tier": 500 + 20 + 8 + 3,
                "note": "500 tenant projects (if every customer runs Cloud Run or MIG) + up to 20 product projects "
                        "+ SQL pool projects + GKE/CI projects", "limit": lim}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--network", default="network")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/network-plan.json")
    a = ap.parse_args(argv)
    n = NetworkPlan(a.registry, a.network, a.security)
    findings = n.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps({**n.out, "quota_report": n.quota_report()}, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    o = n.out
    print(f"{len([s for s in o['subnets'] if s['create']])} subnets, "
          f"{sum(len(v) for v in o['service_projects'].values())} service projects, {len(o['gke_clusters'])} clusters, "
          f"{len(o['cloud_run'])} Cloud Run services/jobs, {len(o['mig'])} MIGs, {len(o['cloud_sql'])} SQL pools, "
          f"{len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
