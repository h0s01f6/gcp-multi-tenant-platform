"""Stage 7 – pipeline planner: affected stack instances, onboarding order, promotion gate (PL01-PL05)."""
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.cicd import planner


def tree(tmp_path, name, edit=None):
    """A checkout root holding a (possibly edited) copy of the registry."""
    root = tmp_path / name
    shutil.copytree(ROOT / "registry", root / "registry")
    if edit:
        edit(root / "registry")
    return root


def edit_tenant(t, fn):
    def _e(reg):
        p = reg / "tenants" / f"{t}.yaml"
        d = yaml.safe_load(p.read_text())
        fn(d)
        p.write_text(yaml.safe_dump(d, sort_keys=False))
    return _e


def plan(base_root, head_root=ROOT, changed=()):
    return planner.build_plan(planner.load(base_root), planner.load(head_root), list(changed), ROOT)


def jobs(p):
    return [j for j in p["order"] if p["run"][j]]


def test_self_check_is_clean():
    assert planner.check(ROOT) == []


def test_no_change_no_jobs(tmp_path):
    p, f = plan(tree(tmp_path, "base"))
    assert jobs(p) == [] and f == []


def test_version_promotion_is_a_deploy_only(tmp_path):
    # before: abc payroll dev 2.0.3, stg 2.0.2 -> now stg 2.0.3 (soaked in dev) and dev 2.1.0
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["payroll"]["versions"].update(dev="2.0.3", stg="2.0.2")))
    p, f = plan(base)
    assert f == []
    assert jobs(p) == ["deploy-nonprd"]                     # versions are not Terraform inputs
    items = {(r["env"], r["from"], r["to"]) for r in p["matrix"]["deploy-nonprd"]["include"]}
    assert items == {("dev", "2.0.3", "2.1.0"), ("stg", "2.0.2", "2.0.3")}
    r = p["matrix"]["deploy-nonprd"]["include"][0]
    assert r["runtime"] == "gke" and r["namespace"] == "abc-payroll-dev" and r["cell"] == "gke-dev-as1-01"


def test_skipping_an_environment_fails_PL01(tmp_path):
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["payroll"]["versions"].update(dev="2.0.2", stg="2.0.2")))
    _, f = plan(base)
    assert [x.rule for x in f] == ["PL01"] and "payroll/stg" in f[0].message


def test_prd_release_needs_uat_and_takes_a_backup(tmp_path):
    # before: uat 3.1.0 / prd 3.0.5 -> now uat 3.1.1 (from stg) and prd 3.1.0 (from uat)
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["crm"]["versions"].update(uat="3.1.0", prd="3.0.5")))
    p, f = plan(base)
    assert f == [] and jobs(p) == ["deploy-nonprd", "deploy-prd"]
    r = p["matrix"]["deploy-prd"]["include"][0]
    assert r["runtime"] == "cloudrun" and r["service"] == "abc-crm-prd" and r["pre_backup"] and r["pool"] == "sql-prd-crm-01"


def test_rollback_is_allowed(tmp_path):
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["payroll"]["versions"].update(prd="2.0.3")))
    p, f = plan(base)
    assert f == [] and p["matrix"]["deploy-prd"]["include"][0]["to"] == "2.0.2"


def test_new_customer_runs_the_onboarding_sequence(tmp_path):
    base = tree(tmp_path, "base", lambda reg: (reg / "tenants" / "xyz.yaml").unlink())
    p, f = plan(base)
    assert f == []
    order = jobs(p)
    for a, b in [("tenant-nonprd", "memberships-nonprd"), ("memberships-nonprd", "db-nonprd"), ("db-nonprd", "deploy-nonprd"),
                 ("edge-nonprd", "deploy-nonprd"), ("cluster-config-nonprd", "deploy-nonprd"), ("deploy-nonprd", "tenant-prd"),
                 ("db-prd", "deploy-prd")]:
        assert order.index(a) < order.index(b), (a, b)
    assert {x["instance"] for x in p["matrix"]["tenant-prd"]["include"]} == {"xyz-prd"}
    assert {x["pool"] for x in p["matrix"]["db-prd"]["include"]} == {"sql-prd-payroll-01", "sql-prd-crm-01"}
    m = p["matrix"]["memberships-prd"]["include"][0]
    assert m["identity"] == "sa:groups-mgr-prd@shr-cicd-prd" and m["state"] == "tfstate-prd/memberships"
    assert all(x["two_phase"] for x in p["matrix"]["cluster-config-nonprd"]["include"])


def test_new_customer_newer_in_prd_than_uat_fails(tmp_path):
    base = tree(tmp_path, "base", lambda reg: (reg / "tenants" / "xyz.yaml").unlink())
    head = tree(tmp_path, "head", edit_tenant("xyz", lambda d: d["subscriptions"]["crm"]["versions"].update(prd="3.0.6", uat="3.0.5")))
    _, f = plan(base, head)
    assert any(x.rule == "PL01" and "crm/prd" in x.message for x in f)


def test_offboarding_is_never_automatic(tmp_path):
    head = tree(tmp_path, "head", lambda reg: (reg / "tenants" / "xyz.yaml").unlink())
    p, f = plan(ROOT, head)
    assert [x.rule for x in f] == ["PL04"] and jobs(p) == []


def test_placement_change_touches_infra_of_one_tier(tmp_path):
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["payroll"]["config"].update(pay_cycle="weekly")))
    p, _ = plan(base)
    assert {x["instance"] for x in p["matrix"]["tenant-nonprd"]["include"]} == {"abc-nonprd"}
    assert {x["instance"] for x in p["matrix"]["tenant-prd"]["include"]} == {"abc-prd"}
    assert "deploy-nonprd" not in jobs(p)                   # no version changed


def test_placement_change_in_nonprd_only(tmp_path):
    base = tree(tmp_path, "base", edit_tenant("abc", lambda d: d["subscriptions"]["crm"]["placement"]["dev"].update(sql="sql-stg-01")))
    p, _ = plan(base)
    assert "tenant-nonprd" in jobs(p) and "tenant-prd" not in jobs(p)
    assert {x["pool"] for x in p["matrix"]["db-nonprd"]["include"]} >= {"sql-dev-01"}


@pytest.mark.parametrize("path,expect", [
    ("terraform/modules/sql-pool/main.tf", {"platform-nonprd", "platform-prd"}),
    ("terraform/modules/gke-cell/main.tf", {"platform-nonprd", "platform-prd"}),
    ("security/k8s-baseline.yaml", {"cluster-config-nonprd", "cluster-config-prd"}),
    ("security/org-policies.yaml", {"org"}),
    ("network/ip-plan.yaml", {"network-nonprd", "network-prd"}),
])
def test_changed_files_map_to_stacks(tmp_path, path, expect):
    p, _ = plan(tree(tmp_path, "base"), changed=[path])
    assert set(jobs(p)) == expect


def test_job_order_respects_dependencies():
    order = planner.job_order(ROOT)
    for j, needs in planner.job_needs(ROOT).items():
        for n in needs:
            if n in order and j in order:
                assert order.index(n) < order.index(j), (n, j)


def test_all_instances_for_drift():
    m = planner.all_instances("nonprd", ROOT)["include"]
    assert {x["stack"] for x in m} >= {"network", "platform", "tenant", "cluster-config", "memberships"}
    assert all(x["tier"] == "nonprd" for x in m)


def test_drift_export_normalisation():
    from tools.monitoring.drift import cross_tenant_iam, from_asset_export, normalise_memberships
    export = [{"resource": "//cloudresourcemanager.googleapis.com/projects/t-abc-prd", "project": "projects/123",
               "policy": {"bindings": [{"role": "roles/storage.objectViewer",
                                        "members": ["serviceAccount:xyz-crm-prd@t-xyz-prd.iam.gserviceaccount.com"]}]}}]
    recs = from_asset_export(export)
    assert recs[0]["project"] == "t-abc-prd"
    assert len(cross_tenant_iam(recs)) == 1
    m = normalise_memberships({"grp-wl-x": ["a@t-abc-prd.iam.gserviceaccount.com", "alice@example.com"]})
    assert m["grp-wl-x"] == ["serviceAccount:a@t-abc-prd.iam.gserviceaccount.com", "user:alice@example.com"]


def test_smoke_hostname(capsys, tmp_path):
    import json
    from tools.cicd import smoke
    from tools.network.edge import Edge
    edge = tmp_path / "edge.json"
    edge.write_text(json.dumps(Edge(str(ROOT / "registry"), str(ROOT / "network"), str(ROOT / "security")).out))
    assert smoke.main(["--tenant", "abc", "--product", "payroll", "--env", "prd", "--dry-run", "--edge", str(edge)]) == 0
    assert capsys.readouterr().out.strip() == "https://abc.payroll.example.com/readyz"
    assert smoke.hostname("abc", "crm", "uat", edge) == "abc-uat.crm.nonprod.example.com"
