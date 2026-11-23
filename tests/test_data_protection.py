"""D9 – secrets, KMS and supply chain."""
from tests.conftest import ROOT
from tools.security.dataprotection import DataProtection


def dp(sec=None, reg_root=ROOT / "registry"):
    return DataProtection(reg_root, sec.root if sec else ROOT / "security")


def rules(sec, reg_root=ROOT / "registry"):
    return sorted({f.rule for f in dp(sec, reg_root).check()})


def test_proposed_configuration_is_clean():
    assert dp().check() == []


def test_prd_secrets_and_buckets_use_customer_key_in_customer_project():
    out = dp().generate()
    for s in out["secrets"]:
        if s["env"] == "prd":
            assert s["kms_key"].startswith(f"projects/{s['project']}/locations/asia-south1/keyRings/kr-{s['tenant']}-prd-as1/")
        else:
            assert s["kms_key"] is None
    keys = {k["id"]: k for k in out["keys"]}
    k = keys["t-abc-prd/kr-abc-prd-as1/payroll-prd"]
    assert all("t-abc-prd" in m for m in k["encrypter_decrypter"])          # only ABC's own service agents
    assert k["rotation_period"] == "7776000s"


def test_each_prd_pool_has_instance_key_in_security_project():
    out = dp().generate()
    pools = {k["sql_instance"]["pool"]: k for k in out["keys"] if k.get("sql_instance")}
    assert set(pools) == {"sql-prd-payroll-01", "sql-prd-crm-01", "sql-prd-g3-01", "psql-notify-prd-01", "psql-ledger-prd-01"}
    assert all(k["project"] == "shr-security" for k in pools.values())


def test_secret_readers_are_the_tenant_workload_only():
    for s in dp().generate()["secrets"]:
        assert s["accessor"].startswith(f"serviceAccount:{s['tenant']}-{s['product']}-{s['env']}@{s['project']}.")


def test_binauthz_enforced_on_every_prd_runtime_project():
    pol = {p["project"]: p for p in dp().generate()["binauthz_policies"]}
    for proj in ("plt-gke-prd", "t-abc-prd", "t-xyz-prd", "p-notify-prd"):
        assert pol[proj]["default_admission_rule"]["enforcement_mode"] == "ENFORCED_BLOCK_AND_AUDIT_LOG"
        assert pol[proj]["default_admission_rule"]["require_attestations_by"] == ["projects/shr-build/attestors/built-by-shr-build"]
    assert pol["plt-gke-nonprd"]["default_admission_rule"]["enforcement_mode"] == "DRYRUN_AUDIT_LOG_ONLY"


def test_terraform_must_not_manage_secret_values(sec):
    sec.edit("data-protection.yaml", lambda d: d["secrets"].update(terraform_manages_values=True))
    assert "DP05" in rules(sec)


def test_key_in_disallowed_project(sec):
    sec.edit("data-protection.yaml", lambda d: d["kms"]["platform"].update(project="plt-sql-prd-01"))
    assert "DP02" in rules(sec)


def test_region_outside_allowed_locations(sec):
    sec.edit("data-protection.yaml", lambda d: d["region"].update(name="us-central1", location_value="in:us-central1-locations"))
    assert "DP03" in rules(sec)


def test_long_rotation_and_short_destroy(sec):
    sec.edit("data-protection.yaml", lambda d: d["kms"].update(rotation_days=365, destroy_scheduled_days=1))
    assert "DP04" in rules(sec)


def test_human_key_user_rejected(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-hum-platform-prd-operators", "scope": "kms:t-abc-prd/payroll-prd",
         "roles": ["roles/cloudkms.cryptoKeyEncrypterDecrypter"], "access": "jit", "entitlement": "pam-prd-support-write", "max_hours": 4}))
    sec.edit("role-catalog.yaml", lambda d: d["roles"].update({"roles/cloudkms.cryptoKeyEncrypterDecrypter": {"class": "data"}}))
    assert "DP04" in rules(sec)


def test_unconditioned_version_adder_rejected(sec):
    def f(d):
        for g in d["grants"]:
            if g["roles"] == ["roles/secretmanager.secretVersionAdder"]:
                g.pop("condition")
    sec.edit("access-matrix.yaml", f)
    assert "DP05" in rules(sec)


def test_prd_not_enforced(sec):
    sec.edit("data-protection.yaml", lambda d: d["supply_chain"]["binary_authorization"]["prd"].update(
        enforcement_mode="DRYRUN_AUDIT_LOG_ONLY"))
    assert "DP06" in rules(sec)


def test_second_signer_rejected(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "sa:deploy-prd@shr-cicd-prd", "scope": "kms:shr-build/attestor-signing",
         "roles": ["roles/cloudkms.signerVerifier"], "access": "standing"}))
    assert "DP07" in rules(sec)


def test_org_policy_for_cloud_run_binauthz_required(sec):
    sec.edit("org-policies.yaml", lambda d: d.update(policies=[p for p in d["policies"]
                                                               if p["constraint"] != "run.allowedBinaryAuthorizationPolicies"]))
    assert "DP08" in rules(sec)
