package platformallowedimages

rel := "asia-south1-docker.pkg.dev/shr-artifacts/release/"

snap := "asia-south1-docker.pkg.dev/shr-artifacts/snapshot/"

pod(image, params) := {"parameters": params, "review": {"object": {"spec": {"containers": [{"name": "app", "image": image}]}}}}

prd := {"releaseRepo": rel, "allowedRepos": [rel], "requireDigest": true}

dev := {"releaseRepo": rel, "allowedRepos": [rel, snap], "requireDigest": false}

digest := "@sha256:0000000000000000000000000000000000000000000000000000000000000000"

test_release_by_digest_allowed {
    count(violation) == 0 with input as pod(concat("", [rel, "payroll", digest]), prd)
}

test_tag_denied_in_prod {
    count(violation) > 0 with input as pod(concat("", [rel, "payroll:2.1.0"]), prd)
}

test_foreign_registry_denied {
    count(violation) > 0 with input as pod(concat("", ["docker.io/library/nginx", digest]), prd)
}

test_snapshot_tag_allowed_in_dev_only {
    count(violation) == 0 with input as pod(concat("", [snap, "payroll:dev-123"]), dev)
    count(violation) > 0 with input as pod(concat("", [snap, "payroll:dev-123"]), prd)
}

test_release_tag_denied_even_in_dev {
    count(violation) > 0 with input as pod(concat("", [rel, "payroll:2.1.0"]), dev)
}
