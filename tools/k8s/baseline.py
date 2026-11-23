"""D8 – render the Kubernetes namespace security baseline from the identity plan, access matrix and registry.

Usage:  python3 -m tools.k8s.baseline [registry] [-o build/k8s]

Writes, per GKE cell:
  build/k8s/<cell>/<namespace>.yaml   Namespace, ServiceAccounts, RoleBindings, NetworkPolicies, ResourceQuota, LimitRange
  build/k8s/<cell>/_cluster.yaml      platform-tenant-edit ClusterRole + policy Constraints with registry-derived parameters
The objects are created by the namespace module BEFORE any workload (Stage 2 §6, review A3).
ConstraintTemplates (Rego) live in policies/k8s/templates/ and are shared by all cells.
Status: implemented + locally tested (structure and rules in Python). Not applied to a cluster; Rego not executed
        (opa / gator not installed here) – T-K1, T-K19, T-K20.
"""
import argparse
import fnmatch
import pathlib
import sys

import yaml

from tools.access.matrix import Matrix
from tools.identity.derive import derive
from tools.registry.loader import load_yaml
from tools.registry.validate import validate

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", v, style="|" if "\n" in v else None))
NS_LABELS = ("tenant", "product", "env", "env_tier", "deployment_model")


def hostnames(tenant, product, env, domain="example.com"):
    """Stage 2 hostname convention (§0): prod <t>.<p>.<domain>; non-prod <t>-<env>.<p>.nonprod.<domain>."""
    return [f"{tenant}.{product}.{domain}"] if env == "prd" else [f"{tenant}-{env}.{product}.nonprod.{domain}"]


def _meta(name, ns=None, labels=None, annotations=None):
    m = {"name": name}
    if ns:
        m["namespace"] = ns
    if labels:
        m["labels"] = labels
    if annotations:
        m["annotations"] = annotations
    return m


def _np(name, ns, spec, cfg):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": _meta(name, ns, {f"{cfg['label_prefix']}/baseline": "true"}), "spec": spec}


def network_policies(ns, tier, cfg):
    n = cfg["network"]
    sql = n["cloud_sql"][tier]
    ip = lambda cidr, port: {"to": [{"ipBlock": {"cidr": cidr}}], "ports": [{"protocol": "TCP", "port": port}]}
    return [
        _np("default-deny-all", ns, {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}, cfg),
        _np("allow-same-namespace", ns, {"podSelector": {}, "policyTypes": ["Ingress", "Egress"],
                                         "ingress": [{"from": [{"podSelector": {}}]}],
                                         "egress": [{"to": [{"podSelector": {}}]}]}, cfg),
        _np("allow-dns", ns, {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{
            "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": n["dns"]["namespace"]}},
                    "podSelector": {"matchLabels": n["dns"]["pod_label"]}}],
            "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}]}, cfg),
        _np("allow-gke-metadata", ns, {"podSelector": {}, "policyTypes": ["Egress"],
                                       "egress": [ip(m["cidr"], m["port"]) for m in n["metadata"]]}, cfg),
        _np("allow-google-apis-and-cloudsql", ns, {"podSelector": {}, "policyTypes": ["Egress"], "egress": [
            ip(n["google_apis"]["cidr"], n["google_apis"]["port"]), ip(sql["cidr"], sql["port"])]}, cfg),
        _np("allow-from-load-balancer", ns, {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{
            "from": [{"ipBlock": {"cidr": c}} for c in n["load_balancer_sources"]],
            "ports": [{"protocol": "TCP", "port": n["app_port_name"]}]}]}, cfg),
    ]


def rbac_subject(principal, cfg):
    if principal.startswith("sa:"):
        acct, project = principal[3:].split("@")
        return {"kind": "User", "name": f"{acct}@{project}.iam.gserviceaccount.com"}
    return {"kind": "Group", "name": f"{principal}@{cfg['group_domain']}", "apiGroup": "rbac.authorization.k8s.io"}


def role_bindings(cell, ns, k8s_binds, cfg):
    """RoleBindings (never ClusterRoleBindings) for every access-matrix k8s grant whose glob matches this namespace."""
    per_role = {}
    for b in k8s_binds:
        cglob, nglob = b["scope"][len("k8s:"):].split("/", 1)
        if fnmatch.fnmatch(cell, cglob) and fnmatch.fnmatch(ns, nglob):
            per_role.setdefault(b["role"], set()).add(b["principal"])
    out = []
    for role, principals in sorted(per_role.items()):
        cr = cfg["rbac_roles"][role]
        out.append({"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
                    "metadata": _meta(f"platform-{role.split('/')[1]}", ns, {f"{cfg['label_prefix']}/baseline": "true"}),
                    "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": cr},
                    "subjects": [rbac_subject(p, cfg) for p in sorted(principals)]})
    return out


PRIVATE = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


def egress_policy(ns, dests, cfg):
    """Stage 4: internet egress for products with an allow-list (network/egress.yaml). The NetworkPolicy opens only
    the declared ports to public addresses; the FQDN restriction is enforced by the tier firewall policy (N3)."""
    return _np("allow-internet-egress", ns, {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{
        "to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": PRIVATE}}],
        "ports": [{"protocol": "TCP", "port": p} for p in sorted({d["port"] for d in dests})]}]}, cfg)


def load_egress(path=None):
    path = pathlib.Path(path or ROOT / "network" / "egress.yaml")
    return load_yaml(path)["products"] if path.exists() else {}


def namespace_objects(entry, wi_bindings, k8s_binds, cfg, egress=None):
    ns, cell, labels = entry["namespace"], entry["cluster"], dict(entry["labels"])
    tier, env = labels["env_tier"], labels["env"]
    lp = cfg["label_prefix"]
    psa = cfg["pod_security"]
    ns_labels = {**labels, f"{lp}/managed": "true",
                 "pod-security.kubernetes.io/enforce": psa, "pod-security.kubernetes.io/enforce-version": "latest",
                 "pod-security.kubernetes.io/warn": psa, "pod-security.kubernetes.io/audit": psa}
    objs = [{"apiVersion": "v1", "kind": "Namespace", "metadata": _meta(ns, labels=ns_labels)}]
    objs.append({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta("default", ns),
                 "automountServiceAccountToken": False})
    for w in sorted(wi_bindings, key=lambda w: w["ksa"]):
        objs.append({"apiVersion": "v1", "kind": "ServiceAccount",
                     "metadata": _meta(w["ksa"], ns, {f"{lp}/baseline": "true"},
                                       {"iam.gke.io/gcp-service-account": w["service_account_email"]})})
    objs += role_bindings(cell, ns, k8s_binds, cfg)
    objs += network_policies(ns, tier, cfg)
    if (egress or {}).get(labels["product"]):
        objs.append(egress_policy(ns, egress[labels["product"]], cfg))
    objs.append({"apiVersion": "v1", "kind": "ResourceQuota",
                 "metadata": _meta("platform-quota", ns, {f"{lp}/baseline": "true"}),
                 "spec": {"hard": {**cfg["quota"][env], **cfg["quota_always"]}}})
    lr = cfg["limit_range"]
    objs.append({"apiVersion": "v1", "kind": "LimitRange",
                 "metadata": _meta("platform-limits", ns, {f"{lp}/baseline": "true"}),
                 "spec": {"limits": [{"type": "Container", "defaultRequest": lr["default_request"],
                                      "default": lr["default_limit"], "max": lr["max"]}]}})
    return objs


def tenant_edit_clusterrole():
    """`k8s/edit`: deploy and operate workloads; cannot touch NetworkPolicy, quota, limits, RBAC or ServiceAccounts."""
    rw = ["get", "list", "watch", "create", "update", "patch", "delete"]
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
            "metadata": {"name": "platform-tenant-edit"},
            "rules": [
                {"apiGroups": [""], "resources": ["pods", "services", "configmaps", "secrets",
                                                  "persistentvolumeclaims"], "verbs": rw},
                {"apiGroups": [""], "resources": ["pods/log", "events", "serviceaccounts", "resourcequotas",
                                                  "limitranges"], "verbs": ["get", "list", "watch"]},
                {"apiGroups": ["apps"], "resources": ["deployments", "statefulsets", "replicasets"], "verbs": rw},
                {"apiGroups": ["batch"], "resources": ["jobs", "cronjobs"], "verbs": rw},
                {"apiGroups": ["autoscaling"], "resources": ["horizontalpodautoscalers"], "verbs": rw},
                {"apiGroups": ["policy"], "resources": ["poddisruptionbudgets"], "verbs": rw},
                {"apiGroups": ["gateway.networking.k8s.io"], "resources": ["httproutes"], "verbs": rw},
                {"apiGroups": ["networking.k8s.io"], "resources": ["networkpolicies"], "verbs": ["get", "list", "watch"]},
            ]}


def constraints(namespaces, served, cfg, env_of_cell):
    """Constraint objects (instances of the templates in policies/k8s/templates) with registry-derived parameters."""
    lp = cfg["label_prefix"]
    managed = {"namespaceSelector": {"matchLabels": {f"{lp}/managed": "true"}}}
    shared_hosts = {}
    for e in namespaces:
        lab = e["labels"]
        if lab["tenant"] == "multi":
            shared_hosts[e["namespace"]] = sorted(h for t in served.get(e["namespace"], [])
                                                  for h in hostnames(t, lab["product"], lab["env"], cfg["domain"]))
    envs = sorted(set(env_of_cell.values()))
    repos = [cfg["registry"]["release"]] + ([cfg["registry"]["snapshot"]] if envs == ["dev"] else [])
    return [
        {"apiVersion": "constraints.gatekeeper.sh/v1beta1", "kind": "PlatformNamespaceBaseline",
         "metadata": {"name": "tenant-namespace-baseline"},
         "spec": {"enforcementAction": "deny",
                  "match": {"kinds": [{"apiGroups": [""], "kinds": ["Namespace"]}],
                            "labelSelector": {"matchLabels": {f"{lp}/managed": "true"}}},
                  "parameters": {"requiredLabels": list(NS_LABELS), "podSecurity": cfg["pod_security"]}}},
        {"apiVersion": "constraints.gatekeeper.sh/v1beta1", "kind": "PlatformHttpRouteHostnames",
         "metadata": {"name": "httproute-hostname-matches-tenant"},
         "spec": {"enforcementAction": "deny",
                  "match": {"kinds": [{"apiGroups": ["gateway.networking.k8s.io"], "kinds": ["HTTPRoute"]}], **managed},
                  "parameters": {"domain": cfg["domain"], "sharedNamespaceHostnames": shared_hosts}}},
        {"apiVersion": "constraints.gatekeeper.sh/v1beta1", "kind": "PlatformAllowedImages",
         "metadata": {"name": "images-from-platform-registry"},
         "spec": {"enforcementAction": "deny",
                  "match": {"kinds": [{"apiGroups": [""], "kinds": ["Pod"]}], **managed},
                  "parameters": {"releaseRepo": cfg["registry"]["release"] + "/",
                                 "allowedRepos": [r + "/" for r in repos],
                                 "requireDigest": envs != ["dev"]}}},
        {"apiVersion": "constraints.gatekeeper.sh/v1beta1", "kind": "PlatformTenantSeparation",
         "metadata": {"name": "tenant-node-separation"},
         "spec": {"enforcementAction": "deny",
                  "match": {"kinds": [{"apiGroups": [""], "kinds": ["Pod"]}], **managed},
                  "parameters": {"key": cfg["separation_key"], "separationTiers": cfg["separation_tiers"]}}},
    ]


TEMPLATE_KINDS = {
    "platformnamespacebaseline": ("PlatformNamespaceBaseline", {
        "requiredLabels": {"type": "array", "items": {"type": "string"}}, "podSecurity": {"type": "string"}}),
    "platformhttproutehostnames": ("PlatformHttpRouteHostnames", {
        "domain": {"type": "string"},
        "sharedNamespaceHostnames": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}}}),
    "platformallowedimages": ("PlatformAllowedImages", {
        "releaseRepo": {"type": "string"}, "allowedRepos": {"type": "array", "items": {"type": "string"}},
        "requireDigest": {"type": "boolean"}}),
    "platformtenantseparation": ("PlatformTenantSeparation", {
        "key": {"type": "string"}, "separationTiers": {"type": "array", "items": {"type": "string"}}}),
}


def constraint_templates(src=ROOT / "policies" / "k8s" / "src"):
    """Gatekeeper / Policy Controller ConstraintTemplates; Rego is embedded from policies/k8s/src/<name>.rego."""
    out = []
    for name, (kind, props) in TEMPLATE_KINDS.items():
        out.append({"apiVersion": "templates.gatekeeper.sh/v1", "kind": "ConstraintTemplate",
                    "metadata": {"name": name},
                    "spec": {"crd": {"spec": {"names": {"kind": kind},
                                              "validation": {"openAPIV3Schema": {"type": "object", "properties": props}}}},
                             "targets": [{"target": "admission.k8s.gatekeeper.sh",
                                          "rego": (pathlib.Path(src) / f"{name}.rego").read_text()}]}})
    return out


def render(registry_root="registry", security_root="security", cfg_path=None, egress_path=None):
    egress = load_egress(egress_path)
    reg, findings = validate(registry_root)
    if findings:
        raise ValueError("registry invalid")
    cfg = load_yaml(cfg_path or pathlib.Path(security_root) / "k8s-baseline.yaml")
    plan = derive(reg)
    k8s_binds = [b for b in Matrix(registry_root, security_root).bindings() if b["scope"].startswith("k8s:")]
    served = {}
    for sa in plan["service_accounts"].values():
        if sa["tenant_scope"] == "multi" and sa["runtime"] == "gke" and sa["purpose"] == "app":
            ns = next(w["namespace"] for w in plan["workload_identity_bindings"].values()
                      if w["service_account_email"] == sa["email"])
            served[ns] = sa["served_tenants"]
    cells = {}
    for e in plan["kubernetes_namespaces"].values():
        wi = [w for w in plan["workload_identity_bindings"].values()
              if w["cluster"] == e["cluster"] and w["namespace"] == e["namespace"]]
        cells.setdefault(e["cluster"], {})[e["namespace"]] = namespace_objects(e, wi, k8s_binds, cfg, egress)
    env_of_cell = {c: v["env"] for c, v in reg.inventory["gke_cells"].items()}
    cluster = {}
    for cell in reg.inventory["gke_cells"]:
        nss = [e for e in plan["kubernetes_namespaces"].values() if e["cluster"] == cell]
        cluster[cell] = [tenant_edit_clusterrole()] + constraints(nss, served, cfg, {cell: env_of_cell[cell]})
    return cells, cluster


def check(cells, cluster, cfg):
    """Baseline invariants (KB01-KB06), evaluated on the rendered objects."""
    errs = []
    for cell, nss in cells.items():
        for ns, objs in nss.items():
            kinds = {}
            for o in objs:
                kinds.setdefault(o["kind"], []).append(o)
            nsobj = kinds["Namespace"][0]["metadata"]["labels"]
            if nsobj.get("pod-security.kubernetes.io/enforce") != cfg["pod_security"]:
                errs.append(f"KB01 {cell}/{ns}: Pod Security '{cfg['pod_security']}' not enforced")
            if not any(p["metadata"]["name"] == "default-deny-all"
                       and p["spec"]["podSelector"] == {} and set(p["spec"]["policyTypes"]) == {"Ingress", "Egress"}
                       for p in kinds.get("NetworkPolicy", [])):
                errs.append(f"KB02 {cell}/{ns}: no default-deny NetworkPolicy")
            for p in kinds.get("NetworkPolicy", []):
                for rule in p["spec"].get("ingress", []) + p["spec"].get("egress", []):
                    for peer in rule.get("from", []) + rule.get("to", []):
                        if "namespaceSelector" in peer and peer["namespaceSelector"].get("matchLabels", {}) \
                                .get("kubernetes.io/metadata.name") != cfg["network"]["dns"]["namespace"]:
                            errs.append(f"KB03 {cell}/{ns}: {p['metadata']['name']} opens traffic to other namespaces")
                        if peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0" and not (
                                p["metadata"]["name"] == "allow-internet-egress"
                                and sorted(peer["ipBlock"].get("except", [])) == sorted(PRIVATE)
                                and rule.get("ports")):
                            errs.append(f"KB03 {cell}/{ns}: {p['metadata']['name']} allows 0.0.0.0/0")
            hard = (kinds.get("ResourceQuota") or [{"spec": {"hard": {}}}])[0]["spec"]["hard"]
            if hard.get("services.loadbalancers") != "0" or hard.get("services.nodeports") != "0" or "pods" not in hard:
                errs.append(f"KB04 {cell}/{ns}: quota missing or allows LoadBalancer/NodePort services")
            if "LimitRange" not in kinds:
                errs.append(f"KB04 {cell}/{ns}: no LimitRange")
            for rb in kinds.get("RoleBinding", []):
                if rb["roleRef"]["name"] in ("edit", "admin", "cluster-admin"):
                    errs.append(f"KB05 {cell}/{ns}: binds built-in {rb['roleRef']['name']}")
            sa_default = [s for s in kinds["ServiceAccount"] if s["metadata"]["name"] == "default"]
            if not sa_default or sa_default[0].get("automountServiceAccountToken") is not False:
                errs.append(f"KB06 {cell}/{ns}: default ServiceAccount token automount not disabled")
    for cell, objs in cluster.items():
        cr = next(o for o in objs if o["kind"] == "ClusterRole")
        for r in cr["rules"]:
            writes = set(r["verbs"]) & {"create", "update", "patch", "delete", "*"}
            if writes and set(r["resources"]) & {"networkpolicies", "resourcequotas", "limitranges", "roles",
                                                 "rolebindings", "serviceaccounts", "namespaces", "*"}:
                errs.append(f"KB05 {cell}: platform-tenant-edit can modify {sorted(r['resources'])}")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("registry", nargs="?", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/k8s")
    a = ap.parse_args(argv)
    cfg = load_yaml(pathlib.Path(a.security) / "k8s-baseline.yaml")
    cells, cluster = render(a.registry, a.security)
    out = pathlib.Path(a.out)
    for cell, nss in cells.items():
        for ns, objs in nss.items():
            (out / cell).mkdir(parents=True, exist_ok=True)
            (out / cell / f"{ns}.yaml").write_text(yaml.safe_dump_all(objs, sort_keys=False))
    for cell, objs in cluster.items():
        (out / cell).mkdir(parents=True, exist_ok=True)
        (out / cell / "_cluster.yaml").write_text(yaml.safe_dump_all(objs, sort_keys=False))
    tpl = ROOT / "policies" / "k8s" / "constraint-templates.yaml"
    tpl.write_text("# Generated by tools/k8s/baseline.py from policies/k8s/src/*.rego – do not edit.\n"
                   + yaml.dump_all(constraint_templates(), Dumper=_Dumper, sort_keys=False))
    errs = check(cells, cluster, cfg)
    for e in errs:
        print(e, file=sys.stderr)
    n = sum(len(v) for v in cells.values())
    print(f"{n} namespaces in {len(cells)} cells, {sum(len(o) for v in cells.values() for o in v.values())} objects; "
          f"{len(errs)} baseline finding(s) -> {out}/")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
