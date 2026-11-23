"""D3 – access-control matrix rules. The real matrix must pass; each mutation must trip exactly its rule."""
import copy
import pathlib
import shutil

import pytest
import yaml

from tools.access.matrix import Matrix

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def sec(tmp_path):
    dst = tmp_path / "security"
    shutil.copytree(ROOT / "security", dst)

    class S:
        root = dst

        def load(self, name):
            return yaml.safe_load((dst / name).read_text())

        def save(self, name, data):
            (dst / name).write_text(yaml.safe_dump(data, sort_keys=False))

        def add_grant(self, **g):
            m = self.load("access-matrix.yaml")
            m["grants"].append(g)
            self.save("access-matrix.yaml", m)

        def rules(self):
            return {f.rule for f in Matrix(ROOT / "registry", dst).check()}

    return S()


def test_real_matrix_passes():
    assert Matrix(ROOT / "registry", ROOT / "security").check() == []


def test_expansion_covers_every_customer_and_pool_project():
    mx = Matrix(ROOT / "registry", ROOT / "security")
    groups = mx.groups()
    for t in ("abc", "xyz"):
        assert f"grp-hum-cust-{t}-support-prd" in groups and f"grp-hum-cust-{t}-support-nonprd" in groups
    assert "grp-wl-sqlconn-prd-01" in groups and "grp-wl-sqlconn-nonprd-01" in groups
    scopes = {b["scope"] for b in mx.bindings() if b["principal"] == "grp-hum-cust-abc-support-prd"}
    assert "project:t-abc-prd" in scopes and not any("xyz" in s for s in scopes)


def test_unknown_role(sec):
    sec.add_grant(principal="grp-hum-platform-nonprd-operators", scope="folder:tenants-nonprd", roles=["roles/made.up"], access="standing")
    assert sec.rules() == {"AC01"}


def test_basic_role_forbidden(sec):
    sec.add_grant(principal="grp-hum-platform-nonprd-operators", scope="folder:tenants-nonprd", roles=["roles/editor"], access="standing")
    assert "AC02" in sec.rules()


def test_standing_human_write_in_prod(sec):
    sec.add_grant(principal="grp-hum-platform-prd-operators", scope="folder:tenants-prd", roles=["roles/run.developer"], access="standing")
    assert sec.rules() == {"AC03"}


def test_standing_human_data_in_prod(sec):
    sec.add_grant(principal="grp-hum-cust-{tenant}-support-prd", scope="project:t-{tenant}-prd", roles=["roles/storage.objectViewer"], access="standing")
    assert sec.rules() == {"AC03"}


def test_group_crossing_tiers(sec):
    sec.add_grant(principal="grp-hum-platform-nonprd-operators", scope="folder:tenants-prd", roles=["roles/browser"], access="standing")
    assert sec.rules() == {"AC04"}


def test_nonprod_pipeline_on_prod_scope(sec):
    sec.add_grant(principal="sa:deploy-nonprd@shr-cicd-nonprd", scope="k8s:gke-prd-*/*", roles=["k8s/edit"], access="standing")
    assert sec.rules() == {"AC04"}


def test_workload_group_with_data_role(sec):
    sec.add_grant(principal="grp-wl-sqlconn-prd-{nn}", scope="project:plt-sql-prd-{nn}", roles=["roles/storage.objectViewer"], access="standing")
    assert sec.rules() == {"AC05"}


def test_workload_group_with_mysql_grant(sec):
    sec.add_grant(principal="grp-wl-sqlconn-prd-{nn}", scope="mysql:sql-prd-*", roles=["mysql/r_platform_dba_ro"], access="standing")
    assert "AC05" in sec.rules() and "AC06" in sec.rules()


def test_too_many_dba_groups_on_an_instance(sec):
    g = sec.load("groups.yaml")
    for i in range(3):
        g["groups"][f"grp-hum-dba-prd-x{i}"] = {"category": "hum", "tier": "prd", "owner": "dba-lead", "membership": "idp",
                                                "cloudsql_mechanism": "sql-group-auth"}
    sec.save("groups.yaml", g)
    for i in range(3):
        sec.add_grant(principal=f"grp-hum-dba-prd-x{i}", scope="mysql:sql-prd-*", roles=["mysql/r_platform_dba_ro"], access="standing")
    assert sec.rules() == {"AC06"}


def test_registry_managed_group_cannot_use_sql_group_auth(sec):
    g = sec.load("groups.yaml")
    g["groups"]["grp-wl-ar-readers-prd"]["cloudsql_mechanism"] = "sql-group-auth"
    sec.save("groups.yaml", g)
    assert "AC06" in sec.rules()


def test_builder_on_runtime_scope(sec):
    sec.add_grant(principal="sa:builder@shr-build", scope="project:plt-gke-prd", roles=["roles/container.developer"], access="standing")
    assert "AC07" in sec.rules()


def test_only_builder_writes_release(sec):
    sec.add_grant(principal="sa:deploy-prd@shr-cicd-prd", scope="repo:release", roles=["roles/artifactregistry.writer"], access="standing")
    assert sec.rules() == {"AC07"}


def test_customer_group_on_other_customer(sec):
    sec.add_grant(principal="grp-hum-cust-{tenant}-support-prd", scope="project:t-xyz-prd", roles=["roles/browser"], access="standing")
    assert sec.rules() == {"AC08"}            # abc's group on xyz's project


def test_missing_assignment_persona(sec):
    m = sec.load("access-matrix.yaml")
    del m["personas"]["customer-specific-users"]
    sec.save("access-matrix.yaml", m)
    assert sec.rules() == {"AC09"}


def test_orphan_group(sec):
    g = sec.load("groups.yaml")
    g["groups"]["grp-hum-unused"] = {"category": "hum", "tier": "prd", "owner": "x", "membership": "idp"}
    sec.save("groups.yaml", g)
    assert sec.rules() == {"AC10"}


def test_unknown_group_in_grant(sec):
    sec.add_grant(principal="grp-hum-nobody", scope="folder:tenants-prd", roles=["roles/browser"], access="standing")
    assert "AC10" in sec.rules()


def test_breakglass_access_only_for_breakglass_group(sec):
    sec.add_grant(principal="grp-hum-platform-prd-operators", scope="org", roles=["roles/resourcemanager.organizationAdmin"], access="breakglass")
    assert "AC11" in sec.rules()


def test_breakglass_group_must_start_empty(sec):
    g = sec.load("groups.yaml")
    g["groups"]["grp-hum-prd-breakglass"]["default_members"] = 2
    sec.save("groups.yaml", g)
    assert sec.rules() == {"AC11"}


def test_jit_without_entitlement(sec):
    sec.add_grant(principal="grp-hum-platform-prd-operators", scope="folder:tenants-prd", roles=["roles/run.developer"], access="jit", max_hours=2)
    assert sec.rules() == {"AC12"}


def test_jit_too_long(sec):
    sec.add_grant(principal="grp-hum-platform-prd-operators", scope="folder:tenants-prd", roles=["roles/run.developer"], access="jit", entitlement="pam-x", max_hours=24)
    assert sec.rules() == {"AC12"}


def test_expiring_grant_needs_expiring_group(sec):
    sec.add_grant(principal="grp-hum-dba-prd-ro", scope="project:plt-sql-prd-{nn}", roles=["roles/cloudsql.admin"], access="expiring", max_hours=2)
    assert sec.rules() == {"AC12"}


def test_exception_must_be_explicit(sec):
    m = sec.load("access-matrix.yaml")
    for g in m["grants"]:
        g.pop("exception", None)
    sec.save("access-matrix.yaml", m)
    assert sec.rules() == {"AC03"}            # security-audit data access is flagged without its documented exception
