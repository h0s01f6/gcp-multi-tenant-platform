package platformtenantseparation

params := {"key": "platform.example.com/tenant", "separationTiers": ["enhanced", "dedicated"]}

req(tier, spec) := {"parameters": params, "review": {
    "object": {"spec": spec},
    "namespaceObject": {"metadata": {"labels": {"tenant": "abc", "isolation_tier": tier}}},
}}

own := {"nodeSelector": {"platform.example.com/tenant": "abc"},
    "tolerations": [{"key": "platform.example.com/tenant", "operator": "Equal", "value": "abc", "effect": "NoSchedule"}]}

test_enhanced_own_nodes_allowed {
    count(violation) == 0 with input as req("enhanced", own)
}

test_enhanced_must_select_nodes {
    count(violation) > 0 with input as req("enhanced", {})
}

test_other_tenant_nodes_denied {
    count(violation) > 0 with input as req("enhanced", {"nodeSelector": {"platform.example.com/tenant": "xyz"}})
}

test_wildcard_toleration_denied {
    count(violation) > 0 with input as req("enhanced", object.union(own, {"tolerations": [{"key": "platform.example.com/tenant", "operator": "Exists"}]}))
}

test_standard_tier_cannot_use_dedicated_nodes {
    count(violation) > 0 with input as req("standard", own)
    count(violation) == 0 with input as req("standard", {})
}
