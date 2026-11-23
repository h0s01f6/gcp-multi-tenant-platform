# Ansible (Stage 6 – MIG products)

Status: **implemented; syntax and templates checked locally** (YAML parse, role wiring, Jinja2 rendering – `tests/test_ansible.py`). `ansible-lint`, Packer builds and runs against VMs are T-AN1.

MIG products follow Stage 2 §2C: the image is **baked** in `shr-build` (Packer runs `playbooks/bake-image.yml`), MIG instance templates (Terraform, `modules/workloads`) boot that image, and customer-specific configuration is **data read at boot** with the VM's own identity – never baked into the image.

| Path | Purpose |
|---|---|
| `playbooks/bake-image.yml` | Image build: `base` + `app` roles, product version pinned (`app_version`) |
| `playbooks/configure.yml` | Day-2 configuration of running MIG VMs through IAP + OS Login (`ansible-<tier>` identity, D6), in batches |
| `inventories/gcp.yml` | Dynamic inventory from labels (`product`, `env`, `env_tier`), one inventory per tier |
| `roles/base` | OS hardening (no password SSH, automatic security updates), Ops Agent for logs/metrics |
| `roles/app` | Installs the pinned product version, systemd unit, boot-time config loader (metadata + Secret Manager references) |

Helm and Terraform do not overlap with this: Terraform owns templates/MIGs/health checks; Ansible owns what is inside the image and day-2 OS configuration.
