"""Run every generator and checker of Stages 1-8 in dependency order (one command for reviewers and CI).

Usage:  python3 -m tools.check_all          exit code 0 only if every step reports 0 findings
"""
import subprocess
import sys

STEPS = [
    ("D1 registry", ["tools.registry.validate", "registry"]),
    ("D2 identity plan", ["tools.identity.derive", "registry", "-o", "build/identity-plan.json"]),
    ("D3 access matrix", ["tools.access.matrix"]),
    ("D4 MySQL grants", ["tools.db.grants", "build/identity-plan.json", "-o", "build/sql"]),
    ("D4 isolation cases", ["tools.db.isotest", "build/identity-plan.json"]),
    ("D5 org policies", ["tools.policy.orgpolicy"]),
    ("D6 CI/CD federation", ["tools.cicd.federation"]),
    ("D7 privileged access", ["tools.access.privileged"]),
    ("D8 Kubernetes baseline", ["tools.k8s.baseline", "registry"]),
    ("D9 data protection", ["tools.security.dataprotection"]),
    ("D10 audit and alerts", ["tools.monitoring.audit"]),
    ("N1 IP address plan", ["tools.network.ipam"]),
    ("N2 VPC / Shared VPC", ["tools.network.vpc"]),
    ("N3 firewall", ["tools.network.firewall"]),
    ("N4 DNS / ingress / NAT", ["tools.network.edge"]),
    ("N5 network quotas", ["tools.network.quotas"]),
    ("S5 tfvars (bridge)", ["tools.iac.tfvars"]),
    ("S5 Terraform static", ["tools.iac.hclcheck"]),
    ("S5 stack catalogue", ["tools.iac.stacks"]),
    ("S6 Helm values + render", ["tools.iac.helmvalues"]),
    ("S7 pipeline planner", ["tools.cicd.planner", "check"]),
    ("S7 workflows", ["tools.cicd.workflows"]),
    ("S8 cost estimate", ["tools.cost.model"]),
    ("S8 capacity", ["tools.cost.capacity"]),
    ("S8 SLOs + monitoring", ["tools.slo.observability"]),
    ("S8 backup + DR", ["tools.slo.dr"]),
]


def main():
    failed = []
    for name, args in STEPS:
        r = subprocess.run([sys.executable, "-m", *args], capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        print(f"{'OK  ' if r.returncode == 0 else 'FAIL'} {name:24} {last}")
        if r.returncode != 0:
            failed.append(name)
            print(r.stdout + r.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
