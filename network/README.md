# Networking (Stage 4)

| File | Step | Content | Status |
|---|---|---|---|
| `ip-plan.yaml` | N1 | Tier supernets, region blocks, per-cell GKE slots, planning inputs | Proposed values; allocator + checks (IP01–IP04) locally tested |
| `vpc.yaml` | N2 | VPC settings, subnets, PSA, GKE / Cloud Run / MIG / Cloud SQL network settings, service agents | Proposed values; generator + checks (NW01–NW07) locally tested |
| `firewall.yaml` | N3 | Hierarchical policies (org, tier folders), network firewall policy per VPC, secure tags | Proposed; generator + checks (FW01–FW07) locally tested |
| `egress.yaml` | N3/N4 | Internet egress allow-list per product (illustrative destinations, A-N4-1) | Proposed |
| `edge.yaml` | N4 | Public/private DNS, certificates, Gateways, ALBs / URL maps, Cloud Armor, Cloud NAT | Proposed; generator + checks (IN01–IN07) locally tested |
| `quotas.yaml` | N5 | Network quota register (B14) | Locally tested (QU01–QU02); `null` limits to confirm |

```bash
python3 -m tools.network.ipam    # N1 -> build/ip-plan.json
python3 -m tools.network.vpc     # N2 -> build/network-plan.json (subnets, attachments, runtime settings, netusers members)
python3 -m tools.network.firewall  # N3 -> build/firewall.json
python3 -m tools.network.edge    # N4 -> build/edge.json (zones, records, certificates, Gateways, ALBs, Cloud Armor, NAT)
python3 -m tools.network.quotas  # N5 quota register
```

## Address plan (asia-south1 active; asia-south2 reserved for DR)

| Block | prd (`vpc-prd`, 10.64.0.0/10) | nonprd (`vpc-nonprd`, 10.128.0.0/10) |
|---|---|---|
| Region asia-south1 | 10.64.0.0/11 | 10.128.0.0/11 |
| GKE Pods (cell slots) | 10.64.0.0/12 – 16 slots × (/17 + /17 reserve) | 10.128.0.0/12 – 48 slots (3 envs × 16) × (/19 + /19 reserve) |
| GKE Services | 10.80.0.0/15 – /20 per cell | 10.144.0.0/15 – /21 per cell |
| GKE nodes | 10.82.0.0/16 – /22 per cell | 10.146.0.0/16 – /22 per cell |
| Cloud Run egress `snet-<tier>-as1-run` | 10.83.0.0/16 | 10.147.0.0/16 |
| PSA (Cloud SQL) `psa-<tier>-01` | 10.84.0.0/16 | 10.148.0.0/16 |
| MIG `snet-<tier>-as1-mig` | 10.85.0.0/17 | 10.149.0.0/17 |
| Proxy-only (reserved, not created) | 10.85.128.0/23 | 10.149.128.0/23 |
| CI runner cluster (reserved, Q14) | 10.86.0.0/16 | 10.150.0.0/16 |
| Region asia-south2 (reserved) | 10.96.0.0/11 | 10.160.0.0/11 |

Reserved and never used by the platform: 10.0.0.0/10 (corporate / hybrid, A10), 10.192.0.0/10, 172.16.0.0/12, 192.168.0.0/16.

Design summary, isolation layers, firewall layering and carried-forward items: [`../documentation/stage-4-networking.md`](../documentation/stage-4-networking.md).
