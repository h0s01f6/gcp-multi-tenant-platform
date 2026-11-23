# Stage 4 – Networking (consolidated)

Stage 4 turns the approved Stage 2 network design (§5.2, diagram 11) and the Stage 3 security configuration into an implementation-ready network plan. No new networking product is introduced: Shared VPC, Cloud NAT, Cloud NGFW, Private Google Access, private services access (PSA), global external Application Load Balancers with Cloud Armor, Certificate Manager and Cloud DNS were all in Stage 2.

**Status legend** as in Stage 3. Everything here is *Proposed* configuration with generators and checks that are *Locally tested*. **Nothing is cloud-tested.**

## 1. Deliverables

| Step | Content | Files | Checks | Generated output (Stage 5 input) | Status | GCP validation |
|---|---|---|---|---|---|---|
| N1 | IP address plan | `network/ip-plan.yaml`, `tools/network/ipam.py` | IP01–IP04 | `build/ip-plan.json` | Locally tested | T-N3 |
| N2 | VPCs, subnets, Shared VPC, runtime network settings | `network/vpc.yaml`, `tools/network/vpc.py` | NW01–NW07 | `build/network-plan.json` | Locally tested | T-N1, T-N4–T-N7 |
| N3 | Firewall (hierarchical + network policies, secure tags, egress allow-list) | `network/firewall.yaml`, `network/egress.yaml`, `tools/network/firewall.py` | FW01–FW07 (+ D8 KB03) | `build/firewall.json` | Locally tested | T-N8, T-N9 |
| N4 | DNS, certificates, ingress, Cloud Armor, Cloud NAT | `network/edge.yaml`, `tools/network/edge.py` | IN01–IN07 | `build/edge.json` | Locally tested | T-N10–T-N12, T-L1 |
| N5 | Consolidation, quota register (B14), diagram 11 | this document, `network/quotas.yaml`, `tools/network/quotas.py` | QU01–QU02 | – | Locally tested | quotas marked `null` |

```bash
python3 -m tools.check_all      # D1–D10 and N1–N5
```

## 2. Environment isolation

| Layer | Control |
|---|---|
| Networks | `vpc-prd` (10.64.0.0/10) and `vpc-nonprd` (10.128.0.0/10) in separate host projects; never peered (NW07); only the PSA service peering exists |
| Attachment | Each service project attaches only to its tier's host project (NW02); D5 `compute.restrictSharedVpcSubnetworks` allows only that tier's host project (NW05) |
| Subnet use | Network User only on the tier's subnets, only through `grp-wl-netusers-<tier>` (NW06; D3 grant moved from project to subnets) |
| Firewall | Tier folder policies deny the other tier's /10 in both directions (FW05), in addition to the networks being separate |
| DNS / ingress | Separate public zones (`<product>.example.com` vs `<product>.nonprod.example.com`), certificates and load balancers per tier |
| Cloud SQL | One PSA range per tier; a pool is reachable only from its tier's VPC (NW03, T-N6) |

## 3. Address plan

See `network/README.md` for the full table. One /10 per tier, one /11 per region (asia-south1 active, asia-south2 reserved for DR), RFC 1918 only, 10.0.0.0/10 kept free for corporate connectivity. Each GKE cell has a fixed slot (prod 16, non-prod 3 × 16) with its own subnet, node range, Pod range plus an equal reserve range (Autopilot may choose more Pods per node than the default of 32 – R-N1-1) and Service range. Cloud Run egress, PSA and MIG ranges are per tier. All sizes are checked against the capacity-model upper bound (500 customers × 20 products).

## 4. Runtime connectivity

| Runtime | Inbound | Outbound | Cloud SQL |
|---|---|---|---|
| GKE (Autopilot, private nodes, DNS-based control-plane endpoint) | Gateway `gw-<product>-<env>-<nn>` (global external) → container-native LB → Pods on 8080; routes only from namespaces with the Gateway's product and env labels; D8 hostname policy | NetworkPolicy default deny (D8) + FQDN allow-list per product from the product's Pod ranges | PSA range :3307 via connectors |
| Cloud Run (Direct VPC egress, `all-traffic`) | ALB `um-<product>-<env>` in `plt-ingress-<tier>` → serverless NEG; ingress `internal-and-cloud-load-balancing` | Run subnet → firewall policy → Cloud NAT; FQDN allow-list for the tier's Cloud Run products (K26) | PSA :3307 |
| MIG (no external IP, secure tags `wl=mig`, `app=<product>`) | ALB → instance group on 8080; IAP SSH for Ansible; no VM-to-VM | Per-product FQDN allow-list by secure tag via Cloud NAT | PSA :3307 |
| Cloud SQL | Private IP only, connectors enforced (`connector_enforcement = REQUIRED`) | – | – |

Google APIs and Artifact Registry are reached through Private Google Access (`private.googleapis.com`, private zones `googleapis.com` and `pkg.dev`), switching to the restricted VIP when VPC Service Controls are enforced (K6).

## 5. Firewall layering

1. **`fw-org`** (organisation): IAP, Google LB/health-check ranges and 10.0.0.0/8 *go to next*; everything else is denied.
2. **`fw-tier-prd` / `fw-tier-nonprd`** (both tier folders): deny the other tier's /10 in both directions.
3. **No platform VPC (classic) rules** – a classic allow would end evaluation before the network policy's default-deny egress. GKE creates its own classic rules.
4. **`fwp-<tier>`** (global network firewall policy, secure tags): IAP SSH to `wl=mig` only; LB to `wl=mig` / `wl=gke-node` on 8080; deny MIG east-west; egress to PSA :3307, the PGA VIP :443, intra-cluster ranges, one FQDN rule per product; **default deny egress**.

## 6. DNS and certificates

- One public zone per product per tier in the tier host project, DNSSEC on. A records are generated from the registry: one per hostname, pointing to the frontend address of the customer's product and environment. Hand-typed hostnames are impossible (IN01).
- Certificate Manager wildcard per product per tier (`*.payroll.example.com`, `*.payroll.nonprod.example.com`) with DNS authorisation; every hostname is a single label under its wildcard (IN03).
- Private zones per VPC for Private Google Access.

## 7. Corrections and integration changes

| ID | Change |
|---|---|
| K26 | Stage 2 said Cloud Run FQDN egress would use network tags. Hierarchical rules cannot target network tags and Cloud Run cannot be targeted by Resource Manager tags, so Cloud Run egress is matched by its subnet; per-product granularity applies to MIG and GKE only (R-N3-1). Architecture §5.2 and diagram 11 updated |
| D3 | `grp-wl-netusers-<tier>`: Network User moved from host project to tier subnets (deferred in D3) |
| D8 | Cloud SQL range placeholders replaced by PSA ranges (A-D8-1 closed); products with an egress allow-list get an `allow-internet-egress` NetworkPolicy (declared ports, public addresses only); KB03 still rejects any other 0.0.0.0/0 |
| Diagram 11 | IP plan, per-cell subnets, firewall layering, K26 |

## 8. Carried to Stage 5 (Terraform) and Stage 6 (Helm)

- **Terraform** consumes `build/ip-plan.json`, `network-plan.json`, `firewall.json`, `edge.json`. It creates VPCs, subnets, PSA, Shared VPC attachments, subnet IAM, service-agent group memberships, firewall policies and tags, Cloud NAT, DNS zones and records, certificates, ALBs and URL maps, Cloud Armor and the GKE clusters with their network settings. The project-level subnet constraint for `shr-cicd-<tier>` (R-N2-1) is added there.
- **Gateways** (`gateway-infra` namespace, one per product per environment per cell) are platform objects, created with the cluster by the platform layer, not by application charts.
- **Helm** application charts only create `HTTPRoute`s with explicit hostnames (D8), serve on port 8080 named `http` (A-N3-1), and create no NetworkPolicies, Services of type LoadBalancer/NodePort, or ServiceAccounts (A-D8-3).

## 9. Outstanding GCP validation

T-N1 (service projects per host, Q20), T-N3–T-N12, T-L1, and the network quotas marked `null` in `network/quotas.yaml`. Suggested order: T-N3 + T-N4 (build the plan and permissions) → T-N6, T-N7 (database and control-plane reachability) → T-N8, T-N9 (firewall behaviour) → T-N10, T-N11 (DNS, certificates, load balancers) → T-N5, T-N12 (scale of Cloud Run egress and NAT).
