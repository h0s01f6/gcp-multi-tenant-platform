"""Stage 8 – availability, backup and disaster recovery checks (slo/dr.yaml) against the Terraform modules, the
capacity model, the pipeline and the network / security configuration; Terraform inputs for the DR replicas.

Usage:  python3 -m tools.slo.dr

Rules
  BC01 backups and HA as declared: sql-pool module keeps 30 backups in prd / 7 elsewhere, binary logs on, PITR days,
       both deletion-protection flags; platform tfvars give REGIONAL to prd and uat pools, ZONAL to dev / stg
  BC02 every failure class has RPO, RTO and a mechanism; RPO/RTO within the availability target's error budget for
       automated classes; the replica-lag alert (slo/slos.yaml) is below the region RPO; the region class without
       DR has an explicit interim target
  BC03 restore model: the largest prd pool (capacity model) is restored within the data-corruption RTO
  BC04 regional DR: when `enabled`, every prerequisite holds (N1 as2 active, D5 location, D9 keys, DR cells);
       when not enabled, no DR replica is generated
  BC05 region failover critical path (runbook R-3) <= region RTO
  BC06 drills exist for restore, zone, region and rollback; the prd release takes an on-demand backup first
       (deploy-release workflow); the bad-release class is backed by automatic rollback in the workflows
Status: implemented + locally tested (tests/test_slo.py). Restores, failovers and drills not run in GCP (T-DR1..5).
"""
import argparse
import pathlib
import re
import sys

from tools.cost.model import capacity_model
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

ROOT = pathlib.Path(__file__).resolve().parents[2]
UNIT = {"s": 1, "m": 60, "h": 3600}


class DisasterRecovery:
    def __init__(self, registry=ROOT / "registry", security=ROOT / "security", root=ROOT):
        self.root = pathlib.Path(root)
        self.path = str(self.root / "slo" / "dr.yaml")
        self.cfg = load_yaml(self.path)
        self.slos = load_yaml(self.root / "slo" / "slos.yaml")
        self.security = pathlib.Path(security)
        self.registry = pathlib.Path(registry)

    # ------------------------------------------------------------------ Terraform inputs
    def enabled(self):
        return bool(self.cfg["regional_dr"]["enabled"])

    def replica(self, pool, env):
        """sql-pool `dr` input: only for prd pools and only once regional DR is activated (BC04)."""
        if not self.enabled() or env != "prd":
            return None
        d = self.cfg["regional_dr"]
        return {"region": d["region"],
                "kms_key": f"projects/shr-security/locations/{d['region']}/keyRings/kr-plt-prd-{d['region_short']}/cryptoKeys/{pool}"}

    def backup_location(self, env):
        return self.cfg["regional_dr"]["region"] if self.enabled() and env == "prd" else None

    # ------------------------------------------------------------------ rules
    def check(self, platform_tfvars=None):
        f, P, c = [], self.path, self.cfg
        # BC01 – module settings (static read of the HCL) and generated pool availability
        hcl = (self.root / "terraform/modules/sql-pool/main.tf").read_text()
        m = re.search(r'retained_backups\s*=\s*var\.pool\.env == "prd" \? (\d+) : (\d+)', hcl)
        if not m or int(m.group(1)) != c["backups"]["prd"]["retained"] or \
                any(int(m.group(2)) != c["backups"][e]["retained"] for e in ("uat", "stg", "dev")):
            f.append(Finding("BC01", "terraform/modules/sql-pool/main.tf", "retained backups differ from slo/dr.yaml"))
        m = re.search(r"transaction_log_retention_days\s*=\s*(\d+)", hcl)
        if not m or any(int(m.group(1)) != b["pitr_days"] for b in c["backups"].values()):
            f.append(Finding("BC01", "terraform/modules/sql-pool/main.tf", "PITR log retention differs from slo/dr.yaml"))
        for needle in ("binary_log_enabled             = true", "deletion_protection = true", "deletion_protection_enabled = true"):
            if needle not in hcl:
                f.append(Finding("BC01", "terraform/modules/sql-pool/main.tf", f"missing `{needle}`"))
        if platform_tfvars is None:
            from tools.iac.tfvars import Bridge
            b = Bridge(str(self.registry), str(self.security))
            platform_tfvars = {t: b.platform(t) for t in b.tiers}
        for tier, pv in platform_tfvars.items():
            for sp in pv["sql_pools"]:
                want = c["backups"][sp["env"]]["ha"]
                if sp["availability"] != want:
                    f.append(Finding("BC01", P, f"{sp['pool']}: availability {sp['availability']}, dr.yaml wants {want}"))
                if (sp.get("dr") is not None) != (self.enabled() and sp["env"] == "prd"):
                    f.append(Finding("BC04", P, f"{sp['pool']}: DR replica present = {sp.get('dr') is not None}, "
                                                f"regional DR enabled = {self.enabled()}"))
        # BC02 – failure classes
        budget_min = (1 - c["availability"]["prd"]) * 28 * 24 * 60
        for name, fc in c["failure_classes"].items():
            if not {"rpo_min", "rto_min", "mechanism"} <= set(fc):
                f.append(Finding("BC02", P, f"{name}: rpo_min, rto_min and mechanism required"))
                continue
            if fc.get("automated") and fc["rto_min"] > budget_min:
                f.append(Finding("BC02", P, f"{name}: automated recovery of {fc['rto_min']} min exceeds the 28-day "
                                            f"error budget ({budget_min:.0f} min)"))
        lag = c["regional_dr"]["replica_lag_alert_s"]
        if lag / 60 >= c["failure_classes"]["region"]["rpo_min"]:
            f.append(Finding("BC02", P, "replica-lag alert must be below the region RPO"))
        pa = next((a for a in self.slos["platform_alerts"] if a["id"] == "PA-SQL-REPLICA-LAG"), None)
        if not pa or pa.get("threshold") != lag:
            f.append(Finding("BC02", P, "PA-SQL-REPLICA-LAG threshold must equal regional_dr.replica_lag_alert_s"))
        if not self.enabled() and not c.get("region_without_dr"):
            f.append(Finding("BC02", P, "regional DR not enabled: an interim region target (region_without_dr) is required"))
        # BC03 – restore model
        cm = capacity_model()
        cap, _, _ = cm.effective_cap(cm.PRD)
        size_gb = min(cap * cm.PRD["tenant_gb"] * (1 + cm.PRD["growth"]) ** cm.PRD["years"], cm.PRD["storage_cap_gb"])
        minutes = size_gb / c["restore"]["clone_gb_per_hour"] * 60 + c["restore"]["fixed_overhead_min"]
        self.restore_minutes = round(minutes)
        if minutes > c["failure_classes"]["data_corruption"]["rto_min"]:
            f.append(Finding("BC03", P, f"restoring a {size_gb:.0f} GB prd pool takes ~{minutes:.0f} min > corruption RTO"))
        # BC04 – regional DR prerequisites
        self.prereq = self.prerequisites()
        if self.enabled():
            for k, ok in self.prereq.items():
                if not ok:
                    f.append(Finding("BC04", P, f"regional DR enabled but prerequisite not met: {k}"))
        # BC05 – failover critical path
        path = sum(c["region_failover_steps_min"].values())
        self.failover_minutes = path
        if path > c["failure_classes"]["region"]["rto_min"]:
            f.append(Finding("BC05", P, f"failover critical path {path} min > region RTO"))
        # BC06 – drills, pre-release backup, rollback
        what = " ".join(d["what"] for d in c["drills"])
        for k in ("restore", "zone", "regional", "rollback"):
            if k not in what:
                f.append(Finding("BC06", P, f"no drill covers {k}"))
        wf = (self.root / "cicd/platform-workflows/.github/workflows/deploy-release.yml").read_text()
        if c["backups"]["prd"]["on_demand_before_release"] and "gcloud sql backups create" not in wf:
            f.append(Finding("BC06", P, "prd releases must take an on-demand backup first (deploy-release.yml)"))
        for needle in ("--atomic", "--to-revisions", 'template=$cur'):
            if needle not in wf:
                f.append(Finding("BC06", P, f"bad_release class needs automatic rollback ({needle})"))
        return f

    def prerequisites(self):
        d = self.cfg["regional_dr"]
        ip = load_yaml(self.root / "network" / "ip-plan.yaml")
        op = (self.security / "org-policies.yaml").read_text()
        from tools.security.dataprotection import DataProtection
        keys = DataProtection(str(self.registry), str(self.security)).generate()["keys"]
        inv = load_yaml(self.registry / "platform" / "inventory.yaml")
        return {
            "N1 region active": (ip.get("regions", {}).get(d["region"]) or {}).get("status") == "active",
            "D5 resource location": f"in:{d['region']}-locations" in op,
            "D9 DR keys": any(k["location"] == d["region"] for k in keys),
            "DR cells": any(f"-{d['region_short']}-" in c for c in inv["gke_cells"]),
        }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    d = DisasterRecovery()
    findings = d.check()
    for x in findings:
        print(x)
    state = "ENABLED" if d.enabled() else "designed, not activated (Q10) – prerequisites: " + \
        ", ".join(f"{k} {'ok' if v else 'open'}" for k, v in d.prereq.items())
    print(f"{len(d.cfg['failure_classes'])} failure classes, prd pool restore ~{d.restore_minutes} min, region failover "
          f"path {d.failover_minutes} min; regional DR {state}; {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
