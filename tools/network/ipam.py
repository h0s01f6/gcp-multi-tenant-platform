"""N1 – IP address plan: allocate every range from network/ip-plan.yaml and the inventory, then check it.

Usage:  python3 -m tools.network.ipam [--registry registry] [--network network] [-o build/ip-plan.json]

Rules
  IP01 tier supernets and reserved ranges are RFC 1918 and pairwise disjoint; every block lies inside its parent
  IP02 no two allocated ranges overlap (blocks, cell slots, subnets, secondary ranges, PSA)
  IP03 capacity at the planning upper bound: cell slots, nodes per cell, Pods, Services, Cloud SQL instances (PSA),
       Cloud Run egress IPs, MIG VMs
  IP04 every inventory GKE cell has a slot in its own tier and environment
Status: implemented + locally tested; ranges not created in GCP (T-N3).
"""
import argparse
import ipaddress as ip
import json
import math
import pathlib
import re
import sys

from tools.registry.loader import load_yaml
from tools.registry.validate import Finding, validate

RFC1918 = [ip.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
CELL_RE = re.compile(r"^gke-(dev|stg|uat|prd)-([a-z0-9]+)-(\d{2})$")


def tier_of_env(env):
    return "prd" if env == "prd" else "nonprd"


def aligned_after(addr, prefix):
    size = 2 ** (32 - prefix)
    n = int(addr)
    return ip.ip_address(((n + size - 1) // size) * size)


class IPPlan:
    def __init__(self, registry_root="registry", network_root="network"):
        self.path = str(pathlib.Path(network_root) / "ip-plan.yaml")
        self.cfg = load_yaml(self.path)
        self.reg, findings = validate(registry_root)
        if findings:
            raise ValueError("registry invalid")
        self.plan = self.allocate()

    # ---------------- allocation ----------------
    def region_block(self, tier, region):
        sup = ip.ip_network(self.cfg["tiers"][tier]["supernet"])
        idx = list(self.cfg["regions"]).index(region)
        return list(sup.subnets(new_prefix=11))[idx]

    def allocate(self):
        c = self.cfg
        out = {"tiers": {}, "cells": {}}
        for tier, t in c["tiers"].items():
            tout = out["tiers"][tier] = {"supernet": t["supernet"], "vpc": t["vpc"], "host_project": t["host_project"],
                                         "regions": {}}
            for region, r in c["regions"].items():
                rb = self.region_block(tier, region)
                rout = tout["regions"][region] = {"cidr": str(rb), "short": r["short"], "status": r["status"],
                                                  "blocks": {}}
                if r["status"] != "active":
                    continue
                cur = rb.network_address
                for b in c["region_layout"]:
                    start = aligned_after(cur, b["prefix"])
                    net = ip.ip_network(f"{start}/{b['prefix']}")
                    rout["blocks"][b["block"]] = {"cidr": str(net), "status": b.get("status", "active")}
                    cur = net.broadcast_address + 1
        # GKE cell slots (active region only)
        region = next(r for r, v in c["regions"].items() if v["status"] == "active")
        for cell, meta in self.reg.inventory["gke_cells"].items():
            out["cells"][cell] = self.cell_ranges(cell, meta["env"], region, out)
        return out

    def slot_index(self, env, nn):
        envs = self.cfg["tiers"][tier_of_env(env)]["envs"]
        return envs.index(env) * self.cfg["cell_slots"]["per_env"] + (nn - 1)

    def cell_ranges(self, cell, env, region, out):
        m = CELL_RE.match(cell)
        nn = int(m.group(3))
        tier = tier_of_env(env)
        s = self.cfg["cell_slots"][tier]
        k = self.slot_index(env, nn)
        blocks = out["tiers"][tier]["regions"][region]["blocks"]

        def nth(block, prefix, i):
            base = ip.ip_network(blocks[block]["cidr"])
            return ip.ip_network(f"{ip.ip_address(int(base.network_address) + i * 2 ** (32 - prefix))}/{prefix}")

        pod_slot = nth("gke_pods", s["pods"] - 1, k)                 # pods + reserve = one prefix shorter
        pods, reserve = list(pod_slot.subnets(new_prefix=s["pods"]))
        short = self.cfg["regions"][region]["short"]
        return {"tier": tier, "env": env, "slot": k, "region": region,
                "subnet": f"snet-{tier}-{short}-gke-{env}-{nn:02d}",
                "nodes": str(nth("gke_nodes", s["nodes"], k)), "pods": str(pods), "pods_reserve": str(reserve),
                "services": str(nth("gke_services", s["services"], k)),
                "pods_range_name": f"pods-{env}-{nn:02d}", "services_range_name": f"svc-{env}-{nn:02d}",
                "pods_reserve_range_name": f"pods2-{env}-{nn:02d}"}

    # ---------------- checks ----------------
    def all_ranges(self):
        """(label, network) for every allocated, non-container range (cells counted, region blocks not)."""
        rs = []
        for tier, t in self.plan["tiers"].items():
            for region, r in t["regions"].items():
                for b, v in r["blocks"].items():
                    if b in ("gke_pods", "gke_services", "gke_nodes"):
                        continue                       # containers of cell slots
                    rs.append((f"{tier}/{region}/{b}", ip.ip_network(v["cidr"])))
        for cell, v in self.plan["cells"].items():
            for k in ("nodes", "pods", "pods_reserve", "services"):
                rs.append((f"{cell}/{k}", ip.ip_network(v[k])))
        return rs

    def check(self):
        f, P, c = [], self.path, self.cfg
        sups = {t: ip.ip_network(v["supernet"]) for t, v in c["tiers"].items()}
        res = [ip.ip_network(r["cidr"]) for r in c["reserved"]]
        for t, n in sups.items():
            if not any(n.subnet_of(r) for r in RFC1918):
                f.append(Finding("IP01", P, f"tier {t} supernet {n} is not RFC 1918"))
            for r in res:
                if n.overlaps(r):
                    f.append(Finding("IP01", P, f"tier {t} overlaps reserved {r}"))
        names = list(sups)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if sups[a].overlaps(sups[b]):
                    f.append(Finding("IP01", P, f"tiers {a} and {b} overlap"))
        for tier, t in self.plan["tiers"].items():
            for region, r in t["regions"].items():
                rb = ip.ip_network(r["cidr"])
                if not rb.subnet_of(sups[tier]):
                    f.append(Finding("IP01", P, f"{tier}/{region} outside the tier supernet"))
                for b, v in r["blocks"].items():
                    if not ip.ip_network(v["cidr"]).subnet_of(rb):
                        f.append(Finding("IP01", P, f"{tier}/{region}/{b} {v['cidr']} outside the region block {rb}"))
        for cell, v in self.plan["cells"].items():
            blocks = self.plan["tiers"][v["tier"]]["regions"][v["region"]]["blocks"]
            for k, b in (("nodes", "gke_nodes"), ("pods", "gke_pods"), ("pods_reserve", "gke_pods"),
                         ("services", "gke_services")):
                if not ip.ip_network(v[k]).subnet_of(ip.ip_network(blocks[b]["cidr"])):
                    f.append(Finding("IP01", P, f"{cell} {k} {v[k]} outside {b}"))

        rs = self.all_ranges()
        for i, (la, a) in enumerate(rs):
            for lb, b in rs[i + 1:]:
                if a.overlaps(b):
                    f.append(Finding("IP02", P, f"{la} {a} overlaps {lb} {b}"))

        p = c["planning"]
        per_env = c["cell_slots"]["per_env"]
        if per_env < p["cells_per_env"]:
            f.append(Finding("IP03", P, f"{per_env} cell slots per environment < {p['cells_per_env']} needed"))
        for tier in c["tiers"]:
            s = c["cell_slots"][tier]
            node_block = 2 ** (32 - (32 - math.ceil(math.log2(2 * p["autopilot_pods_per_node"]))))
            nodes_by_pods = 2 ** (32 - s["pods"]) // node_block
            pods_needed = p["namespaces_per_cell"] * p["pods_per_namespace"][tier]
            nodes_needed = math.ceil(pods_needed / (p["autopilot_pods_per_node"] * p["node_fill"]))
            if nodes_by_pods < nodes_needed:
                f.append(Finding("IP03", P, f"{tier}: Pod range /{s['pods']} holds {nodes_by_pods} nodes < {nodes_needed} needed"))
            if 2 ** (32 - s["nodes"]) - 4 < nodes_needed:
                f.append(Finding("IP03", P, f"{tier}: node range /{s['nodes']} too small for {nodes_needed} nodes"))
            svc_needed = p["namespaces_per_cell"] * p["services_per_namespace"][tier]
            if 2 ** (32 - s["services"]) < svc_needed:
                f.append(Finding("IP03", P, f"{tier}: Service range /{s['services']} < {svc_needed} Services"))
            region = next(r for r, v in c["regions"].items() if v["status"] == "active")
            blocks = self.plan["tiers"][tier]["regions"][region]["blocks"]
            psa = ip.ip_network(blocks["psa"]["cidr"])
            if psa.num_addresses // 256 * p["sql_instances_per_24"] < p["sql_instances"][tier]:
                f.append(Finding("IP03", P, f"{tier}: PSA {psa} too small for {p['sql_instances'][tier]} instances"))
            run = ip.ip_network(blocks["run"]["cidr"])
            if run.num_addresses < p["cloud_run_peak_instances"][tier] * p["cloud_run_ips_per_instance"]:
                f.append(Finding("IP03", P, f"{tier}: Cloud Run subnet {run} < 2 IPs x peak instances"))
            mig = ip.ip_network(blocks["mig"]["cidr"])
            if mig.num_addresses - 4 < p["mig_peak_vms"][tier]:
                f.append(Finding("IP03", P, f"{tier}: MIG subnet {mig} too small"))
            used_slots = len(c["tiers"][tier]["envs"]) * per_env
            pods_block = ip.ip_network(blocks["gke_pods"]["cidr"])
            if used_slots * 2 ** (32 - (s["pods"] - 1)) > pods_block.num_addresses:
                f.append(Finding("IP03", P, f"{tier}: {used_slots} Pod slots do not fit {pods_block}"))
            if used_slots * 2 ** (32 - s["services"]) > ip.ip_network(blocks["gke_services"]["cidr"]).num_addresses:
                f.append(Finding("IP03", P, f"{tier}: Service slots do not fit"))
            if used_slots * 2 ** (32 - s["nodes"]) > ip.ip_network(blocks["gke_nodes"]["cidr"]).num_addresses:
                f.append(Finding("IP03", P, f"{tier}: node slots do not fit"))

        for cell, meta in self.reg.inventory["gke_cells"].items():
            m = CELL_RE.match(cell)
            if not m or m.group(1) != meta["env"]:
                f.append(Finding("IP04", P, f"cell {cell}: name does not match its environment {meta['env']}"))
                continue
            if int(m.group(3)) > per_env:
                f.append(Finding("IP04", P, f"cell {cell}: number above {per_env} slots"))
            expected_project = f"plt-gke-{tier_of_env(meta['env'])}"
            if meta["project"] != expected_project:
                f.append(Finding("IP04", P, f"cell {cell}: project {meta['project']} is not {expected_project}"))
        return f

    def summary(self):
        c, p = self.cfg, self.cfg["planning"]
        rows = []
        for tier in c["tiers"]:
            s = c["cell_slots"][tier]
            node_block = 2 * p["autopilot_pods_per_node"]
            rows.append({"tier": tier, "slots": len(c["tiers"][tier]["envs"]) * c["cell_slots"]["per_env"],
                         "nodes_per_cell": 2 ** (32 - s["pods"]) // node_block,
                         "services_per_cell": 2 ** (32 - s["services"])})
        return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--network", default="network")
    ap.add_argument("-o", "--out", default="build/ip-plan.json")
    a = ap.parse_args(argv)
    p = IPPlan(a.registry, a.network)
    findings = p.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(p.plan, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(p.all_ranges())} ranges, {len(p.plan['cells'])} cells allocated, {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
