package platformnamespacebaseline

# Tenant namespaces carry the registry labels, Pod Security "restricted", and a name derived from the labels.

labels := object.get(input.review.object.metadata, "labels", {})

name := input.review.object.metadata.name

violation[{"msg": msg}] {
    required := input.parameters.requiredLabels[_]
    not labels[required]
    msg := sprintf("namespace %v: missing label %v", [name, required])
}

violation[{"msg": msg}] {
    object.get(labels, "pod-security.kubernetes.io/enforce", "") != input.parameters.podSecurity
    msg := sprintf("namespace %v: pod-security.kubernetes.io/enforce must be %v", [name, input.parameters.podSecurity])
}

violation[{"msg": msg}] {
    labels.tenant != "multi"
    expected := sprintf("%v-%v-%v", [labels.tenant, labels.product, labels.env])
    name != expected
    msg := sprintf("namespace %v: name must be %v (derived from labels)", [name, expected])
}

violation[{"msg": msg}] {
    labels.tenant == "multi"
    not startswith(name, sprintf("shr-%v-", [labels.product]))
    not startswith(name, sprintf("coh-%v-", [labels.product]))
    msg := sprintf("namespace %v: shared namespaces must be shr-<product>-* or coh-<product>-*", [name])
}

violation[{"msg": msg}] {
    labels.tenant == "multi"
    not endswith(name, sprintf("-%v", [labels.env]))
    msg := sprintf("namespace %v: must end with -%v", [name, labels.env])
}
