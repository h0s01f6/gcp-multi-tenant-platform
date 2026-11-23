"""D7 – PAM entitlements, time-bound groups, break-glass."""
from tests.conftest import ROOT
from tools.access.privileged import Privileged


def rules(sec):
    return sorted({f.rule for f in Privileged(ROOT / "registry", sec.root).check()})


def test_proposed_configuration_is_clean():
    assert Privileged(ROOT / "registry", ROOT / "security").check() == []


def test_entitlements_match_matrix_per_resource():
    ents = {e["entitlement_id"]: e for e in Privileged(ROOT / "registry", ROOT / "security").render()}
    assert set(ents["pam-prd-support-write-folder-tenants-prd"]["roles"]) == {"roles/run.developer", "roles/compute.instanceAdmin.v1"}
    assert ents["pam-prd-support-write-folder-platform-prd"]["roles"] == ["roles/container.developer"]
    assert ents["pam-org-admin-org"]["max_request_duration"] == "7200s"
    s = ents["pam-prd-secret-write-payroll-folder-tenants-prd"]
    assert s["condition"].endswith("startsWith('payroll-')") and s["max_request_duration"] == "3600s"
    for e in ents.values():
        assert e["approvals_needed"] >= 1 and e["requester_justification"]
        assert not set(e["approvers"]) & set(e["eligible_principals"])


def test_jit_grant_without_entitlement(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-hum-platform-prd-operators", "scope": "project:plt-gke-prd", "roles": ["roles/container.admin"],
         "access": "jit", "entitlement": "pam-unknown", "max_hours": 2}))
    assert "PA01" in rules(sec)


def test_self_approval_rejected(sec):
    sec.edit("privileged-access.yaml", lambda d: d["entitlements"]["pam-prd-support-write"].update(
        approvers=["grp-hum-platform-prd-operators"]))
    assert "PA02" in rules(sec)


def test_approval_and_justification_required(sec):
    sec.edit("privileged-access.yaml", lambda d: d["entitlements"]["pam-org-admin"].update(approvals_required=0))
    assert "PA03" in rules(sec)


def test_security_must_be_notified(sec):
    sec.edit("privileged-access.yaml", lambda d: d["entitlements"]["pam-org-admin"].update(notify=[]))
    assert "PA04" in rules(sec)


def test_dba_membership_needs_mandatory_expiry_within_limit(sec):
    sec.edit("privileged-access.yaml", lambda d: d["expiring_groups"]["grp-hum-dba-prd-admin"].update(
        expiry="optional", max_hours=24))
    assert "PA05" in rules(sec)


def test_dba_adder_must_be_group_manager(sec):
    sec.edit("access-matrix.yaml", lambda d: d.update(grants=[g for g in d["grants"]
                                                             if g["roles"] != ["cloudidentity/group-manager"]
                                                             or "dba" not in g["scope"]]))
    assert "PA05" in rules(sec)


def test_breakglass_accounts(sec):
    sec.edit("privileged-access.yaml", lambda d: d["breakglass"]["accounts"][0].update(
        federated=True, iam_bindings=["roles/owner"]))
    assert "PA06" in rules(sec)


def test_breakglass_alerts_required(sec):
    sec.edit("privileged-access.yaml", lambda d: d["required_alerts"].pop("AL-BG-LOGIN"))
    assert "PA06" in rules(sec)


def test_no_extra_manager_of_privileged_group(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-hum-platform-prd-operators", "scope": "groups:grp-hum-prd-breakglass",
         "roles": ["cloudidentity/group-manager"], "access": "standing", "exception": "test"}))
    assert "PA07" in rules(sec)
