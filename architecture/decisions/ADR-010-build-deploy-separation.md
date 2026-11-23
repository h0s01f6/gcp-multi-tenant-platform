# ADR-010: Separate build from deploy, and prod from non-prod pipelines

- **Status:** Proposed (Stage 2 review, 2026-11-22)
- **Review IDs:** A5, F9, P2–P6

## Context
The assignment requires production to be isolated from non-production and automation to use dedicated identities **[C10]**. Stage 2 had separate prod/non-prod deployer SAs and runner pools, but: VM images were baked on the non-prod runner and used in prod; Artifact Registry writers were not separated; Terraform state for both tiers lived in one bucket; nothing stopped a workflow from targeting prod runners.

## Decision
1. **Build** happens only in `shr-build` (ephemeral runners, identity `builder@shr-build`). It produces images, Helm charts and VM images, scans them and signs them (attestations).
2. **Artifact Registry** in `shr-artifacts` has a `release` repository writable only by `builder@shr-build`, and a `snapshot` repository for developer builds that only the Dev environment may pull.
3. **Prod deploys only signed release artifacts by digest.** Binary Authorization in prod clusters and Cloud Run enforces the attestation **[R]**.
4. **Deployer identities:** `deploy-nonprd@shr-cicd-nonprd` and `deploy-prd@shr-cicd-prd`, obtained only through Workload Identity Federation. The WIF provider checks the GitHub repository ID; the prod SA binding requires `environment = prd` and the protected `main` ref. Runner machines' own service accounts have **no** deploy permissions.
5. **GitHub controls:** prod runner group restricted to named platform repositories/workflows; environment `prd` with required reviewers and deployment-branch rules; CODEOWNERS on `prd` version lines.
6. **Terraform state:** separate buckets `tfstate-prd` and `tfstate-nonprd` (plus `tfstate-org` for org/bootstrap stacks) with tier-specific IAM.

## Alternatives considered
| Option | Why not chosen |
|---|---|
| Separate Artifact Registry per tier with a promotion copy | Valid; more copies and storage; signing + digest pinning gives the same guarantee with one store |
| GitHub-hosted runners only | Simpler, but no private network path and less control of egress; still possible for build jobs [Q14] |
| Single deployer for both tiers | Violates [C10] |

## Rationale
The only legitimate non-prod → prod flow is a signed artifact produced by a build pipeline that neither tier's deployer controls.

## Disadvantages
- One more project, pipeline and signing key to operate.
- Binary Authorization policies must be maintained; break-glass deployment path must be documented.
- GitHub organisation owners remain able to change protections → treated as privileged identities.

## Revisit when
- The company already operates a central build/signing system that should be reused.
