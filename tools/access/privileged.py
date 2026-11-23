"""D7 – privileged access: PAM entitlements, time-bound groups, break-glass (security/privileged-access.yaml).

Usage:  python3 -m tools.access.privileged [--registry registry] [--security security] [-o build/pam-entitlements.json]

Rules
  PA01 every access-matrix jit grant is covered by an entitlement; every entitlement maps to matrix jit grants
  PA02 eligible principals equal the matrix grant principals; approvers are existing human groups, not the eligible group
  PA03 approval and justification required; entitlement duration = matrix max_hours
  PA04 notification to the security group
  PA05 expiring groups: every matrix `expiring` group is listed; expiry mandatory; max_hours <= group max duration;
       the adder holds group-manager on exactly that group; approver is the group owner
  PA06 break-glass: group empty by default and listed with access breakglass in the matrix; 2 non-federated accounts
       with hardware keys and no IAM bindings; membership expiry; required alerts cover every privileged path
  PA07 no other human group can change group membership of privileged groups
Status: implemented + locally tested; nothing applied (T-P1..T-P3).
"""
import argparse
import json
import pathlib
import sys

from tools.access.matrix import Matrix
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

PRIVILEGED_GROUPS = ("grp-hum-prd-breakglass", "grp-hum-dba-prd-admin", "grp-hum-platform-admins")
ALERT_PATHS = {"AL-BG-LOGIN", "AL-BG-MEMBERSHIP", "AL-BG-USE", "AL-PAM-GRANT", "AL-DBA-MEMBERSHIP"}


class Privileged:
    def __init__(self, registry_root="registry", security_root="security"):
        self.path = str(pathlib.Path(security_root) / "privileged-access.yaml")
        self.doc = load_yaml(self.path)
        self.matrix = Matrix(registry_root, security_root)
        self.binds = self.matrix.bindings()
        self.groups = self.matrix.groups()

    def entitlements(self):
        """Concrete PAM entitlements: one per (matrix entitlement, scope resource)."""
        out = {}
        for b in self.binds:
            if b["access"] != "jit":
                continue
            key = (b["entitlement"], b["scope"])
            e = out.setdefault(key, {"entitlement": b["entitlement"], "resource": b["scope"], "roles": [],
                                     "eligible": set(), "max_hours": b["max_hours"], "conditions": set(),
                                     "values": b["values"]})
            if b["role"] not in e["roles"]:
                e["roles"].append(b["role"])
            e["eligible"].add(b["principal"])
            if b.get("condition"):
                e["conditions"].add(b["condition"])
        return out

    def _spec(self, name, values):
        for tpl, spec in self.doc["entitlements"].items():
            if tpl == name or (values and tpl.format(**values) == name):
                return tpl, spec
        return None, None

    def check(self):
        f, P, d = [], self.path, self.doc
        ents = self.entitlements()
        used_tpls = set()
        for (name, res), e in sorted(ents.items()):
            tpl, spec = self._spec(name, e["values"])
            if spec is None:
                f.append(Finding("PA01", P, f"matrix jit grant {name} on {res} has no entitlement definition"))
                continue
            used_tpls.add(tpl)
            elig = {g.format(**e["values"]) if e["values"] else g for g in spec["eligible"]}
            if elig != e["eligible"]:
                f.append(Finding("PA02", P, f"{name}: eligible {sorted(elig)} != matrix principals {sorted(e['eligible'])}"))
            for a in spec.get("approvers", []):
                a = a.format(**e["values"]) if e["values"] else a
                g = self.groups.get(a)
                if not g or g["category"] != "hum":
                    f.append(Finding("PA02", P, f"{name}: approver {a} is not a human group"))
                if a in elig:
                    f.append(Finding("PA02", P, f"{name}: approver group {a} is also eligible (self-approval)"))
            if spec.get("approvals_required", 0) < 1 or spec.get("justification") != "required":
                f.append(Finding("PA03", P, f"{name}: approval and justification must be required"))
            if not e["max_hours"]:
                f.append(Finding("PA03", P, f"{name}: no maximum duration in the matrix"))
            if "grp-hum-security-audit" not in spec.get("notify", []):
                f.append(Finding("PA04", P, f"{name}: security group must be notified"))
        for tpl in d["entitlements"]:
            if tpl not in used_tpls:
                f.append(Finding("PA01", P, f"entitlement {tpl} grants nothing in the access matrix"))

        exp_groups = {b["principal"] for b in self.binds if b["access"] == "expiring"}
        for g in sorted(exp_groups - set(d["expiring_groups"])):
            f.append(Finding("PA05", P, f"{g}: matrix expiring grant without a membership process"))
        for g, spec in d["expiring_groups"].items():
            meta = self.groups.get(g, {})
            if spec.get("expiry") != "mandatory":
                f.append(Finding("PA05", P, f"{g}: expiry must be mandatory"))
            if spec.get("max_hours", 99) > meta.get("max_duration_hours", 0):
                f.append(Finding("PA05", P, f"{g}: max_hours exceeds the group's max_duration_hours"))
            if spec.get("approved_by") != meta.get("owner"):
                f.append(Finding("PA05", P, f"{g}: approval must come from the group owner {meta.get('owner')}"))
            if not any(b["principal"] == spec.get("added_by") and b["role"] == "cloudidentity/group-manager"
                       and b["scope"] == f"groups:{g}" for b in self.binds):
                f.append(Finding("PA05", P, f"{g}: {spec.get('added_by')} is not group manager of exactly this group"))
            if spec.get("added_by") == g:
                f.append(Finding("PA05", P, f"{g}: members cannot add themselves"))

        bg = d["breakglass"]
        gmeta = self.groups.get(bg["group"], {})
        if gmeta.get("membership") != "manual-breakglass" or gmeta.get("default_members", 1) != 0:
            f.append(Finding("PA06", P, f"{bg['group']} must be a manual-breakglass group, empty by default"))
        if not any(b["principal"] == bg["group"] and b["access"] == "breakglass" for b in self.binds):
            f.append(Finding("PA06", P, f"{bg['group']} has no breakglass grant in the access matrix"))
        if len(bg["accounts"]) != 2:
            f.append(Finding("PA06", P, "exactly two break-glass accounts are required"))
        for a in bg["accounts"]:
            if a.get("federated") or a.get("mfa") != "hardware-key" or a.get("iam_bindings"):
                f.append(Finding("PA06", P, f"break-glass account {a['id']}: non-federated, hardware key, no IAM bindings"))
            if any(a["id"] in b["principal"] for b in self.binds):
                f.append(Finding("PA06", P, f"break-glass account {a['id']} appears in the access matrix"))
        if not bg.get("membership_expiry_hours") or not bg.get("two_person_rule"):
            f.append(Finding("PA06", P, "break-glass membership needs an expiry and the two-person rule"))
        missing = ALERT_PATHS - set(d.get("required_alerts", {}))
        if missing:
            f.append(Finding("PA06", P, f"required alerts missing: {sorted(missing)}"))

        for b in self.binds:
            if b["role"] != "cloudidentity/group-manager":
                continue
            target = b["scope"][len("groups:"):]
            allowed = {spec.get("added_by") for g, spec in d["expiring_groups"].items() if g == target}
            if target in PRIVILEGED_GROUPS and b["principal"] not in allowed:
                f.append(Finding("PA07", P, f"{b['principal']} can change membership of privileged group {target}"))
            if target.startswith("grp-hum-") and b["principal"].startswith("sa:"):
                f.append(Finding("PA07", P, f"automation {b['principal']} must not manage human group {target}"))
        return f

    def render(self):
        """Terraform input (google_privileged_access_manager_entitlement), one per resource."""
        out = []
        for (name, res), e in sorted(self.entitlements().items()):
            tpl, spec = self._spec(name, e["values"])
            fmt = (lambda s: s.format(**e["values"])) if e["values"] else (lambda s: s)
            out.append({"entitlement_id": f"{name}-{res.replace(':', '-').replace('/', '-')}"[:63],
                        "parent": res, "roles": e["roles"],
                        "condition": sorted(e["conditions"])[0] if e["conditions"] else None,
                        "max_request_duration": f"{e['max_hours'] * 3600}s",
                        "eligible_principals": sorted(f"group:{g}@example.com" for g in e["eligible"]),
                        "approvers": sorted(f"group:{fmt(a)}@example.com" for a in spec["approvers"]),
                        "approvals_needed": spec["approvals_required"], "requester_justification": True,
                        "notification_recipients": sorted(f"{g}@example.com" for g in spec["notify"])})
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/pam-entitlements.json")
    a = ap.parse_args(argv)
    pv = Privileged(a.registry, a.security)
    findings = pv.check()
    ents = pv.render()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(ents, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(ents)} PAM entitlements, {len(pv.doc['expiring_groups'])} expiring group(s), "
          f"{len(pv.doc['breakglass']['accounts'])} break-glass accounts, {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
