"""D11 – the consolidated registers are complete and consistent with what the code and configuration reference."""
import re

from tests.conftest import ROOT
from tools.registry.loader import load_yaml

REGISTER = ROOT / "documentation" / "assumptions-and-open-questions.md"
ID_RE = re.compile(r"\b(T-[A-Z]{1,2}\d+|[RA]-D\d+-\d+)\b")
SCAN = ["security", "tools", "policies", "documentation", "architecture", "registry", "network", "terraform", "helm",
        "ansible", "interfaces", "cicd", "cost", "slo", "README.md", "CHANGELOG.md"]


def register_ids():
    ids = []
    for line in REGISTER.read_text().splitlines():
        m = re.match(r"^\| (T-[A-Z]{1,2}\d+|[RA]-D\d+-\d+)\b", line)
        if m:
            ids.append(m.group(1))
    return ids


def referenced_ids():
    refs = {}
    for top in SCAN:
        p = ROOT / top
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()
                                          and f.suffix in (".md", ".yaml", ".py", ".rego", ".json")]
        for f in files:
            if f == REGISTER:
                continue
            for i in ID_RE.findall(f.read_text()):
                refs.setdefault(i, f.relative_to(ROOT).as_posix())
    return refs


def test_register_ids_are_unique():
    ids = register_ids()
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, dup


def test_every_referenced_id_is_registered():
    reg = set(register_ids())
    missing = {i: where for i, where in referenced_ids().items() if i not in reg}
    assert not missing, missing


def test_org_policy_validation_items_registered():
    reg = set(register_ids())
    for p in load_yaml(ROOT / "security" / "org-policies.yaml")["policies"]:
        if p.get("validation"):
            assert p["validation"] in reg, p


def test_required_alerts_implemented_and_documented():
    req = set(load_yaml(ROOT / "security" / "privileged-access.yaml")["required_alerts"])
    alerts = set(load_yaml(ROOT / "security" / "audit-monitoring.yaml")["alerts"])
    assert req <= alerts
    doc = (ROOT / "documentation" / "stage-3-security-implementation.md").read_text()
    for a in alerts:
        assert a in doc, a


def test_stage3_document_covers_every_deliverable():
    doc = (ROOT / "documentation" / "stage-3-security-implementation.md").read_text()
    for d in range(1, 12):
        assert re.search(rf"\bD{d}\b", doc), f"D{d}"
