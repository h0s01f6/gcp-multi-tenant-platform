"""Stage 4 N3 – firewall policies (and the D8 egress NetworkPolicy they pair with)."""
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.k8s import baseline as B
from tools.network.firewall import Firewall


@pytest.fixture
def net(tmp_path):
    dst = tmp_path / "network"
    shutil.copytree(ROOT / "network", dst)

    class N:
        root = dst

        def edit(self, rel, fn):
            d = yaml.safe_load((dst / rel).read_text())
            fn(d)
            (dst / rel).write_text(yaml.safe_dump(d, sort_keys=False))

    return N()


def fw(net_root=ROOT / "network", sec_root=ROOT / "security"):
    return Firewall(ROOT / "registry", net_root, sec_root)


def rules(net_root=ROOT / "network", sec_root=ROOT / "security"):
    return sorted({f.rule for f in fw(net_root, sec_root).check()})


def test_design_is_clean():
    assert fw().check() == []


def test_tier_policies_and_default_deny():
    o = fw().out
    assert o["hierarchical"]["fw-tier-prd"]["attach"] == ["fldr-tenants/prd", "fldr-platform/prd"]
    deny = {(r["direction"], tuple(r.get("src", r.get("dst")))) for r in o["hierarchical"]["fw-tier-prd"]["rules"]}
    assert deny == {("INGRESS", ("10.128.0.0/10",)), ("EGRESS", ("10.128.0.0/10",))}
    for p in o["network_policies"].values():
        last = max(p["rules"], key=lambda r: r["priority"])
        assert last["action"] == "deny" and last["dst"] == ["0.0.0.0/0"]


def test_fqdn_egress_per_product_from_its_runtime_only():
    rules_ = {r["product"]: r for r in fw().out["network_policies"]["fwp-prd"]["rules"] if r.get("dst_fqdns")}
    assert rules_["payroll"]["src"] == ["10.64.0.0/17"] and rules_["payroll"]["ports"] == ["tcp:587"]
    assert rules_["crm"]["src"] == ["10.83.0.0/16"]           # Cloud Run: subnet granularity (K26)
    assert "ledger" not in rules_                              # no egress declared


@pytest.mark.parametrize("rule,code", [
    ({"priority": 1500, "direction": "INGRESS", "action": "allow", "src": [ "0.0.0.0/0"], "ports": ["tcp:443"]}, "FW02"),
    ({"priority": 1501, "direction": "INGRESS", "action": "allow", "src": "@iap", "target_tags": ["wl=gke-node"], "ports": ["tcp:22"]}, "FW03"),
    ({"priority": 1502, "direction": "EGRESS", "action": "allow", "dst": ["0.0.0.0/0"], "ports": ["tcp:443"]}, "FW04"),
    ({"priority": 1503, "direction": "EGRESS", "action": "allow", "dst": "@tier:nonprd", "ports": ["all"]}, "FW05"),
    ({"priority": 1000, "direction": "EGRESS", "action": "deny", "dst": ["10.0.0.0/8"], "ports": ["all"]}, "FW01"),
])
def test_bad_rules_detected(net, rule, code):
    net.edit("firewall.yaml", lambda d: d["network_policy"]["rules"].append(rule))
    assert code in rules(net.root)


def test_tier_isolation_rule_required(net):
    net.edit("firewall.yaml", lambda d: d["hierarchical"]["fw-tier-nonprd"].update(rules=[]))
    assert "FW05" in rules(net.root)


def test_goto_next_outside_hierarchy_rejected(net):
    net.edit("firewall.yaml", lambda d: d["network_policy"]["rules"].append(
        {"priority": 1600, "direction": "INGRESS", "action": "goto_next", "src": "@iap", "ports": ["tcp:22"]}))
    assert "FW01" in rules(net.root)


def test_d8_consistency(sec):
    sec.edit("k8s-baseline.yaml", lambda d: d["network"].update(load_balancer_sources=["35.191.0.0/16"]))
    assert "FW07" in rules(sec_root=sec.root)


def test_d8_egress_networkpolicy_only_for_products_with_allow_list(reg):
    cells, cluster = B.render(reg.root, ROOT / "security")
    nps = {o["metadata"]["name"]: o for o in cells["gke-prd-as1-01"]["abc-payroll-prd"] if o["kind"] == "NetworkPolicy"}
    eg = nps["allow-internet-egress"]["spec"]["egress"][0]
    assert eg["to"][0]["ipBlock"] == {"cidr": "0.0.0.0/0", "except": B.PRIVATE}
    assert eg["ports"] == [{"protocol": "TCP", "port": 587}]
    assert B.check(cells, cluster, B.load_yaml(ROOT / "security" / "k8s-baseline.yaml")) == []


def test_d8_open_internet_without_except_still_rejected(reg):
    import copy
    cells, cluster = B.render(reg.root, ROOT / "security")
    cells = copy.deepcopy(cells)
    for o in cells["gke-prd-as1-01"]["abc-payroll-prd"]:
        if o["metadata"]["name"] == "allow-internet-egress":
            o["spec"]["egress"][0]["to"][0]["ipBlock"].pop("except")
    assert any(e.startswith("KB03") for e in B.check(cells, cluster, B.load_yaml(ROOT / "security" / "k8s-baseline.yaml")))
