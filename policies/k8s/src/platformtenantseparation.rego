package platformtenantseparation

# Autopilot workload separation (ADR-004 enhanced/dedicated): a pod may select or tolerate dedicated nodes only
# for its own tenant, only if its namespace's isolation tier allows it, and such namespaces must use them.

key := input.parameters.key

ns_labels := input.review.namespaceObject.metadata.labels

spec := input.review.object.spec

separated_tier {
    ns_labels.isolation_tier == input.parameters.separationTiers[_]
}

values[v] {
    v := spec.nodeSelector[key]
}

values[v] {
    t := spec.tolerations[_]
    t.key == key
    v := object.get(t, "value", "*")
}

values[v] {
    term := spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[_]
    e := term.matchExpressions[_]
    e.key == key
    v := e.values[_]
}

violation[{"msg": msg}] {
    not input.review.namespaceObject
    msg := "namespace object not available to the policy – failing closed"
}

violation[{"msg": msg}] {
    v := values[_]
    v != ns_labels.tenant
    msg := sprintf("pod uses %v=%v but its namespace belongs to tenant %v", [key, v, ns_labels.tenant])
}

violation[{"msg": msg}] {
    count(values) > 0
    not separated_tier
    msg := sprintf("isolation tier %v does not use dedicated nodes", [object.get(ns_labels, "isolation_tier", "none")])
}

violation[{"msg": msg}] {
    separated_tier
    not spec.nodeSelector[key]
    msg := sprintf("isolation tier %v requires nodeSelector %v=%v", [ns_labels.isolation_tier, key, ns_labels.tenant])
}
