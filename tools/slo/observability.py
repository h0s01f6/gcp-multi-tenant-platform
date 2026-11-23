"""Stage 8 – monitoring, SLOs and alerting plan per tier (slo/slos.yaml + registry) -> Terraform inputs of the
observability stack and of the uptime checks in the tenant stack.

Usage:  python3 -m tools.slo.observability [-o build/observability.json]

Per tier: scoping projects plt-obs-<tier>-NN (sharded, <= 375 monitored projects each – K27), the monitored projects,
notification channels, one custom service per product (sharded), availability + latency SLOs per customer per
product (prd), burn-rate alert policies per product (PromQL, grouped by customer), the uptime alert, the platform
alerts and the dashboards. Uptime checks per customer host name are created in the customer's prd project.
Rules
  SL01 every prd subscription has an availability and a latency SLO and an uptime check; no SLO without a subscription
  SL02 Cloud Monitoring limits per scope: <= 375 monitored projects, <= 500 SLOs per service, <= 2,000 alert policies,
       <= 6 conditions per policy, <= 16 channels per policy, <= 100 uptime checks per project, <= 1,000 dashboards
  SL03 burn-rate alerts: short window < long window, page burn rates above ticket, every alert consumes a meaningful
       share of the budget (burn x long / window >= 1 %) and fires before the budget is gone
  SL04 platform alerts cover every Stage 2 §6.5 platform signal; every policy routes to a defined channel
  SL05 an SLI source exists for every runtime and deployment model in the registry
  SL06 every project of the tier is monitored by exactly one scope of the tier, including the LB projects the SLIs
       read (plt-ingress-<tier>, plt-gke-<tier>)
Status: implemented + locally tested (tests/test_slo.py); nothing created in Google Cloud (T-SL1..T-SL6).
"""
import argparse
import json
import pathlib
import re
import sys

from tools.cost.capacity import config as capacity_config, scope_shards
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding, validate

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIMITS = {"projects_per_scope": 375, "slos_per_service": 500, "policies_per_scope": 2000, "conditions_per_policy": 6,
          "channels_per_policy": 16, "uptime_per_project": 100, "dashboards_per_scope": 1000}
DUR = {"m": 60, "h": 3600, "d": 86400}


def seconds(d):
    return int(d[:-1]) * DUR[d[-1]]


WIDGET_FILTERS = {      # dashboard widget -> metric filter (Cloud Monitoring); others become section headers
    "availability per product": 'metric.type="loadbalancing.googleapis.com/https/request_count" resource.type="https_lb_rule"',
    "requests": 'metric.type="loadbalancing.googleapis.com/https/request_count" resource.type="https_lb_rule"',
    "5xx ratio": 'metric.type="loadbalancing.googleapis.com/https/request_count" resource.type="https_lb_rule" metric.label.response_code_class="500"',
    "latency per product": 'metric.type="loadbalancing.googleapis.com/https/total_latencies" resource.type="https_lb_rule"',
    "latency p95": 'metric.type="loadbalancing.googleapis.com/https/total_latencies" resource.type="https_lb_rule"',
    "uptime": 'metric.type="monitoring.googleapis.com/uptime_check/check_passed" resource.type="uptime_url"',
    "SQL pool CPU/connections/disk": 'metric.type="cloudsql.googleapis.com/database/cpu/utilization" resource.type="cloudsql_database"',
    "replica lag": 'metric.type="cloudsql.googleapis.com/database/replication/replica_lag" resource.type="cloudsql_database"',
    "NAT ports": 'metric.type="router.googleapis.com/nat/allocated_ports" resource.type="nat_gateway"',
    "cells pods/pending": 'metric.type="kubernetes.io/container/restart_count" resource.type="k8s_container"',
    "pipeline job failures": 'metric.type="run.googleapis.com/job/completed_execution_count" resource.type="cloud_run_job"',
}


def dashboard_json(did, spec, tier, product=None):
    tiles = []
    for i, w in enumerate(spec["widgets"]):
        flt = WIDGET_FILTERS.get(w)
        if flt and product:
            flt += f' resource.label.backend_target_name=monitoring.regex.full_match(".*-{product}-{"prd" if tier == "prd" else ".*"}.*")'
        widget = {"title": w, "xyChart": {"dataSets": [{"timeSeriesQuery": {"timeSeriesFilter": {
            "filter": flt, "aggregation": {"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_RATE"}}}}]}} \
            if flt else {"title": w, "text": {"content": f"{w}: see the SLO and alert views (S8)", "format": "MARKDOWN"}}
        tiles.append({"xPos": (i % 2) * 6, "yPos": (i // 2) * 4, "width": 6, "height": 4, "widget": widget})
    out = {"displayName": f"{did} ({tier})", "mosaicLayout": {"columns": 12, "tiles": tiles}}
    if spec.get("filter"):
        out["dashboardFilters"] = [{"labelKey": spec["filter"], "filterType": "USER_METADATA_LABEL"}]
    return out


class Observability:
    def __init__(self, registry=ROOT / "registry", slo=ROOT / "slo" / "slos.yaml", root=ROOT):
        self.reg, _ = validate(registry)
        self.cfg = load_yaml(slo)
        self.path = str(slo)
        self.root = pathlib.Path(root)
        self.cap = capacity_config(root)

    # ------------------------------------------------------------------ inputs
    def subscriptions(self):
        """prd subscriptions: (tenant, product, runtime, model)."""
        out = []
        for t, (_, d) in sorted(self.reg.tenants.items()):
            for p, sub in sorted(d["subscriptions"].items()):
                _, prod = self.reg.products[p]
                envs = set((sub.get("versions") or sub.get("cohort") or {}).keys()) or {"prd"}
                if "prd" in envs:
                    out.append((t, p, prod["runtime"], prod["deployment_model"]))
        return out

    def tier_projects(self, tier):
        inv = self.reg.inventory
        pools = {**inv["sql_pools"], **inv.get("product_sql_pools", {})}
        cells = {c["project"] for c in inv["gke_cells"].values()}
        ps = {f"t-{t}-{tier}" for t in self.reg.tenants}
        ps |= {p["project"] for p in pools.values() if (p["env"] == "prd") == (tier == "prd")}
        ps |= {c for c in cells if c.endswith(f"-{tier}")}
        ps |= {f"plt-ingress-{tier}", f"plt-gke-{tier}", f"shr-cicd-{tier}"}
        ps |= {f"p-{p}-{tier}" for p, (_, d) in self.reg.products.items() if d["deployment_model"] != "dedicated"}
        return sorted(ps)

    # ------------------------------------------------------------------ SLI filters
    def backend_regex(self, tenant, product, runtime):
        tpl = self.cfg["sli"]["dedicated"]["backend_match"][runtime]
        return tpl.format(tenant=tenant if tenant else "[a-z0-9]+", product=product)

    def slo_filters(self, tenant, product, runtime, model):
        s = self.cfg["sli"]
        bad = s["bad_response_class"]
        if model == "dedicated":
            d = s["dedicated"]
            rx = self.backend_regex(tenant, product, runtime)
            sel = (f'resource.type="{d["resource"]}" resource.label.backend_target_name=monitoring.regex.full_match("{rx}")'
                   if any(ch in rx for ch in ".*[") else f'resource.type="{d["resource"]}" resource.label.backend_target_name="{rx}"')
            total = f'metric.type="{d["request_count"]}" {sel}'
            return {"total": total, "good": f'{total} metric.label.response_code_class!="{bad}"',
                    "latency": f'metric.type="{d["latency"]}" {sel}'}
        d = s["shared"]
        sel = f'resource.type="{d["resource"]}" metric.label.tenant="{tenant}" metric.label.product="{product}"'
        total = f'metric.type="{d["request_count"]}" {sel}'
        return {"total": total, "good": f'{total} metric.label.response_code_class!="{d["bad_response_class"]}"',
                "latency": f'metric.type="{d["latency"]}" {sel}'}

    def promql(self, product, runtime, model, window, goal, burn):
        bad = self.cfg["sli"]["bad_response_class"] if model == "dedicated" else self.cfg["sli"]["shared"]["bad_response_class"]
        if model == "dedicated":
            rx = self.backend_regex(None, product, runtime)
            m, by, sel = "loadbalancing_googleapis_com:https_request_count", "backend_target_name", \
                f'monitored_resource="https_lb_rule",backend_target_name=~"{rx}"'
        else:
            m, by, sel = "logging_googleapis_com:user_lb_requests_by_tenant", "tenant", \
                f'monitored_resource="https_lb_rule",product="{product}"'
        ratio = (f'sum by ({by}) (rate({m}{{{sel},response_code_class="{bad}"}}[{window}])) / '
                 f'sum by ({by}) (rate({m}{{{sel}}}[{window}]))')
        return f"({ratio}) > {round(burn * (1 - goal), 6)}"

    # ------------------------------------------------------------------ plan
    def plan(self, tier):
        cfg, o = self.cfg, {"tier": tier}
        projects = self.tier_projects(tier)
        shards = scope_shards(len(projects), self.cap)
        scopes, monitored, i = [], [], 0
        for n, size in enumerate(shards, 1):
            scope = f"plt-obs-{tier}-{n:02d}"
            scopes.append(scope)
            monitored += [{"scope": scope, "project": p} for p in projects[i:i + size]]
            i += size
        home = scopes[0]                                   # SLOs, product alerts and dashboards (LB projects here)
        o["scoping_projects"] = [{"name": s, "folder": f"fldr-platform/{tier}"} for s in scopes]
        o["monitored_projects"] = monitored
        ch = {"platform-oncall": cfg["channels"]["platform-oncall"], "security": cfg["channels"]["security"]}
        for p, (_, d) in sorted(self.reg.products.items()):
            ch[f"product-{p}"] = {"type": "email", "address": cfg["channels"]["product"]["address"].format(owner_group=d["owner_group"])}
        o["channels"] = [{"scope": s, "id": k, **v} for s in [home] for k, v in sorted(ch.items())]
        o["services"], o["slos"], o["alert_policies"], o["log_metrics"] = [], [], [], []
        per_service = int(self.cap["slos_per_service"]["limit"] * self.cap["slos_per_service"]["warn"])
        if tier == "prd":
            subs = self.subscriptions()
            obj = cfg["objectives"]["prd"]
            by_product = {}
            for s in subs:
                by_product.setdefault(s[1], []).append(s)
            for product, items in sorted(by_product.items()):
                for k in range(0, len(items), per_service):
                    sid = cfg["services"]["id"].format(product=product, tier=tier, nn=f"{k // per_service + 1:02d}")
                    o["services"].append({"scope": home, "id": sid, "product": product})
                    for t, p, rt, model in items[k:k + per_service]:
                        f = self.slo_filters(t, p, rt, model)
                        o["slos"].append({"service": sid, "id": f"{t}-{p}-availability", "tenant": t, "product": p,
                                          "type": "availability", "goal": obj["availability"]["goal"],
                                          "rolling_days": obj["availability"]["window_days"],
                                          "good_filter": f["good"], "total_filter": f["total"]})
                        o["slos"].append({"service": sid, "id": f"{t}-{p}-latency", "tenant": t, "product": p,
                                          "type": "latency", "goal": obj["latency"]["goal"],
                                          "rolling_days": obj["latency"]["window_days"],
                                          "threshold_ms": obj["latency"]["threshold_ms"], "latency_filter": f["latency"]})
                _, prod = self.reg.products[product]
                for a in cfg["burn_rate_alerts"]:
                    o["alert_policies"].append({
                        "scope": home, "id": f"slo-{product}-{a['id']}", "severity": a["severity"],
                        "display_name": f"{product} prd error budget burn ({a['id']}) per customer",
                        "conditions": [{"name": f"burn {a['long']} and {a['short']}",
                                        "promql": f"{self.promql(product, prod['runtime'], prod['deployment_model'], a['long'], obj['availability']['goal'], a['burn_rate'])}"
                                                  f" and {self.promql(product, prod['runtime'], prod['deployment_model'], a['short'], obj['availability']['goal'], a['burn_rate'])}",
                                        "duration": "0s"}],
                        "channels": [f"product-{product}"] + (["platform-oncall"] if a["severity"] == "page" else [])})
            if {m for _, _, _, m in subs} - {"dedicated"}:
                d = cfg["sli"]["shared"]
                for name, kind in (("lb_requests_by_tenant", "counter"), ("lb_latency_by_tenant", "distribution")):
                    o["log_metrics"].append({"project": f"plt-ingress-{tier}", "name": name, "kind": kind,
                                             "filter": d["log_filter"], "labels": d["labels"],
                                             "value_extractor": "EXTRACT(httpRequest.latency)" if kind == "distribution" else None})
            u = cfg["uptime"]
            o["alert_policies"].append({
                "scope": home, "id": "uptime-customer-hosts", "severity": u["alert"]["severity"],
                "display_name": "Customer host name unreachable (uptime, per check)",
                "conditions": [{"name": "uptime failing", "duration": u["alert"]["duration"],
                                "promql": "count by (check_id, host) (avg_over_time(monitoring_googleapis_com:uptime_check_check_passed"
                                          f"{{monitored_resource=\"uptime_url\"}}[5m]) < 1) >= {u['alert']['failing_regions']}"}],
                "channels": ["platform-oncall"] + [f"product-{p}" for p in sorted(by_product)][:15]})
        for a in cfg["platform_alerts"]:
            if a.get("outside_monitoring"):
                continue                                   # raised outside Cloud Monitoring (documented, SL04)
            cond = {"name": a["id"], "duration": "600s"}
            for k in ("filter", "comparison", "threshold", "promql", "log_filter"):
                if k in a:
                    cond[k] = a[k]
            cond["aligner"] = a.get("aligner", "ALIGN_MEAN")
            o["alert_policies"].append({"scope": home, "id": a["id"].lower(), "severity": a["severity"],
                                        "display_name": f"{a['id']} ({a['covers']})", "covers": a["covers"],
                                        "conditions": [cond], "channels": ["platform-oncall"]})
        o["dashboards"] = []
        for d in cfg["dashboards"]:
            items = [(f"{d['id']}-{p}", p) for p in sorted(self.reg.products)] if d.get("per") == "product" else [(d["id"], None)]
            for did, product in items:
                o["dashboards"].append({"scope": home, "id": did,
                                        "json": json.dumps(dashboard_json(did, d, tier, product), sort_keys=True)})
        return o

    def uptime_checks(self, tenant, tier):
        """Uptime checks for the tenant stack (prd only): one per customer host name."""
        if tier != "prd":
            return []
        u = self.cfg["uptime"]
        edge = json.loads((self.root / "build" / "edge.json").read_text()) if (self.root / "build/edge.json").exists() else None
        if edge is None:
            from tools.network.edge import Edge
            edge = Edge(str(self.root / "registry"), str(self.root / "network"), str(self.root / "security")).out
        hosts = sorted(r["hostname"] for r in edge["records"] if r.get("tenant") == tenant and r["zone"].endswith("-prd"))
        return [{"id": f"up-{h.split('.')[1]}", "host": h, "product": h.split(".")[1], "path": u["path"],
                 "period": f"{u['period_seconds']}s", "timeout": f"{u['timeout_seconds']}s", "regions": u["regions"]}
                for h in hosts]

    # ------------------------------------------------------------------ rules
    def check(self):
        f, P, cfg = [], self.path, self.cfg
        plans = {t: self.plan(t) for t in ("prd", "nonprd")}
        prd = plans["prd"]
        want = {(t, p) for t, p, _, _ in self.subscriptions()}
        for kind in ("availability", "latency"):
            have = {(s["tenant"], s["product"]) for s in prd["slos"] if s["type"] == kind}
            for t, p in sorted(want - have):
                f.append(Finding("SL01", P, f"{t}/{p}: no prd {kind} SLO"))
            for t, p in sorted(have - want):
                f.append(Finding("SL01", P, f"{t}/{p}: {kind} SLO without a prd subscription"))
        for t in sorted({t for t, _ in want}):
            checks = {c["product"] for c in self.uptime_checks(t, "prd")}
            for p in sorted({p for tt, p in want if tt == t} - checks):
                f.append(Finding("SL01", P, f"{t}/{p}: no uptime check on the prd host name"))
            if len(checks) > LIMITS["uptime_per_project"]:
                f.append(Finding("SL02", P, f"t-{t}-prd: {len(checks)} uptime checks > {LIMITS['uptime_per_project']}"))
        for tier, o in plans.items():
            per_scope = {}
            for m in o["monitored_projects"]:
                per_scope[m["scope"]] = per_scope.get(m["scope"], 0) + 1
            for s, n in per_scope.items():
                if n > LIMITS["projects_per_scope"]:
                    f.append(Finding("SL02", P, f"{s}: {n} monitored projects > {LIMITS['projects_per_scope']}"))
            for svc in o["services"]:
                n = sum(1 for s in o["slos"] if s["service"] == svc["id"])
                if n > LIMITS["slos_per_service"]:
                    f.append(Finding("SL02", P, f"{svc['id']}: {n} SLOs > {LIMITS['slos_per_service']}"))
            if len(o["alert_policies"]) > LIMITS["policies_per_scope"]:
                f.append(Finding("SL02", P, f"{tier}: {len(o['alert_policies'])} alert policies"))
            if len(o["dashboards"]) > LIMITS["dashboards_per_scope"]:
                f.append(Finding("SL02", P, f"{tier}: {len(o['dashboards'])} dashboards"))
            chans = {c["id"] for c in o["channels"]}
            for a in o["alert_policies"]:
                if len(a["conditions"]) > LIMITS["conditions_per_policy"] or len(a["channels"]) > LIMITS["channels_per_policy"]:
                    f.append(Finding("SL02", P, f"{a['id']}: too many conditions or channels"))
                for c in a["channels"]:
                    if c not in chans:
                        f.append(Finding("SL04", P, f"{a['id']}: unknown channel {c}"))
            # SL06 – every project in exactly one scope, LB projects included
            seen = [m["project"] for m in o["monitored_projects"]]
            if sorted(seen) != sorted(set(seen)) or set(seen) != set(self.tier_projects(tier)):
                f.append(Finding("SL06", P, f"{tier}: monitored projects not covered exactly once"))
            home = o["scoping_projects"][0]["name"]
            for lb in (f"plt-ingress-{tier}", f"plt-gke-{tier}"):
                if {"scope": home, "project": lb} not in o["monitored_projects"]:
                    f.append(Finding("SL06", P, f"{lb} must be in the home scope {home} (SLI metrics)"))
        # SL03 – burn-rate maths
        obj = cfg["objectives"]["prd"]["availability"]
        window = obj["window_days"] * 86400
        alerts = cfg["burn_rate_alerts"]
        for a in alerts:
            if seconds(a["short"]) >= seconds(a["long"]):
                f.append(Finding("SL03", P, f"{a['id']}: short window must be shorter than the long window"))
            spent = a["burn_rate"] * seconds(a["long"]) / window
            if spent < 0.01 or a["burn_rate"] * (1 - obj["goal"]) >= 1:
                f.append(Finding("SL03", P, f"{a['id']}: burn rate {a['burn_rate']} over {a['long']} spends {spent:.1%} of the budget"))
        pages = [a["burn_rate"] for a in alerts if a["severity"] == "page"]
        tickets = [a["burn_rate"] for a in alerts if a["severity"] == "ticket"]
        if pages and tickets and min(pages) <= max(tickets):
            f.append(Finding("SL03", P, "page burn rates must be above ticket burn rates"))
        # SL04 – platform coverage, one condition kind per alert
        covered = {a["covers"] for a in cfg["platform_alerts"]}
        for a in cfg["platform_alerts"]:
            kinds = [k for k in ("filter", "promql", "log_filter", "outside_monitoring") if a.get(k)]
            if len(kinds) != 1 or ("filter" in kinds and not {"comparison", "threshold"} <= set(a)):
                f.append(Finding("SL04", P, f"{a['id']}: exactly one of filter (+comparison, threshold), promql, log_filter, outside_monitoring"))
        for c in cfg["required_platform_coverage"]:
            if c not in covered:
                f.append(Finding("SL04", P, f"no platform alert covers {c}"))
        # SL05 – SLI source per runtime / model
        for p, (_, d) in self.reg.products.items():
            if d["deployment_model"] == "dedicated" and d["runtime"] not in cfg["sli"]["dedicated"]["backend_match"]:
                f.append(Finding("SL05", P, f"{p}: no SLI backend match for runtime {d['runtime']}"))
            if d["deployment_model"] != "dedicated" and "shared" not in cfg["sli"]:
                f.append(Finding("SL05", P, f"{p}: no SLI source for {d['deployment_model']}"))
        return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="build/observability.json")
    a = ap.parse_args(argv)
    ob = Observability()
    plans = {t: ob.plan(t) for t in ("prd", "nonprd")}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plans, indent=1))
    findings = ob.check()
    for x in findings:
        print(x)
    p = plans["prd"]
    print(f"prd: {len(p['scoping_projects'])} scope(s), {len(p['monitored_projects'])} monitored projects, "
          f"{len(p['services'])} services, {len(p['slos'])} SLOs, {len(p['alert_policies'])} alert policies, "
          f"{sum(len(ob.uptime_checks(t, 'prd')) for t in ob.reg.tenants)} uptime checks; {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
