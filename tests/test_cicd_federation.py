"""D6 – CI/CD identities and Workload Identity Federation."""
import pytest

from tests.conftest import ROOT
from tools.cicd.federation import Federation


def rules(sec, reg_root=ROOT / "registry"):
    return sorted({f.rule for f in Federation(reg_root, sec.root).check()})


def ident(d, sa):
    return d["pipeline_identities"][sa]


def test_proposed_configuration_is_clean():
    assert Federation(ROOT / "registry", ROOT / "security").check() == []


def test_every_pipeline_identity_bound_and_prd_gates_are_exact():
    fed = Federation(ROOT / "registry", ROOT / "security")
    binds = {b["service_account"]: b for b in fed.wif_bindings()}
    assert binds["deploy-prd@shr-cicd-prd.iam.gserviceaccount.com"]["members"] == [
        "principalSet://iam.googleapis.com/projects/${BOOTSTRAP_PROJECT_NUMBER}/locations/global/"
        "workloadIdentityPools/ci-pool/attribute.gate/${REPO_ID_PLATFORM_TENANTS}:prd:main"]
    for sa, b in binds.items():
        assert b["role"] == "roles/iam.workloadIdentityUser"
        assert not any(m.endswith("/*") for m in b["members"])      # never the whole pool
    # attached identities get no WIF binding
    assert not any(s.startswith(("sqlboot-", "isotest-")) for s in binds)


def test_no_gate_reaches_two_tiers():
    fed = Federation(ROOT / "registry", ROOT / "security")
    seen = {}
    for b in fed.wif_bindings():
        for m in b["members"]:
            seen.setdefault(m, set()).add(b["tier"])
    assert all(len(t) == 1 for t in seen.values())


def test_missing_entry_for_pipeline_identity(sec):
    sec.edit("cicd-identities.yaml", lambda d: d["pipeline_identities"].pop("sa:ansible-prd@shr-cicd-prd"))
    assert "CI01" in rules(sec)


def test_provider_must_pin_organisation(sec):
    def f(d):
        d["federation"]["providers"]["github"]["attribute_condition"] = "assertion.repository_owner == 'acme'"
    sec.edit("cicd-identities.yaml", f)
    assert "CI02" in rules(sec)


@pytest.mark.parametrize("sa,allow", [
    ("sa:deploy-prd@shr-cicd-prd", {"repos": ["platform-tenants"], "environment": "prd", "ref": "other"}),   # PR branch -> prod deployer
    ("sa:tf-prd@shr-cicd-prd", {"repos": ["platform-infra"], "environment": "none", "ref": "main"}),         # no reviewed environment
    ("sa:deploy-nonprd@shr-cicd-nonprd", {"repos": ["platform-tenants"], "environment": "prd", "ref": "main"}),  # cross tier
    ("sa:builder@shr-build", {"repos": ["app-payroll"], "environment": "none", "ref": "other"}),             # feature branch -> release writer
])
def test_tier_discipline(sec, sa, allow):
    sec.edit("cicd-identities.yaml", lambda d: ident(d, sa)["allow"].append(allow))
    assert "CI04" in rules(sec)


def test_unknown_or_non_federating_repository(sec):
    sec.edit("cicd-identities.yaml", lambda d: ident(d, "sa:deploy-nonprd@shr-cicd-nonprd")["allow"].append(
        {"repos": ["platform-workflows"], "environment": "nonprd", "ref": "main"}))
    assert "CI03" in rules(sec)


def test_same_gate_for_two_tiers(sec):
    sec.edit("cicd-identities.yaml", lambda d: ident(d, "sa:tf-plan-prd@shr-cicd-prd")["allow"].append(
        {"repos": ["platform-infra"], "environment": "plan-nonprd", "ref": "main"}))
    assert {"CI04", "CI05"} <= set(rules(sec))


def test_runner_identity_must_not_hold_grants(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "sa:runner-prd@shr-cicd-prd", "scope": "folder:tenants-prd", "roles": ["roles/run.developer"],
         "access": "standing"}))
    assert "CI06" in rules(sec)


def test_prd_environment_needs_two_reviewers(sec):
    sec.edit("cicd-identities.yaml", lambda d: d["github"]["environments"]["prd"].update(required_reviewers=1))
    assert "CI07" in rules(sec)


def test_new_product_needs_repository(sec, reg):
    import yaml
    d = yaml.safe_load((reg.root / "products" / "crm.yaml").read_text())
    d["product"] = "billing"
    (reg.root / "products" / "billing.yaml").write_text(yaml.safe_dump(d))
    reg.edit("platform/inventory.yaml", lambda inv: inv["product_groups"]["g2"].append("billing"))
    assert "CI08" in rules(sec, reg.root)


def test_attached_job_needs_invoker(sec):
    def f(d):
        d["grants"] = [g for g in d["grants"] if not (g["principal"] == "sa:tf-prd@shr-cicd-prd"
                                                       and g["roles"] == ["roles/run.invoker"]
                                                       and g["scope"] == "project:shr-cicd-prd")]
    sec.edit("access-matrix.yaml", f)
    assert "CI09" in rules(sec)
