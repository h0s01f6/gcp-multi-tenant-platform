#!/usr/bin/env bash
# Ansible runner: ansible-core + Google collection; reaches VMs via IAP tunnels + OS Login.
set -euo pipefail
apt-get update -y
apt-get install -y python3-pip python3-venv git
python3 -m venv /opt/ansible
/opt/ansible/bin/pip install "ansible-core>=2.17" google-auth requests
/opt/ansible/bin/ansible-galaxy collection install google.cloud
cat >/etc/profile.d/ansible.sh <<'PROFILE'
export PATH=/opt/ansible/bin:$PATH
# SSH goes through IAP; the ProxyCommand is set per host in ansible/inventory/gcp.yml
PROFILE
