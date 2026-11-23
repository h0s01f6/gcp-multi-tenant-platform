# D8 – Kubernetes policy constraints (Gatekeeper / Policy Controller)

Status: **implemented; Rego not executed** (no `opa`/`gator` in this workspace). Python tests check structure, parameters and the rendered baseline. Validation: T-K1 (Policy Controller on Autopilot), T-K19 (`opa test` + `gator verify`, `namespaceObject` availability).

| Template (`src/<name>.rego`) | Rule | Why |
|---|---|---|
| `platformnamespacebaseline` | Managed namespaces carry `tenant, product, env, env_tier, deployment_model`; Pod Security `restricted`; name = `<tenant>-<product>-<env>` (or `shr-/coh-<product>-…-<env>`) | Labels drive every other policy; PSA blocks privileged pods, host namespaces, hostPath, privilege escalation |
| `platformhttproutehostnames` | HTTPRoute hostnames must equal the namespace's derived hostname; shared namespaces only their served tenants' hostnames (parameter from the registry); empty hostname list denied | Review A6 – hostname hijack on the shared Gateway |
| `platformallowedimages` | Images only from `shr-artifacts`; release images always by digest; digest required outside dev; snapshot repo only in dev | ADR-010; complements Binary Authorization (D9) |
| `platformtenantseparation` | Workload-separation key `platform.example.com/tenant` only with the pod's own tenant value, only for `enhanced`/`dedicated` tiers, and mandatory for them | ADR-004 enhanced tier on Autopilot |

```bash
python3 -m tools.k8s.baseline registry      # renders build/k8s/<cell>/*.yaml and constraint-templates.yaml
opa test policies/k8s/src -v                # NOT run here (opa not installed) – T-K19
```

`constraint-templates.yaml` is generated from `src/` (do not edit). Constraints with registry-derived parameters are rendered per cell into `build/k8s/<cell>/_cluster.yaml`.
