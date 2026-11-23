"""Stage 8 – SLOs / monitoring plan (SL01-SL06) and backup / DR checks (BC01-BC06)."""
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.slo.dr import DisasterRecovery
from tools.slo.observability import Observability


@pytest.fixture
def root(tmp_path):
    for d in ("slo", "registry", "security", "network", "terraform", "cost", "cicd"):
        shutil.copytree(ROOT / d, tmp_path / d)
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts")
    return tmp_path


def edit_yaml(path, fn):
    d = yaml.safe_load(path.read_text())
    fn(d)
    path.write_text(yaml.safe_dump(d, sort_keys=False))


def obs(root):
    return Observability(root / "registry", root / "slo" / "slos.yaml", root)


def test_observability_clean():
    assert Observability().check() == []


def test_every_prd_subscription_has_slos_and_uptime():
    o = Observability()
    p = o.plan("prd")
    subs = {(t, pr) for t, pr, _, _ in o.subscriptions()}
    assert {(s["tenant"], s["product"]) for s in p["slos"] if s["type"] == "availability"} == subs
    assert {(s["tenant"], s["product"]) for s in p["slos"] if s["type"] == "latency"} == subs
    assert {c["product"] for c in o.uptime_checks("abc", "prd")} == {"payroll", "crm", "notify", "ledger"}
    assert o.uptime_checks("abc", "nonprd") == []


def test_sli_source_per_deployment_model():
    o = Observability()
    slo = {s["id"]: s for s in o.plan("prd")["slos"]}
    assert 'backend_target_name="bs-abc-crm-prd"' in slo["abc-crm-availability"]["total_filter"]          # Cloud Run, dedicated
    assert "monitoring.regex.full_match" in slo["abc-payroll-availability"]["total_filter"]               # GKE Gateway
    assert 'metric.label.tenant="abc"' in slo["abc-notify-availability"]["total_filter"]                  # shared: log metric
    assert o.plan("prd")["log_metrics"] and o.plan("nonprd")["slos"] == []


def test_alert_count_does_not_grow_with_customers():
    o = Observability()
    burn = [a for a in o.plan("prd")["alert_policies"] if a["id"].startswith("slo-")]
    assert len(burn) == 3 * len(o.reg.products)
    assert all("sum by (" in a["conditions"][0]["promql"] for a in burn)


def test_lb_projects_in_home_scope():
    p = Observability().plan("prd")
    home = p["scoping_projects"][0]["name"]
    assert home == "plt-obs-prd-01"
    assert {"scope": home, "project": "plt-ingress-prd"} in p["monitored_projects"]


def test_burn_rate_window_error_is_caught(root):
    edit_yaml(root / "slo/slos.yaml", lambda d: d["burn_rate_alerts"][0].update(short="2h"))
    assert any(f.rule == "SL03" for f in obs(root).check())


def test_missing_platform_coverage_is_caught(root):
    edit_yaml(root / "slo/slos.yaml", lambda d: d.update(platform_alerts=[a for a in d["platform_alerts"] if a["covers"] != "cert-expiry"]))
    assert any(f.rule == "SL04" and "cert-expiry" in f.message for f in obs(root).check())


def test_dr_clean_and_not_activated():
    d = DisasterRecovery()
    assert d.check() == []
    assert not d.enabled() and d.replica("sql-prd-crm-01", "prd") is None
    assert d.restore_minutes <= 240 and d.failover_minutes <= 240


def test_enabling_dr_without_prerequisites_fails(root):
    edit_yaml(root / "slo/dr.yaml", lambda d: d["regional_dr"].update(enabled=True))
    d = DisasterRecovery(root / "registry", root / "security", root)
    assert d.replica("sql-prd-crm-01", "prd")["region"] == "asia-south2"
    assert any(f.rule == "BC04" and "prerequisite" in f.message for f in d.check())


def test_backup_retention_mismatch(root):
    edit_yaml(root / "slo/dr.yaml", lambda d: d["backups"]["prd"].update(retained=14))
    assert any(f.rule == "BC01" for f in DisasterRecovery(root / "registry", root / "security", root).check())


def test_slow_restore_breaks_rto(root):
    edit_yaml(root / "slo/dr.yaml", lambda d: d["restore"].update(clone_gb_per_hour=300))
    assert any(f.rule == "BC03" for f in DisasterRecovery(root / "registry", root / "security", root).check())


def test_failover_path_over_rto(root):
    edit_yaml(root / "slo/dr.yaml", lambda d: d["region_failover_steps_min"].update(promote_replicas=200))
    assert any(f.rule == "BC05" for f in DisasterRecovery(root / "registry", root / "security", root).check())


def test_release_without_backup_is_caught(root):
    p = root / "cicd/platform-workflows/.github/workflows/deploy-release.yml"
    p.write_text(p.read_text().replace("gcloud sql backups create", "echo skip-backup"))
    assert any(f.rule == "BC06" for f in DisasterRecovery(root / "registry", root / "security", root).check())
