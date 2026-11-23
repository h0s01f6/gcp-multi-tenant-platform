"""Stage 4 N2 – VPCs, subnets, Shared VPC and runtime network settings."""
from tests.conftest import ROOT
from tools.network.vpc import NetworkPlan


def nplan(reg_root=ROOT / "registry", sec_root=ROOT / "security"):
    return NetworkPlan(reg_root, ROOT / "network", sec_root)


def rules(reg_root=ROOT / "registry", sec_root=ROOT / "security"):
    return sorted({f.rule for f in nplan(reg_root, sec_root).check()})


def test_plan_is_clean():
    assert nplan().check() == []


def test_subnets_per_tier_and_cell():
    o = nplan().out
    names = {s["name"]: s for s in o["subnets"] if s["create"]}
    assert set(names) == {"snet-prd-as1-run", "snet-prd-as1-mig", "snet-prd-as1-gke-prd-01",
                          "snet-nonprd-as1-run", "snet-nonprd-as1-mig", "snet-nonprd-as1-gke-dev-01",
                          "snet-nonprd-as1-gke-stg-01", "snet-nonprd-as1-gke-uat-01"}
    g = names["snet-prd-as1-gke-prd-01"]
    assert g["cidr"] == "10.82.0.0/22" and [r["range_name"] for r in g["secondary"]] == ["pods-prd-01", "svc-prd-01"]
    assert all(s["private_google_access"] for s in names.values())


def test_only_vpc_workload_projects_attached_to_own_tier():
    sp = nplan().out["service_projects"]
    assert "t-abc-prd" in sp["prd"] and "t-abc-nonprd" in sp["nonprd"]
    assert not set(sp["prd"]) & set(sp["nonprd"])
    assert all("nonprd" not in p for p in sp["prd"])


def test_gke_only_customer_is_not_attached(reg):
    def f(d):
        d["subscriptions"].pop("crm")
    reg.edit("tenants/xyz.yaml", f)
    sp = nplan(reg.root).out["service_projects"]
    assert "t-xyz-prd" not in sp["prd"] and "t-xyz-nonprd" not in sp["nonprd"]


def test_runtime_settings():
    o = nplan().out
    run = {r.get("service") or r.get("job"): r for r in o["cloud_run"] if r["tier"] == "prd"}
    assert run["abc-crm-prd"]["subnet"] == "snet-prd-as1-run" and run["abc-crm-prd"]["egress"] == "all-traffic"
    assert run["abc-crm-prd"]["network_tags"] == ["run-prd", "run-crm"]
    assert {r["job"] for r in o["cloud_run"] if r.get("job")} == {"db-bootstrap", "db-isotest"}
    assert all(not m["external_ip"] for m in o["mig"])
    assert all(s["ipv4_enabled"] is False and s["connector_enforcement"] == "REQUIRED" for s in o["cloud_sql"])
    gke = {c["cluster"]: c for c in o["gke_clusters"]}["gke-prd-as1-01"]
    assert gke["private_nodes"] and gke["control_plane"]["ip_endpoint_external_access"] is False


def test_netusers_members_are_service_agents_of_own_tier():
    o = nplan().out
    for grp, members in o["netusers_members"].items():
        tier = grp.rsplit("-", 1)[1]
        for m in members:
            proj = m.split("PROJECT_NUMBER:")[1].split("}")[0]
            assert ("nonprd" in proj) == (tier == "nonprd"), m
    assert any(b["role"] == "roles/container.hostServiceAgentUser" for b in o["host_bindings"])


def test_project_level_network_user_rejected(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-wl-netusers-prd", "scope": "project:net-host-prd", "roles": ["roles/compute.networkUser"],
         "access": "standing"}))
    assert "NW06" in rules(sec_root=sec.root)


def test_cross_tier_subnet_grant_rejected(sec):
    sec.edit("access-matrix.yaml", lambda d: d["grants"].append(
        {"principal": "grp-wl-netusers-nonprd", "scope": "subnet:snet-prd-as1-run", "roles": ["roles/compute.networkUser"],
         "access": "standing"}))
    assert {"NW06"} <= set(rules(sec_root=sec.root))


def test_d5_subnet_constraint_must_allow_host(sec):
    def f(d):
        for p in d["policies"]:
            if p["constraint"] == "compute.restrictSharedVpcSubnetworks" and p["node"] == "fldr-tenants/prd":
                p["allow"] = ["under:projects/net-host-prd-other"]
    sec.edit("org-policies.yaml", f)
    assert "NW05" in rules(sec_root=sec.root)


def test_peering_rejected(tmp_path):
    import shutil
    import yaml
    dst = tmp_path / "network"
    shutil.copytree(ROOT / "network", dst)
    d = yaml.safe_load((dst / "vpc.yaml").read_text())
    d["vpc"]["peering"] = "full-mesh"
    (dst / "vpc.yaml").write_text(yaml.safe_dump(d))
    assert "NW07" in {f.rule for f in NetworkPlan(ROOT / "registry", dst, ROOT / "security").check()}
