"""D10 – check and render audit logging, the central audit sink and the security alerts.

Usage:  python3 -m tools.monitoring.audit [--registry registry] [--security security] [-o build/monitoring.json]

Rules
  AU01 every alert D7 requires (privileged-access.yaml required_alerts) is implemented
  AU02 every alert has a known severity, a filter, a runbook and what it covers; break-glass alerts page; filters are
       balanced and never mix AND/OR without parentheses
  AU03 Data Access logs on for IAM credentials, STS, KMS, Secret Manager and Cloud SQL at the org and for Cloud
       Storage in prod folders; no exempted principals; only known nodes
  AU04 org sink: includes children, captures cloudaudit logs, writes to a locked bucket with >= 365 days retention in a
       region allowed by D5
  AU05 identities named in filters exist (access matrix pipeline SAs, groups, break-glass accounts)
  AU06 only the security group reads the audit bucket (access matrix), and no human has logging config rights there
  AU07 every Stage 3 risk whose treatment relies on alerting is covered by an alert
Status: implemented + locally tested; filters not executed against real logs (T-A1..T-A5).
"""
import argparse
import json
import pathlib
import re
import sys

from tools.access.matrix import Matrix
from tools.policy.orgpolicy import OrgPolicies
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

SEVERITIES = {"page", "ticket", "info"}
REQUIRED_DATA_ACCESS = {("org", "iamcredentials.googleapis.com"), ("org", "sts.googleapis.com"),
                        ("org", "cloudkms.googleapis.com"), ("org", "secretmanager.googleapis.com"),
                        ("org", "cloudsql.googleapis.com"), ("fldr-tenants/prd", "storage.googleapis.com"),
                        ("fldr-platform/prd", "storage.googleapis.com")}
DETECTION_RISKS = {"R-D4-1", "R-D6-2", "R-D7-1", "R-D7-2"}
PAGE_REQUIRED = {"AL-BG-LOGIN", "AL-BG-MEMBERSHIP", "AL-BG-USE", "AL-BINAUTHZ-BREAKGLASS"}
LOG_ADMIN_ROLES = {"roles/logging.admin", "roles/logging.configWriter", "roles/logging.bucketWriter"}


def mixed_top_level(flt):
    """True if AND and OR are mixed outside parentheses (Logging evaluates OR before AND – easy to misread)."""
    depth, ops, i, inq = 0, set(), 0, False
    while i < len(flt):
        ch = flt[i]
        if ch == '"' and (i == 0 or flt[i - 1] != "\\"):
            inq = not inq
        elif not inq and ch == "(":
            depth += 1
        elif not inq and ch == ")":
            depth -= 1
        elif not inq and depth == 0:
            for op in (" AND ", " OR "):
                if flt.startswith(op, i):
                    ops.add(op)
        i += 1
    return len(ops) == 2


class Audit:
    def __init__(self, registry_root="registry", security_root="security"):
        sec = pathlib.Path(security_root)
        self.path = str(sec / "audit-monitoring.yaml")
        self.doc = load_yaml(self.path)
        self.priv = load_yaml(sec / "privileged-access.yaml")
        self.org = OrgPolicies(sec / "org-policies.yaml")
        self.matrix = Matrix(registry_root, security_root)

    def check(self):
        f, P, d = [], self.path, self.doc
        alerts = d["alerts"]
        for a in sorted(set(self.priv["required_alerts"]) - set(alerts)):
            f.append(Finding("AU01", P, f"required alert {a} (D7) is not implemented"))
        for name, a in alerts.items():
            if a.get("severity") not in SEVERITIES or not a.get("filter") or not a.get("runbook") or not a.get("covers"):
                f.append(Finding("AU02", P, f"{name}: severity, filter, runbook and covers are required"))
            if name in PAGE_REQUIRED and a.get("severity") != "page":
                f.append(Finding("AU02", P, f"{name}: break-glass alerts must page"))
            if a.get("filter", "").count("(") != a.get("filter", "").count(")") or a.get("filter", "").count('"') % 2:
                f.append(Finding("AU02", P, f"{name}: unbalanced parentheses or quotes in filter"))
            if mixed_top_level(a.get("filter", "")):
                f.append(Finding("AU02", P, f"{name}: AND and OR mixed without parentheses (Logging gives OR precedence)"))
        for sev, chans in d["severity_channels"].items():
            for c in chans:
                if c not in d["channels"]:
                    f.append(Finding("AU02", P, f"severity {sev}: unknown channel {c}"))

        have = set()
        for e in d["data_access_logs"]:
            if e["node"] not in self.org.nodes:
                f.append(Finding("AU03", P, f"unknown node {e['node']}"))
            if e.get("exempted_members"):
                f.append(Finding("AU03", P, f"{e['service']} on {e['node']}: exempted principals are not allowed"))
            if "DATA_READ" in e["log_types"]:
                have.add((e["node"], e["service"]))
        for node, svc in sorted(REQUIRED_DATA_ACCESS - have):
            f.append(Finding("AU03", P, f"Data Access (DATA_READ) logs missing for {svc} on {node}"))

        s, b = d["sink"], d["log_bucket"]
        if s["parent"] != "org" or not s.get("include_children") or "cloudaudit.googleapis.com" not in s["filter"]:
            f.append(Finding("AU04", P, "org sink must include children and capture cloudaudit logs"))
        if s["destination_bucket"] != b["name"] or not b.get("locked") or b.get("retention_days", 0) < 365:
            f.append(Finding("AU04", P, "audit bucket must be the sink destination, locked, retention >= 365 days"))
        locs = self.org.effective("org", "gcp.resourceLocations").get("values", [])
        if f"in:{b['location']}-locations" not in locs:
            f.append(Finding("AU04", P, f"audit bucket location {b['location']} not allowed by D5"))

        binds = self.matrix.bindings()
        sas = {b_["principal"][3:].split("@")[0] for b_ in binds if b_["principal"].startswith("sa:")}
        groups = set(self.matrix.groups())
        bg_accounts = {a["id"] for a in self.priv["breakglass"]["accounts"]}
        for name, a in alerts.items():
            flt = a.get("filter", "")
            for sa in re.findall(r"([a-z][a-z0-9-]+)@(?:bootstrap-seed|shr-cicd-|shr-build)", flt):
                if sa not in sas:
                    f.append(Finding("AU05", P, f"{name}: unknown pipeline identity {sa}"))
            for g in re.findall(r"(grp-[a-z0-9-]+)@", flt):
                if g not in groups:
                    f.append(Finding("AU05", P, f"{name}: unknown group {g}"))
            for acct in re.findall(r"\b(bg-\d\d)\b", flt):
                if acct not in bg_accounts:
                    f.append(Finding("AU05", P, f"{name}: unknown break-glass account {acct}"))
            if name == "AL-BG-LOGIN" and set(re.findall(r"\b(bg-\d\d)\b", flt)) != bg_accounts:
                f.append(Finding("AU05", P, "AL-BG-LOGIN must cover every break-glass account"))

        readers = {b_["principal"] for b_ in binds if b_["scope"] == f"project:{b['project']}"
                   and b_["role"] == "roles/logging.privateLogViewer"}
        if readers != set(b["readers"]):
            f.append(Finding("AU06", P, f"audit bucket readers in the access matrix {sorted(readers)} != {b['readers']}"))
        for b_ in binds:
            if b_["scope"] in (f"project:{b['project']}", "org") and b_["role"] in LOG_ADMIN_ROLES \
                    and not b_["principal"].startswith("sa:tf-org"):
                f.append(Finding("AU06", P, f"{b_['principal']} can change logging configuration on {b_['scope']}"))

        covered = {c for a in alerts.values() for c in a.get("covers", [])}
        for r in sorted(DETECTION_RISKS - covered):
            f.append(Finding("AU07", P, f"risk {r} relies on detection but no alert covers it"))
        return f

    def render(self):
        """Terraform input (Stage 5): audit configs, bucket, sink, channels, log-based alert policies."""
        d = self.doc
        sev = d["severity_channels"]
        return {
            "audit_configs": [{"node": e["node"], "service": e["service"], "log_types": e["log_types"]}
                              for e in d["data_access_logs"]],
            "log_bucket": d["log_bucket"], "sink": d["sink"], "channels": d["channels"],
            "alert_policies": [{
                "display_name": name, "project": d["log_bucket"]["project"], "severity": a["severity"],
                "condition_matched_log": {"filter": a["filter"]},
                "notification_rate_limit": "300s", "auto_close": "1800s",
                "notification_channels": sev[a["severity"]],
                "documentation": a["runbook"], "covers": a["covers"]} for name, a in d["alerts"].items()],
            "drift_checks": d["drift_checks"],
        }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/monitoring.json")
    a = ap.parse_args(argv)
    au = Audit(a.registry, a.security)
    findings = au.check()
    out = au.render()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(out['audit_configs'])} Data Access configs, {len(out['alert_policies'])} alert policies, "
          f"{len(out['drift_checks'])} drift checks, {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
