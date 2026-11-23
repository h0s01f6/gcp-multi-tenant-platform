"""Stage 5 – Terraform: static checks, stack catalogue, generated tfvars (terraform itself is not available here)."""
import json
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.iac import hclcheck, stacks
from tools.iac.tfvars import Bridge, scope_parts


@pytest.fixture(scope="module")
def bridge():
    return Bridge(ROOT / "registry", ROOT / "security", ROOT / "network")


@pytest.fixture(scope="module")
def tfvars(bridge, tmp_path_factory):
    out = tmp_path_factory.mktemp("tfvars")
    for (stack, inst), data in bridge.all().items():
        (out / stack).mkdir(exist_ok=True)
        (out / stack / f"{inst}.auto.tfvars.json").write_text(json.dumps(data, default=list))
    return out


def test_hcl_static_checks_clean(tfvars):
    findings, dirs = hclcheck.check(ROOT / "terraform", tfvars)
    assert findings == []
    assert len(dirs) == 28                     # 18 modules + 10 stacks (Stage 8: observability)


def test_stack_catalogue_clean():
    assert stacks.check() == []
    order = stacks.order()
    assert order.index("org") < order.index("network") < order.index("platform") < order.index("tenant")
    assert order.index("tenant") < order.index("cluster-config")


@pytest.fixture
def tf(tmp_path):
    dst = tmp_path / "terraform"
    shutil.copytree(ROOT / "terraform", dst)
    return dst


def rules(tf, tfvars=None):
    return {f.rule for f in hclcheck.check(tf, tfvars)[0]}


@pytest.mark.parametrize("path,old,new,rule", [
    ("modules/network/main.tf", "var.host_project", "var.host_projekt", "HC02"),
    ("modules/edge/main.tf", 'resource "google_compute_ssl_policy" "this" {', 'resource "google_compute_ssl_policy" "this" {{', "HC01"),
    ("stacks/network/main.tf", "  psa             = var.psa\n", "", "HC03"),
    ("stacks/platform/outputs.tf", "module.sql_pools", "module.sql_poolz", "HC04"),
    ("modules/sql-pool/versions.tf", 'version = ">= 6.0, < 8.0"', "", "HC05"),
    ("modules/workloads/main.tf", "# No google_secret_manager_secret_version", 'resource "google_secret_manager_secret_version" "x" {}\n#', "HC07"),
])
def test_static_check_detects(tf, path, old, new, rule):
    p = tf / path
    s = p.read_text()
    assert old in s
    p.write_text(s.replace(old, new, 1))
    assert rule in rules(tf)


def test_tfvars_mismatch_detected(tf, tfvars, tmp_path):
    bad = tmp_path / "tv"
    shutil.copytree(tfvars, bad)
    f = bad / "network" / "prd.auto.tfvars.json"
    d = json.loads(f.read_text())
    d.pop("psa")
    d["unexpected"] = 1
    f.write_text(json.dumps(d))
    found = [x.message for x in hclcheck.check(tf, bad)[0] if x.rule == "HC06"]
    assert any("psa" in m for m in found) and any("unexpected" in m for m in found)


def test_missing_stack_permission_detected(sec):
    sec.edit("access-matrix.yaml", lambda d: d.update(grants=[
        g for g in d["grants"] if not (g["principal"] == "sa:tf-prd@shr-cicd-prd" and g["scope"] == "project:plt-ingress-prd")]))
    assert any(f.rule == "SK02" for f in stacks.check(security=sec.root))


def test_every_matrix_binding_has_one_owner(bridge):
    org = {(b["role"], b["member"]) for b in bridge.iam_bindings("org")}
    assert ("roles/compute.networkUser", "group:grp-wl-netusers-prd@example.com") not in org     # subnet scope: network stack
    assert ("roles/resourcemanager.folderAdmin", "serviceAccount:tf-org@bootstrap-seed.iam.gserviceaccount.com") in org
    assert all(b["role"] not in ("k8s/view", "k8s/edit") for b in bridge.iam_bindings("org"))


def test_jit_and_breakglass_roles_are_not_standing_bindings(bridge):
    org = bridge.iam_bindings("org")
    assert not any(b["role"] == "roles/resourcemanager.organizationAdmin" for b in org)


@pytest.mark.parametrize("scope,expected", [
    ("folder:tenants-prd", ("folder", "fldr-tenants/prd")),
    ("folder:shared", ("folder", "fldr-shared")),
    ("kms:shr-build/attestor-signing", ("kms_key", "projects/shr-build/locations/asia-south1/keyRings/kr-build-as1/cryptoKeys/attestor-signing")),
    ("kms:shr-security/kr-plt-prd-as1", ("kms_keyring", "projects/shr-security/locations/asia-south1/keyRings/kr-plt-prd-as1")),
    ("repo:release", ("artifact_repository", "projects/shr-artifacts/locations/asia-south1/repositories/release")),
])
def test_scope_mapping(scope, expected):
    assert scope_parts(scope) == expected


def test_tenant_tfvars_hold_only_their_own_resources(bridge):
    res = bridge.all()
    for (stack, inst), d in res.items():
        if stack != "tenant":
            continue
        w = d["workloads"]
        tenant = inst.rsplit("-", 1)[0]
        assert w["project"] == f"t-{inst}"
        assert all(s["tenant"] == tenant for s in w["service_accounts"])
        assert all(b["name"].startswith(f"bs-{tenant}-") for b in w["backend_services"])
        assert all(k["project"] == w["project"] for k in w["kms_keys"])
        assert all(s["project"] == w["project"] for s in w["secrets"])
        assert all(u["sa_email"].startswith(f"{tenant}-") for u in w["sql_users"])
        assert all(b["resource"].endswith(f"@{w['project']}.iam.gserviceaccount.com") for b in w["isotest_bindings"])


def test_memberships_stay_in_tier(bridge):
    for tier in ("prd", "nonprd"):
        for m in bridge.memberships(tier)["memberships"]:
            assert m["group"].endswith(tier) or f"-{tier}-" in m["group"], m


def test_cluster_config_points_at_rendered_baseline(bridge):
    cc = bridge.cluster_config("gke-prd-as1-01")
    assert cc["manifests_dir"] == "build/k8s/gke-prd-as1-01" and "gw-payroll-prd-01" in cc["gateways"]


def test_stack_catalogue_documents_every_stack_directory():
    cat = yaml.safe_load((ROOT / "terraform" / "stacks.yaml").read_text())
    assert {p.name for p in (ROOT / "terraform" / "stacks").iterdir()} == set(cat["stacks"])
