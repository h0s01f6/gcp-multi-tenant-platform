"""D9 – secrets, KMS keys and supply-chain policy, generated from the registry and checked.

Usage:  python3 -m tools.security.dataprotection [--registry registry] [--security security] [-o build/data-protection.json]

Output (Terraform input, Stage 5): secrets, CMEK keys with service-agent bindings, bucket/secret key assignment,
Binary Authorization project policies and attestor-verifier bindings.

Rules
  DP01 every prd secret and bucket of a customer has a CMEK key in that customer's project; every prd SQL pool a key
  DP02 every key project is allowed by the effective D5 gcp.restrictCmekCryptoKeyProjects policy of its folder
  DP03 key and resource locations equal the configured region, which D5 gcp.resourceLocations allows
  DP04 encrypt/decrypt only for service agents; symmetric rotation <= 90 days; destroy schedule >= 30 days
  DP05 secrets: Terraform never manages values; only the owning tenant's workload reads a secret; version adders
       exist only as product-conditioned grants in the access matrix
  DP06 Binary Authorization: every prd project that runs GKE or Cloud Run workloads enforces the attestor; non-prod in
       dry-run; attestor key is asymmetric and in HSM
  DP07 only the build identity can sign or attach attestations
  DP08 D5 carries the matching org policies (Cloud Run Binary Authorization in prd, trusted image project for MIGs)
Status: implemented + locally tested; nothing applied (T-S1..T-S6).
"""
import argparse
import json
import pathlib
import sys

from tools.access.matrix import Matrix
from tools.identity.derive import derive
from tools.policy.orgpolicy import OrgPolicies
from tools.registry.loader import load_yaml
from tools.registry.validate import Finding

AGENT = {
    "storage": "service-${PROJECT_NUMBER:%s}@gs-project-accounts.iam.gserviceaccount.com",
    "secretmanager": "service-${PROJECT_NUMBER:%s}@gcp-sa-secretmanager.iam.gserviceaccount.com",
    "cloudsql": "service-${PROJECT_NUMBER:%s}@gcp-sa-cloud-sql.iam.gserviceaccount.com",
    "binauthz": "service-${PROJECT_NUMBER:%s}@gcp-sa-binaryauthorization.iam.gserviceaccount.com",
}
ENCRYPTER = "roles/cloudkms.cryptoKeyEncrypterDecrypter"


def folder_of(project):
    tier = "prd" if project.endswith("-prd") or "-prd-" in project else "nonprd"
    return f"fldr-tenants/{tier}" if project.startswith("t-") else f"fldr-platform/{tier}"


class DataProtection:
    def __init__(self, registry_root="registry", security_root="security"):
        sec = pathlib.Path(security_root)
        self.path = str(sec / "data-protection.yaml")
        self.cfg = load_yaml(self.path)
        self.matrix = Matrix(registry_root, security_root)
        self.reg = self.matrix.reg
        self.plan = derive(self.reg)
        self.org = OrgPolicies(sec / "org-policies.yaml")

    # ---------------- generation ----------------
    def generate(self):
        c, region = self.cfg, self.cfg["region"]
        kms, keys, secrets, buckets = c["kms"], {}, [], []

        def tenant_key(tenant, product, env, project, agent):
            ring = kms["tenant"]["key_ring"].format(tenant=tenant, tier="prd", region_short=region["short"])
            name = kms["tenant"]["key"].format(product=product, env=env)
            k = keys.setdefault(f"{project}/{ring}/{name}", self._key(project, ring, name, "tenant", tenant))
            member = AGENT[agent] % project
            if member not in k["encrypter_decrypter"]:
                k["encrypter_decrypter"].append(member)
            return f"projects/{project}/locations/{region['name']}/keyRings/{ring}/cryptoKeys/{name}"

        sa_tenant = {s["email"]: s for s in self.plan["service_accounts"].values()}
        for r in self.plan["resource_iam"].values():
            env = r["resource"].split("-")[1] if r["resource_type"] == "secret" else r["resource"].split("-")[2]
            prd = env == "prd"
            sa = sa_tenant[r["member"].split(":", 1)[1]]
            if r["resource_type"] == "secret" and r["role"] == "roles/secretmanager.secretAccessor":
                secrets.append({
                    "project": r["project"], "secret_id": r["resource"], "tenant": r["tenant"], "product": sa["product"],
                    "env": env, "replication": c["secrets"]["replication"], "accessor": r["member"],
                    "kms_key": tenant_key(r["tenant"], sa["product"], env, r["project"], "secretmanager") if prd else None,
                    "labels": {"tenant": r["tenant"], "product": sa["product"], "env": env},
                    "annotations": {"rotation-review-days": str(c["secrets"]["rotation_review_days"])},
                    "version_destroy_ttl": f"{c['secrets']['version_destroy_ttl_days'] * 86400}s"})
            if r["resource_type"] == "storage_bucket" and r["role"] == "roles/storage.objectAdmin":
                buckets.append({"project": r["project"], "bucket": r["resource"], "tenant": r["tenant"],
                                "location": region["name"],
                                "default_kms_key": tenant_key(r["tenant"], sa["product"], env, r["project"], "storage")
                                if prd else None})
        for name, pool in {**self.reg.inventory["sql_pools"], **self.reg.inventory.get("product_sql_pools", {})}.items():
            if pool["env"] != "prd":
                continue
            p = kms["platform"]
            ring = p["key_ring"].format(tier="prd", region_short=region["short"])
            k = keys.setdefault(f"{p['project']}/{ring}/{name}", self._key(p["project"], ring, name, "platform", None))
            k["encrypter_decrypter"].append(AGENT["cloudsql"] % pool["project"])
            k["sql_instance"] = {"pool": name, "project": pool["project"]}

        sc = c["supply_chain"]
        att = sc["attestor"]
        attestor = f"projects/{att['project']}/attestors/{att['name']}"
        enforcing = {}
        for cell in self.reg.inventory["gke_cells"].values():
            tier = "prd" if cell["env"] == "prd" else "nonprd"
            enforcing.setdefault(cell["project"], {"tier": tier, "runtimes": set()})["runtimes"].add("gke")
        for s in self.plan["service_accounts"].values():
            if s["runtime"] == "cloudrun" and s["purpose"] == "app":
                enforcing.setdefault(s["project"], {"tier": s["env_tier"], "runtimes": set()})["runtimes"].add("cloudrun")
        policies = []
        for project, e in sorted(enforcing.items()):
            mode = sc["binary_authorization"][e["tier"]]
            policies.append({"project": project, "tier": e["tier"], "runtimes": sorted(e["runtimes"]),
                             "global_policy_evaluation_mode": sc["binary_authorization"]["global_policy_evaluation"],
                             "default_admission_rule": {**mode, "require_attestations_by": [attestor]},
                             "verifier": {"attestor": attestor, "role": "roles/binaryauthorization.attestorsVerifier",
                                          "member": AGENT["binauthz"] % project}})
        return {"keys": sorted(keys.values(), key=lambda k: k["id"]), "secrets": secrets, "buckets": buckets,
                "binauthz_policies": policies,
                "attestor": {**att, "resource": attestor,
                             "key_resource": f"projects/{att['project']}/locations/{region['name']}/keyRings/"
                                             f"{att['key']['key_ring']}/cryptoKeys/{att['key']['key']}"}}

    def _key(self, project, ring, name, kind, tenant):
        k = self.cfg["kms"]
        return {"id": f"{project}/{ring}/{name}", "project": project, "key_ring": ring, "key": name, "kind": kind,
                "tenant": tenant, "location": self.cfg["region"]["name"], "purpose": k["purpose"],
                "protection_level": k["protection_level"], "rotation_period": f"{k['rotation_days'] * 86400}s",
                "destroy_scheduled_duration": f"{k['destroy_scheduled_days'] * 86400}s",
                "encrypter_decrypter": []}

    # ---------------- checks ----------------
    def check(self, out=None):
        out = out or self.generate()
        f, P, c = [], self.path, self.cfg
        keys = {k["id"]: k for k in out["keys"]}

        def key_id(res):
            parts = res.split("/")
            return f"{parts[1]}/{parts[5]}/{parts[7]}"

        for s in out["secrets"]:
            if s["env"] == "prd":
                if not s["kms_key"] or keys.get(key_id(s["kms_key"]), {}).get("project") != s["project"]:
                    f.append(Finding("DP01", P, f"prd secret {s['project']}/{s['secret_id']} needs a CMEK key in its project"))
        for b in out["buckets"]:
            if b["bucket"].split("-")[2] == "prd":
                if not b["default_kms_key"] or keys.get(key_id(b["default_kms_key"]), {}).get("project") != b["project"]:
                    f.append(Finding("DP01", P, f"prd bucket {b['bucket']} needs a CMEK key in its project"))
            if b["location"] != c["region"]["name"]:
                f.append(Finding("DP03", P, f"bucket {b['bucket']} outside {c['region']['name']}"))
        prd_pools = [n for n, p in {**self.reg.inventory["sql_pools"],
                                    **self.reg.inventory.get("product_sql_pools", {})}.items() if p["env"] == "prd"]
        for n in prd_pools:
            if not any(k.get("sql_instance", {}).get("pool") == n for k in out["keys"]):
                f.append(Finding("DP01", P, f"prd pool {n} has no CMEK key"))

        for k in out["keys"]:
            user_folder = folder_of(k["sql_instance"]["project"]) if k.get("sql_instance") else folder_of(k["project"])
            eff = self.org.effective(user_folder, "gcp.restrictCmekCryptoKeyProjects")
            allowed = eff.get("values", [])
            ok = f"projects/{k['project']}" in allowed or (
                k["project"].startswith("t-") and any(v.startswith("under:folders/fldr-tenants/prd") for v in allowed))
            if eff["kind"] == "allow" and not ok:
                f.append(Finding("DP02", P, f"key {k['id']} is in a project D5 does not allow for {user_folder}"))
            if k["location"] != c["region"]["name"]:
                f.append(Finding("DP03", P, f"key {k['id']} not in {c['region']['name']}"))
            for m in k["encrypter_decrypter"]:
                if not (m.startswith("service-") and m.split("@")[1].startswith(("gs-project-accounts", "gcp-sa-"))):
                    f.append(Finding("DP04", P, f"key {k['id']}: {m} is not a service agent"))
            if int(k["rotation_period"][:-1]) > 90 * 86400:
                f.append(Finding("DP04", P, f"key {k['id']}: rotation longer than 90 days"))
            if int(k["destroy_scheduled_duration"][:-1]) < 30 * 86400:
                f.append(Finding("DP04", P, f"key {k['id']}: destroy schedule shorter than 30 days"))
        locs = self.org.effective("org", "gcp.resourceLocations").get("values", [])
        if c["region"]["location_value"] not in locs:
            f.append(Finding("DP03", P, f"region {c['region']['name']} not allowed by D5 gcp.resourceLocations"))
        for kb in self.matrix.bindings():
            if kb["role"] == ENCRYPTER:
                f.append(Finding("DP04", P, f"{kb['principal']} holds {ENCRYPTER} in the access matrix"))

        if c["secrets"].get("terraform_manages_values") is not False:
            f.append(Finding("DP05", P, "Terraform must not manage secret values (state is readable by plan identities)"))
        for s in out["secrets"]:
            if f"@{s['project']}." not in s["accessor"] or not s["accessor"].split(":")[1].startswith(f"{s['tenant']}-"):
                f.append(Finding("DP05", P, f"secret {s['project']}/{s['secret_id']} read by {s['accessor']}"))
        for b in self.matrix.bindings():
            if b["role"] == "roles/secretmanager.secretVersionAdder":
                cond = b.get("condition") or ""
                if "product" not in b["values"] or f"startsWith('{b['values']['product']}-')" not in cond:
                    f.append(Finding("DP05", P, f"{b['principal']}: secretVersionAdder must be limited to its product"))
            if b["role"] == "roles/secretmanager.secretAccessor":
                f.append(Finding("DP05", P, f"{b['principal']} reads secret values via the access matrix"))

        sc = c["supply_chain"]
        prd_runtime_projects = {s["project"] for s in self.plan["service_accounts"].values()
                                if s["runtime"] == "cloudrun" and s["env"] == "prd"} | \
                               {cell["project"] for cell in self.reg.inventory["gke_cells"].values() if cell["env"] == "prd"}
        pol = {p["project"]: p for p in out["binauthz_policies"]}
        for proj in sorted(prd_runtime_projects):
            p = pol.get(proj)
            if not p or p["default_admission_rule"]["enforcement_mode"] != "ENFORCED_BLOCK_AND_AUDIT_LOG" \
                    or p["default_admission_rule"]["evaluation_mode"] != "REQUIRE_ATTESTATION" \
                    or out["attestor"]["resource"] not in p["default_admission_rule"]["require_attestations_by"]:
                f.append(Finding("DP06", P, f"prd project {proj} does not enforce the build attestation"))
        for p in out["binauthz_policies"]:
            if p["tier"] == "nonprd" and p["default_admission_rule"]["enforcement_mode"] != "DRYRUN_AUDIT_LOG_ONLY":
                f.append(Finding("DP06", P, f"non-prod project {p['project']} should be dry-run (unsigned dev snapshots)"))
        ak = sc["attestor"]["key"]
        if ak["purpose"] != "ASYMMETRIC_SIGN" or ak["protection_level"] != "HSM":
            f.append(Finding("DP06", P, "attestor key must be an asymmetric signing key in HSM"))

        for b in self.matrix.bindings():
            if (b["scope"] == f"kms:{sc['attestor']['project']}/{ak['key']}" and b["role"] == "roles/cloudkms.signerVerifier") \
                    or (b["scope"].startswith("attestor:") and b["role"].startswith("roles/containeranalysis")):
                if b["principal"] != sc["attestor"]["signer"]:
                    f.append(Finding("DP07", P, f"{b['principal']} can sign or attach attestations"))
        if not any(b["principal"] == sc["attestor"]["signer"] and b["role"] == "roles/cloudkms.signerVerifier"
                   for b in self.matrix.bindings()):
            f.append(Finding("DP07", P, "the build identity has no signing grant"))

        for folder in ("fldr-tenants/prd", "fldr-platform/prd"):
            e = self.org.effective(folder, "run.allowedBinaryAuthorizationPolicies")
            if e.get("values") != ["default"]:
                f.append(Finding("DP08", P, f"{folder}: run.allowedBinaryAuthorizationPolicies must allow only 'default'"))
        mig_projects = {s["project"] for s in self.plan["service_accounts"].values() if s["runtime"] == "mig"}
        for proj in sorted(mig_projects):
            e = self.org.effective(folder_of(proj), "compute.trustedImageProjects")
            if e.get("values") != [f"projects/{sc['vm_images']['trusted_image_project']}"]:
                f.append(Finding("DP08", P, f"{proj}: compute.trustedImageProjects must allow only shr-build"))
        return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="registry")
    ap.add_argument("--security", default="security")
    ap.add_argument("-o", "--out", default="build/data-protection.json")
    a = ap.parse_args(argv)
    dp = DataProtection(a.registry, a.security)
    out = dp.generate()
    findings = dp.check(out)
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(out, indent=2, default=sorted) + "\n")
    for x in findings:
        print(f"{x.rule}: {x.message}")
    print(f"{len(out['keys'])} keys, {len(out['secrets'])} secrets, {len(out['buckets'])} buckets, "
          f"{len(out['binauthz_policies'])} Binary Authorization policies, {len(findings)} finding(s) -> {a.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
