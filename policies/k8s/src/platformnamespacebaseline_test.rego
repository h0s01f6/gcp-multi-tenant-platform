package platformnamespacebaseline

params := {"requiredLabels": ["tenant", "product", "env", "env_tier", "deployment_model"], "podSecurity": "restricted"}

ns(name, labels) := {"parameters": params, "review": {"object": {"metadata": {"name": name, "labels": labels}}}}

good := {"tenant": "abc", "product": "payroll", "env": "prd", "env_tier": "prd", "deployment_model": "dedicated",
    "pod-security.kubernetes.io/enforce": "restricted"}

test_valid_tenant_namespace {
    count(violation) == 0 with input as ns("abc-payroll-prd", good)
}

test_missing_label {
    count(violation) > 0 with input as ns("abc-payroll-prd", object.remove(good, ["env_tier"]))
}

test_psa_not_restricted {
    count(violation) > 0 with input as ns("abc-payroll-prd", object.union(good, {"pod-security.kubernetes.io/enforce": "baseline"}))
}

test_name_must_match_labels {
    count(violation) > 0 with input as ns("xyz-payroll-prd", good)
}

test_shared_namespace {
    shared := object.union(good, {"tenant": "multi", "deployment_model": "shared"})
    count(violation) == 0 with input as ns("shr-payroll-prd", shared)
    count(violation) > 0 with input as ns("abc-payroll-prd", shared)
}
