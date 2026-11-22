#!/usr/bin/env sh
# Applies 5-tenant-base / 6-tenant-env for the customer-envs listed in the matrix file.
# $1 = matrix.json from tools/changed_tenants.py, $2 = nonprod | prod
set -eu
MATRIX="$1"; SCOPE="$2"
TF_SA=$([ "$SCOPE" = prod ] && echo "$TF_SA_PROD" || echo "$TF_SA_NONPROD")
COMMON="-var terraform_sa=$TF_SA -var billing_project=$SEED_PROJECT -var state_bucket=$STATE_BUCKET"

if [ "$SCOPE" = prod ]; then
  for c in $(python3 -c "import json,sys;[print(x['customer']) for x in json.load(open('$MATRIX'))['base']]"); do
    terraform -chdir=terraform/stacks/5-tenant-base init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=tenants/$c/base"
    terraform -chdir=terraform/stacks/5-tenant-base apply -auto-approve -var customer="$c" $COMMON
  done
fi

python3 -c "import json;[print(x['customer'],x['env']) for x in json.load(open('$MATRIX'))['env']]" | while read -r c e; do
  if [ "$SCOPE" = prod ] && [ "$e" != prod ]; then continue; fi
  if [ "$SCOPE" = nonprod ] && [ "$e" = prod ]; then continue; fi
  terraform -chdir=terraform/stacks/6-tenant-env init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=tenants/$c/$e"
  terraform -chdir=terraform/stacks/6-tenant-env apply -auto-approve -var customer="$c" -var env="$e" $COMMON
done
