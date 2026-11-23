"""D6 – check CI/CD identities and Workload Identity Federation (security/cicd-identities.yaml).

Usage:  python3 -m tools.cicd.federation [--registry registry] [--security security] [-o build/wif-bindings.json]

Rules
  CI01 every pipeline SA of the access matrix (persona automated-deployment-pipelines) has exactly one entry, and back
  CI02 every enabled provider pins the organisation / workspace in attribute_condition and maps attribute.gate
  CI03 allow entries use known, federating repositories and known environment / ref classes
  CI04 tier discipline: each identity only from its tier's environments (prd|plan-prd, nonprd|plan-nonprd,
       org|plan-org, build: none); write-capable identities only from the reviewed environment on main; the build
       identity only from main or release tags; read-only identities never from the reviewed prd/org environments
  CI05 no gate value maps to identities of two different tiers
  CI06 runner machine identities hold no grant in the access matrix and are not pipeline identities
  CI07 environments used by prd/org identities need >= 2 reviewers, no self-review and main only; the prd runner group
       accepts only the central reusable workflows
  CI08 every registry product has exactly one application repository
  CI09 attached identities are started by a WIF identity of the same tier holding run.invoker on the job's project
Status: implemented + locally tested; nothing applied (T-W1..T-W5).
"""
import argparse
import json
import pathlib
import re
import sys

from tools.access.matrix import Matrix
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

ENVS = {"none", "nonprd", "prd", "org", "plan-nonprd", "plan-prd", "plan-org"}
TIER_ENVS = {"prd": {"prd", "plan-prd"}, "nonprd": {"nonprd", "plan-nonprd"}, "org": {"org", "plan-org"},
             "shared": {"none"}}
REFS = {"main", "release-tag", "other"}
WRITE_CLASSES = {"write", "admin"}
POOL_MEMBER = ("principalSet://iam.googleapis.com/projects/${BOOTSTRAP_PROJECT_NUMBER}/locations/global/"
               "workloadIdentityPools/{pool}/attribute.gate/{gate}")


class Federation:
    def __init__(self, registry_root="registry", security_root="security"):
        self.path = str(pathlib.Path(security_root) / "cicd-identities.yaml")
        self.doc = load_yaml(self.path)
        self.matrix = Matrix(registry_root, security_root)
        self.binds = self.matrix.bindings()
        self.products = sorted(self.matrix.reg.products)

    # ---------- helpers ----------
    def repos_of(self, entry):
        out = []
        for r in entry["repos"]:
            if r == "@product":
                out += [n for n, m in self.doc["repositories"].items() if m.get("kind") == "product"]
            else:
                out.append(r)
        return out

    def write_capable(self, sa_tpl):
        return any(b["principal_template"] == sa_tpl and b["role_class"] in WRITE_CLASSES for b in self.binds)

    def gates(self, sa_tpl):
        spec = self.doc["pipeline_identities"][sa_tpl]
        for a in spec.get("allow", []):
            for r in self.repos_of(a):
                yield r, a["environment"], a["ref"]

    def expand_sa(self, sa_tpl):
        return [names[0] for _, names in self.matrix._expand(sa_tpl)]

    # ---------- rules ----------
    def check(self):
        f, P, d = [], self.path, self.doc
        ids = d["pipeline_identities"]
        persona = set(self.matrix.matrix["personas"]["automated-deployment-pipelines"]["principals"])
        for sa in sorted(persona - set(ids)):
            f.append(Finding("CI01", P, f"{sa}: pipeline identity without an authentication entry"))
        for sa in sorted(set(ids) - persona):
            f.append(Finding("CI01", P, f"{sa}: not a pipeline identity in the access matrix"))

        for name, prov in d["federation"]["providers"].items():
            if not prov.get("enabled"):
                continue
            cond = prov.get("attribute_condition", "")
            if not re.search(r"(repository_owner_id|workspaceUuid)\s*==\s*'\$\{\w+\}'", cond):
                f.append(Finding("CI02", P, f"provider {name}: attribute_condition must pin the organisation by id"))
            if "attribute.gate" not in prov.get("attribute_mapping", {}):
                f.append(Finding("CI02", P, f"provider {name}: attribute.gate mapping missing"))

        repos = d["repositories"]
        gate_tiers = {}
        for sa, spec in ids.items():
            tier = spec["tier"]
            if spec["auth"] == "attached":
                continue
            if spec["auth"] != "wif":
                f.append(Finding("CI03", P, f"{sa}: unknown auth '{spec['auth']}'"))
                continue
            wc = self.write_capable(sa)
            for repo, env, ref in self.gates(sa):
                if repo not in repos or repos[repo].get("federates") is False:
                    f.append(Finding("CI03", P, f"{sa}: repository {repo} unknown or not allowed to federate"))
                if env not in ENVS or ref not in REFS:
                    f.append(Finding("CI03", P, f"{sa}: unknown environment/ref {env}/{ref}"))
                if tier in ("prd", "org") and wc and (env != tier or ref != "main"):
                    f.append(Finding("CI04", P, f"{sa}: write-capable {tier} identity reachable from {repo}:{env}:{ref}"))
                if env not in TIER_ENVS.get(tier, set()):
                    f.append(Finding("CI04", P, f"{sa}: {tier} identity reachable from environment {env}"))
                if tier == "nonprd" and wc and (env != "nonprd" or ref != "main"):
                    f.append(Finding("CI04", P, f"{sa}: write-capable non-prod identity reachable from {repo}:{env}:{ref}"))
                if tier == "shared" and ref not in ("main", "release-tag"):
                    f.append(Finding("CI04", P, f"{sa}: build identity reachable from {repo}:{env}:{ref}"))
                if not wc and env in ("prd", "org"):
                    f.append(Finding("CI04", P, f"{sa}: read-only identity should not use environment {env}"))
                gate_tiers.setdefault(f"{repo}:{env}:{ref}", set()).add(tier)
        for gate, tiers in sorted(gate_tiers.items()):
            if len(tiers & {"prd", "nonprd", "org"}) > 1:
                f.append(Finding("CI05", P, f"gate {gate} reaches identities of tiers {sorted(tiers)}"))

        for r in d["runner_identities"]:
            if any(b["principal"] == r or b["principal_template"] == r for b in self.binds):
                f.append(Finding("CI06", P, f"runner identity {r} holds a grant in the access matrix"))
            if r in ids:
                f.append(Finding("CI06", P, f"runner identity {r} must not be a pipeline identity"))
        groups_runner = {g["runner_sa"] for g in d["github"]["runner_groups"].values()}
        if groups_runner != set(d["runner_identities"]):
            f.append(Finding("CI06", P, "runner groups and runner_identities differ"))

        envs = d["github"]["environments"]
        for sa, spec in ids.items():
            if spec["auth"] != "wif":
                continue
            for _, env, _ in self.gates(sa):
                if env in ("prd", "org"):
                    e = envs.get(env, {})
                    if e.get("required_reviewers", 0) < 2 or not e.get("prevent_self_review") or e.get("branches") != ["main"]:
                        f.append(Finding("CI07", P, f"environment {env} (used by {sa}) needs >=2 reviewers, no self-review, main only"))
                elif env != "none" and env not in envs:
                    f.append(Finding("CI07", P, f"environment {env} (used by {sa}) is not defined"))
        if not d["github"]["runner_groups"].get("prd", {}).get("workflows_only_from"):
            f.append(Finding("CI07", P, "prd runner group must accept only the central reusable workflows"))

        prod_repos = {}
        for n, m in repos.items():
            if m.get("kind") == "product":
                if m.get("product") not in self.products:
                    f.append(Finding("CI08", P, f"repository {n}: unknown product {m.get('product')}"))
                prod_repos.setdefault(m.get("product"), []).append(n)
        for p in self.products:
            if len(prod_repos.get(p, [])) != 1:
                f.append(Finding("CI08", P, f"product {p} needs exactly one application repository"))

        for sa, spec in ids.items():
            if spec["auth"] != "attached":
                continue
            starter = spec.get("started_by")
            sspec = ids.get(starter)
            if not sspec or sspec["auth"] != "wif" or sspec["tier"] != spec["tier"]:
                f.append(Finding("CI09", P, f"{sa}: started_by must be a WIF identity of tier {spec['tier']}"))
                continue
            job_project = spec["runs_as"].split(" in ")[-1]
            if not any(b["principal_template"] == starter and b["role"] == "roles/run.invoker"
                       and b["scope_template"] == f"project:{job_project}" for b in self.binds):
                f.append(Finding("CI09", P, f"{starter} lacks roles/run.invoker on {job_project} to start {sa}"))
        return f

    # ---------- output ----------
    def wif_bindings(self):
        """Terraform input: roles/iam.workloadIdentityUser on each pipeline SA for its gate principalSets."""
        pool, repos, out = self.doc["federation"]["pool"]["id"], self.doc["repositories"], []
        for sa_tpl, spec in self.doc["pipeline_identities"].items():
            if spec["auth"] != "wif":
                continue
            members = sorted({POOL_MEMBER.replace("{pool}", pool).replace("{gate}", f"{repos[r]['id']}:{e}:{ref}")
                              for r, e, ref in self.gates(sa_tpl)})
            for sa in self.expand_sa(sa_tpl):
                acct, project = sa[3:].split("@")
                out.append({"service_account": f"{acct}@{project}.iam.gserviceaccount.com",
                            "role": "roles/iam.workloadIdentityUser", "members": members, "tier": spec["tier"]})
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/wif-bindings.json")
    a = ap.parse_args(argv)
    fed = Federation(a.registry, a.security)
    findings = fed.check()
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    binds = fed.wif_bindings()
    pathlib.Path(a.out).write_text(json.dumps(binds, indent=2) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(fed.doc['pipeline_identities'])} pipeline identities, {len(binds)} WIF bindings, "
          f"{len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
