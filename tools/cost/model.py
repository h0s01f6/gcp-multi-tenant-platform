"""Stage 8 – monthly cost estimate for 200 and 500 customers (capacity-model scenarios x cost/cost-model.yaml).

Usage:  python3 -m tools.cost.model [--write-doc] [-o build/cost.json]
        --write-doc regenerates documentation/cost-estimate.md (CO04 fails when it is stale)

Counts (subscriptions, deployments, GKE cells, Cloud SQL pools incl. DR replicas, MIG floor) come from
scripts/capacity_model.py, so cost and capacity can never disagree. Prices, sizing and usage are the illustrative
inputs of cost/cost-model.yaml (indicative list prices – T-CO1).
Rules
  CO01 every price has a value, unit and source; region_factor and as_of are set
  CO02 counts used equal the capacity model (pools + DR + non-prod pools = total instances; cells; MIG floor)
  CO03 every cost component of the platform is priced (non-negative) for every scenario
  CO04 documentation/cost-estimate.md equals its generated form
Status: implemented + locally tested (tests/test_cost.py). Figures are planning estimates, not quotes.
"""
import argparse
import importlib.util
import json
import pathlib
import sys

from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "documentation" / "cost-estimate.md"
ENVS = ["dev", "stg", "uat", "prd"]
COMPONENTS = ["gke_clusters", "gke_pods", "cloud_run", "mig_vms", "cloud_sql", "sql_backups", "sql_dr",
              "load_balancing", "internet_egress", "nat", "cloud_armor", "dns", "logging", "monitoring",
              "kms_secrets", "artifacts_scanning", "cicd_runners", "fixed"]


def capacity_model():
    spec = importlib.util.spec_from_file_location("capacity_model", ROOT / "scripts" / "capacity_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class CostModel:
    def __init__(self, path=ROOT / "cost" / "cost-model.yaml"):
        self.path = str(path)
        self.cfg = load_yaml(path)
        self.cm = capacity_model()
        self.h = self.cfg["hours_per_month"]

    def p(self, key):
        pr = self.cfg["prices"][key]
        return pr["value"] * (self.cfg["region_factor"] if pr.get("regional") else 1.0)

    # ------------------------------------------------------------------ one scenario
    def estimate(self, customers, label, products):
        cm, c, h, p = self.cm, self.cfg, self.h, self.p
        r = cm.row(customers, label, products)
        sz, us = c["sizing"], c["usage"]
        P = r["P"]
        dep_env = r["mixed_deploy"] / 4                       # deployments per environment (illustrative model mix)
        mix = cm.RUNTIME_MIX
        dep = {rt: dep_env * share for rt, share in mix.items()}
        out = {k: {"prd": 0.0, "nonprd": 0.0, "dr": 0.0, "shared": 0.0} for k in COMPONENTS}
        office = {}                                            # dev/stg part of each component (office-hours lever)
        cud = {}                                               # prd steady-state part eligible for a CUD

        # GKE: management fee per cell (+ pilot-light DR cells), Autopilot pod requests
        cells = r["cells_env"]
        out["gke_clusters"]["nonprd"] = 3 * cells * h * p("gke_cluster_fee_hour")
        out["gke_clusters"]["prd"] = cells * h * p("gke_cluster_fee_hour")
        out["gke_clusters"]["dr"] = (cells * h * p("gke_cluster_fee_hour")) if c["dr"]["regional"] else 0.0
        pod = lambda e: sz["gke"][e]["replicas"] * (sz["gke"][e]["vcpu"] * p("autopilot_vcpu_hour") +
                                                    sz["gke"][e]["gib"] * p("autopilot_gib_hour")) * h * dep["gke"]
        out["gke_pods"]["prd"] = pod("prd")
        out["gke_pods"]["nonprd"] = pod("uat") + pod("stg") + pod("dev")
        office["gke_pods"] = pod("stg") + pod("dev")
        cud["gke_pods"] = pod("prd")

        # Cloud Run: prd min instances (instance billing) + burst; non-prod request billing, scale to zero
        crp, crn = sz["cloudrun"]["prd"], sz["cloudrun"]["nonprd"]
        inst = (crp["vcpu"] * p("run_instance_vcpu_second") + crp["gib"] * p("run_instance_gib_second")) * 3600 * h
        out["cloud_run"]["prd"] = dep["cloudrun"] * inst * (crp["min_instances"] + crp["busy_extra_instances"])
        cud["cloud_run"] = dep["cloudrun"] * inst * crp["min_instances"]
        req = (crn["vcpu"] * p("run_request_vcpu_second") + crn["gib"] * p("run_request_gib_second")) * 3600 * h
        out["cloud_run"]["nonprd"] = 3 * dep["cloudrun"] * req * crn["duty"]

        # MIG: capacity-model floor (prd 3 / non-prod 1 VM per deployment), e2-standard-2 + boot disk
        vm = h * p("e2_standard_2_hour") + sz["mig"]["disk_gb"] * p("pd_balanced_gb_month")
        mig_env = r["subs"] * mix["mig"]
        out["mig_vms"]["prd"] = mig_env * cm.MIG_MIN_VMS_PRD * vm
        out["mig_vms"]["nonprd"] = mig_env * cm.NONPROD_ENVS * cm.MIG_MIN_VMS_NONPROD * vm
        office["mig_vms"] = mig_env * 2 * cm.MIG_MIN_VMS_NONPROD * vm
        cud["mig_vms"] = out["mig_vms"]["prd"]

        # Cloud SQL pools (counts from the capacity model) – prd Enterprise Plus HA, uat HA, dev/stg zonal
        sp, sn = sz["sql"]["prd"], sz["sql"]["nonprd"]
        prd_inst = (sp["vcpu"] * p("sql_entplus_vcpu_hour") + sp["gib"] * p("sql_entplus_gib_hour")) * h
        npr_inst = (sn["vcpu"] * p("sql_ent_vcpu_hour") + sn["gib"] * p("sql_ent_gib_hour")) * h
        prd_gb = r["subs"] * sz["sql"]["tenant_gb"]["prd"]
        npr_gb_env = r["subs"] * sz["sql"]["tenant_gb"]["nonprd"]
        per_env_npr = r["npr"] / cm.NONPROD_ENVS
        out["cloud_sql"]["prd"] = r["prd"] * prd_inst * 2 + prd_gb * p("sql_ssd_gb_month") * 2
        cud["cloud_sql"] = r["prd"] * prd_inst * 2
        out["cloud_sql"]["nonprd"] = per_env_npr * npr_inst * (2 + 1 + 1) + npr_gb_env * p("sql_ssd_gb_month") * (2 + 1 + 1)
        office["cloud_sql"] = per_env_npr * npr_inst * 2
        if c["dr"]["regional"]:
            out["sql_dr"]["dr"] = r["dr"] * prd_inst * (2 if c["dr"]["replica_ha"] else 1) + prd_gb * p("sql_ssd_gb_month")
            cud["sql_dr"] = r["dr"] * prd_inst
        bo = sz["sql"]["backup_overhead"] * p("sql_backup_gb_month")
        out["sql_backups"]["prd"] = prd_gb * bo
        out["sql_backups"]["nonprd"] = npr_gb_env * cm.NONPROD_ENVS * bo * 0.5      # 7 instead of 30 backups

        # Load balancing, egress, NAT, Cloud Armor, DNS
        prd_req = r["subs"] * us["requests_million"]                                    # million requests / month
        frontends_env = cm.CATALOGUE * sz["frontends_per_product_env"] + cm.CATALOGUE * mix["gke"] * max(cells - 1, 0)
        rule = h * p("lb_forwarding_rule_hour")
        gb = prd_req * us["kb_per_response"]                                            # GB (1M x KB = GB)
        out["load_balancing"]["prd"] = frontends_env * rule + gb * p("lb_data_processed_gb")
        out["load_balancing"]["nonprd"] = 3 * frontends_env * rule + 0.05 * gb * p("lb_data_processed_gb")
        out["internet_egress"]["prd"] = gb * p("internet_egress_gb")
        out["internet_egress"]["nonprd"] = 0.05 * gb * p("internet_egress_gb")
        out["nat"]["prd"] = h * p("nat_gateway_hour") + 39 * h * p("static_ip_hour") + r["subs"] * us["nat_gb"] * p("nat_data_gb")
        out["nat"]["nonprd"] = h * p("nat_gateway_hour") + 28 * h * p("static_ip_hour") + 0.3 * r["subs"] * us["nat_gb"] * p("nat_data_gb")
        out["cloud_armor"]["prd"] = p("armor_policy_month") + 10 * p("armor_rule_month") + prd_req * p("armor_requests_million")
        out["cloud_armor"]["nonprd"] = p("armor_policy_month") + 10 * p("armor_rule_month") + 0.05 * prd_req * p("armor_requests_million")
        zones = cm.CATALOGUE * 2 + 4
        out["dns"]["shared"] = zones * p("dns_zone_month") + 0.05 * prd_req * p("dns_queries_million")

        # Logging: Cloud Run/MIG logs in each customer's project (free 50 GiB/project), GKE logs in the cluster
        # projects, LB request logs in the ingress / cluster projects, org audit sink (D10)
        free = c["free_tier"]["logging_gib_per_project"]
        lg = us["log_gib"]
        per_cust_prd = P * (mix["cloudrun"] + mix["mig"]) * lg["prd"]
        per_cust_npr = P * (mix["cloudrun"] + mix["mig"]) * lg["nonprd"] * 3
        tenant_log = customers * (max(per_cust_prd - free, 0) + max(per_cust_npr - free, 0))
        gke_log = max(dep["gke"] * lg["prd"] - 2 * free, 0) + max(3 * dep["gke"] * lg["nonprd"] - 2 * free, 0)
        lb_log = max(prd_req * us["lb_log_sample_rate"] * us["lb_log_kb_per_request"] * 1e6 / 2**20 - 2 * free, 0)
        audit = max(us["audit_log_gib"] - free, 0) * p("logging_ingest_gib") + \
            us["audit_log_gib"] * max(us["audit_retention_days"] - 30, 0) / 30 * p("logging_retention_gib_month")
        out["logging"]["prd"] = (tenant_log * per_cust_prd / max(per_cust_prd + per_cust_npr, 1e-9) + gke_log * 0.6 + lb_log) * p("logging_ingest_gib")
        out["logging"]["nonprd"] = (tenant_log * per_cust_npr / max(per_cust_prd + per_cust_npr, 1e-9) + gke_log * 0.4) * p("logging_ingest_gib")
        out["logging"]["shared"] = audit

        # Monitoring: alert conditions, Managed Prometheus samples, uptime checks in the customer projects
        conds = cm.CATALOGUE * us["alert_conditions_per_product"] + us["platform_alert_conditions"]
        out["monitoring"]["prd"] = conds * p("alert_condition_month") + \
            dep["gke"] * us["prometheus_samples_million_per_gke_deployment"] * p("prometheus_samples_million")
        out["monitoring"]["nonprd"] = 3 * dep["gke"] * us["prometheus_samples_million_per_gke_deployment"] * p("prometheus_samples_million")
        up = us["uptime"]
        exec_per_project = P * up["regions"] * (h * 60 / up["period_minutes"])
        out["monitoring"]["prd"] += customers * max(exec_per_project - c["free_tier"]["uptime_executions_per_project"], 0) / 1000 * \
            p("uptime_executions_thousand")

        # Keys, secrets, artifacts, scanning, CI/CD runners, fixed
        keys = customers * us["keys_per_prd_tenant"] + r["prd"]
        out["kms_secrets"]["prd"] = keys * p("kms_software_key_month") + p("kms_hsm_key_month")
        out["kms_secrets"]["dr"] = (r["dr"] * p("kms_software_key_month")) if c["dr"]["regional"] else 0.0
        out["kms_secrets"]["nonprd"] = 0.0
        out["kms_secrets"]["shared"] = r["mixed_deploy"] * us["secrets_per_deployment"] * p("secret_version_month")
        a = us["artifact"]
        out["artifacts_scanning"]["shared"] = cm.CATALOGUE * a["versions_kept"] * a["gb_per_image"] * p("artifact_storage_gb_month") + \
            cm.CATALOGUE * a["builds_per_product_month"] * p("artifact_scan_image")
        out["cicd_runners"]["shared"] = sum(v["count"] * v["busy"] * h * p(v["vm"]) for v in us["cicd_runners"].values())
        out["fixed"]["shared"] = us["fixed_month"]

        total = sum(sum(v.values()) for v in out.values())
        lv = c["levers"]
        save = sum(cud.get(k, 0.0) for k in ("gke_pods", "cloud_run", "mig_vms")) * lv["cud_flex_3y"] + \
            (cud.get("cloud_sql", 0.0) + cud.get("sql_dr", 0.0)) * lv["cud_sql_3y"] + \
            sum(office.values()) * (1 - lv["nonprd_office_hours"])
        by_tier = {t: sum(v[t] for v in out.values()) for t in ("prd", "nonprd", "dr", "shared")}
        return {"customers": customers, "scenario": label, "avg_products": P, "subscriptions": r["subs"],
                "counts": {"cells_per_env": cells, "sql_prd": r["prd"], "sql_dr": r["dr"], "sql_nonprd": r["npr"],
                           "sql_total": r["total"], "mig_vms": r["mig_vms"], "deployments": r["mixed_deploy"]},
                "components": {k: {t: round(x, 2) for t, x in v.items()} for k, v in out.items()},
                "by_tier": {k: round(v, 2) for k, v in by_tier.items()},
                "total_list": round(total, 2), "total_optimised": round(total - save, 2),
                "per_customer_list": round(total / customers, 2),
                "per_customer_optimised": round((total - save) / customers, 2),
                "per_subscription_list": round(total / r["subs"], 2)}

    def scenarios(self):
        return [self.estimate(c, s, p) for c in self.cm.CUSTOMERS for s, p in self.cm.SCENARIOS]

    # ------------------------------------------------------------------ rules
    def check(self):
        f, P = [], self.path
        for k, v in self.cfg["prices"].items():
            if not isinstance(v.get("value"), (int, float)) or v["value"] < 0 or not v.get("unit") or not v.get("source"):
                f.append(Finding("CO01", P, f"price {k}: value, unit and source required"))
        for k in ("region_factor", "as_of", "region"):
            if not self.cfg.get(k):
                f.append(Finding("CO01", P, f"{k} missing"))
        for e in self.scenarios():
            r = self.cm.row(e["customers"], e["scenario"], e["avg_products"])
            cnt = e["counts"]
            if cnt["sql_prd"] + cnt["sql_dr"] + cnt["sql_nonprd"] != r["total"] or cnt["mig_vms"] != r["mig_vms"] \
                    or cnt["cells_per_env"] != r["cells_env"]:
                f.append(Finding("CO02", P, f"{e['customers']}/{e['scenario']}: counts differ from the capacity model"))
            for comp in COMPONENTS:
                vals = e["components"].get(comp)
                if vals is None or min(vals.values()) < 0:
                    f.append(Finding("CO03", P, f"{e['customers']}/{e['scenario']}: component {comp} not priced"))
        if not DOC.exists() or DOC.read_text() != self.render_doc():
            f.append(Finding("CO04", str(DOC.relative_to(ROOT)), "stale – run python3 -m tools.cost.model --write-doc"))
        return f

    # ------------------------------------------------------------------ document
    def render_doc(self):
        rows = self.scenarios()
        L = ["<!-- GENERATED by `python3 -m tools.cost.model --write-doc` from cost/cost-model.yaml and",
             "     scripts/capacity_model.py – do not edit by hand (CO04). -->",
             "# Cost estimate – 200 and 500 customers (Stage 8)",
             "",
             f"Monthly figures in {self.cfg['currency']}, on-demand **list** prices (as of {self.cfg['as_of']}, "
             f"region factor {self.cfg['region_factor']} for {self.cfg['region']}), **indicative planning estimates, "
             "not quotes** – validate with the Pricing Calculator / Billing Catalog API and negotiated discounts (T-CO1). "
             "Counts come from the capacity model; sizing and usage are the illustrative inputs of "
             "[`cost/cost-model.yaml`](../cost/cost-model.yaml). *Optimised* applies 3-year commitments to the steady "
             "prd base (Cloud SQL, Autopilot, Cloud Run min instances, MIG VMs) and office-hours scale-down of dev/stg.",
             "",
             "## 1. Totals by scenario",
             "",
             "| Customers | Scenario | Avg products | Subscriptions | Cloud SQL instances (prd + DR + non-prd) | List / month | Optimised / month | List per customer | Optimised per customer | List per subscription |",
             "|---|---|---|---|---|---|---|---|---|---|"]
        for e in rows:
            c = e["counts"]
            L.append(f"| {e['customers']} | {e['scenario']} | {e['avg_products']} | {e['subscriptions']:,} | "
                     f"{c['sql_prd']} + {c['sql_dr']} + {c['sql_nonprd']} | ${e['total_list']:,.0f} | ${e['total_optimised']:,.0f} | "
                     f"${e['per_customer_list']:,.0f} | ${e['per_customer_optimised']:,.0f} | ${e['per_subscription_list']:,.0f} |")
        base = [e for e in rows if e["scenario"] == "Baseline"]
        L += ["", "## 2. Breakdown – Baseline (3 products per customer)", "",
              "| Component | " + " | ".join(f"{e['customers']} customers" for e in base) + " | Share at 500 |",
              "|---|" + "---|" * (len(base) + 1)]
        tot500 = base[-1]["total_list"]
        for comp in COMPONENTS:
            vals = [sum(e["components"][comp].values()) for e in base]
            L.append(f"| {comp.replace('_', ' ')} | " + " | ".join(f"${v:,.0f}" for v in vals) +
                     f" | {100 * vals[-1] / tot500:.1f} % |")
        L.append("| **total (list)** | " + " | ".join(f"**${e['total_list']:,.0f}**" for e in base) + " | 100 % |")
        L += ["", "## 3. By tier – Baseline", "", "| Tier | " + " | ".join(f"{e['customers']} customers" for e in base) + " |",
              "|---|" + "---|" * len(base)]
        for t in ("prd", "nonprd", "dr", "shared"):
            L.append(f"| {t} | " + " | ".join(f"${e['by_tier'][t]:,.0f}" for e in base) + " |")
        L.append("")
        return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-doc", action="store_true")
    ap.add_argument("-o", "--out", default="build/cost.json")
    a = ap.parse_args(argv)
    m = CostModel()
    if a.write_doc:
        DOC.write_text(m.render_doc())
    rows = m.scenarios()
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    findings = m.check()
    for x in findings:
        print(x)
    b = {e["customers"]: e for e in rows if e["scenario"] == "Baseline"}
    print(f"Baseline list/month: 200 -> ${b[200]['total_list']:,.0f} (${b[200]['per_customer_list']:,.0f}/customer), "
          f"500 -> ${b[500]['total_list']:,.0f} (${b[500]['per_customer_list']:,.0f}/customer); {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
