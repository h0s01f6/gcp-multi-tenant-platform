#!/usr/bin/env bash
# Registers an ephemeral GitHub Actions runner at boot. The registration token is
# rotated by a scheduled job and stored in Secret Manager (never in metadata).
set -euo pipefail
RUNNER_VERSION="2.321.0"
ORG_URL="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/github-org-url || echo https://github.com/my-company)"
TOKEN="$(gcloud secrets versions access latest --secret=runner-registration-token)"
POOL="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/pool || hostname)"

useradd -m runner || true
cd /home/runner
curl -sL -o runner.tgz "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf runner.tgz && chown -R runner:runner /home/runner
sudo -u runner ./config.sh --unattended --ephemeral --url "${ORG_URL}" --token "${TOKEN}" \
  --labels "self-hosted,gcp,${POOL}" --name "$(hostname)"
./svc.sh install runner && ./svc.sh start
