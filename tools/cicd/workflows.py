"""Stage 7 – static checks of the GitHub Actions workflows against the CI/CD identity model (D6) and the stack
catalogue, plus the generator of the two pipeline workflows (apply-pipeline.yml, pr-pipeline.yml).

Usage:  python3 -m tools.cicd.workflows [--write]       --write regenerates the pipeline workflows from stacks.yaml

Layout (one directory per GitHub repository of Stage 2 §1):
  cicd/platform-workflows/.github/workflows/*.yml   reusable workflows (the only place prd / org jobs are defined)
  cicd/platform-workflows/.github/actions/*/        composite actions
  cicd/repos/<repository>/.github/workflows/*.yml   caller workflows of each repository
  .github/workflows/ci.yml                          CI of this design repository (runnable as is)

Every caller job is followed into the reusable workflows it calls (inputs substituted, `if:` conditions evaluated
with three-valued logic: unknown = may run), so the checks cover what each repository can actually reach.
Rules
  CW01 least privilege: top-level `permissions: contents: read`; `id-token: write` exactly on jobs that authenticate
       to Google Cloud; `contents: write` only on the job that moves the `applied` marker tag
  CW02 Google Cloud authentication only through WIF (vars.WIF_PROVIDER) as a WIF pipeline identity of D6; no
       credentials_json / service-account keys; secrets limited to the GitHub App key of the workspace action
  CW03 identity gate: for every repository, trigger (ref class) and reachable auth step, (repository, environment,
       ref class) is an allowed gate of that identity in security/cicd-identities.yaml
  CW04 prd / org environments only in jobs of platform-workflows; callers use platform-workflows only at @v1
  CW05 actions pinned to a release tag or commit SHA, never a branch
  CW06 runner groups: jobs with a cloud identity run on the self-hosted group of the identity's tier, and the
       repository is a member of that runner group; build identity only on the build group
  CW07 safe change: Terraform applies are serialised per state (concurrency, no cancel); releases are deployed by
       digest with automatic rollback (helm --atomic, Cloud Run traffic revert, MIG previous template); no :latest
  CW08 the pipeline workflows equal their generated form (job graph = tools/cicd/planner.job_needs)
  CW09 every product repository builds and signs its image (and bakes a VM image for MIG products); every caller
       repository is a known repository of D6; every WIF identity of D6 is used by at least one workflow
Status: implemented + locally tested (tests/test_cicd_workflows.py). actionlint / a real run are T-CI1, T-CI3.
"""
import argparse
import pathlib
import re
import sys

import yaml

from tools.cicd.federation import Federation
from tools.cicd.planner import TIERS, catalogue, job_needs, job_order
from tools.registry.validate import Finding, load_registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
CICD = ROOT / "cicd"
OWNER = "example-org"                    # placeholder GitHub organisation (${GH_ORG} in cicd-identities.yaml)
WF_PREFIX = f"{OWNER}/platform-workflows/.github/"
WF_REF = "v1"
ALLOWED_SECRETS = {"PLATFORM_READER_APP_KEY"}
UNKNOWN = object()


# ======================================================================================= expression evaluation
class Expr:
    """Tiny evaluator for GitHub expressions: literals, contexts, == != && || ! ( ), function calls -> unknown."""
    TOK = re.compile(r"\s*(?:(?P<s>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||!|\(|\)|,|\[|\])|(?P<n>-?\d+(?:\.\d+)?)"
                     r"|(?P<id>\.?[A-Za-z_][\w.\-*]*))")

    def __init__(self, text, ctx):
        self.toks, pos = [], 0
        while pos < len(text):
            m = self.TOK.match(text, pos)
            if not m or m.end() == pos:
                raise ValueError(f"cannot parse expression: {text}")
            pos = m.end()
            kind = m.lastgroup
            self.toks.append((kind, m.group(kind)))
        self.i, self.ctx = 0, ctx

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        v = self.or_()
        if self.i != len(self.toks):
            raise ValueError("trailing tokens")
        return v

    def or_(self):
        v = self.and_()
        while self.peek() == ("op", "||"):
            self.take()
            w = self.and_()
            if v is UNKNOWN:
                v = UNKNOWN
            elif not truthy(v):
                v = w
        return v

    def and_(self):
        v = self.not_()
        while self.peek() == ("op", "&&"):
            self.take()
            w = self.not_()
            if v is UNKNOWN:
                v = w if (w is not UNKNOWN and not truthy(w)) else UNKNOWN
            elif truthy(v):
                v = w
        return v

    def not_(self):
        if self.peek() == ("op", "!"):
            self.take()
            v = self.not_()
            return UNKNOWN if v is UNKNOWN else (not truthy(v))
        return self.cmp()

    def cmp(self):
        v = self.primary()
        if self.peek() in (("op", "=="), ("op", "!=")):
            op = self.take()[1]
            w = self.primary()
            if v is UNKNOWN or w is UNKNOWN:
                return UNKNOWN
            eq = str(v).lower() == str(w).lower() if isinstance(v, str) and isinstance(w, str) else v == w
            return eq if op == "==" else not eq
        return v

    def primary(self):
        kind, val = self.take()
        if (kind, val) == ("op", "("):
            v = self.or_()
            self.take()
            return v
        if kind == "s":
            return val[1:-1].replace("''", "'")
        if kind == "n":
            return float(val)
        if kind == "id":
            if val in ("true", "false"):
                return val == "true"
            if val == "null":
                return None
            if self.peek() == ("op", "("):                 # function call: evaluate nothing, skip arguments
                depth = 0
                while True:
                    k, t = self.take()
                    depth += t == "(" if k == "op" else 0
                    depth -= t == ")" if k == "op" else 0
                    if depth == 0:
                        break
                self._skip_index()
                return UNKNOWN
            had_index = self.peek() in (("op", "["),) or (self.peek()[0] == "id" and str(self.peek()[1]).startswith("."))
            self._skip_index()
            return UNKNOWN if had_index else self.ctx.get(val, UNKNOWN)
        raise ValueError(f"unexpected token {val}")

    def _skip_index(self):
        """Index / property access after a call or context (`x['a'].b[0]`) – the value stays unknown."""
        while True:
            k, t = self.peek()
            if (k, t) == ("op", "["):
                depth = 0
                while True:
                    k, t = self.take()
                    depth += (t == "[") - (t == "]") if k == "op" else 0
                    if depth == 0:
                        break
            elif k == "id" and t.startswith("."):
                self.take()
            else:
                break


def truthy(v):
    return bool(v) and v != "false"


def evaluate(expr, ctx):
    try:
        return Expr(expr, ctx).parse()
    except (ValueError, IndexError):
        return UNKNOWN


EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def resolve(value, ctx):
    """String with ${{ }} -> resolved string, or UNKNOWN if any part is unknown. Non-strings unchanged."""
    if not isinstance(value, str):
        return value
    m = EXPR.fullmatch(value.strip())
    if m:
        return evaluate(m.group(1), ctx)
    out, unknown = [], False

    def sub(mm):
        nonlocal unknown
        v = evaluate(mm.group(1), ctx)
        if v is UNKNOWN:
            unknown = True
            return ""
        return str(v).lower() if isinstance(v, bool) else str(v)
    out = EXPR.sub(sub, value)
    return UNKNOWN if unknown else out


def condition(cond, ctx):
    """Job / step `if:` -> True, False or UNKNOWN (bare expressions are allowed in `if:`)."""
    if cond is None:
        return True
    if isinstance(cond, bool):
        return cond
    text = cond.strip()
    m = EXPR.fullmatch(text)
    v = evaluate(m.group(1) if m else text, ctx)
    return v if v is UNKNOWN else truthy(v)


# ======================================================================================= loading
def load_wf(path):
    doc = yaml.safe_load(path.read_text())
    doc["on"] = doc.get("on", doc.pop(True, None))
    return doc


class Workflows:
    def __init__(self, root=ROOT, security="security"):
        self.root = pathlib.Path(root)
        self.cicd = self.root / "cicd"
        self.reusable = {f"{WF_PREFIX}workflows/{p.name}": (p, load_wf(p))
                         for p in sorted((self.cicd / "platform-workflows/.github/workflows").glob("*.yml"))}
        self.callers = {}
        for p in sorted((self.cicd / "repos").glob("*/.github/workflows/*.yml")):
            self.callers.setdefault(p.parts[-4], []).append((p, load_wf(p)))
        own = self.root / ".github/workflows"
        self.own = [(p, load_wf(p)) for p in sorted(own.glob("*.yml"))] if own.exists() else []
        self.actions = {f"{WF_PREFIX}actions/{p.parent.name}": (p, yaml.safe_load(p.read_text()))
                        for p in sorted((self.cicd / "platform-workflows/.github/actions").glob("*/action.yml"))}
        self.fed = Federation(str(self.root / "registry"), str(self.root / security))
        self.ids = self.fed.doc

    def all_files(self):
        yield from self.reusable.values()
        for files in self.callers.values():
            yield from files
        yield from self.own

    # ------------------------------------------------------------------- walk
    @staticmethod
    def ref_classes(on):
        classes = set()
        if isinstance(on, str):
            on = {on: None}
        if isinstance(on, list):
            on = {k: None for k in on}
        for ev, spec in (on or {}).items():
            spec = spec or {}
            if ev == "push":
                if spec.get("branches"):
                    classes |= {"main" if b == "main" else "other" for b in spec["branches"]}
                if spec.get("tags"):
                    classes |= {"release-tag" if t.startswith("v") else "other" for t in spec["tags"]}
                if not spec.get("branches") and not spec.get("tags"):
                    classes |= {"main", "other", "release-tag"}
            elif ev in ("pull_request", "pull_request_target"):
                classes.add("other")
            elif ev in ("schedule", "workflow_dispatch", "workflow_run"):
                classes.add("main")             # default branch; environments restrict branches to main (CI07)
        return classes

    def walk(self, uses_key, ctx, depth=0):
        """Yield (file, job_id, job, ctx) for every job reachable from a reusable workflow call."""
        path, doc = self.reusable[uses_key]
        inputs = ((doc["on"] or {}).get("workflow_call") or {}).get("inputs") or {}
        jctx = {f"inputs.{k}": (ctx.get(f"inputs.{k}", v.get("default", UNKNOWN))) for k, v in inputs.items()}
        for jid, job in (doc.get("jobs") or {}).items():
            if condition(job.get("if"), jctx) is False:
                continue
            if "uses" in job:
                sub_ctx = {f"inputs.{k}": resolve(v, jctx) for k, v in (job.get("with") or {}).items()}
                yield from self.walk(job["uses"].split("@")[0], sub_ctx, depth + 1)
            else:
                yield path, jid, job, jctx

    def caller_jobs(self):
        """(repo, caller file, ref classes, reusable file, job id, job, ctx) for every reachable job of every caller."""
        for repo, files in self.callers.items():
            for path, doc in files:
                refs = self.ref_classes(doc["on"])
                for jid, job in (doc.get("jobs") or {}).items():
                    if "uses" in job and job["uses"].startswith(WF_PREFIX):
                        ctx = {f"inputs.{k}": resolve(v, {}) for k, v in (job.get("with") or {}).items()}
                        for f, j, jb, c in self.walk(job["uses"].split("@")[0], ctx):
                            yield repo, path, refs, f, j, jb, c
                    elif "steps" in job:
                        yield repo, path, refs, path, jid, job, {}

    @staticmethod
    def auth_steps(job, ctx):
        for st in job.get("steps") or []:
            if str(st.get("uses", "")).startswith("google-github-actions/auth@") and condition(st.get("if"), ctx) is not False:
                yield st

    def sa_tpl(self, email):
        """email -> pipeline identity template of cicd-identities.yaml (or None)."""
        if email is UNKNOWN or not isinstance(email, str):
            return None
        sa = "sa:" + email.replace(".iam.gserviceaccount.com", "")
        for tpl in self.ids["pipeline_identities"]:
            if sa in self.fed.expand_sa(tpl) or sa == tpl:
                return tpl
        return None

    # ------------------------------------------------------------------- rules
    def check(self):
        f = []
        f += self.check_files()
        f += self.check_callers()
        f += self.check_generated()
        f += self.check_products()
        return f

    def check_files(self):
        f = []
        for path, doc in self.all_files():
            rel = str(path.relative_to(self.root))
            text = path.read_text()
            top = doc.get("permissions")
            if top != {"contents": "read"}:
                f.append(Finding("CW01", rel, f"top-level permissions must be exactly contents: read (is {top})"))
            for jid, job in (doc.get("jobs") or {}).items():
                perms = job.get("permissions") or {}
                steps = job.get("steps") or []
                has_auth = any(str(s.get("uses", "")).startswith("google-github-actions/auth@") for s in steps)
                if "uses" in job:
                    if perms:
                        f.append(Finding("CW01", rel, f"{jid}: calling job sets permissions; the called workflow owns them"))
                else:
                    if has_auth != (perms.get("id-token") == "write"):
                        f.append(Finding("CW01", rel, f"{jid}: id-token: write must be set exactly when the job authenticates"))
                    for k, v in perms.items():
                        if v == "write" and k not in ("id-token",) and not (k == "contents" and jid == "mark-applied"):
                            f.append(Finding("CW01", rel, f"{jid}: write permission {k} not allowed"))
                env = job.get("environment")
                env = env.get("name") if isinstance(env, dict) else env
                in_wf = "platform-workflows" in rel
                if env and not in_wf and str(env).split("-")[-1] in ("prd", "org") and not str(env).startswith("plan-"):
                    f.append(Finding("CW04", rel, f"{jid}: environment {env} outside platform-workflows"))
                for st in steps:
                    if str(st.get("uses", "")).startswith("google-github-actions/auth@"):
                        w = st.get("with") or {}
                        if "credentials_json" in w or w.get("workload_identity_provider") != "${{ vars.WIF_PROVIDER }}":
                            f.append(Finding("CW02", rel, f"{jid}: authenticate through vars.WIF_PROVIDER only"))
                        tpl = self.sa_tpl(resolve(w.get("service_account"), {}))
                        if tpl is None and EXPR.search(str(w.get("service_account"))) is None:
                            f.append(Finding("CW02", rel, f"{jid}: {w.get('service_account')} is not a pipeline identity"))
            for u in re.findall(r"uses:\s*([^\s#]+)", text):
                f += self.pin(rel, u)
            for s in set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) - ALLOWED_SECRETS:
                f.append(Finding("CW02", rel, f"secret {s} not allowed (no long-lived cloud credentials)"))
            if "credentials_json" in text or re.search(r":latest\b", text):
                f.append(Finding("CW02" if "credentials_json" in text else "CW07", rel,
                                 "credentials_json or :latest image reference"))
        for path, act in self.actions.values():
            for u in re.findall(r"uses:\s*([^\s#]+)", path.read_text()):
                f += self.pin(str(path.relative_to(self.root)), u)
        # CW07 – safe change in the deploy / apply workflows
        dep = self.reusable.get(f"{WF_PREFIX}workflows/deploy-release.yml")
        if dep:
            t = dep[0].read_text()
            for line in [x for x in t.splitlines() if "helm upgrade" in x]:
                if "--atomic" not in t[t.index(line):t.index(line) + 600]:
                    f.append(Finding("CW07", "deploy-release.yml", "helm upgrade without --atomic"))
            for need in ("--to-revisions", "@${{ steps.img.outputs.digest }}", "--version \"template=$cur\""):
                if need not in t:
                    f.append(Finding("CW07", "deploy-release.yml", f"missing rollback / digest construct: {need}"))
        for key in (f"{WF_PREFIX}workflows/tf-apply.yml", f"{WF_PREFIX}workflows/db-jobs.yml"):
            if key in self.reusable:
                for jid, job in self.reusable[key][1]["jobs"].items():
                    c = job.get("concurrency")
                    if jid in ("apply", "bootstrap") and (not c or c.get("cancel-in-progress") is not False):
                        f.append(Finding("CW07", key.split("/")[-1], f"{jid}: needs a non-cancelling concurrency group"))
                    if jid == "apply" and "matrix.state" not in str(c):
                        f.append(Finding("CW07", "tf-apply.yml", "apply concurrency group must be per state"))
        return f

    @staticmethod
    def _hosted(runs_on):
        return isinstance(runs_on, str) and runs_on.startswith(("ubuntu-", "windows-", "macos-"))

    @staticmethod
    def pin(rel, u):
        if u.startswith("./"):
            return [Finding("CW04", rel, f"{u}: local actions/workflows resolve in the caller – use {WF_PREFIX}…@{WF_REF}")]
        if "@" not in u:
            return [Finding("CW05", rel, f"{u}: not pinned")]
        name, ref = u.rsplit("@", 1)
        if name.startswith(WF_PREFIX.rstrip("/").rsplit("/.github", 1)[0]):
            return [] if ref == WF_REF else [Finding("CW04", rel, f"{u}: platform-workflows must be used at @{WF_REF}")]
        if re.fullmatch(r"[0-9a-f]{40}", ref) or re.fullmatch(r"v\d+(\.\d+){0,2}", ref):
            return []
        return [Finding("CW05", rel, f"{u}: pin to a release tag or commit SHA")]

    def check_callers(self):
        f, seen = [], set()
        groups = self.ids["github"]["runner_groups"]
        repos = self.ids["repositories"]
        for repo, path, refs, wf, jid, job, ctx in self.caller_jobs():
            rel = f"{repo}:{path.name}->{wf.name}:{jid}"
            if repo not in repos:
                f.append(Finding("CW09", str(path.relative_to(self.root)), f"repository {repo} unknown to D6"))
                continue
            env = job.get("environment")
            env = resolve(env.get("name") if isinstance(env, dict) else env, ctx) if env else "none"
            runs = job.get("runs-on")
            labels = [resolve(x, ctx) for x in (runs if isinstance(runs, list) else [runs])]
            for st in self.auth_steps(job, ctx):
                email = resolve((st.get("with") or {}).get("service_account"), ctx)
                tpl = self.sa_tpl(email)
                if tpl is None:
                    f.append(Finding("CW02", rel, f"identity {email if email is not UNKNOWN else '(unresolved)'} unknown"))
                    continue
                spec = self.ids["pipeline_identities"][tpl]
                if spec["auth"] != "wif":
                    f.append(Finding("CW02", rel, f"{tpl} is not a WIF identity"))
                allowed = set(self.fed.gates(tpl))
                for ref in sorted(refs):
                    key = (repo, env, ref)
                    if env is UNKNOWN or key not in allowed:
                        f.append(Finding("CW03", rel, f"{tpl} from ({repo}, {env if env is not UNKNOWN else '?'}, {ref}) "
                                                      f"is not an allowed gate"))
                    seen.add((tpl, key))
                # CW06 runner group
                want = {"prd": "prd", "org": "prd", "nonprd": "nonprd", "shared": "build"}[spec["tier"]]
                if self._hosted(runs) or UNKNOWN in labels or want not in labels or "self-hosted" not in labels:
                    f.append(Finding("CW06", rel, f"{tpl} must run on [self-hosted, {want}] (runs-on {runs})"))
                elif repo not in groups[want]["repositories"]:
                    f.append(Finding("CW06", rel, f"repository {repo} is not in runner group {want}"))
        self.gates_used = seen
        used = {t for t, _ in seen}
        for tpl, spec in self.ids["pipeline_identities"].items():
            if spec["auth"] == "wif" and tpl not in used and not any(sa in used for sa in self.fed.expand_sa(tpl)):
                f.append(Finding("CW09", "security/cicd-identities.yaml", f"{tpl}: WIF identity used by no workflow"))
        return f

    # ------------------------------------------------------------------- generated pipelines (CW08)
    def check_generated(self):
        f = []
        for name, text in render_pipelines(self.root).items():
            p = self.cicd / "platform-workflows/.github/workflows" / name
            if not p.exists() or p.read_text() != text:
                f.append(Finding("CW08", str(p.relative_to(self.root)),
                                 "differs from the generated pipeline – run python3 -m tools.cicd.workflows --write"))
        return f

    def check_products(self):
        f = []
        reg, _ = load_registry(self.root / "registry")
        for product, (_, p) in sorted(reg.products.items()):
            repo = f"app-{product}"
            files = self.callers.get(repo, [])
            uses = " ".join(str(j.get("uses", "")) for _, d in files for j in (d.get("jobs") or {}).values())
            if "workflows/build-image.yml" not in uses:
                f.append(Finding("CW09", f"cicd/repos/{repo}", f"{product}: no build-image workflow"))
            if p["runtime"] == "mig" and "workflows/bake-vm-image.yml" not in uses:
                f.append(Finding("CW09", f"cicd/repos/{repo}", f"{product}: MIG product without bake-vm-image"))
        return f


# ======================================================================================= generator
HEAD = """# GENERATED by `python3 -m tools.cicd.workflows --write` from terraform/stacks.yaml + tools/cicd/planner.py.
# Do not edit by hand: CW08 fails when this file differs from its generated form.
"""


def _job(lines, jid, uses, needs, cond, with_):
    lines.append(f"  {jid}:")
    lines.append(f"    needs: [{', '.join(needs)}]")
    lines.append(f"    if: {cond}")
    lines.append(f"    uses: {WF_PREFIX}workflows/{uses}@{WF_REF}")
    lines.append("    secrets: inherit")
    lines.append("    with:")
    for k, v in with_.items():
        lines.append(f"      {k}: {v}")


def render_pipelines(root=ROOT):
    cat = catalogue(root)
    needs = job_needs(root)
    order = job_order(root)
    run = "fromJSON(needs.plan.outputs.run)"
    mat = "toJSON(fromJSON(needs.plan.outputs.matrix)"
    a = [HEAD + "# Stage 7 – apply pipeline of one push to main: planner -> org -> per tier (nonprd, then prd) stacks in",
         "# catalogue order -> database gate (bootstrap + isolation test) -> releases. Jobs without work are skipped;",
         "# a failure stops every job that depends on it. Customer onboarding is this pipeline for a new tenant file.",
         "name: apply-pipeline", "on:", "  workflow_call:", "    inputs:",
         "      allow_org: { type: boolean, default: false }      # only platform-infra may apply the org stack",
         "      allow_deploy: { type: boolean, default: false }   # only platform-tenants deploys releases",
         "      platform_ref: { type: string, default: main }",
         "permissions:", "  contents: read", "concurrency:", "  group: apply-${{ github.repository }}",
         "  cancel-in-progress: false", "jobs:",
         "  marker:",
         "    runs-on: ubuntu-latest",
         "    permissions:",
         "      contents: read",
         "    outputs:",
         "      base: ${{ steps.base.outputs.sha }}",
         "    steps:",
         "      - uses: actions/checkout@v4",
         "        with: { fetch-depth: 0 }",
         "      - id: base",
         "        name: Last applied commit (tag `applied`), or the empty tree on the first run",
         "        run: echo \"sha=$(git rev-parse -q --verify refs/tags/applied || git hash-object -t tree /dev/null)\" >> \"$GITHUB_OUTPUT\"",
         "  plan:",
         "    needs: [marker]",
         f"    uses: {WF_PREFIX}workflows/plan.yml@{WF_REF}",
         "    secrets: inherit",
         "    with:",
         "      base_sha: ${{ needs.marker.outputs.base }}",
         "      platform_ref: ${{ inputs.platform_ref }}"]
    for j in order:
        deps = ["plan"] + sorted(n for n in needs.get(j, set()) if n in order)
        if j == "org":
            cond = f"${{{{ inputs.allow_org && {run}['org'] }}}}"
            _job(a, j, "tf-apply.yml", deps, cond, {"tier": "org", "stack": "org",
                                                    "matrix": f"${{{{ {mat}['org']) }}}}",
                                                    "platform_ref": "${{ inputs.platform_ref }}"})
            continue
        stack, tier = j.rsplit("-", 1)
        cond = f"${{{{ !failure() && !cancelled() && {run}['{j}'] }}}}"
        if stack == "deploy":
            cond = f"${{{{ !failure() && !cancelled() && inputs.allow_deploy && {run}['{j}'] }}}}"
            _job(a, j, "deploy-release.yml", deps, cond, {"tier": tier, "matrix": f"${{{{ {mat}['{j}']) }}}}",
                                                           "platform_ref": "${{ inputs.platform_ref }}"})
        elif stack == "db":
            _job(a, j, "db-jobs.yml", deps, cond, {"tier": tier, "matrix": f"${{{{ {mat}['{j}']) }}}}"})
        else:
            _job(a, j, "tf-apply.yml", deps, cond, {"tier": tier, "stack": stack,
                                                    "matrix": f"${{{{ {mat}['{j}']) }}}}",
                                                    "platform_ref": "${{ inputs.platform_ref }}"})
    a += ["  mark-applied:",
          f"    needs: [{', '.join(order)}]",
          "    if: ${{ !failure() && !cancelled() }}",
          "    runs-on: ubuntu-latest",
          "    permissions:",
          "      contents: write",
          "    steps:",
          "      - uses: actions/checkout@v4",
          "      - name: Move the `applied` marker to this commit",
          "        run: git tag -f applied \"$GITHUB_SHA\" && git push -f origin refs/tags/applied"]
    p = [HEAD + "# Stage 7 – pull-request pipeline: validation (no cloud identity), planner (PL01-PL05) and read-only",
         "# Terraform plans of every stack instance the change touches, per tier.",
         "name: pr-pipeline", "on:", "  workflow_call:", "    inputs:",
         "      allow_org: { type: boolean, default: false }",
         "      platform_ref: { type: string, default: main }",
         "permissions:", "  contents: read", "jobs:",
         "  validate:",
         f"    uses: {WF_PREFIX}workflows/validate.yml@{WF_REF}",
         "    secrets: inherit",
         "    with:",
         "      platform_ref: ${{ inputs.platform_ref }}",
         "  plan:",
         f"    uses: {WF_PREFIX}workflows/plan.yml@{WF_REF}",
         "    secrets: inherit",
         "    with:",
         "      base_sha: ${{ github.event.pull_request.base.sha }}",
         "      platform_ref: ${{ inputs.platform_ref }}"]
    for tier in ["org"] + TIERS:
        cond = f"${{{{ fromJSON(needs.plan.outputs.tiers)['{tier}'].include[0] != null }}}}"
        if tier == "org":
            cond = f"${{{{ inputs.allow_org && fromJSON(needs.plan.outputs.tiers)['org'].include[0] != null }}}}"
        p += [f"  plan-{tier}:", "    needs: [plan]", f"    if: {cond}",
              f"    uses: {WF_PREFIX}workflows/tf-plan.yml@{WF_REF}", "    secrets: inherit", "    with:",
              f"      tier: {tier}", f"      matrix: ${{{{ toJSON(fromJSON(needs.plan.outputs.tiers)['{tier}']) }}}}",
              "      platform_ref: ${{ inputs.platform_ref }}"]
    _ = cat
    return {"apply-pipeline.yml": "\n".join(a) + "\n", "pr-pipeline.yml": "\n".join(p) + "\n"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        for name, text in render_pipelines().items():
            (CICD / "platform-workflows/.github/workflows" / name).write_text(text)
    w = Workflows()
    findings = w.check()
    for x in findings:
        print(x)
    n_callers = sum(len(v) for v in w.callers.values())
    print(f"{len(w.reusable)} reusable + {n_callers} caller workflows in {len(w.callers)} repositories, "
          f"{len(getattr(w, 'gates_used', ()))} identity gate uses checked; {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
