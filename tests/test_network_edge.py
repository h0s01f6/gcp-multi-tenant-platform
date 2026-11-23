"""Stage 4 N4 – DNS, certificates, ingress, Cloud Armor, Cloud NAT."""
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.network.edge import Edge, wildcard_covers


def edge(reg_root=ROOT / "registry", net_root=ROOT / "network"):
    return Edge(reg_root, net_root, ROOT / "security")


@pytest.fixture
def net(tmp_path):
    dst = tmp_path / "network"
    shutil.copytree(ROOT / "network", dst)

    class N:
        root = dst

        def edit(self, fn):
            d = yaml.safe_load((dst / "edge.yaml").read_text())
            fn(d)
            (dst / "edge.yaml").write_text(yaml.safe_dump(d, sort_keys=False))

    return N()


def test_design_is_clean():
    assert edge().check() == []


def test_records_and_frontends_from_registry():
    o = edge().out
    recs = {r["hostname"]: r for r in o["records"]}
    assert recs["abc.payroll.example.com"]["frontend"] == "gw-payroll-prd-01"
    assert recs["abc-uat.crm.nonprod.example.com"]["frontend"] == "um-crm-uat"
    assert recs["abc.notify.example.com"]["frontend"] == "um-notify-prd"
    hr = {h["host"]: h for h in o["albs"]["um-crm-prd"]["host_rules"]}
    assert hr["xyz.crm.example.com"]["backend_project"] == "t-xyz-prd"
    assert hr["xyz.crm.example.com"]["backend_service"] == "bs-xyz-crm-prd"
    assert o["albs"]["um-notify-prd"]["host_rules"][0]["backend_service"] == "bs-notify-prd"


def test_shared_product_hostnames_for_served_tenants_only(reg):
    reg.edit("tenants/xyz.yaml", lambda d: d["subscriptions"].update({"notify": {"config": {}}}))
    hosts = {h["host"] for h in edge(reg.root).out["albs"]["um-notify-prd"]["host_rules"]}
    assert hosts == {"abc.notify.example.com", "xyz.notify.example.com"}


def test_wildcard_covers_single_label_only():
    assert wildcard_covers("*.crm.example.com", "abc.crm.example.com")
    assert not wildcard_covers("*.crm.example.com", "a.b.crm.example.com")
    assert not wildcard_covers("*.crm.example.com", "abc.payroll.example.com")


def test_cross_customer_backend_detected():
    e = edge()
    e.out["albs"]["um-crm-prd"]["host_rules"][0]["backend_project"] = "t-xyz-prd"
    assert "IN02" in {f.rule for f in e.check()}


def test_duplicate_hostname_detected():
    e = edge()
    e.out["records"].append(dict(e.out["records"][0]))
    assert "IN01" in {f.rule for f in e.check()}


def test_uat_must_deny_by_default(net):
    net.edit(lambda d: d["cloud_armor"]["policies"]["ca-nonprd-uat"].update(default_action="allow"))
    assert "IN04" in {f.rule for f in edge(net_root=net.root).check()}


def test_private_zone_must_use_pga_vip(net):
    net.edit(lambda d: d["dns"].update(pga_vip_ips=["199.36.153.4"]))
    assert "IN05" in {f.rule for f in edge(net_root=net.root).check()}


def test_nat_sized_for_upper_bound(net):
    net.edit(lambda d: d["nat"].update(headroom=0.5))
    assert "IN06" in {f.rule for f in edge(net_root=net.root).check()}
    nat = {n["tier"]: n for n in edge().out["nat"]}
    assert nat["prd"]["static_ips"] == 39 and "snet-prd-as1-gke-prd-01" in nat["prd"]["subnets"]


def test_gateway_route_selector(net):
    e = edge()
    next(iter(e.out["gateways"].values()))["allowed_route_selector"] = {"product": "payroll"}
    assert "IN07" in {f.rule for f in e.check()}


def test_quota_register():
    from tools.network import quotas
    f, rows = quotas.check(edge(), ROOT / "network" / "quotas.yaml")
    assert f == []
    use = dict((n, u) for n, u, _ in rows)
    assert use["shared_vpc_service_projects_per_host"] == 530 and use["nat_static_ips_per_region"] == 39


def test_quota_without_validation_item_rejected(tmp_path):
    from tools.network import quotas
    p = tmp_path / "q.yaml"
    d = yaml.safe_load((ROOT / "network" / "quotas.yaml").read_text())
    d["quotas"]["records_per_public_zone"]["validation"] = "T-ZZ9"
    d["quotas"]["cloud_run_ips_per_tier"]["value"] = 1000
    p.write_text(yaml.safe_dump(d))
    rules = {x.rule for x in quotas.check(edge(), p)[0]}
    assert rules == {"QU01", "QU02"}
