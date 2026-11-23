"""N5 – network quota register: usage at the capacity-model upper bound vs known limits (review B14).

Usage:  python3 -m tools.network.quotas [--registry registry] [--network network] [--security security]
Rules
  QU01 every quota has an owner; an unknown limit names a registered validation item
  QU02 usage at the upper bound stays below alert_threshold x a known limit
Status: implemented + locally tested; limits marked null still need confirmation (see register).
"""
import argparse
import math
import pathlib
import sys

from tools.network.edge import Edge
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding


def usage(edge):
    ipp, c = edge.net.ipp, edge.net.ipp.cfg
    p = c["planning"]
    customers, products = 500, 20                                     # capacity-model upper bound
    return {
        "shared_vpc_service_projects_per_host": customers + products + 10,
        "secondary_ranges_per_subnet": 3,                                # pods, services, pods reserve
        "gke_cell_subnets_per_vpc": max(len(t["envs"]) for t in c["tiers"].values()) * p["cells_per_env"],
        "cloud_sql_instances_per_psa_range": max(p["sql_instances"].values()),
        "cloud_run_ips_per_tier": max(p["cloud_run_peak_instances"].values()) * p["cloud_run_ips_per_instance"],
        "nat_static_ips_per_region": max(n["static_ips"] for n in edge.out["nat"]),
        "host_rules_per_url_map": customers,
        "records_per_public_zone": customers * 3,                        # non-prod zone: dev + stg + uat per customer
        "rules_per_network_firewall_policy": 10 + products,
    }


def check(edge, path):
    doc = load_yaml(path)
    reg_text = (pathlib.Path(__file__).resolve().parents[2] / "documentation" / "assumptions-and-open-questions.md").read_text()
    use = usage(edge)
    f, rows = [], []
    for name, q in doc["quotas"].items():
        if not q.get("owner"):
            f.append(Finding("QU01", str(path), f"{name}: no owner"))
        if q["value"] is None and (not q.get("validation") or f"| {q['validation']} " not in reg_text):
            f.append(Finding("QU01", str(path), f"{name}: unknown limit without a registered validation item"))
        u = use.get(name)
        if q["value"] is not None and u is not None and u > doc["alert_threshold"] * q["value"]:
            f.append(Finding("QU02", str(path), f"{name}: usage {u} above {doc['alert_threshold']:.0%} of {q['value']}"))
        rows.append((name, u, q["value"]))
    return f, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--network", default="network")
    ap.add_argument("--security", default="security")
    a = ap.parse_args(argv)
    e = Edge(a.registry, a.network, a.security)
    findings, rows = check(e, pathlib.Path(a.network) / "quotas.yaml")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    unknown = sum(1 for _, _, v in rows if v is None)
    print(f"{len(rows)} quotas, {unknown} limits to confirm in GCP, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
