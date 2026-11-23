package platformhttproutehostnames

params := {"domain": "example.com", "sharedNamespaceHostnames": {"shr-notify-prd": ["abc.notify.example.com"]}}

req(ns, labels, hosts) := {"parameters": params, "review": {
    "object": {"metadata": {"name": "r", "namespace": ns}, "spec": {"hostnames": hosts}},
    "namespaceObject": {"metadata": {"name": ns, "labels": labels}},
}}

abc_prd := {"tenant": "abc", "product": "payroll", "env": "prd"}

test_own_hostname_allowed {
    count(violation) == 0 with input as req("abc-payroll-prd", abc_prd, ["abc.payroll.example.com"])
}

test_other_tenant_hostname_denied {
    count(violation) > 0 with input as req("abc-payroll-prd", abc_prd, ["xyz.payroll.example.com"])
}

test_nonprod_hostname {
    l := {"tenant": "abc", "product": "crm", "env": "uat"}
    count(violation) == 0 with input as req("abc-crm-uat", l, ["abc-uat.crm.nonprod.example.com"])
    count(violation) > 0 with input as req("abc-crm-uat", l, ["abc.crm.example.com"])
}

test_empty_hostnames_denied {
    count(violation) > 0 with input as req("abc-payroll-prd", abc_prd, [])
}

test_shared_namespace_served_tenants_only {
    l := {"tenant": "multi", "product": "notify", "env": "prd"}
    count(violation) == 0 with input as req("shr-notify-prd", l, ["abc.notify.example.com"])
    count(violation) > 0 with input as req("shr-notify-prd", l, ["xyz.notify.example.com"])
}
