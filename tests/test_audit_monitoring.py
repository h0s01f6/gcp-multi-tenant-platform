"""D10 – audit logging, central sink, alerts and drift checks."""
import json

import pytest

from tests.conftest import ROOT
from tools.monitoring import drift
from tools.monitoring.audit import Audit, mixed_top_level


def rules(sec):
    return sorted({f.rule for f in Audit(ROOT / "registry", sec.root).check()})


def test_proposed_configuration_is_clean():
    assert Audit(ROOT / "registry", ROOT / "security").check() == []


def test_every_d7_alert_rendered_with_channels():
    out = Audit(ROOT / "registry", ROOT / "security").render()
    names = {a["display_name"]: a for a in out["alert_policies"]}
    for req in ("AL-BG-LOGIN", "AL-BG-MEMBERSHIP", "AL-BG-USE", "AL-PAM-GRANT", "AL-DBA-MEMBERSHIP", "AL-BINAUTHZ-BREAKGLASS"):
        assert req in names
    assert names["AL-BG-LOGIN"]["notification_channels"] == ["security-page", "security-ticket"]
    assert all(a["project"] == "shr-security" for a in out["alert_policies"])


def test_missing_required_alert(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"].pop("AL-PAM-GRANT"))
    assert "AU01" in rules(sec)


def test_breakglass_alert_must_page(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"]["AL-BG-USE"].update(severity="ticket"))
    assert "AU02" in rules(sec)


def test_ambiguous_filter_rejected(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"]["AL-SA-KEY-CREATED"].update(
        filter='protoPayload.serviceName="iam.googleapis.com" AND protoPayload.methodName="a" OR protoPayload.methodName="b"'))
    assert "AU02" in rules(sec)


@pytest.mark.parametrize("flt,mixed", [("a AND b OR c", True), ("(a AND b) OR (c AND d)", False),
                                       ('x="a OR b" AND y', False), ("a AND NOT b", False)])
def test_precedence_heuristic(flt, mixed):
    assert mixed_top_level(flt) is mixed


def test_data_access_logs_for_secrets_required(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d.update(data_access_logs=[
        e for e in d["data_access_logs"] if e["service"] != "secretmanager.googleapis.com"]))
    assert "AU03" in rules(sec)


def test_no_exempted_principals(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["data_access_logs"][0].update(
        exempted_members=["serviceAccount:isotest-prd@shr-cicd-prd.iam.gserviceaccount.com"]))
    assert "AU03" in rules(sec)


def test_bucket_must_be_locked_with_retention(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["log_bucket"].update(locked=False, retention_days=30))
    assert "AU04" in rules(sec)


def test_unknown_identity_in_filter(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"]["AL-TF-ORG-USE"].update(
        filter='protoPayload.authenticationInfo.principalEmail="tf-global@bootstrap-seed.iam.gserviceaccount.com"'))
    assert "AU05" in rules(sec)


def test_bg_login_must_cover_both_accounts(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"]["AL-BG-LOGIN"].update(
        filter='protoPayload.serviceName="login.googleapis.com" AND protoPayload.authenticationInfo.principalEmail="bg-01@example.com"'))
    assert "AU05" in rules(sec)


def test_extra_audit_reader_rejected(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-hum-platform-admins", "scope": "project:shr-security", "roles": ["roles/logging.privateLogViewer"],
         "access": "standing", "exception": "test"}))
    assert "AU06" in rules(sec)


def test_detection_risk_must_be_covered(sec):
    sec.edit("audit-monitoring.yaml", lambda d: d["alerts"].pop("AL-ISOTEST-TOKEN"))
    assert "AU07" in rules(sec)


# ---------------- drift checks ----------------
def plan():
    return json.loads((ROOT / "tests" / "golden" / "identity-plan.json").read_text())


def test_dr01_cross_tenant_member_detected():
    recs = [
        {"project": "t-abc-prd", "resource": "abc-payroll-prd-data", "role": "roles/storage.objectAdmin",
         "member": "serviceAccount:abc-payroll-prd@t-abc-prd.iam.gserviceaccount.com"},
        {"project": "t-abc-prd", "resource": "abc-payroll-prd-data", "role": "roles/storage.objectViewer",
         "member": "serviceAccount:xyz-payroll-prd@t-xyz-prd.iam.gserviceaccount.com"},
        {"project": "t-abc-prd", "resource": "crm-prd-api-key", "role": "roles/secretmanager.secretAccessor",
         "member": "serviceAccount:abc-crm-dev@t-abc-nonprd.iam.gserviceaccount.com"},
    ]
    out = drift.cross_tenant_iam(recs)
    assert any("belongs to customer 'xyz'" in o for o in out)
    assert any("from tier nonprd" in o for o in out)
    assert len(out) == 2


def test_dr01_plan_itself_has_no_cross_tenant_member():
    recs = [{"project": r["project"], "resource": r["resource"], "role": r["role"], "member": r["member"]}
            for r in plan()["resource_iam"].values()]
    assert drift.cross_tenant_iam(recs) == []


def test_dr02_group_drift():
    p = plan()
    actual = {}
    for gm in p["group_memberships"].values():
        actual.setdefault(gm["group"], []).append(f"serviceAccount:{gm['member']}")
    assert drift.group_drift(p, actual) == []
    g = next(iter(actual))
    actual[g].append("user:alice@example.com")
    actual[g].append("serviceAccount:rogue@t-xyz-prd.iam.gserviceaccount.com")
    missing = actual[g].pop(0)
    actual["grp-hum-platform-prd-operators"] = ["serviceAccount:deploy-prd@shr-cicd-prd.iam.gserviceaccount.com"]
    out = "\n".join(drift.group_drift(p, actual))
    assert "human member user:alice" in out and "unexpected member serviceAccount:rogue" in out
    assert f"expected member {missing} missing" in out and "service account" in out
