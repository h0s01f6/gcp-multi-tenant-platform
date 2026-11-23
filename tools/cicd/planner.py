"""Stage 7 – pipeline planner: which stack instances to plan/apply and which releases to deploy for a change,
in which order, plus the promotion gate. Used by the PR and apply workflows (cicd/) and by check_all.

Usage:
  python3 -m tools.cicd.planner diff --base <dir> --head <dir> [--changed FILE ...] [-o build/cicd/plan.json]
         <dir> is a checkout root holding registry/ (base = merge base of the PR, head = the PR / main)
  python3 -m tools.cicd.planner onboard <tenant> [--root .]     ordered onboarding jobs of one customer
  python3 -m tools.cicd.planner all --tier <org|nonprd|prd>     every stack instance of a tier (drift workflow)
  python3 -m tools.cicd.planner check [--root .]                self-check used by tools.check_all

Output (consumed by the workflows with fromJSON):
  run    {"<job>": bool}   job = <stack>-<tier> | org | db-<tier> | deploy-<tier>
  matrix {"<job>": {"include": [...]}}   one entry per stack instance / pool / release
  tiers  {"org|nonprd|prd": {"include": [...]}}   all stack instances of a tier (PR plans)
  order  job names in apply order (stacks.yaml `after` + db gate + deploys)

Rules
  PL01 promotion: a version raised at env E (not dev) must equal the version already running at the previous env
       of the same deployment (it has soaked there); a NEW deployment (onboarding) may not be newer than its own
       previous env; going back to an older supported version (rollback) is allowed
  PL02 the registry of the head passes D1 validation (supported / blocked versions, placement, names)
  PL03 every job of the plan uses the stack identity and state of terraform/stacks.yaml; apply order respects `after`
  PL04 removals (offboarding a customer or a subscription) are never applied automatically – runbook (S7 doc §7.6)
  PL05 placement capacity: new placements keep cells and pools under the Stage 8 thresholds (tools/cost/capacity.py)
Status: implemented + locally tested (tests/test_cicd_planner.py); runs offline (no cloud access needed).
"""
import argparse
import copy
import json
import pathlib
import re
import sys

from tools.iac.stacks import order as _stack_order
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding, _semver, validate

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENVS = ["dev", "stg", "uat", "prd"]
ENV_TIER = {"dev": "nonprd", "stg": "nonprd", "uat": "nonprd", "prd": "prd"}
TIERS = ["nonprd", "prd"]                         # nonprd jobs always run before prd jobs (infra promotion)

# changed path -> stacks whose inputs it feeds (conservative; a no-op plan is cheap, a missed one is not)
PATH_STACKS = [
    (r"^terraform/stacks\.yaml$", "*"),
    (r"^tools/", "*"),
    (r"^security/(org-policies|cicd-identities|privileged-access|audit-monitoring|role-catalog)\.yaml$", ["org"]),
    (r"^security/k8s-baseline\.yaml$", ["cluster-config"]),
    (r"^security/groups\.yaml$", ["org", "memberships"]),
    (r"^security/access-matrix\.yaml$", ["org", "network", "tenant", "product", "cluster-config", "memberships"]),
    (r"^security/data-protection\.yaml$", ["org", "platform", "tenant", "product"]),
    (r"^policies/k8s/", ["cluster-config"]),
    (r"^network/firewall\.yaml$", ["org", "network", "tenant", "product"]),
    (r"^network/edge\.yaml$", ["network", "edge", "cluster-config"]),
    (r"^network/", ["network"]),
    (r"^registry/platform/", ["network", "platform", "cluster-config", "edge", "observability"]),
    (r"^registry/products/", ["platform", "tenant", "product", "edge", "cluster-config", "memberships", "observability"]),
    (r"^slo/", ["observability", "platform"]),
]


# ----------------------------------------------------------------------------------------------- inputs
def stack_order(root=ROOT):
    return _stack_order(pathlib.Path(root))


def load(root):
    """Registry of a checkout root; a missing registry (first commit) is an empty one."""
    root = pathlib.Path(root)
    if not (root / "registry" / "platform" / "inventory.yaml").exists():
        return None
    reg, findings = validate(root / "registry")
    return reg, findings


def catalogue(root=ROOT):
    return load_yaml(pathlib.Path(root) / "terraform" / "stacks.yaml")["stacks"]


def module_users(root=ROOT):
    """module name -> stacks whose main.tf calls it."""
    out = {}
    for d in (pathlib.Path(root) / "terraform" / "stacks").iterdir():
        for tf in d.glob("*.tf"):
            for m in re.findall(r'source\s*=\s*"\.\./\.\./modules/([\w-]+)"', tf.read_text()):
                out.setdefault(m, set()).add(d.name)
    return out


def cell_tier(inv, cell):
    return "prd" if inv["gke_cells"][cell]["project"].endswith("-prd") else "nonprd"


def instances(stack, spec, reg):
    """All instances of a stack for a registry: [(tier, instance, values)]."""
    kind = spec["instances"]
    if kind == "once":
        return [("org", "org", {"tier": "org"})]
    if kind == "per-tier":
        return [(t, t, {"tier": t}) for t in TIERS]
    if kind == "per-cell":
        return [(cell_tier(reg.inventory, c), c, {"tier": cell_tier(reg.inventory, c), "cell": c})
                for c in sorted(reg.inventory["gke_cells"])]
    if kind == "per-tenant-per-tier":
        return [(t, f"{n}-{t}", {"tier": t, "tenant": n}) for n in sorted(reg.tenants) for t in TIERS]
    if kind == "per-shared-product-per-tier":
        return [(t, f"{p}-{t}", {"tier": t, "product": p}) for p, (_, d) in sorted(reg.products.items())
                if d["deployment_model"] in ("shared", "cohort") for t in TIERS]
    raise ValueError(f"{stack}: unknown instances kind {kind}")


def job_entry(stack, spec, tier, inst, vals):
    fmt = {**vals, "tier": tier if tier != "org" else "org"}
    return {"stack": stack, "tier": tier, "instance": inst,
            "state": spec["state"].format(**fmt) if "{" in spec["state"] else spec["state"],
            "identity": spec["identity"].format(**fmt) if "{" in spec["identity"] else spec["identity"],
            "two_phase": stack == "cluster-config"}


# ----------------------------------------------------------------------------------------------- diff
def _tier_view(tenant_doc, tier, drop_versions=True):
    """Infra-relevant part of a tenant file for one tier (versions excluded – they are deploys, not Terraform)."""
    if tenant_doc is None:
        return None
    d = copy.deepcopy(tenant_doc)
    for sub in d.get("subscriptions", {}).values():
        for key in ("versions", "placement", "cohort"):
            if key in sub:
                sub[key] = {e: v for e, v in sub[key].items() if ENV_TIER[e] == tier}
        if drop_versions:
            sub.pop("versions", None)
    return d


def _versions(reg):
    out = {}
    if reg is None:
        return out
    for t, (_, d) in reg.tenants.items():
        for p, sub in d["subscriptions"].items():
            for e, v in (sub.get("versions") or {}).items():
                out[(t, p, e)] = v
    return out


def release_item(reg, tenant, product, env, frm, to):
    _, prod = reg.products[product]
    sub = reg.tenants[tenant][1]["subscriptions"][product]
    pl = (sub.get("placement") or {}).get(env, {})
    pool = pl.get("sql")
    pools = {**reg.inventory["sql_pools"], **reg.inventory.get("product_sql_pools", {})}
    ns = f"{tenant}-{product}-{env}"
    return {"tenant": tenant, "product": product, "env": env, "tier": ENV_TIER[env], "from": frm, "to": to,
            "runtime": prod["runtime"], "chart": prod.get("chart"), "cell": pl.get("gke"),
            "cell_project": reg.inventory["gke_cells"][pl["gke"]]["project"] if pl.get("gke") else None,
            "namespace": ns if prod["runtime"] == "gke" else None,
            "service": ns if prod["runtime"] == "cloudrun" else None,
            "mig": f"mig-{ns}" if prod["runtime"] == "mig" else None,
            "project": f"t-{tenant}-{ENV_TIER[env]}",
            "pool": pool, "pool_project": pools[pool]["project"] if pool else None,
            "pre_backup": env == "prd" and bool(pool)}


def promotion(base, head):
    """PL01 – findings for version changes that skip an environment."""
    f = []
    bv, hv = _versions(base), _versions(head)
    for (t, p, e), v in sorted(hv.items()):
        old = bv.get((t, p, e))
        if old == v or e == "dev":
            continue
        if old is not None and _semver(v) < _semver(old):
            continue                                  # rollback to an older supported version is allowed
        prev = ENVS[ENVS.index(e) - 1]
        if old is not None:
            if bv.get((t, p, prev)) != v:
                f.append(Finding("PL01", f"registry/tenants/{t}.yaml",
                                 f"{p}/{e}: {old} -> {v}, but {prev} runs {bv.get((t, p, prev))} – promote through {prev} first"))
        elif (t, p, prev) in hv and _semver(v) > _semver(hv[(t, p, prev)]):
            f.append(Finding("PL01", f"registry/tenants/{t}.yaml",
                             f"{p}/{e}: new deployment at {v} is newer than its own {prev} ({hv[(t, p, prev)]})"))
    return f


def affected(base, head, changed, root=ROOT):
    """-> (set of (stack, instance)), releases, findings."""
    breg, hreg = (base or (None,))[0], head[0]
    cat = catalogue(root)
    users = module_users(root)
    stacks_all = {s for s in cat if s != "bootstrap"}
    touched, findings, releases = set(), [], []

    def add_stack(s, only=None):
        if s not in cat or s == "bootstrap":
            return
        for tier, inst, vals in instances(s, cat[s], hreg):
            if only is None or only(tier, inst, vals):
                touched.add((s, inst))

    for path in changed:
        m = re.match(r"^terraform/modules/([\w-]+)/", path)
        if m:
            for s in users.get(m.group(1), set()):
                add_stack(s)
            continue
        m = re.match(r"^terraform/stacks/([\w-]+)/", path)
        if m:
            add_stack(m.group(1))
            continue
        for rx, stacks in PATH_STACKS:
            if re.match(rx, path):
                for s in (stacks_all if stacks == "*" else stacks):
                    add_stack(s)
                break

    # tenant files: compared by content, so the result does not depend on the changed-file list
    bt = breg.tenants if breg else {}
    for name in sorted(set(bt) | set(hreg.tenants)):
        old = bt.get(name, (None, None))[1]
        new = hreg.tenants.get(name, (None, None))[1]
        if new is None:
            findings.append(Finding("PL04", f"registry/tenants/{name}.yaml",
                                    "customer removed – offboarding is a runbook, not an automatic apply"))
            continue
        for p in sorted(set((old or {}).get("subscriptions", {})) - set(new["subscriptions"])):
            findings.append(Finding("PL04", f"registry/tenants/{name}.yaml",
                                    f"subscription {p} removed – offboarding runbook required"))
        for tier in TIERS:
            if _tier_view(old, tier) != _tier_view(new, tier):
                touched.add(("tenant", f"{name}-{tier}"))
                touched.add(("memberships", tier))
                touched.add(("edge", tier))
                if "observability" in cat:
                    touched.add(("observability", tier))
                for sub in new["subscriptions"].values():
                    for env, pl in (sub.get("placement") or {}).items():
                        if ENV_TIER[env] == tier and pl.get("gke"):
                            touched.add(("cluster-config", pl["gke"]))
                for p, sub in new["subscriptions"].items():
                    if "cohort" in sub:
                        touched.add(("product", f"{p}-{tier}"))
    # releases: every version that differs from the base (a new tenant deploys all its environments)
    bv, hv = _versions(breg), _versions(hreg)
    for key in sorted(hv, key=lambda k: (k[0], k[1], ENVS.index(k[2]))):
        if bv.get(key) != hv[key]:
            releases.append(release_item(hreg, *key, bv.get(key), hv[key]))
    findings += promotion(breg, hreg)
    return touched, releases, findings


def db_pools(reg, touched):
    """Pools whose databases / grants the bootstrap job must (re)apply: pools of touched tenant instances."""
    pools = {**reg.inventory["sql_pools"], **reg.inventory.get("product_sql_pools", {})}
    out = {}
    for s, inst in touched:
        if s != "tenant":
            continue
        name, tier = inst.rsplit("-", 1)
        for sub in reg.tenants[name][1]["subscriptions"].values():
            for env, pl in (sub.get("placement") or {}).items():
                if ENV_TIER[env] == tier and pl.get("sql"):
                    out[pl["sql"]] = {"pool": pl["sql"], "project": pools[pl["sql"]]["project"], "tier": tier}
    return sorted(out.values(), key=lambda x: x["pool"])


def build_plan(base, head, changed, root=ROOT):
    cat = catalogue(root)
    reg = head[0]
    touched, releases, findings = affected(base, head, changed, root)
    jobs = {}
    for s in [x for x in stack_order(root) if x != "bootstrap"]:
        for tier, inst, vals in instances(s, cat[s], reg):
            if (s, inst) in touched:
                key = "org" if tier == "org" else f"{s}-{tier}"
                jobs.setdefault(key, []).append(job_entry(s, cat[s], tier, inst, vals))
    for tier in TIERS:
        pools = [p for p in db_pools(reg, touched) if p["tier"] == tier]
        if pools:
            jobs[f"db-{tier}"] = pools
        rel = [r for r in releases if r["tier"] == tier]
        if rel:
            jobs[f"deploy-{tier}"] = rel
    order = job_order(root)
    tiers = {t: {"include": [e for j in order if j in jobs and not j.startswith(("db-", "deploy-"))
                             for e in jobs[j] if e["tier"] == t]} for t in ["org"] + TIERS}
    return {"run": {j: j in jobs for j in order},
            "matrix": {j: {"include": jobs.get(j, [])} for j in order},
            "tiers": tiers,
            "run_tiers": {t: bool(v["include"]) for t, v in tiers.items()},
            "order": order,
            "findings": [str(x) for x in findings]}, findings


def all_instances(tier, root=ROOT):
    """Every stack instance of a tier (drift detection)."""
    reg = load(root)[0]
    cat = catalogue(root)
    return {"include": [job_entry(s, cat[s], t, inst, vals) for s in stack_order(root) if s != "bootstrap"
                        for t, inst, vals in instances(s, cat[s], reg) if t == tier]}


def job_order(root=ROOT):
    """Apply order of the job names: org, then per tier (nonprd first) the stacks in catalogue order, the database
    gate after the tenant/product stacks, the deploys last."""
    cat = catalogue(root)
    seq = ["org"]
    for tier in TIERS:
        for s in stack_order(root):
            if s in ("bootstrap", "org"):
                continue
            seq.append(f"{s}-{tier}")
            if s == "memberships":
                seq.append(f"db-{tier}")
        seq.append(f"deploy-{tier}")
    # memberships is last in the catalogue order of most trees; make sure db follows tenant/product in any case
    return [j for j in seq if j.rsplit("-", 1)[0] in cat or j.startswith(("db-", "deploy-")) or j == "org"]


def job_needs(root=ROOT):
    """job -> jobs it must wait for (used by tools/cicd/workflows.py to check the caller workflows)."""
    cat = catalogue(root)
    needs = {"org": set()}
    for tier in TIERS:
        prev_tier = {f"{s}-nonprd" for s in cat if s not in ("bootstrap", "org")} | {"db-nonprd", "deploy-nonprd"} \
            if tier == "prd" else set()
        for s in cat:
            if s in ("bootstrap", "org"):
                continue
            needs[f"{s}-{tier}"] = {"org" if a == "org" else f"{a}-{tier}" for a in cat[s].get("after", [])
                                    if a != "bootstrap"} | (prev_tier & {f"{s}-nonprd"})
        needs[f"db-{tier}"] = {f"tenant-{tier}", f"product-{tier}", f"memberships-{tier}"}
        needs[f"deploy-{tier}"] = {f"db-{tier}", f"cluster-config-{tier}", f"edge-{tier}", f"memberships-{tier}"} | \
            ({"deploy-nonprd"} if tier == "prd" else set())
    return needs


# ----------------------------------------------------------------------------------------------- onboarding
def onboarding(tenant, root=ROOT):
    """Ordered job list that onboarding <tenant> produces (empty base for that customer)."""
    head = load(root)
    reg = head[0]
    if tenant not in reg.tenants:
        raise SystemExit(f"unknown tenant {tenant}")
    base_reg = copy.copy(reg)
    base_reg.tenants = {k: v for k, v in reg.tenants.items() if k != tenant}
    plan, findings = build_plan((base_reg, []), head, [], root)
    return [(j, [x.get("instance") or (f"{x['product']}/{x['env']}@{x['to']}" if "to" in x else x.get("pool")) for x in
                 plan["matrix"][j]["include"]]) for j in plan["order"] if plan["run"][j]], findings


def check(root=ROOT):
    """Self-check: plan stays consistent with stacks.yaml, PL01 holds for the current registry, every tenant onboards."""
    f = []
    head = load(root)
    f += [Finding("PL02", x.path, x.message) for x in head[1]]
    cat = catalogue(root)
    needs = job_needs(root)
    pos = {j: i for i, j in enumerate(job_order(root))}
    for j, ns in needs.items():
        for n in ns:
            if n in pos and j in pos and pos[n] > pos[j]:
                f.append(Finding("PL03", "terraform/stacks.yaml", f"job order puts {j} before its dependency {n}"))
    for tenant in sorted(head[0].tenants):
        seq, fs = onboarding(tenant, root)
        f += [x for x in fs if x.rule != "PL04"]
        names = [j for j, _ in seq]
        for required in ("tenant-nonprd", "db-nonprd", "deploy-nonprd", "tenant-prd", "db-prd", "deploy-prd"):
            if required not in names:
                f.append(Finding("PL03", f"registry/tenants/{tenant}.yaml", f"onboarding misses job {required}"))
    for s, spec in cat.items():
        if s == "bootstrap":
            continue
        for tier, inst, vals in instances(s, spec, head[0]):
            e = job_entry(s, spec, tier, inst, vals)
            if "{" in e["state"] or "{" in e["identity"]:
                f.append(Finding("PL03", "terraform/stacks.yaml", f"{s}/{inst}: unresolved template in state/identity"))
    try:
        from tools.cost.capacity import check_placements
        f += check_placements(head[0])
    except ImportError:
        pass
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff")
    d.add_argument("--base", required=True)
    d.add_argument("--head", default=".")
    d.add_argument("--changed", nargs="*", default=[])
    d.add_argument("-o", "--out", default="build/cicd/plan.json")
    o = sub.add_parser("onboard")
    o.add_argument("tenant")
    o.add_argument("--root", default=str(ROOT))
    al = sub.add_parser("all")
    al.add_argument("--tier", required=True, choices=["org"] + TIERS)
    al.add_argument("--root", default=str(ROOT))
    c = sub.add_parser("check")
    c.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    if a.cmd == "diff":
        head = load(a.head)
        plan, findings = build_plan(load(a.base), head, a.changed, a.head)
        try:
            from tools.cost.capacity import check_placements
            cap = check_placements(head[0])
            findings += cap
            plan["findings"] += [str(x) for x in cap]
        except ImportError:
            pass
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, indent=1))
        for x in findings:
            print(x)
        jobs = [j for j in plan["order"] if plan["run"][j]]
        print(f"jobs: {', '.join(jobs) or 'none'}; {len(findings)} finding(s)")
        return 1 if [x for x in findings if x.rule != "PL04"] else 0
    if a.cmd == "onboard":
        seq, findings = onboarding(a.tenant, a.root)
        for i, (j, items) in enumerate(seq, 1):
            print(f"{i:2}. {j:24} {', '.join(items)}")
        return 1 if findings else 0
    if a.cmd == "all":
        print(json.dumps(all_instances(a.tier, a.root), separators=(",", ":")))
        return 0
    findings = check(a.root)
    for x in findings:
        print(x)
    print(f"planner self-check: {len(job_order(a.root))} pipeline jobs, {len(load(a.root)[0].tenants)} tenant "
          f"onboarding sequence(s); {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
