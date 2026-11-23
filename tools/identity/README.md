# Identity plan (Stage 3 – D2)

`python3 -m tools.identity.derive registry -o build/identity-plan.json`

Generates a deterministic, Terraform-ready JSON plan from the **validated** registry (it refuses to run on an invalid registry). Stage 5 modules consume it with `for_each`; nothing in it is hand-written.

| Section | Content |
|---|---|
| `service_accounts` | One SA per customer-product-environment (`app`, `mig`, optional `ro`) in `t-<cust>-<env_tier>`; product SAs for Shared/Cohort products in `p-<product>-<env_tier>`. Every SA declares `tenant_scope` (`single`/`multi`), `isolation_boundary` and `served_tenants` |
| `workload_identity_bindings` | `roles/iam.workloadIdentityUser` for KSA `<product>` / `<product>-migrate` in namespace `<cust>-<product>-<env>` → its own GSA |
| `kubernetes_namespaces` | Namespaces with tenant labels per GKE cell (baseline policies come in D8) |
| `cloud_sql_databases` | `<cust>_<product>` on the placed pool (Shared/Cohort: on the product-owned pool **registered** in `inventory.yaml` → `product_sql_pools`, validator rule R17) |
| `cloud_sql_iam_users` | `CLOUD_IAM_SERVICE_ACCOUNT` users; MySQL username = SA local part (M1). Grants are generated in D4 |
| `group_memberships` | Workload SAs → `grp-wl-sqlconn-<tier>-NN` (mechanism 1: connect only) |
| `project_iam` | Individual connect bindings where no shared pool group applies (product projects, dedicated instances) |
| `resource_iam` | Per-tenant data access for Dedicated identities: bucket (app objectAdmin, ro objectViewer), secret (app secretAccessor) |

## Isolation boundary – two models, stated explicitly

| Model | Identity | Database access | Where the customer boundary is enforced |
|---|---|---|---|
| **Dedicated** | One SA per customer-product-environment (`tenant_scope: single`) | Exactly one database (`<cust>_<product>`) | **IAM identity + MySQL grants** (`isolation_boundary: identity-and-database`); the tests prove no Dedicated grant crosses tenants |
| **Shared / Cohort** | One product SA per environment (and cohort) serving several customers (`tenant_scope: multi`) | One MySQL database **per customer**, but the **same identity can reach all of them** in that deployment | **Application** (`isolation_boundary: application`) – ADR-006 rev. 3. Separate databases limit accidental mixing and make per-customer export/restore possible, but they are **not** an identity-level boundary |

Bounds the tests do enforce for multi-tenant identities:
- only their own product's databases;
- only on their own registered product pool and environment;
- only for the tenants in their deployment (a different cohort means a different identity);
- never on a tenant (`sql-*`) pool; and Dedicated identities never on a product (`psql-*`) pool.

Notes
- Project names are **logical** (`t-abc-prd`); Stage 5 maps them to real project IDs, which carry a random suffix. The Workload Identity member therefore shows `plt-gke-prd.svc.id.goog` instead of the real pool `<PROJECT_ID>.svc.id.goog`.
- Bucket names are logical; Stage 5 appends the global-uniqueness suffix.
- The plan is declarative: removing a subscription removes its entries, and Terraform destroys them (offboarding).

Status: **implemented, locally tested** (`tests/test_identity.py`, including two customers on one Shared product and on one Cohort; golden file `tests/golden/identity-plan.json` as regression guard). **Not cloud-tested.**
