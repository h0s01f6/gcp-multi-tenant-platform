"""Stage 4 N1 – IP address plan."""
import ipaddress as ip

import pytest
import yaml

from tests.conftest import ROOT
from tools.network.ipam import IPPlan
from tools.registry.loader import load_yaml


@pytest.fixture
def net(tmp_path):
    import shutil
    dst = tmp_path / "network"
    shutil.copytree(ROOT / "network", dst)

    class N:
        root = dst

        def edit(self, fn):
            d = yaml.safe_load((dst / "ip-plan.yaml").read_text())
            fn(d)
            (dst / "ip-plan.yaml").write_text(yaml.safe_dump(d, sort_keys=False))

    return N()


def rules(reg_root, net_root):
    return sorted({f.rule for f in IPPlan(reg_root, net_root).check()})


def plan():
    return IPPlan(ROOT / "registry", ROOT / "network")


def test_plan_is_clean():
    assert plan().check() == []


def test_tiers_and_regions():
    p = plan().plan
    assert p["tiers"]["prd"]["regions"]["asia-south1"]["cidr"] == "10.64.0.0/11"
    assert p["tiers"]["nonprd"]["regions"]["asia-south1"]["cidr"] == "10.128.0.0/11"
    assert p["tiers"]["prd"]["regions"]["asia-south2"]["status"] == "reserved"
    assert not ip.ip_network("10.64.0.0/10").overlaps(ip.ip_network("10.128.0.0/10"))


def test_cell_slots_are_deterministic_and_separate_per_env():
    cells = plan().plan["cells"]
    assert cells["gke-prd-as1-01"] == {**cells["gke-prd-as1-01"], "nodes": "10.82.0.0/22", "pods": "10.64.0.0/17",
                                       "pods_reserve": "10.64.128.0/17", "services": "10.80.0.0/20"}
    assert cells["gke-stg-as1-01"]["slot"] == 16 and cells["gke-uat-as1-01"]["slot"] == 32
    pods = [ip.ip_network(c["pods"]) for c in cells.values()]
    assert all(not a.overlaps(b) for i, a in enumerate(pods) for b in pods[i + 1:])


def test_new_cell_gets_next_slot(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["gke_cells"].update(
        {"gke-prd-as1-02": {"env": "prd", "project": "plt-gke-prd"}}))
    c = IPPlan(reg.root, ROOT / "network").plan["cells"]["gke-prd-as1-02"]
    assert c["pods"] == "10.65.0.0/17" and c["nodes"] == "10.82.4.0/22" and c["services"] == "10.80.16.0/20"
    assert IPPlan(reg.root, ROOT / "network").check() == []


def test_overlap_with_reserved_detected(reg, net):
    net.edit(lambda d: d["tiers"]["prd"].update(supernet="10.0.0.0/10"))
    assert "IP01" in rules(reg.root, net.root)


def test_non_rfc1918_detected(reg, net):
    net.edit(lambda d: d["tiers"]["nonprd"].update(supernet="100.64.0.0/10"))
    assert "IP01" in rules(reg.root, net.root)


def test_layout_overflow_detected(reg, net):
    net.edit(lambda d: d["region_layout"].insert(0, {"block": "extra", "prefix": 11}))
    assert "IP01" in rules(reg.root, net.root)


@pytest.mark.parametrize("change", [
    lambda d: d["planning"].update(cloud_run_peak_instances={"prd": 40000, "nonprd": 8000}),
    lambda d: d["planning"].update(sql_instances={"prd": 20000, "nonprd": 195}),
    lambda d: d["planning"].update(namespaces_per_cell=5000),
    lambda d: d["planning"].update(cells_per_env=20),
])
def test_capacity_shortfalls_detected(reg, net, change):
    net.edit(change)
    assert "IP03" in rules(reg.root, net.root)


def test_cell_in_wrong_project_detected(reg):
    reg.edit("platform/inventory.yaml", lambda d: d["gke_cells"].update(
        {"gke-prd-as1-02": {"env": "prd", "project": "plt-gke-nonprd"}}))
    assert "IP04" in sorted({f.rule for f in IPPlan(reg.root, ROOT / "network").check()})


def test_k8s_baseline_uses_the_psa_ranges():
    p = plan().plan["tiers"]
    k8s = load_yaml(ROOT / "security" / "k8s-baseline.yaml")["network"]["cloud_sql"]
    for tier in ("prd", "nonprd"):
        assert k8s[tier]["cidr"] == p[tier]["regions"]["asia-south1"]["blocks"]["psa"]["cidr"]
