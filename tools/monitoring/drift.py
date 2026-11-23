"""D10 – nightly drift checks against the registry-derived identity plan (D2).

DR01 cross-tenant IAM: an IAM member on a customer project/resource that belongs to ANOTHER customer's project.
DR02 workload-group drift: grp-wl-* members that the plan does not expect; humans in wl groups; SAs in hum groups.

Inputs are exports (Cloud Asset Inventory IAM policies, Cloud Identity memberships), normalised to:
  iam_records:  [{"project": "t-abc-prd", "resource": "...", "role": "...", "member": "serviceAccount:x@t-xyz-prd..."}]
  memberships:  {"grp-wl-sqlconn-prd-01": ["serviceAccount:...", ...], ...}
CLI (Stage 7 drift workflow, nightly):
  python3 -m tools.monitoring.drift --plan build/identity-plan.json --iam <gcloud asset search-all-iam-policies JSON>
                                    --memberships <{"group": ["email", ...]}>
Status: implemented + locally tested with fixtures; export + schedule written in Stage 7 (cicd/…/drift.yml), not run
against an organisation (T-A4).
"""
import argparse
import json
import re
import sys

TENANT_PROJECT = re.compile(r"^t-([a-z][a-z0-9]{2,9})-(prd|nonprd)$")
SA_PROJECT = re.compile(r"serviceAccount:[^@]+@([a-z0-9-]+)\.iam\.gserviceaccount\.com$")


def cross_tenant_iam(iam_records):
    """DR01 – findings for members whose SA lives in a different customer's project."""
    out = []
    for r in iam_records:
        m = TENANT_PROJECT.match(r["project"])
        sm = SA_PROJECT.match(r["member"])
        if not m or not sm:
            continue
        other = TENANT_PROJECT.match(sm.group(1))
        if other and other.group(1) != m.group(1):
            out.append(f"DR01 {r['project']} {r.get('resource', '')} {r['role']}: member {r['member']} "
                       f"belongs to customer '{other.group(1)}'")
        if other and other.group(2) != m.group(2):
            out.append(f"DR01 {r['project']}: member {r['member']} is from tier {other.group(2)}")
    return out


def group_drift(plan, memberships):
    """DR02 – compare actual workload-group memberships with the identity plan."""
    expected = {}
    for gm in plan["group_memberships"].values():
        expected.setdefault(gm["group"], set()).add(f"serviceAccount:{gm['member']}"
                                                    if not gm["member"].startswith("serviceAccount:") else gm["member"])
    out = []
    for group, members in sorted(memberships.items()):
        for m in sorted(members):
            if group.startswith("grp-wl-"):
                if not m.startswith("serviceAccount:"):
                    out.append(f"DR02 {group}: human member {m} in a workload group")
                elif group in expected and m not in expected[group]:
                    out.append(f"DR02 {group}: unexpected member {m}")
            if group.startswith("grp-hum-") and m.startswith("serviceAccount:"):
                out.append(f"DR02 {group}: service account {m} in a human group")
    for group, members in sorted(expected.items()):
        for m in sorted(members - set(memberships.get(group, []))):
            out.append(f"DR02 {group}: expected member {m} missing")
    return out


def from_asset_export(results):
    """Normalise `gcloud asset search-all-iam-policies --format=json` into iam_records."""
    out = []
    for r in results:
        project = (r.get("project") or "").split("/")[-1]
        name = r.get("resource", "")
        m = re.search(r"/projects/([a-z][a-z0-9-]+)", name)
        if m:
            project = m.group(1)
        for b in (r.get("policy") or {}).get("bindings", []):
            for member in b.get("members", []):
                out.append({"project": project, "resource": name, "role": b["role"], "member": member})
    return out


def normalise_memberships(raw):
    return {g: [m if ":" in m else (f"serviceAccount:{m}" if m.endswith(".gserviceaccount.com") else f"user:{m}")
                for m in ms] for g, ms in raw.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="D10 drift checks DR01/DR02 on exports")
    ap.add_argument("--plan", default="build/identity-plan.json")
    ap.add_argument("--iam", required=True)
    ap.add_argument("--memberships", required=True)
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan))
    out = cross_tenant_iam(from_asset_export(json.load(open(a.iam))))
    out += group_drift(plan, normalise_memberships(json.load(open(a.memberships))))
    for line in out:
        print(line)
    print(f"drift: {len(out)} finding(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
