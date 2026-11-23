"""Stage 6 bridge: registry + Terraform outputs -> generated values of every Helm release (GKE subscriptions).

Usage:  python3 -m tools.iac.helmvalues [-o build/helm]
        writes build/helm/<cell>/<namespace>/<product>.values.json (contract: interfaces/helm-release.schema.json)

Locally the Terraform outputs are derived from the same plans Terraform consumes (deterministic names:
instance connection name = <pool project>:<region>:<pool>, secret id = projects/<project>/secrets/<id>, ...).
In the pipeline `terraform output -json` of the named stacks provides them; tests check those outputs exist.
The image digest is resolved by the pipeline from the registry version (tag -> digest in the release repository);
locally a deterministic placeholder digest is used.
Also provides render(): merged values -> manifests through tools/helmrender (Go text/template).
Status: implemented + locally tested.
"""
import argparse
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

import yaml

from tools.identity.derive import derive
from tools.network.edge import Edge
from tools.security.dataprotection import DataProtection

ROOT = pathlib.Path(__file__).resolve().parents[2]
HELM = ROOT / "helm"
REGION = "asia-south1"
RELEASE_REPO = f"{REGION}-docker.pkg.dev/shr-artifacts/release"


def placeholder_digest(product, version):
    return "sha256:" + hashlib.sha256(f"{product}:{version}".encode()).hexdigest()


def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


class Releases:
    def __init__(self, registry="registry", security="security", network="network"):
        self.edge = Edge(registry, network, security)
        self.reg = self.edge.reg
        self.plan = self.edge.net.plan
        self.dp = DataProtection(registry, security).generate()
        self.pools = {(s["pool"]): s for s in self.edge.net.out["cloud_sql"]}

    def version_of(self, tenant, product, env):
        sub = self.reg.tenants[tenant][1]["subscriptions"][product]
        pdef = self.reg.products[product][1]
        if "versions" in sub:
            return sub["versions"][env]
        if "cohort" in sub:
            return pdef["cohorts"][sub["cohort"][env]]
        return pdef["version"]

    def generate(self):
        out = {}
        for ns in self.plan["kubernetes_namespaces"].values():
            lab = ns["labels"]
            tenant, product, env = lab["tenant"], lab["product"], lab["env"]
            wi = [w for w in self.plan["workload_identity_bindings"].values()
                  if w["namespace"] == ns["namespace"] and w["cluster"] == ns["cluster"]]
            ksa = {w["ksa"]: w for w in wi}
            sa_app = next(w["service_account_email"] for w in wi if not w["ksa"].endswith("-migrate"))
            sa_mig = next(w["service_account_email"] for w in wi if w["ksa"].endswith("-migrate"))
            users = {u["sa_email"]: u for u in self.plan["cloud_sql_iam_users"].values()}
            u_app = users[sa_app]
            gw = next(g for name, g in self.edge.out["gateways"].items()
                      if g["cluster"] == ns["cluster"] and g["product"] == product and g["env"] == env)
            gw_name = next(name for name, g in self.edge.out["gateways"].items() if g is gw)
            hosts = sorted(r["hostname"] for r in self.edge.out["records"]
                           if r["frontend"] == gw_name and (tenant == "multi" or r["tenant"] == tenant))
            project = sa_app.split("@")[1].split(".")[0]
            secrets = {s["secret_id"].split(f"{product}-{env}-", 1)[1]: f"projects/{s['project']}/secrets/{s['secret_id']}"
                       for s in self.dp["secrets"] if s["project"] == project and s["product"] == product and s["env"] == env}
            buckets = {b["bucket"].split(f"-{env}-", 1)[1]: b["bucket"] for b in self.dp["buckets"]
                       if b["project"] == project and b["bucket"].startswith(f"{tenant}-{product}-{env}-")}
            version = self.version_of(tenant, product, env) if tenant != "multi" else self.reg.products[product][1].get("version")
            sub = self.reg.tenants[tenant][1]["subscriptions"][product] if tenant != "multi" else {}
            pool = self.pools[u_app["pool"]]
            values = {
                "tenant": tenant, "product": product, "env": env,
                "image": {"repository": f"{RELEASE_REPO}/{product}", "digest": placeholder_digest(product, version),
                          "version": str(version)},
                "serviceAccount": {"name": next(k for k in ksa if not k.endswith("-migrate")),
                                   "migrationName": next(k for k in ksa if k.endswith("-migrate"))},
                "route": {"gateway": {"name": gw_name, "namespace": gw["namespace"]}, "hostnames": hosts},
                "database": {"enabled": True, "instanceConnectionName": f"{pool['project']}:{REGION}:{pool['pool']}",
                             "name": u_app["databases"][0], "user": u_app["user"], "migrationUser": users[sa_mig]["user"]},
                "secrets": secrets, "buckets": buckets,
                "config": sub.get("config", {}) or {},
                "isolation": {"dedicatedNodes": lab.get("isolation_tier") in ("enhanced", "dedicated")},
            }
            out[(ns["cluster"], ns["namespace"], product)] = values
        return out


def merged_values(product, env, generated):
    base = yaml.safe_load((HELM / "charts" / product / "values.yaml").read_text())
    env_vals = yaml.safe_load((HELM / "environments" / f"{env}.yaml").read_text())
    v = deep_merge(deep_merge(base, env_vals), generated)
    v["cloudSqlProxy"]["image"]["digest"] = v["cloudSqlProxy"]["image"]["digest"] or placeholder_digest("cloud-sql-proxy", "2")
    return v


def renderer():
    exe = ROOT / "build" / "helmrender"
    if not exe.exists():
        exe.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["go", "build", "-o", str(exe), "."], cwd=ROOT / "tools" / "helmrender", check=True)
    return exe


def render(product, namespace, values):
    """Render a product chart (with platform-lib) through Go text/template; returns parsed manifests."""
    chart = yaml.safe_load((HELM / "charts" / product / "Chart.yaml").read_text())
    files = sorted(str(p) for p in (HELM / "charts" / "platform-lib" / "templates").glob("*.tpl")) + \
        sorted(str(p) for p in (HELM / "charts" / product / "templates").glob("*.yaml"))
    ctx = {"Values": values, "Release": {"Name": product, "Namespace": namespace},
           "Chart": {"Name": chart["name"], "Version": chart["version"]}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(ctx, fh)
    r = subprocess.run([str(renderer()), fh.name, *files], capture_output=True, text=True)
    pathlib.Path(fh.name).unlink()
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout, [d for d in yaml.safe_load_all(r.stdout) if d]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="build/helm")
    a = ap.parse_args(argv)
    rel = Releases().generate()
    for (cell, ns, product), v in rel.items():
        d = pathlib.Path(a.out) / cell / ns
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{product}.values.json").write_text(json.dumps(v, indent=2) + "\n")
        text, _ = render(product, ns, merged_values(product, v["env"], v))
        (d / f"{product}.rendered.yaml").write_text(text)
    print(f"{len(rel)} releases -> {a.out}/ (values + rendered manifests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
