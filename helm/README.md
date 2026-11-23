# Helm (Stage 6)

Status: **implemented and locally tested** – charts rendered with Go `text/template` (the engine Helm uses) through `tools/helmrender` and checked against the D8 rules and JSON schemas. Real `helm lint/template/install` is T-H1.

```
helm/
  charts/platform-lib/   library chart: Deployment, Service, HTTPRoute, HealthCheckPolicy, HPA, PDB, ConfigMap,
                         migration Job, Cloud SQL Auth Proxy sidecar, labels, security contexts
  charts/payroll/        product chart (GKE product of the example registry) = platform-lib + values + schema
  environments/          dev / stg / uat / prd sizing shared by all releases
```

One release per customer namespace: `helm upgrade --install payroll helm/charts/payroll -n abc-payroll-prd -f helm/environments/prd.yaml -f build/helm/gke-prd-as1-01/abc-payroll-prd/payroll.values.json`.

**What Helm creates:** Deployment (app + Cloud SQL Auth Proxy native sidecar), ClusterIP Service, HTTPRoute on the platform Gateway, HealthCheckPolicy, HPA, PDB, ConfigMap (customer `config`), pre-install/pre-upgrade migration Job.
**What Helm never creates:** Namespaces, ServiceAccounts, RBAC, NetworkPolicies, quotas, Gateways, load balancers, secrets, databases, IAM – those are Terraform (Stage 5) and the D8 baseline.

**Contract with Terraform:** `interfaces/helm-release.schema.json` – every generated field names its producer (`x-source`); a test checks each Terraform output exists. A new GKE product = a new chart directory with the eight one-line templates and its own `values.yaml`/schema.
