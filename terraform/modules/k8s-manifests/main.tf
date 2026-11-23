# Applies platform-owned Kubernetes objects to one cell (cluster-config stack): the D8 namespace baselines and
# cluster objects rendered by tools/k8s/baseline.py, the Policy Controller templates, and the shared Gateways.
# Application objects are NEVER here – they belong to Helm releases (Stage 6).
locals {
  files = fileset(var.manifests_dir, "*.yaml")
  docs = merge([for f in local.files : {
    for i, d in [for x in split("\n---\n", file("${var.manifests_dir}/${f}")) : yamldecode(x) if trimspace(x) != ""] :
    "${f}|${i}|${d.kind}|${try(d.metadata.namespace, "")}|${d.metadata.name}" => d
  }]...)
  # cluster-scoped objects and Namespaces first, then namespaced objects
  first  = { for k, d in local.docs : k => d if contains(["Namespace", "ClusterRole", "ConstraintTemplate"], d.kind) }
  second = { for k, d in local.docs : k => d if !contains(["Namespace", "ClusterRole", "ConstraintTemplate"], d.kind) }
  templates = { for i, d in [for x in split("\n---\n", file(var.constraint_templates_file)) : yamldecode(x) if trimspace(x) != "" && !startswith(trimspace(x), "#")] : d.metadata.name => d }
}

resource "kubernetes_manifest" "templates" {
  for_each = local.templates
  manifest = each.value
}

resource "kubernetes_manifest" "first" {
  for_each   = local.first
  manifest   = each.value
  depends_on = [kubernetes_manifest.templates]
}

resource "kubernetes_manifest" "second" {
  for_each   = local.second
  manifest   = each.value
  depends_on = [kubernetes_manifest.first]
}

resource "kubernetes_namespace_v1" "gateway_infra" {
  metadata {
    name   = "gateway-infra"
    labels = { "platform.example.com/managed" = "platform" }
  }
}

# One Gateway per product per environment in this cell; routes only from namespaces of that product + env (IN07).
resource "kubernetes_manifest" "gateway" {
  for_each = var.gateways
  manifest = {
    apiVersion = "gateway.networking.k8s.io/v1"
    kind       = "Gateway"
    metadata = {
      name      = each.key
      namespace = kubernetes_namespace_v1.gateway_infra.metadata[0].name
      annotations = {
        "networking.gke.io/certmap" = "cm-${each.value.certificate}"
      }
    }
    spec = {
      gatewayClassName = each.value.class
      addresses        = [{ type = "NamedAddress", value = each.value.address }]
      listeners = [{
        name     = "https"
        protocol = "HTTPS"
        port     = 443
        allowedRoutes = {
          kinds = [{ kind = "HTTPRoute" }]
          namespaces = {
            from     = "Selector"
            selector = { matchLabels = each.value.allowed_route_selector }
          }
        }
      }]
    }
  }
}
