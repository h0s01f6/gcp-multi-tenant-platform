"""Stage 7 – GitHub Actions workflows vs the CI/CD identity model (CW01-CW09) and the expression evaluator."""
import shutil

import pytest
import yaml

from tests.conftest import ROOT
from tools.cicd import workflows as W

WF = "cicd/platform-workflows/.github/workflows"


@pytest.fixture
def repo(tmp_path):
    for d in ("cicd", "registry", "security", "terraform", ".github"):
        shutil.copytree(ROOT / d, tmp_path / d)
    return tmp_path


def rules(root):
    return sorted({f.rule for f in W.Workflows(root).check()})


def edit(root, rel, old, new):
    p = root / rel
    t = p.read_text()
    assert old in t, old
    p.write_text(t.replace(old, new, 1))


def test_clean():
    w = W.Workflows(ROOT)
    assert w.check() == []
    assert len(w.gates_used) >= 13                         # every WIF identity is exercised by some workflow


def test_generated_pipelines_are_current():
    for name, text in W.render_pipelines(ROOT).items():
        assert (ROOT / WF / name).read_text() == text


@pytest.mark.parametrize("expr,ctx,expect", [
    ("inputs.tier == 'nonprd' && 'nonprd' || 'prd'", {"inputs.tier": "nonprd"}, "nonprd"),
    ("inputs.tier == 'nonprd' && 'nonprd' || 'prd'", {"inputs.tier": "org"}, "prd"),
    ("inputs.allow_org && fromJSON(x)['org']", {"inputs.allow_org": False}, False),
    ("!failure() && fromJSON(x)['a'].include[0] != null", {}, W.UNKNOWN),
    ("inputs.tier != 'org' && inputs.stack == 'memberships'", {"inputs.tier": "prd"}, W.UNKNOWN),
])
def test_expressions(expr, ctx, expect):
    assert W.evaluate(expr, ctx) is expect if expect is W.UNKNOWN else W.evaluate(expr, ctx) == expect


def test_app_repo_cannot_deploy(repo):
    p = repo / "cicd/repos/app-payroll/.github/workflows/build.yml"
    d = yaml.safe_load(p.read_text())
    d["jobs"]["ship"] = {"needs": "image", "uses": "example-org/platform-workflows/.github/workflows/deploy-release.yml@v1",
                         "secrets": "inherit", "with": {"tier": "prd", "matrix": "{}"}}
    p.write_text(yaml.safe_dump(d, sort_keys=False).replace("'on':", "on:").replace("true:", "on:"))
    assert "CW03" in rules(repo)


def test_prd_environment_only_in_platform_workflows(repo):
    edit(repo, "cicd/repos/app-crm/.github/workflows/build.yml", "    runs-on: ubuntu-latest\n",
         "    runs-on: ubuntu-latest\n    environment: prd\n")
    assert "CW04" in rules(repo)


def test_branch_pinned_action(repo):
    edit(repo, f"{WF}/build-image.yml", "actions/checkout@v4", "actions/checkout@main")
    assert rules(repo) == ["CW05"]


def test_platform_workflows_must_use_release_tag(repo):
    edit(repo, "cicd/repos/app-crm/.github/workflows/build.yml", "build-image.yml@v1", "build-image.yml@main")
    assert "CW04" in rules(repo)


def test_service_account_key_is_rejected(repo):
    edit(repo, f"{WF}/build-chart.yml", "workload_identity_provider: ${{ vars.WIF_PROVIDER }}",
         "credentials_json: ${{ secrets.GCP_SA_KEY }}")
    assert "CW02" in rules(repo)


def test_helm_without_atomic(repo):
    edit(repo, f"{WF}/deploy-release.yml", "--atomic --wait", "--wait")
    assert rules(repo) == ["CW07"]


def test_apply_concurrency_must_not_cancel(repo):
    edit(repo, f"{WF}/tf-apply.yml", "cancel-in-progress: false", "cancel-in-progress: true")
    assert rules(repo) == ["CW07"]


def test_id_token_only_where_needed(repo):
    edit(repo, f"{WF}/validate.yml", "    permissions:\n      contents: read\n",
         "    permissions:\n      contents: read\n      id-token: write\n")
    assert rules(repo) == ["CW01"]


def test_wrong_runner_group(repo):
    edit(repo, f"{WF}/ansible-configure.yml", 'runs-on: [self-hosted, "${{ inputs.tier }}"]', "runs-on: [self-hosted, build]")
    assert rules(repo) == ["CW06"]


def test_hand_edit_of_generated_pipeline(repo):
    edit(repo, f"{WF}/apply-pipeline.yml", "cancel-in-progress: false", "cancel-in-progress: true")
    assert rules(repo) == ["CW08"]


def test_gate_tightened_in_d6_is_caught(repo):
    # platform-infra applies the memberships stack (K28); removing that gate must break the workflows check
    edit(repo, "security/cicd-identities.yaml",
         '"sa:groups-mgr-prd@shr-cicd-prd":   { auth: wif, tier: prd,    allow: [{ repos: [platform-infra, platform-tenants]',
         '"sa:groups-mgr-prd@shr-cicd-prd":   { auth: wif, tier: prd,    allow: [{ repos: [platform-tenants]')
    assert "CW03" in rules(repo)


def test_product_without_build(repo):
    (repo / "cicd/repos/app-notify/.github/workflows/build.yml").unlink()
    assert "CW09" in rules(repo)
