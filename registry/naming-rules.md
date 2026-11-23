# Tenant registry – naming rules and validation (schema v2.1)

> Stage 2 final corrections (2026-11-22), review ID **K18**. Enforced by `tools/registry/naming.py` and `tools/registry/validate.py` (rule R11), tested by `tests/test_naming.py`. Wiring into the registry PR job is Stage 7.

## Why these rules exist
- Google IAM service-account IDs: **6–30 characters**, lowercase letters, digits and hyphens, starting with a letter and not ending with a hyphen (`[a-z]([-a-z0-9]*[a-z0-9])`).
- Cloud SQL for MySQL uses the SA's local part as the MySQL username; MySQL 8.x usernames are limited to **32 characters**, and the name must be unique on each shared pool (M1).
- Names must split unambiguously into customer / product / environment.

## Slug rules

| Field | Regex | Length |
|---|---|---|
| `tenant` (customer slug) | `^[a-z][a-z0-9]{2,9}$` | 3–10, no hyphens |
| product slug (catalogue key) | `^[a-z][a-z0-9]{1,10}$` | 2–11, no hyphens |
| environment | `dev`, `stg`, `uat`, `prd` | 3 |

## Derived names (never written by hand in tenant files)

| Name | Pattern | Max |
|---|---|---|
| App SA ID | `<cust>-<product>-<env>` | 26 |
| Read-only SA ID | `<cust>-<product>-<env>-ro` | 29 |
| Migration SA ID | `<cust>-<product>-<env>-mig` | **30** (limit 30) |
| MySQL username | SA ID | 30 (limit 32) |
| MySQL role | `r_<cust>_<product>_<app\|ddl\|ro>` | 28 (limit 32) |
| Database | `<cust>_<product>` | 22 (limit 64) |
| Namespace / Helm release | `<cust>-<product>-<env>` | 26 (limit 63) |

## Validation rules (registry PR job)
1. `tenant` and every subscribed product slug match the regexes above.
2. Every derived SA ID is 6–30 characters and matches the IAM regex; every MySQL name is ≤ 32.
3. Derived names are unique across the registry (no two tenant/product pairs produce the same SA ID or database name).
4. Tenant files contain no free-form resource names or hostnames (A6).
5. Product slugs are validated once in the catalogue, so a too-long product is rejected before any customer subscribes to it.

## Boundary tests (in `tests/test_naming.py`)

| Case | Input | Expected |
|---|---|---|
| Longest valid | `abcdefghij` + `abcdefghijk` + `prd` → migration SA `abcdefghij-abcdefghijk-prd-mig` (30) | valid |
| Customer slug too long | 11-char customer → migration SA 31 | rejected |
| Product slug too long | 12-char product → migration SA 31 | rejected |
| Shortest valid | `abc` + `hr` + `dev` → `abc-hr-dev` (10) | valid |
| Customer too short | `ab` | rejected |
| Hyphen in slug | `ab-c`, `pay-roll` | rejected |
| Uppercase / leading digit | `ABC`, `1abc` | rejected |
| Unknown environment | `qa` | rejected |
| Duplicate entries | same subscription twice in a file (R01), same tenant in two files (R04), duplicate deployment or derived-name collision (R12) | rejected (`tests/test_registry.py`) |
