"""D8 – namespace security baseline and policy constraints (structure and rules; Rego itself is not executed here)."""
import copy
import pathlib
import re

import pytest
import yaml

from tools.k8s import baseline as B
from tools.registry.loader import load_yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = load_yaml(ROOT / "security" / "k8s-baseline.yaml")
SRC = ROOT / "policies" / "k8s" / "src"


@pytest.fixture
def rendered(reg):
    return B.render(reg.root, ROOT / "security")


def objs(cells, cell, ns, kind=None):
    return [o for o in cells[cell][ns] if kind is None or o["kind"] == kind]


def test_every_namespace_gets_the_full_baseline(rendered):
    cells, cluster = rendered
    assert sum(len(v) for v in cells.values()) == 8
    assert B.check(cells, cluster, CFG) == []
    for cell, nss in cells.items():
        for ns, o in nss.items():
            kinds = [x["kind"] for x in o]
            assert kinds[0] == "Namespace"            # namespace first, then everything else, before workloads
            for k in ("ServiceAccount", "RoleBinding", "NetworkPolicy", "ResourceQuota", "LimitRange"):
                assert k in kinds, (ns, k)
            assert "ClusterRoleBinding" not in kinds


def test_namespace_labels_and_pod_security(rendered):
    cells, _ = rendered
    labels = objs(cells, "gke-prd-as1-01", "abc-payroll-prd", "Namespace")[0]["metadata"]["labels"]
    assert labels["tenant"] == "abc" and labels["env_tier"] == "prd"
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"


def test_workload_identity_annotations_match_plan(rendered):
    cells, _ = rendered
    sas = {s["metadata"]["name"]: s for s in objs(cells, "gke-prd-as1-01", "abc-payroll-prd", "ServiceAccount")}
    assert sas["payroll"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"] == \
        "abc-payroll-prd@t-abc-prd.iam.gserviceaccount.com"
    assert sas["payroll-migrate"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"] == \
        "abc-payroll-prd-mig@t-abc-prd.iam.gserviceaccount.com"
    assert sas["default"]["automountServiceAccountToken"] is False


def test_rbac_follows_access_matrix(rendered):
    cells, _ = rendered
    def subjects(cell, ns):
        return {rb["roleRef"]["name"]: {s["name"] for s in rb["subjects"]}
                for rb in objs(cells, cell, ns, "RoleBinding")}
    prd = subjects("gke-prd-as1-01", "abc-payroll-prd")
    assert "grp-hum-cust-abc-support-prd@example.com" in prd["view"]
    assert not any("xyz" in s for v in prd.values() for s in v)            # no other customer's group
    assert prd["platform-tenant-edit"] == {"deploy-prd@shr-cicd-prd.iam.gserviceaccount.com"}
    dev = subjects("gke-dev-as1-01", "abc-payroll-dev")
    assert "grp-hum-product-payroll-dev@example.com" in dev["view"]
    assert "grp-hum-platform-nonprd-operators@example.com" in dev["platform-tenant-edit"]
    assert not any("product-payroll" in s for v in prd.values() for s in v)  # product devs: no prod namespace access


def test_network_policies(rendered):
    cells, _ = rendered
    nps = {n["metadata"]["name"]: n["spec"] for n in objs(cells, "gke-prd-as1-01", "abc-payroll-prd", "NetworkPolicy")}
    assert nps["default-deny-all"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}
    md = {(r["to"][0]["ipBlock"]["cidr"], r["ports"][0]["port"]) for r in nps["allow-gke-metadata"]["egress"]}
    assert md == {("169.254.169.252/32", 988), ("169.254.169.254/32", 80)}
    sql = [r for r in nps["allow-google-apis-and-cloudsql"]["egress"] if r["ports"][0]["port"] == 3307][0]
    assert sql["to"][0]["ipBlock"]["cidr"] == CFG["network"]["cloud_sql"]["prd"]["cidr"]
    # nothing reaches another tenant namespace: the only namespaceSelector is kube-dns
    for spec in nps.values():
        for rule in spec.get("ingress", []) + spec.get("egress", []):
            for peer in rule.get("from", []) + rule.get("to", []):
                if "namespaceSelector" in peer:
                    assert peer["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "kube-system"}


def test_nonprod_namespace_uses_nonprod_sql_range(rendered):
    cells, _ = rendered
    nps = {n["metadata"]["name"]: n["spec"] for n in objs(cells, "gke-uat-as1-01", "abc-payroll-uat", "NetworkPolicy")}
    cidrs = {r["to"][0]["ipBlock"]["cidr"] for r in nps["allow-google-apis-and-cloudsql"]["egress"]}
    assert CFG["network"]["cloud_sql"]["nonprd"]["cidr"] in cidrs and CFG["network"]["cloud_sql"]["prd"]["cidr"] not in cidrs


def test_quota_blocks_loadbalancer_and_nodeport(rendered):
    cells, _ = rendered
    hard = objs(cells, "gke-prd-as1-01", "abc-payroll-prd", "ResourceQuota")[0]["spec"]["hard"]
    assert hard["services.loadbalancers"] == "0" and hard["services.nodeports"] == "0"
    assert hard["pods"] == CFG["quota"]["prd"]["pods"]


def test_tenant_edit_role_cannot_remove_baseline(rendered):
    _, cluster = rendered
    cr = cluster["gke-prd-as1-01"][0]
    assert cr["metadata"]["name"] == "platform-tenant-edit"
    for r in cr["rules"]:
        if set(r["verbs"]) & {"create", "update", "patch", "delete"}:
            assert not set(r["resources"]) & {"networkpolicies", "resourcequotas", "limitranges", "serviceaccounts",
                                              "roles", "rolebindings", "namespaces"}


@pytest.mark.parametrize("breakage,rule", [
    (lambda o: [x for x in o if x["metadata"]["name"] != "default-deny-all"], "KB02"),
    (lambda o: [dict(x, metadata={**x["metadata"], "labels": {**x["metadata"]["labels"],
                "pod-security.kubernetes.io/enforce": "privileged"}}) if x["kind"] == "Namespace" else x for x in o], "KB01"),
    (lambda o: [x for x in o if x["kind"] != "LimitRange"], "KB04"),
    (lambda o: o + [{"kind": "NetworkPolicy", "metadata": {"name": "open"}, "spec": {"podSelector": {},
                "egress": [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}]}}], "KB03"),
    (lambda o: o + [{"kind": "NetworkPolicy", "metadata": {"name": "cross"}, "spec": {"podSelector": {},
                "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"tenant": "xyz"}}}]}]}}], "KB03"),
    (lambda o: [dict(x, roleRef={**x["roleRef"], "name": "edit"}) if x["kind"] == "RoleBinding" else x for x in o], "KB05"),
])
def test_check_detects_broken_baseline(rendered, breakage, rule):
    cells, cluster = copy.deepcopy(rendered)
    ns = cells["gke-prd-as1-01"]
    ns["abc-payroll-prd"] = breakage(ns["abc-payroll-prd"])
    assert any(e.startswith(rule) for e in B.check(cells, cluster, CFG))


def test_hostname_convention_matches_stage2_examples():
    assert B.hostnames("abc", "payroll", "prd") == ["abc.payroll.example.com"]
    assert B.hostnames("abc", "crm", "uat") == ["abc-uat.crm.nonprod.example.com"]


def test_shared_gke_namespace_hostnames_are_served_tenants_only(reg):
    reg.edit("products/notify.yaml", lambda d: d.update(runtime="gke"))
    cells, cluster = B.render(reg.root, ROOT / "security")
    c = next(o for o in cluster["gke-prd-as1-01"] if o["kind"] == "PlatformHttpRouteHostnames")
    assert c["spec"]["parameters"]["sharedNamespaceHostnames"] == {"shr-notify-prd": ["abc.notify.example.com"]}
    assert "shr-notify-prd" in cells["gke-prd-as1-01"]


def test_image_policy_parameters_per_environment(rendered):
    _, cluster = rendered
    def p(cell):
        return next(o for o in cluster[cell] if o["kind"] == "PlatformAllowedImages")["spec"]["parameters"]
    assert p("gke-prd-as1-01")["requireDigest"] is True
    assert not any("snapshot" in r for r in p("gke-uat-as1-01")["allowedRepos"])
    assert p("gke-dev-as1-01")["requireDigest"] is False and any("snapshot" in r for r in p("gke-dev-as1-01")["allowedRepos"])


def test_constraints_match_templates_and_schemas(rendered):
    _, cluster = rendered
    templates = {t["spec"]["crd"]["spec"]["names"]["kind"]: t for t in B.constraint_templates()}
    for cell, objs_ in cluster.items():
        for c in [o for o in objs_ if o["apiVersion"].startswith("constraints.gatekeeper.sh")]:
            t = templates[c["kind"]]
            props = t["spec"]["crd"]["spec"]["validation"]["openAPIV3Schema"]["properties"]
            assert set(c["spec"]["parameters"]) <= set(props), c["kind"]
            assert c["spec"]["enforcementAction"] == "deny"


@pytest.mark.parametrize("name", sorted(B.TEMPLATE_KINDS))
def test_rego_sources_present_with_tests(name):
    src = (SRC / f"{name}.rego").read_text()
    test = (SRC / f"{name}_test.rego").read_text()
    assert re.search(rf"^package {name}$", src, re.M) and re.search(rf"^package {name}$", test, re.M)
    assert "violation[{\"msg\": msg}]" in src
    assert len(re.findall(r"^test_\w+", test, re.M)) >= 4
    assert src.count("{") == src.count("}")


def test_committed_templates_are_current():
    text = (ROOT / "policies" / "k8s" / "constraint-templates.yaml").read_text()
    docs = list(yaml.safe_load_all(text))
    assert docs == B.constraint_templates()
