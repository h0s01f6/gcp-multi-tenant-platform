# Tenant registry (schema v2.1)

The registry is the **source of truth** for customers, products, versions and placement. Every
identity, group membership, database grant and deployment is derived from it (Stage 3 D2–D4).

| Path | Content | Changed by |
|---|---|---|
| `schemas/tenant.schema.json`, `schemas/product.schema.json` | JSON Schema 2020-12 | Platform team |
| `platform/inventory.yaml` | Product groups, GKE cells, Cloud SQL for MySQL tenant pools (`sql_pools`) and product-owned pools (`product_sql_pools`) | Platform PRs only |
| `products/<product>.yaml` | Product catalogue: runtime, deployment model, database, resources, versions | Product team + platform review |
| `tenants/<tenant>.yaml` | One file per customer: subscriptions, versions/cohorts per environment, placement | Onboarding PRs |
| `naming-rules.md` | Slug rules and length budget (K18) | Platform team |

All example files are **illustrative**.

## Validate

```bash
python3 -m tools.registry.validate registry      # exit 0 = valid
python3 -m pytest -q tests                       # validator + naming tests
```

## Rules

| ID | Rule |
|---|---|
| R01 | YAML parses; **duplicate keys are rejected** (e.g. a subscription declared twice in one file) |
| R02 | File matches its JSON Schema (types, enums, slug regexes, no unknown fields) |
| R03 | File name equals the tenant / product slug |
| R04 | A tenant or product slug is defined in only one file |
| R05 | Subscribed product exists in the catalogue |
| R06 | Deployment model: Dedicated → `versions`; Shared → `config` only; Cohort → known `cohort` per environment |
| R07 | Promotion chain: environments must be `dev`, `dev+stg`, `dev+stg+uat` or all four |
| R08 | Versions match `supported_versions` and are not in `blocked_versions` |
| R09 | `prd` version is not newer than `uat` (history-based check of "passed UAT" is a Stage 7 pipeline step) |
| R10 | Placement exists for every deployed environment and matches the inventory: cell/pool environment, runtime, MySQL version, product group or split product pool |
| R11 | Naming rules and 30-character service-account budget (K18) |
| R12 | No duplicate (tenant, product, environment) deployment; no derived-name collision between tenants |
| R13 | `config` must not contain reserved keys (hostname, bucket, project …) – resource names are derived |
| R14 | `owners.technical` is the customer-support group family `grp-hum-cust-<tenant>-support`; the actual groups `…-support-prd` and `…-support-nonprd` are derived (K22, `security/groups.yaml`) |
| R15 | Product `pool_group` exists in the inventory and lists the product |
| R16 | Enhanced/Dedicated tenants use a prod instance dedicated to them; standard tenants never use one |
| R17 | Shared/Cohort products with a database have a **registered** product-owned pool (`product_sql_pools`) for every environment they are deployed in; pool name `psql-<product>-<env>-NN`, project `p-<product>-<env_tier>`, matching MySQL version, owner not Dedicated. Tenant placement cannot reference these pools |

Capacity headroom at placement time (choosing a pool or cell with space) is a Stage 7 pipeline step that **writes** placement; this validator **checks** it.
