"""Stage 8 – cost model (CO01-CO04) and capacity planning (CP01-CP02, planner PL05)."""
import shutil

import yaml

from tests.conftest import ROOT
from tools.cost import capacity
from tools.cost.model import COMPONENTS, CostModel
from tools.registry.validate import validate


def model(tmp_path, edit=None):
    p = tmp_path / "cost-model.yaml"
    d = yaml.safe_load((ROOT / "cost/cost-model.yaml").read_text())
    if edit:
        edit(d)
    p.write_text(yaml.safe_dump(d, sort_keys=False))
    return CostModel(p)


def test_clean():
    assert CostModel().check() == []


def test_counts_come_from_the_capacity_model():
    m = CostModel()
    e = m.estimate(500, "Baseline", 3)
    r = m.cm.row(500, "Baseline", 3)
    assert e["counts"]["sql_total"] == r["total"] == 131 and e["subscriptions"] == 1500
    assert set(e["components"]) == set(COMPONENTS)


def test_cost_grows_with_customers_and_products():
    m = CostModel()
    for c in (200, 500):
        tot = [m.estimate(c, s, p)["total_list"] for s, p in m.cm.SCENARIOS]
        assert tot == sorted(tot)
    for s, p in m.cm.SCENARIOS:
        assert m.estimate(500, s, p)["total_list"] > m.estimate(200, s, p)["total_list"]


def test_optimised_is_cheaper_and_scale_lowers_unit_cost_at_baseline():
    m = CostModel()
    a, b = m.estimate(200, "Baseline", 3), m.estimate(500, "Baseline", 3)
    assert a["total_optimised"] < a["total_list"] and b["total_optimised"] < b["total_list"]
    assert b["per_customer_list"] < a["per_customer_list"]


def test_regional_dr_is_a_separable_cost(tmp_path):
    on = model(tmp_path).estimate(500, "Baseline", 3)
    off = model(tmp_path, lambda d: d["dr"].update(regional=False)).estimate(500, "Baseline", 3)
    assert off["by_tier"]["dr"] == 0 and on["by_tier"]["dr"] > 0
    assert round(on["total_list"] - off["total_list"], 0) == round(on["by_tier"]["dr"], 0)


def test_region_factor_applies_to_regional_prices_only(tmp_path):
    hi = model(tmp_path).estimate(200, "Baseline", 3)
    lo = model(tmp_path, lambda d: d.update(region_factor=1.0)).estimate(200, "Baseline", 3)
    assert lo["total_list"] < hi["total_list"]
    assert lo["components"]["dns"] == hi["components"]["dns"]          # not regional


def test_price_without_source_fails(tmp_path):
    m = model(tmp_path, lambda d: d["prices"]["nat_data_gb"].pop("source"))
    assert any(f.rule == "CO01" for f in m.check())


def test_scope_shards():
    assert capacity.scope_shards(100) == [100]
    assert capacity.scope_shards(800) == [267, 267, 266]
    assert all(n <= 300 for n in capacity.scope_shards(1012))


def test_placement_above_capacity_is_refused(tmp_path):
    shutil.copytree(ROOT / "cost", tmp_path / "cost")
    p = tmp_path / "cost/cost-model.yaml"
    d = yaml.safe_load(p.read_text())
    d["capacity"]["namespaces_per_cell"]["limit"] = 1
    p.write_text(yaml.safe_dump(d, sort_keys=False))
    reg, _ = validate(ROOT / "registry")
    f = capacity.check_placements(reg, tmp_path)
    assert f and all(x.rule == "PL05" for x in f) and "gke-prd-as1-01" in " ".join(x.message for x in f)


def test_utilisation_counts_registry_placements():
    reg, _ = validate(ROOT / "registry")
    u = {(x["resource"], x["name"]): x for x in capacity.utilisation(reg)}
    assert u[("namespaces_per_cell", "gke-prd-as1-01")]["used"] == 2           # abc + xyz payroll
    assert u[("tenants_per_pool", "sql-prd-payroll-01")]["limit"] == 40         # capacity model effective cap
    assert u[("uptime_checks_per_project", "t-abc-prd")]["used"] == 4
