# ADR-002: Environment-first folder hierarchy

- **Status:** Proposed (Stage 2 baseline)
- **Date:** 2026-11-22

## Context
Folders inherit IAM bindings and organisation policies. The two candidate axes are environment (prod / non-prod) and customer.

## Decision
`Organization → fldr-tenants → {prd, nonprd} → t-<cust>-<tier>` (and the same split under `fldr-platform`). Customer grouping is expressed with **labels and tags** (`tenant=abc`, `isolation_tier=standard`). (Stage 2 review K2: the former `tier` label was split into `env_tier` and `isolation_tier`.)

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Customer-first: `tenants/<cust>/{prd,nonprd}` | One binding gives a customer team access to all that customer's environments; offboarding deletes one folder | Prod policies, prod access groups and Shared VPC subnet access must be repeated per customer (or via tag-conditional policies); a parent folder cannot hold more than 300 child folders, so 500 customers need folder sharding |
| Hybrid: `tenants/{prd,nonprd}/<cust>` | Both groupings | 2× folders, deeper tree, little practical gain |

## Rationale
The policies that matter most for security – production org policies, production access, production networking – are uniform per environment and different per environment. Environment-first sets each of them **once**. Per-customer access is needed too, but it is created by the project factory from the tenant file, so it does not require a folder.

## Disadvantages
- Per-customer IAM is applied per project (2 per customer) rather than once per folder – automated, but more bindings to audit.
- "Show me everything for ABC" relies on labels/tags and Cloud Asset Inventory queries, not on the folder tree.

## Revisit when
- Customers need materially different policies from each other (e.g. many regulated customers each with unique constraints).
- An external requirement mandates per-customer folders (e.g. customer-delegated administration).
