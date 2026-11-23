"""N4 – DNS zones and records, certificates, ingress (Gateways, ALBs, URL maps), Cloud Armor, Cloud NAT.

Usage:  python3 -m tools.network.edge [--registry registry] [--network network] [--security security]
                                      [-o build/edge.json]
Rules
  IN01 hostnames follow the Stage 2 convention, are unique, and each has exactly one A record and one frontend
  IN02 every ALB host rule's backend service lives in the project of the customer named by the hostname (or, for a
       Shared/Cohort product, in the product project and only for served customers) – review A6/X3
  IN03 every hostname is covered by its product/tier wildcard certificate and lies in its product/tier public zone
  IN04 every environment's backends use a Cloud Armor policy; prod policy has WAF and rate limiting; UAT denies by default
  IN05 private DNS zones send Google APIs and Artifact Registry to the Private Google Access VIP (same VIP as N3 / D8)
  IN06 Cloud NAT covers the runtime subnets with enough static IPs at the planning upper bound
  IN07 GKE Gateways only accept routes from namespaces of their product and environment (D8 hostname policy is the
       second layer)
Status: implemented + locally tested; nothing created in GCP (T-N10, T-N11, T-N12).
"""
import argparse
import ipaddress as ip
import json
import math
import pathlib
import sys

from tools.k8s.baseline import hostnames
from tools.network.firewall import Firewall
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding


def wildcard_covers(pattern, host):
    return pattern.startswith("*.") and host.endswith(pattern[1:]) and "." not in host[: -len(pattern) + 1]


class Edge:
    def __init__(self, registry_root="registry", network_root="network", security_root="security"):
        nr = pathlib.Path(network_root)
        self.path = str(nr / "edge.yaml")
        self.cfg = load_yaml(self.path)
        self.fw = Firewall(registry_root, network_root, security_root)
        self.net = self.fw.net
        self.reg = self.net.reg
        self.out = self.generate()

    def _tier(self, env):
        return "prd" if env == "prd" else "nonprd"

    def generate(self):
        c, d = self.cfg, self.cfg["domain"]
        out = {"public_zones": {}, "records": [], "certificates": {}, "gateways": {}, "albs": {}, "private_zones": [],
               "cloud_armor": c["cloud_armor"], "nat": []}
        plan = self.net.plan
        products = self.reg.products
        for pname in sorted(products):
            for tier in ("prd", "nonprd"):
                zone = c["dns"]["public_zones"][tier].format(product=pname, domain=d)
                out["public_zones"][f"{pname}-{tier}"] = {"dns_name": zone + ".", "tier": tier, "product": pname,
                                                          "project": self.net.ipp.cfg["tiers"][tier]["host_project"],
                                                          "dnssec": c["dns"]["dnssec"]}
                out["certificates"][f"{pname}-{tier}"] = {"domain": c["certificates"][tier].format(product=pname, domain=d),
                                                          "dns_authorization_zone": f"{pname}-{tier}"}
        # frontends per subscription: GKE via namespaces, Cloud Run / MIG via app service accounts
        for n in plan["kubernetes_namespaces"].values():
            lab = n["labels"]
            nn = n["cluster"].rsplit("-", 1)[1]
            tenants = [lab["tenant"]] if lab["tenant"] != "multi" else self._served(n["namespace"])
            gw = c["ingress"]["gke"]["name"].format(product=lab["product"], env=lab["env"], nn=nn)
            g = out["gateways"].setdefault(gw, {
                "cluster": n["cluster"], "namespace": c["ingress"]["gke"]["namespace"],
                "class": c["ingress"]["gke"]["gateway_class"], "product": lab["product"], "env": lab["env"],
                "address": c["ingress"]["gke"]["address"].format(product=lab["product"], env=lab["env"], nn=nn),
                "project": self.reg.inventory["gke_cells"][n["cluster"]]["project"],
                "allowed_route_selector": {k: lab[k] for k in c["ingress"]["gke"]["allowed_route_namespace_labels"]},
                "certificate": f"{lab['product']}-{lab['env_tier']}",
                "cloud_armor": c["cloud_armor"]["attach"][lab["env"]], "hostnames": []})
            for t in tenants:
                for h in hostnames(t, lab["product"], lab["env"], d):
                    g["hostnames"].append(h)
                    out["records"].append({"hostname": h, "zone": f"{lab['product']}-{lab['env_tier']}",
                                           "type": "A", "ttl": c["dns"]["record_ttl"], "target": f"address:{g['address']}",
                                           "tenant": t, "frontend": gw})
        for sa in plan["service_accounts"].values():
            if sa["purpose"] != "app" or sa["runtime"] not in ("cloudrun", "mig"):
                continue
            env, product, tier = sa["env"], sa["product"], sa["env_tier"]
            um = c["ingress"]["alb"]["url_map"].format(product=product, env=env)
            alb = out["albs"].setdefault(um, {
                "project": c["ingress"]["alb"]["project"].format(tier=tier), "product": product, "env": env,
                "runtime": sa["runtime"], "address": c["ingress"]["alb"]["address"].format(product=product, env=env),
                "certificate": f"{product}-{tier}", "cloud_armor": c["cloud_armor"]["attach"][env], "host_rules": []})
            bs = c["ingress"]["alb"]["backend_service"].format(owner=sa["tenant"], product=product, env=env) \
                if sa["tenant_scope"] != "multi" else f"bs-{sa['account_id']}"      # bs-notify-prd, bs-ledger-v4-prd
            tenants = [sa["tenant"]] if sa["tenant_scope"] != "multi" else sa["served_tenants"]
            for t in tenants:
                for h in hostnames(t, product, env, d):
                    alb["host_rules"].append({"host": h, "tenant": t, "backend_service": bs,
                                              "backend_project": sa["project"],
                                              "backend_kind": "serverless_neg" if sa["runtime"] == "cloudrun" else "instance_group"})
                    out["records"].append({"hostname": h, "zone": f"{product}-{tier}", "type": "A",
                                           "ttl": c["dns"]["record_ttl"], "target": f"address:{alb['address']}",
                                           "tenant": t, "frontend": um})
        for tier, t in self.net.ipp.cfg["tiers"].items():
            for z in c["dns"]["private_zones"]:
                recs = [{**r, "value": c["dns"]["pga_vip_ips"] if r["value"] == "@pga_vip_ips" else [r["value"]]}
                        for r in z["records"]]
                out["private_zones"].append({"name": f"{z['name']}-{tier}", "dns_name": z["dns_name"],
                                             "project": t["host_project"], "networks": [t["vpc"]], "records": recs})
            out["nat"].append(self._nat(tier))
        return out

    def _served(self, namespace):
        for sa in self.net.plan["service_accounts"].values():
            if sa["tenant_scope"] == "multi" and sa["runtime"] == "gke" and sa["purpose"] == "app":
                ws = [w for w in self.net.plan["workload_identity_bindings"].values()
                      if w["service_account_email"] == sa["email"] and w["namespace"] == namespace]
                if ws:
                    return sa["served_tenants"]
        return []

    def _nat(self, tier):
        c, ipp = self.cfg["nat"], self.net.ipp
        _, short = self.net.region()
        p = ipp.cfg["planning"]
        nodes_per_cell = math.ceil(p["namespaces_per_cell"] * p["pods_per_namespace"][tier] /
                                   (p["autopilot_pods_per_node"] * p["node_fill"]))
        endpoints = (p["cells_per_env"] * len(ipp.cfg["tiers"][tier]["envs"]) * nodes_per_cell
                     + p["mig_peak_vms"][tier] + p["cloud_run_peak_instances"][tier])
        ips = math.ceil(endpoints * c["min_ports_per_vm"] * c["headroom"] / c["ports_per_ip"])
        subnets = [s["name"] for s in self.net.out["subnets"] if s["tier"] == tier and s["create"] and s["kind"] in c["subnets"]]
        return {"tier": tier, "name": c["name"].format(tier=tier, short=short), "router": c["router"].format(tier=tier, short=short),
                "project": ipp.cfg["tiers"][tier]["host_project"], "subnets": subnets,
                "include_secondary_ranges_for": [s["name"] for s in self.net.out["subnets"] if s["tier"] == tier and s["kind"] == "gke"],
                "ip_allocation": c["ip_allocation"], "static_ips": ips, "endpoints_at_upper_bound": endpoints,
                **{k: c[k] for k in ("min_ports_per_vm", "max_ports_per_vm", "dynamic_port_allocation",
                                     "endpoint_independent_mapping", "log_filter")}}

    def check(self):
        f, P, o, c = [], self.path, self.out, self.cfg
        d = c["domain"]
        seen = {}
        for r in o["records"]:
            seen.setdefault(r["hostname"], []).append(r)
        for h, rs in seen.items():
            if len(rs) != 1:
                f.append(Finding("IN01", P, f"{h}: {len(rs)} records / frontends"))
        for r in o["records"]:
            label = r["hostname"].split(".")[0]
            if not (label == r["tenant"] or label.startswith(f"{r['tenant']}-")):
                f.append(Finding("IN01", P, f"{r['hostname']}: not derived from tenant {r['tenant']}"))
        for name, alb in o["albs"].items():
            for hr in alb["host_rules"]:
                t = hr["host"].split(".")[0].split("-")[0]
                proj = hr["backend_project"]
                if proj.startswith("t-"):
                    if not proj.startswith(f"t-{t}-"):
                        f.append(Finding("IN02", P, f"{name}: {hr['host']} -> backend in {proj} (not customer {t})"))
                elif proj.startswith("p-"):
                    serving = [s for s in self.net.plan["service_accounts"].values()
                               if s["project"] == proj and s["purpose"] == "app" and s["product"] == alb["product"]
                               and s["env"] == alb["env"] and t in s["served_tenants"]]
                    if not serving:
                        f.append(Finding("IN02", P, f"{name}: {hr['host']} -> product backend not serving {t}"))
                else:
                    f.append(Finding("IN02", P, f"{name}: {hr['host']} -> backend in {proj}"))
                if alb["product"] not in hr["host"].split("."):
                    f.append(Finding("IN02", P, f"{name}: host {hr['host']} of another product"))
        for r in o["records"]:
            zone = o["public_zones"][r["zone"]]
            cert = o["certificates"][r["zone"]]
            if not r["hostname"].endswith("." + zone["dns_name"].rstrip(".")):
                f.append(Finding("IN03", P, f"{r['hostname']} not in zone {zone['dns_name']}"))
            if not wildcard_covers(cert["domain"], r["hostname"]):
                f.append(Finding("IN03", P, f"{r['hostname']} not covered by {cert['domain']}"))
        ca = c["cloud_armor"]
        envs = {e for t in self.net.ipp.cfg["tiers"].values() for e in t["envs"]}
        for e in envs:
            if ca["attach"].get(e) not in ca["policies"]:
                f.append(Finding("IN04", P, f"environment {e} has no Cloud Armor policy"))
        prd_rules = ca["policies"]["ca-prd"]["rules"]
        if not any("Waf" in r.get("expression", "") for r in prd_rules) or not any(r["action"] == "throttle" for r in prd_rules):
            f.append(Finding("IN04", P, "ca-prd needs WAF rules and rate limiting"))
        if not ca["policies"][ca["attach"]["uat"]]["default_action"].startswith("deny"):
            f.append(Finding("IN04", P, "UAT policy must deny by default (customer allow-lists)"))
        for fe in list(o["albs"].values()) + list(o["gateways"].values()):
            if fe["cloud_armor"] != ca["attach"][fe["env"]]:
                f.append(Finding("IN04", P, f"frontend for {fe['product']}/{fe['env']} uses the wrong Cloud Armor policy"))
        vip = ip.ip_network(self.fw.cfg["google_ranges"]["pga_vip"][0])
        for z in o["private_zones"]:
            for r in z["records"]:
                if r["type"] == "A" and not all(ip.ip_address(v) in vip for v in r["value"]):
                    f.append(Finding("IN05", P, f"{z['name']}: A record outside the PGA VIP"))
                if r["type"] == "CNAME" and r["value"] != ["private.googleapis.com."]:
                    f.append(Finding("IN05", P, f"{z['name']}: CNAME not to private.googleapis.com"))
        names = {z["dns_name"] for z in o["private_zones"]}
        if not {"googleapis.com.", "pkg.dev."} <= names:
            f.append(Finding("IN05", P, "private zones for googleapis.com and pkg.dev required"))
        for n in o["nat"]:
            runtime = {s["name"] for s in self.net.out["subnets"] if s["tier"] == n["tier"] and s["create"]}
            if set(n["subnets"]) != runtime:
                f.append(Finding("IN06", P, f"{n['name']}: does not cover every runtime subnet"))
            if n["static_ips"] * c["nat"]["ports_per_ip"] < n["endpoints_at_upper_bound"] * c["nat"]["min_ports_per_vm"]:
                f.append(Finding("IN06", P, f"{n['name']}: not enough NAT IPs"))
        for name, g in o["gateways"].items():
            if set(g["allowed_route_selector"]) != {"product", "env"}:
                f.append(Finding("IN07", P, f"{name}: routes must be limited by product and env labels"))
        return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--network", default="network")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/edge.json")
    a = ap.parse_args(argv)
    e = Edge(a.registry, a.network, a.security)
    findings = e.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(e.out, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    o = e.out
    print(f"{len(o['public_zones'])} public zones, {len(o['records'])} records, {len(o['gateways'])} Gateways, "
          f"{len(o['albs'])} ALB URL maps, NAT IPs {[n['static_ips'] for n in o['nat']]}, "
          f"{len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
