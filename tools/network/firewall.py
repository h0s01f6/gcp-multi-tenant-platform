"""N3 – firewall policies: expand network/firewall.yaml per tier and check them.

Usage:  python3 -m tools.network.firewall [--registry registry] [--network network] [--security security]
                                          [-o build/firewall.json]
Rules
  FW01 unique priorities per policy; valid direction/action; goto_next only in hierarchical policies; no classic rules
  FW02 ingress allows / goto_next only from Google LB/health-check ranges, IAP or internal 10.0.0.0/8; never 0.0.0.0/0
  FW03 SSH (tcp:22) only from IAP and only to wl=mig
  FW04 each VPC policy ends with a default-deny egress; every egress allow has a specific destination
  FW05 tier isolation: each tier folder denies the other tier's supernet in both directions; no allow references it
  FW06 one FQDN egress rule per product with egress, sourced only from that product's runtime ranges in the tier
  FW07 consistency with D8 (LB sources, Google APIs VIP, Cloud SQL range) and N2 (secure tags on MIGs)
Status: implemented + locally tested; nothing created in GCP (T-N8, T-N9).
"""
import argparse
import ipaddress as ip
import json
import pathlib
import sys

from tools.network.vpc import NetworkPlan
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

ACTIONS = {"allow", "deny", "goto_next"}
INTERNAL = ip.ip_network("10.0.0.0/8")


class Firewall:
    def __init__(self, registry_root="registry", network_root="network", security_root="security"):
        nr = pathlib.Path(network_root)
        self.path = str(nr / "firewall.yaml")
        self.cfg = load_yaml(self.path)
        self.egress = load_yaml(nr / "egress.yaml")["products"]
        self.net = NetworkPlan(registry_root, network_root, security_root)
        self.k8s = load_yaml(pathlib.Path(security_root) / "k8s-baseline.yaml")
        self.out = self.generate()

    def _ranges(self, tier):
        ipp = self.net.ipp
        region, _ = self.net.region()
        blocks = ipp.plan["tiers"][tier]["regions"][region]["blocks"]
        return {"supernet": ipp.cfg["tiers"][tier]["supernet"], "blocks": blocks,
                "cells": {c: v for c, v in ipp.plan["cells"].items() if v["tier"] == tier}}

    def _resolve(self, value, tier):
        g, c = self.cfg["google_ranges"], self.cfg
        if isinstance(value, list):
            return value
        if value.startswith("@tier:"):
            return [self._ranges(value.split(":")[1])["supernet"]]
        if value.startswith("@subnet:"):
            return [self._ranges(tier)["blocks"][value.split(":")[1]]["cidr"]]
        if value == "@psa":
            return [self._ranges(tier)["blocks"]["psa"]["cidr"]]
        if value == "@gke_ranges":
            r = self._ranges(tier)["blocks"]
            return [r["gke_nodes"]["cidr"], r["gke_pods"]["cidr"], r["gke_services"]["cidr"]]
        return g[value[1:]]

    def _ports(self, ports):
        return [p.replace("@app_port", str(self.cfg["app_port"])).replace("@cloudsql_port", str(self.cfg["cloudsql_port"]))
                for p in ports]

    def product_sources(self, product, tier):
        """Runtime ranges of a product in a tier: Cloud Run subnet, MIG tag, or the Pod ranges of its cells."""
        o, r = self.net.out, self._ranges(tier)
        runtime = self.net.reg.products[product][1]["runtime"]
        if runtime == "cloudrun":
            return {"src": [r["blocks"]["run"]["cidr"]], "note": "Cloud Run is matched by subnet (shared by all Cloud Run products of the tier, K26)"}
        if runtime == "mig":
            return {"target_tags": [f"app={product}"], "note": "MIG VMs by secure tag"}
        cells = sorted({n["cluster"] for n in self.net.plan["kubernetes_namespaces"].values()
                        if n["labels"]["product"] == product and n["labels"]["env_tier"] == tier})
        return {"src": [r["cells"][c]["pods"] for c in cells], "target_tags": ["wl=gke-node"],
                "note": "Pod ranges of the cells running the product; namespace-level control by NetworkPolicy (D8)"}

    def generate(self):
        c = self.cfg
        out = {"hierarchical": {}, "network_policies": {}, "secure_tags": {}, "classic_rules": []}
        for name, pol in c["hierarchical"].items():
            out["hierarchical"][name] = {"attach": pol["attach"], "rules": [
                {**{k: v for k, v in r.items() if k not in ("src", "dst")},
                 **({"src": self._resolve(r["src"], None)} if "src" in r else {}),
                 **({"dst": self._resolve(r["dst"], None)} if "dst" in r else {}),
                 "ports": r["ports"]} for r in pol["rules"]]}
        for tier, t in self.net.ipp.cfg["tiers"].items():
            rules = []
            for r in c["network_policy"]["rules"]:
                if r.get("dst_fqdn") == "@egress":
                    for i, (product, dests) in enumerate(sorted(self.egress.items())):
                        if not dests or not any(n["labels"]["product"] == product for n in
                                                self.net.plan["kubernetes_namespaces"].values()) and \
                                not any(s["product"] == product for s in self.net.plan["service_accounts"].values()):
                            continue
                        srcs = self.product_sources(product, tier)
                        rules.append({"priority": r["priority"] + i, "direction": "EGRESS", "action": "allow",
                                      "product": product, "dst_fqdns": sorted({d["fqdn"] for d in dests}),
                                      "ports": sorted({f"tcp:{d['port']}" for d in dests}), **srcs,
                                      "why": f"internet egress allow-list for {product}"})
                    continue
                rr = {k: v for k, v in r.items() if k not in ("src", "dst")}
                if "src" in r:
                    rr["src"] = self._resolve(r["src"], tier)
                if "dst" in r:
                    rr["dst"] = self._resolve(r["dst"], tier)
                rr["ports"] = self._ports(r.get("ports", []))
                rules.append(rr)
            out["network_policies"][f"fwp-{tier}"] = {"tier": tier, "host_project": t["host_project"],
                                                     "network": t["vpc"], "enforcement_order": "AFTER_CLASSIC_FIREWALL",
                                                     "rules": rules}
            out["secure_tags"][tier] = {"project": t["host_project"], "purpose": "GCE_FIREWALL", "network": t["vpc"],
                                        "keys": {"wl": c["secure_tags"]["wl"], "app": sorted(self.net.reg.products)}}
        return out

    def check(self):
        f, P, o, c = [], self.path, self.out, self.cfg
        g = c["google_ranges"]
        allowed_ingress = {*map(ip.ip_network, g["iap"] + g["lb_health_checks"]), INTERNAL}
        policies = [(n, p, True) for n, p in o["hierarchical"].items()] + \
                   [(n, p, False) for n, p in o["network_policies"].items()]
        for name, pol, hier in policies:
            prios = [r["priority"] for r in pol["rules"]]
            if len(prios) != len(set(prios)):
                f.append(Finding("FW01", P, f"{name}: duplicate priorities"))
            for r in pol["rules"]:
                if r["direction"] not in ("INGRESS", "EGRESS") or r["action"] not in ACTIONS:
                    f.append(Finding("FW01", P, f"{name}/{r['priority']}: invalid direction or action"))
                if r["action"] == "goto_next" and not hier:
                    f.append(Finding("FW01", P, f"{name}/{r['priority']}: goto_next only in hierarchical policies"))
                if r["direction"] == "INGRESS" and r["action"] in ("allow", "goto_next"):
                    for s in r.get("src", []):
                        n = ip.ip_network(s)
                        if not any(n.subnet_of(a) for a in allowed_ingress):
                            f.append(Finding("FW02", P, f"{name}/{r['priority']}: ingress from {s}"))
                    if any("tcp:22" == p for p in r.get("ports", [])):
                        if set(r.get("src", [])) != set(g["iap"]) or (not hier and r.get("target_tags") != ["wl=mig"]):
                            f.append(Finding("FW03", P, f"{name}/{r['priority']}: SSH only from IAP to wl=mig"))
                if r["direction"] == "EGRESS" and r["action"] == "allow" and not r.get("dst_fqdns"):
                    if any(ip.ip_network(d).prefixlen == 0 for d in r.get("dst", [])) or not r.get("dst"):
                        f.append(Finding("FW04", P, f"{name}/{r['priority']}: egress allow without a specific destination"))
        if o["classic_rules"]:
            f.append(Finding("FW01", P, "classic VPC firewall rules are not used by the platform"))
        for name, pol in o["network_policies"].items():
            last = max(pol["rules"], key=lambda r: r["priority"])
            if not (last["direction"] == "EGRESS" and last["action"] == "deny" and last.get("dst") == ["0.0.0.0/0"]):
                f.append(Finding("FW04", P, f"{name}: must end with a default-deny egress rule"))

        tiers = self.net.ipp.cfg["tiers"]
        for tier in tiers:
            other = [t for t in tiers if t != tier][0]
            osup = tiers[other]["supernet"]
            pol = next((p for p in o["hierarchical"].values()
                        if all(a.endswith(f"/{tier}") for a in p["attach"]) and p["attach"]), None)
            dirs = {(r["direction"], r["action"]) for r in (pol or {"rules": []})["rules"]
                    if osup in r.get("src", []) + r.get("dst", [])}
            if dirs != {("INGRESS", "deny"), ("EGRESS", "deny")}:
                f.append(Finding("FW05", P, f"{tier}: tier folder policy must deny {osup} both ways"))
            if pol and set(pol["attach"]) != {f"fldr-tenants/{tier}", f"fldr-platform/{tier}"}:
                f.append(Finding("FW05", P, f"{tier}: tier policy must attach to both {tier} folders"))
            for r in o["network_policies"][f"fwp-{tier}"]["rules"]:
                if r["action"] == "allow":
                    for x in r.get("src", []) + r.get("dst", []):
                        if ip.ip_network(x).overlaps(ip.ip_network(osup)):
                            f.append(Finding("FW05", P, f"fwp-{tier}/{r['priority']}: allows {x} of tier {other}"))

        for tier in tiers:
            rules = [r for r in o["network_policies"][f"fwp-{tier}"]["rules"] if r.get("dst_fqdns")]
            got = {r["product"] for r in rules}
            want = {p for p, d in self.egress.items() if d and p in self.net.reg.products}
            for p in sorted(want - got):
                f.append(Finding("FW06", P, f"fwp-{tier}: no egress rule for {p}"))
            sup = ip.ip_network(tiers[tier]["supernet"])
            for r in rules:
                if not all(ip.ip_network(s).subnet_of(sup) for s in r.get("src", [])):
                    f.append(Finding("FW06", P, f"fwp-{tier}: egress rule for {r['product']} sourced outside the tier"))
                if not r.get("src") and not r.get("target_tags"):
                    f.append(Finding("FW06", P, f"fwp-{tier}: egress rule for {r['product']} applies to everything"))

        k = self.k8s["network"]
        if sorted(k["load_balancer_sources"]) != sorted(g["lb_health_checks"]):
            f.append(Finding("FW07", P, "D8 load-balancer sources differ from the firewall's"))
        if [k["google_apis"]["cidr"]] != g["pga_vip"]:
            f.append(Finding("FW07", P, "D8 Google APIs range differs from the PGA VIP"))
        for tier in tiers:
            if k["cloud_sql"][tier]["port"] != c["cloudsql_port"]:
                f.append(Finding("FW07", P, f"D8 Cloud SQL port differs ({tier})"))
        for m in self.net.out["mig"]:
            if "wl=mig" not in m["secure_tags"]:
                f.append(Finding("FW07", P, f"MIG {m['deployment']}: no wl=mig tag"))
        return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--network", default="network")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/firewall.json")
    a = ap.parse_args(argv)
    fw = Firewall(a.registry, a.network, a.security)
    findings = fw.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(fw.out, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    n = sum(len(p["rules"]) for p in fw.out["hierarchical"].values()) + \
        sum(len(p["rules"]) for p in fw.out["network_policies"].values())
    print(f"{len(fw.out['hierarchical'])} hierarchical + {len(fw.out['network_policies'])} network policies, "
          f"{n} rules, {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
