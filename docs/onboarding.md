# Runbooks

## Onboard a new customer

1. Pick the next free `subnet_index` (CI rejects duplicates) and create `config/tenants/<customer>/tenant.yaml`:
   ```yaml
   customer: initech
   display_name: Initech
   region: asia-south1
   network: { subnet_index: 3 }
   gke:
     dev:   { mode: pooled, cluster: gke-dev-pool-01 }
     stage: { mode: pooled, cluster: gke-stage-pool-01 }
     uat:   { mode: pooled, cluster: gke-uat-pool-01 }
     prod:  { mode: pooled, cluster: gke-prod-pool-01 }
   budgets_usd: { dev: 300, stage: 300, uat: 500, prod: 3000 }
   data_sharing: { masked_from_prod_to: [dev, stage, uat], raw_from_prod_to: [] }
   access: { support_group: initech-support@example.com }
   ```
2. Add one release file per product and env, for example `config/tenants/initech/dev/orders.yaml`.
3. Open a PR. CI validates the config, then plans `tenants/initech/{dev,stage,uat}`.
4. After merge, the pipeline applies `5-tenant-base` (folder, 5 projects, CMEK, perimeter in **dry-run**) and then `6-tenant-env` for each env. Argo CD creates the namespaces and Applications.
5. Check the VPC-SC dry-run logs. Once they're clean, set `vpc_sc_enforced: true` in `tenant.yaml`.

## Promote a version for one customer

Edit `version` in the next environment's file (`dev → stage → uat → prod`). For Cloud Run, a canary can be staged first:

```yaml
cloudrun:
  canary: { version: "1.9.0", percent: 10 }
```

Remove `canary` and set `version: "1.9.0"` to complete the rollout.

## Customer-specific build (last resort)

1. Branch `customer/<customer>/<major.minor>` from the release tag. CI publishes `<version>-<customer>.<n>`.
2. Pin it in that customer's release files. The validator only accepts it for that customer, and only when the base version is still supported.
3. Track it as debt and remove it at the next upgrade.

## Move a customer from pooled to dedicated GKE

1. Set `gke.prod: { mode: dedicated, cluster: <customer>-prod-dedicated, dedicated_index: <free> }` and update `cluster:` in the prod GKE release files.
2. Apply `6-tenant-env` for prod. This creates the cluster and switches the Workload Identity binding to the customer project's pool.
3. Argo CD deploys to the new cluster. Switch DNS, then the old pooled namespace is pruned.

## Offboard a customer

1. Remove the release files. Argo CD prunes the workloads, and `6-tenant-env` destroys the Cloud Run and MIG resources.
2. Run `terraform destroy` on `tenants/<customer>/<env>` for each env, then on `tenants/<customer>/base`. The KMS keys have `prevent_destroy`, so you destroy the key versions deliberately to crypto-shred the data.
3. Free up the `subnet_index`.
