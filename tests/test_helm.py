"""Stage 6 – Helm: generated release values (Terraform -> Helm contract) and charts rendered with Go text/template."""
import copy
import json
import re

import jsonschema
import pytest
import yaml

from tests.conftest import ROOT
from tools.iac import helmvalues as H
from tools.k8s.baseline import hostnames

IFACE = json.loads((ROOT / "interfaces" / "helm-release.schema.json").read_text())
CHART_SCHEMA = json.loads((ROOT / "helm" / "charts" / "payroll" / "values.schema.json").read_text())
ALLOWED_KINDS = {"Deployment", "Service", "HTTPRoute", "HealthCheckPolicy", "HorizontalPodAutoscaler",
                 "PodDisruptionBudget", "ConfigMap", "Job"}
DIGEST = re.compile(r"^asia-south1-docker\.pkg\.dev/shr-artifacts/release/.+@sha256:[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def releases():
    return H.Releases(ROOT / "registry", ROOT / "security", ROOT / "network").generate()


@pytest.fixture(scope="module")
def rendered(releases):
    out = {}
    for (cell, ns, product), v in releases.items():
        out[(cell, ns, product)] = H.render(product, ns, H.merged_values(product, v["env"], v))[1]
    return out


def test_every_gke_namespace_has_a_release(releases):
    assert len(releases) == 8
    assert ("gke-prd-as1-01", "abc-payroll-prd", "payroll") in releases


def test_generated_values_match_the_interface_contract(releases):
    for v in releases.values():
        jsonschema.validate(v, IFACE)


def test_merged_values_match_the_chart_schema(releases):
    for v in releases.values():
        jsonschema.validate(H.merged_values("payroll", v["env"], v), CHART_SCHEMA)


def test_interface_sources_exist_as_terraform_outputs():
    def sources(o):
        if isinstance(o, dict):
            if "x-source" in o:
                yield o["x-source"]
            for v in o.values():
                yield from sources(v)
    from tools.iac.hclcheck import load_dir
    for s in sources(IFACE):
        if s.startswith("terraform:"):
            stack, _, output = s[len("terraform:"):].split(" ")[0].partition(".output.")
            assert output in load_dir(ROOT / "terraform" / "stacks" / stack).outputs, s


def test_registry_versions_per_environment(releases):
    assert releases[("gke-prd-as1-01", "abc-payroll-prd", "payroll")]["image"]["version"] == "2.0.2"
    assert releases[("gke-dev-as1-01", "abc-payroll-dev", "payroll")]["image"]["version"] == "2.1.0"
    assert releases[("gke-prd-as1-01", "xyz-payroll-prd", "payroll")]["image"]["version"] == "1.5.3"


def test_rendered_objects_are_application_only(rendered):
    for key, docs in rendered.items():
        kinds = {d["kind"] for d in docs}
        assert kinds <= ALLOWED_KINDS, (key, kinds)
        assert all(d["metadata"]["namespace"] == key[1] for d in docs)
        for d in docs:
            if d["kind"] == "Service":
                assert d["spec"]["type"] == "ClusterIP"


def pods(docs):
    for d in docs:
        if d["kind"] in ("Deployment", "Job"):
            yield d, d["spec"]["template"]["spec"]


def test_pods_meet_the_d8_baseline(rendered, releases):
    for key, docs in rendered.items():
        v = releases[key]
        for d, spec in pods(docs):
            want = v["serviceAccount"]["migrationName"] if d["kind"] == "Job" else v["serviceAccount"]["name"]
            assert spec["serviceAccountName"] == want
            for c in spec.get("initContainers", []) + spec["containers"]:
                assert DIGEST.match(c["image"]), c["image"]                       # PlatformAllowedImages
                sc = c["securityContext"]
                assert sc["runAsNonRoot"] and not sc["allowPrivilegeEscalation"] and sc["capabilities"]["drop"] == ["ALL"]
                assert sc["seccompProfile"]["type"] == "RuntimeDefault"
                assert c["resources"]["requests"] == c["resources"]["limits"]
            assert "nodeSelector" not in spec                                      # standard isolation tier


def test_routes_use_registry_hostnames_and_platform_gateway(rendered, releases):
    for key, docs in rendered.items():
        v = releases[key]
        route = next(d for d in docs if d["kind"] == "HTTPRoute")
        assert route["spec"]["hostnames"] == hostnames(v["tenant"], v["product"], v["env"])
        assert route["spec"]["parentRefs"][0] == {"name": v["route"]["gateway"]["name"], "namespace": "gateway-infra",
                                                  "sectionName": "https"}


def test_database_access_through_iam_proxy(rendered, releases):
    for key, docs in rendered.items():
        v = releases[key]
        for d, spec in pods(docs):
            proxy = spec["initContainers"][0]
            assert proxy["restartPolicy"] == "Always" and "--auto-iam-authn" in proxy["args"]
            assert v["database"]["instanceConnectionName"] in proxy["args"]
            env = {e["name"]: e["value"] for e in spec["containers"][0]["env"]}
            assert env["DB_USER"] == (v["database"]["migrationUser"] if d["kind"] == "Job" else v["database"]["user"])
            assert env["DB_NAME"] == f"{v['tenant']}_{v['product']}"
            assert not any("PASSWORD" in k and not k.startswith("SECRET_") for k in env)   # only secret references


def test_migration_is_a_pre_upgrade_hook(rendered):
    for docs in rendered.values():
        job = next(d for d in docs if d["kind"] == "Job")
        assert job["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"


def test_environment_sizing(rendered):
    prd = rendered[("gke-prd-as1-01", "abc-payroll-prd", "payroll")]
    dev = rendered[("gke-dev-as1-01", "abc-payroll-dev", "payroll")]
    assert {d["kind"] for d in prd} >= {"HorizontalPodAutoscaler", "PodDisruptionBudget"}
    assert not {"HorizontalPodAutoscaler", "PodDisruptionBudget"} & {d["kind"] for d in dev}
    assert next(d for d in dev if d["kind"] == "Deployment")["spec"]["replicas"] == 1


def test_customer_config_is_data_only(releases):
    v = copy.deepcopy(releases[("gke-prd-as1-01", "abc-payroll-prd", "payroll")])
    v["config"] = {"x": "{{ .Release.Name }}\n---\nkind: ClusterRoleBinding"}
    docs = H.render("payroll", "abc-payroll-prd", H.merged_values("payroll", "prd", v))[1]
    assert {d["kind"] for d in docs} <= ALLOWED_KINDS
    cm = next(d for d in docs if d["kind"] == "ConfigMap")
    assert cm["data"]["X"].startswith("{{ .Release.Name }}")                      # rendered as a literal string


def test_dedicated_nodes_for_enhanced_tier(releases):
    v = copy.deepcopy(releases[("gke-prd-as1-01", "abc-payroll-prd", "payroll")])
    v["isolation"]["dedicatedNodes"] = True
    docs = H.render("payroll", "abc-payroll-prd", H.merged_values("payroll", "prd", v))[1]
    spec = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"platform.example.com/tenant": "abc"}
    assert spec["tolerations"][0]["value"] == "abc"


@pytest.mark.parametrize("mutate", [
    lambda v: v["image"].update(digest="latest"),
    lambda v: v["image"].update(repository="docker.io/library/payroll"),
    lambda v: v["route"].update(hostnames=[]),
    lambda v: v["database"].update(instanceConnectionName="10.84.0.5"),
    lambda v: v["secrets"].update({"x": "plain-text-value"}),
    lambda v: v.update(extra="not allowed"),
])
def test_contract_rejects_bad_values(releases, mutate):
    v = copy.deepcopy(releases[("gke-prd-as1-01", "abc-payroll-prd", "payroll")])
    mutate(v)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(v, IFACE)


def test_render_fails_without_required_values(releases):
    v = H.merged_values("payroll", "prd", releases[("gke-prd-as1-01", "abc-payroll-prd", "payroll")])
    v["image"]["digest"] = ""
    with pytest.raises(RuntimeError, match="image digest is required"):
        H.render("payroll", "abc-payroll-prd", v)


def test_no_missing_values_in_output(releases):
    for (cell, ns, product), v in releases.items():
        text, _ = H.render(product, ns, H.merged_values(product, v["env"], v))
        assert "<no value>" not in text
