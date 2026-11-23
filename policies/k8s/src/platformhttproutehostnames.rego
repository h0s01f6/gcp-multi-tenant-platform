package platformhttproutehostnames

# Review A6: an HTTPRoute may only claim the hostnames derived from its namespace's tenant/product/env labels.
# Shared/Cohort namespaces (tenant=multi) may claim the hostnames of the tenants they serve (parameter generated
# from the registry). Requires input.review.namespaceObject (Gatekeeper >= 3.x; confirm on Policy Controller, T-K19).

route := input.review.object

ns_labels := input.review.namespaceObject.metadata.labels

violation[{"msg": msg}] {
    not input.review.namespaceObject
    msg := "namespace object not available to the policy – failing closed"
}

violation[{"msg": msg}] {
    count(object.get(route.spec, "hostnames", [])) == 0
    msg := sprintf("HTTPRoute %v: hostnames must be listed explicitly (an empty list matches every host)", [route.metadata.name])
}

violation[{"msg": msg}] {
    host := route.spec.hostnames[_]
    not allowed(host)
    msg := sprintf("HTTPRoute %v: hostname %v is not allowed in namespace %v", [route.metadata.name, host, route.metadata.namespace])
}

expected := h {
    ns_labels.env == "prd"
    h := sprintf("%v.%v.%v", [ns_labels.tenant, ns_labels.product, input.parameters.domain])
}

expected := h {
    ns_labels.env != "prd"
    h := sprintf("%v-%v.%v.nonprod.%v", [ns_labels.tenant, ns_labels.env, ns_labels.product, input.parameters.domain])
}

allowed(host) {
    ns_labels.tenant != "multi"
    host == expected
}

allowed(host) {
    ns_labels.tenant == "multi"
    host == input.parameters.sharedNamespaceHostnames[route.metadata.namespace][_]
}
