"""D5 – organisation / folder policy checker."""
import pathlib
import shutil

import pytest
import yaml

from tools.policy.orgpolicy import OrgPolicies, at_least_as_strict

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "security" / "org-policies.yaml"


@pytest.fixture
def op(tmp_path):
    dst = tmp_path / "org-policies.yaml"
    shutil.copy(SRC, dst)

    class P:
        path = dst

        def edit(self, fn):
            d = yaml.safe_load(dst.read_text())
            fn(d)
            dst.write_text(yaml.safe_dump(d, sort_keys=False))

        def rules(self):
            return sorted({f.rule for f in OrgPolicies(dst).check()})

        def findings(self):
            return OrgPolicies(dst).check()

    return P()


def test_proposed_policy_set_is_clean():
    assert OrgPolicies(SRC).check() == []


def test_isolation_critical_constraints_enforced_on_every_tenant_and_platform_folder():
    o = OrgPolicies(SRC)
    for node in ("fldr-tenants/prd", "fldr-tenants/nonprd", "fldr-platform/prd", "fldr-platform/nonprd"):
        for c in ("iam.managed.disableServiceAccountKeyCreation", "sql.restrictPublicIp",
                  "storage.publicAccessPrevention", "iam.disableCrossProjectServiceAccountUsage"):
            e = o.effective(node, c, include_dry_run=False)
            assert e["kind"] == "boolean" and e["enforce"], (node, c)
        assert o.effective(node, "compute.vmExternalIpAccess")["kind"] == "deny_all"
        assert o.effective(node, "iam.allowedPolicyMemberDomains")["values"] == ["${CUSTOMER_ID}"]


def test_tier_boundary_subnets():
    o = OrgPolicies(SRC)
    assert o.effective("fldr-tenants/prd", "compute.restrictSharedVpcSubnetworks")["values"] == ["under:projects/net-host-prd"]
    assert o.effective("fldr-tenants/nonprd", "compute.restrictSharedVpcSubnetworks")["values"] == ["under:projects/net-host-nonprd"]


def test_prod_stricter_examples():
    o = OrgPolicies(SRC)
    assert o.effective("fldr-tenants/prd", "gcp.restrictNonCmekServices")["kind"] == "deny"
    assert o.effective("fldr-tenants/nonprd", "gcp.restrictNonCmekServices")["kind"] == "unset"


def test_unknown_constraint_and_wrong_shape(op):
    op.edit(lambda d: d["policies"].extend([
        {"node": "org", "constraint": "made.up", "enforce": True},
        {"node": "fldr-shared", "constraint": "sql.restrictPublicIp", "allow": ["x"]}]))
    assert "OP01" in op.rules()


def test_unknown_node_and_duplicate(op):
    op.edit(lambda d: d["policies"].extend([
        {"node": "fldr-nowhere", "constraint": "sql.restrictPublicIp", "enforce": True},
        {"node": "org", "constraint": "sql.restrictPublicIp", "enforce": True}]))
    assert "OP02" in op.rules()


def test_baseline_missing_at_org(op):
    op.edit(lambda d: d.update(policies=[p for p in d["policies"]
                                         if not (p["node"] == "org" and p["constraint"] == "storage.uniformBucketLevelAccess")]))
    assert "OP03" in op.rules()


def test_prod_weaker_than_nonprod(op):
    op.edit(lambda d: d["policies"].append(
        {"node": "fldr-tenants/nonprd", "constraint": "run.allowedIngress", "allow": ["internal"]}))
    assert "OP04" in op.rules()


def test_tier_scoped_value_naming_other_tier(op):
    def f(d):
        for p in d["policies"]:
            if p["node"] == "fldr-tenants/nonprd" and p["constraint"] == "compute.restrictSharedVpcSubnetworks":
                p["allow"] = ["under:projects/net-host-prd"]
    op.edit(f)
    assert "OP04" in op.rules()


def test_relaxation_needs_complete_exception(op):
    relax = {"node": "fldr-shared", "constraint": "compute.requireShieldedVm", "enforce": False}
    op.edit(lambda d: d["policies"].append(dict(relax)))
    assert op.rules() == ["OP05"]
    op.edit(lambda d: d["policies"][-1].update(exception={"reason": "legacy image", "approved_by": "security-team",
                                                         "review_by": "2027-03-31"}))
    assert op.rules() == []


def test_mandatory_never_relaxed_even_with_exception(op):
    op.edit(lambda d: d["policies"].append(
        {"node": "fldr-tenants/nonprd", "constraint": "sql.restrictPublicIp", "enforce": False,
         "exception": {"reason": "x", "approved_by": "y", "review_by": "2027-01-01"}}))
    assert "OP07" in op.rules()


def test_high_impact_must_start_in_dry_run(op):
    def f(d):
        for p in d["policies"]:
            if p["constraint"] == "gcp.resourceLocations":
                p.pop("dry_run")
    op.edit(f)
    assert "OP06" in op.rules()


def test_unknown_placeholder(op):
    op.edit(lambda d: d["policies"].append(
        {"node": "fldr-shared", "constraint": "iam.workloadIdentityPoolProviders", "allow": ["${TODO}"]}))
    assert "OP08" in op.rules()


@pytest.mark.parametrize("a,b,expected", [
    ({"kind": "deny_all"}, {"kind": "allow", "values": ["x"]}, True),
    ({"kind": "allow", "values": ["x"]}, {"kind": "allow", "values": ["x", "y"]}, True),
    ({"kind": "allow", "values": ["x", "y"]}, {"kind": "allow", "values": ["x"]}, False),
    ({"kind": "deny", "values": ["x", "y"]}, {"kind": "deny", "values": ["x"]}, True),
    ({"kind": "unset"}, {"kind": "boolean", "enforce": True}, False),
    ({"kind": "boolean", "enforce": True}, {"kind": "unset"}, True),
])
def test_strictness_order(a, b, expected):
    assert at_least_as_strict(a, b) is expected


def test_generated_markdown_is_current():
    assert (ROOT / "security" / "org-policies.md").read_text() == OrgPolicies(SRC).render_markdown()
