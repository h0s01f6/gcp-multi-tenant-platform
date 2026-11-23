#!/usr/bin/env bash
# Stage 7 – one Terraform stack instance, as run by the reusable workflows tf-plan / tf-apply / drift.
# usage: tools/cicd/tf.sh plan|apply|drift      (run from the platform-infra root after `python -m tools.check_all`)
# env:   STACK INSTANCE STATE (from the planner matrix), TWO_PHASE=true|false,
#        TFSTATE_BUCKET_SUFFIX, TF_VAR_org_state_bucket, TF_VAR_github_org_id, TF_VAR_github_org (repository variables)
# Exit codes: plan/apply 0 ok, 1 error; drift 0 = no change, 2 = drift (terraform -detailed-exitcode).
set -euo pipefail
mode="$1"
dir="terraform/stacks/${STACK}"
vars="$PWD/build/tfvars/${STACK}/${INSTANCE}.auto.tfvars.json"
bucket="${STATE%%/*}${TFSTATE_BUCKET_SUFFIX:+-${TFSTATE_BUCKET_SUFFIX}}"
prefix="${STATE#*/}"
[ -f "$vars" ] || { echo "::error::no generated tfvars for ${STACK}/${INSTANCE} (${vars})"; exit 1; }

# plans of PRs and drift checks never take the state lock (read identities hold objectViewer only)
lock=$([ "$mode" = apply ] && echo true || echo false)
terraform -chdir="$dir" init -input=false -reconfigure -backend-config="bucket=${bucket}" -backend-config="prefix=${prefix}"

case "$mode" in
  plan)
    terraform -chdir="$dir" plan -input=false -lock="$lock" -var-file="$vars" -out=tfplan
    terraform -chdir="$dir" show -no-color tfplan > "$PWD/build/plan-${STACK}-${INSTANCE}.txt"
    ;;
  apply)
    if [ "${TWO_PHASE:-false}" = true ]; then
      # R-TF-1: Constraint CRDs exist only after their ConstraintTemplates are processed
      terraform -chdir="$dir" apply -input=false -auto-approve -var-file="$vars" -target=module.manifests.kubernetes_manifest.templates
    fi
    terraform -chdir="$dir" plan -input=false -var-file="$vars" -out=tfplan
    terraform -chdir="$dir" apply -input=false tfplan
    ;;
  drift)
    set +e
    terraform -chdir="$dir" plan -input=false -lock=false -var-file="$vars" -detailed-exitcode -no-color > "$PWD/build/drift-${STACK}-${INSTANCE}.txt"
    rc=$?
    set -e
    [ $rc -eq 2 ] && echo "::warning::drift in ${STACK}/${INSTANCE}"
    exit $rc
    ;;
  *) echo "unknown mode $mode"; exit 1 ;;
esac
