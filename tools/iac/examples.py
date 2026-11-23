"""Stage 5/6 – refresh the committed ABC / XYZ examples (examples/) from the generators.

Usage:  python3 -m tools.iac.examples          (tests/test_examples.py fails if the committed copies are stale)
"""
import json
import pathlib
import sys

from tools.iac import helmvalues as H
from tools.iac.tfvars import Bridge

ROOT = pathlib.Path(__file__).resolve().parents[2]
EX = ROOT / "examples"


def build():
    b = Bridge(ROOT / "registry", ROOT / "security", ROOT / "network")
    res = b.all()
    files = {}
    for inst in ("abc-prd", "xyz-prd", "abc-nonprd"):
        files[f"terraform/tenant-{inst}.auto.tfvars.json"] = json.dumps(res[("tenant", inst)], indent=2, default=list) + "\n"
    rel = H.Releases(ROOT / "registry", ROOT / "security", ROOT / "network").generate()
    for (cell, ns, product), v in sorted(rel.items()):
        if ns.endswith(("-prd", "-dev")):
            files[f"helm/{ns}.values.json"] = json.dumps(v, indent=2) + "\n"
    v = rel[("gke-prd-as1-01", "abc-payroll-prd", "payroll")]
    files["helm/abc-payroll-prd.rendered.yaml"] = H.render("payroll", "abc-payroll-prd", H.merged_values("payroll", "prd", v))[0]
    return files


def main():
    for rel, text in build().items():
        p = EX / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(f"examples refreshed in {EX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
