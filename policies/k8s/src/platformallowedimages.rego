package platformallowedimages

# Images only from the platform registry; release images always by digest; digest required outside dev.
# Complements Binary Authorization (D9), which verifies the build attestation.

containers[c] {
    c := input.review.object.spec.containers[_]
}

containers[c] {
    c := input.review.object.spec.initContainers[_]
}

containers[c] {
    c := input.review.object.spec.ephemeralContainers[_]
}

from_allowed_repo(image) {
    startswith(image, input.parameters.allowedRepos[_])
}

violation[{"msg": msg}] {
    c := containers[_]
    not from_allowed_repo(c.image)
    msg := sprintf("container %v: image %v is not from the platform registry", [c.name, c.image])
}

violation[{"msg": msg}] {
    c := containers[_]
    input.parameters.requireDigest
    not contains(c.image, "@sha256:")
    msg := sprintf("container %v: image %v must be referenced by digest", [c.name, c.image])
}

violation[{"msg": msg}] {
    c := containers[_]
    startswith(c.image, input.parameters.releaseRepo)
    not contains(c.image, "@sha256:")
    msg := sprintf("container %v: release image %v must be referenced by digest", [c.name, c.image])
}
