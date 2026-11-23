# Worked examples – ABC and XYZ (Stages 5 and 6)

Generated from the example registry (`registry/tenants/abc.yaml`, `xyz.yaml`) – refresh with `python3 -m tools.iac.examples`; `tests/test_examples.py` fails if they are stale.

| File | Shows |
|---|---|
| `terraform/tenant-abc-prd.auto.tfvars.json`, `tenant-xyz-prd…`, `tenant-abc-nonprd…` | Inputs of the tenant stack: ABC and XYZ get separate projects, SAs, keys, buckets, secrets, SQL users, Cloud Run service (CRM) and backend services – nothing shared |
| `helm/<tenant>-payroll-<env>.values.json` | Generated Helm values (contract `interfaces/helm-release.schema.json`): ABC prd runs payroll 2.0.2, XYZ prd 1.5.3, ABC dev 2.1.0, XYZ dev 2.0.2 – per-customer versions |
| `helm/abc-payroll-prd.rendered.yaml` | The manifests the payroll chart renders for ABC prod |
