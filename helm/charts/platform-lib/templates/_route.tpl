{{/* HTTPRoute on the shared Gateway created by Terraform (cluster-config). Hostnames are generated from the
     registry; the D8 policy rejects any other hostname and the Gateway only accepts this product + env. */}}
{{- define "platform-lib.httproute" -}}
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
spec:
  parentRefs:
    - name: {{ required "route.gateway.name is required" .Values.route.gateway.name }}
      namespace: {{ .Values.route.gateway.namespace }}
      sectionName: https
  hostnames:
    {{- toYaml (required "route.hostnames is required" .Values.route.hostnames) | nindent 4 }}
  rules:
    - backendRefs:
        - name: {{ .Release.Name }}
          port: {{ .Values.service.port }}
{{- end -}}

{{/* GKE load-balancer health check on the readiness path. */}}
{{- define "platform-lib.healthcheckpolicy" -}}
apiVersion: networking.gke.io/v1
kind: HealthCheckPolicy
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
spec:
  default:
    config:
      type: HTTP
      httpHealthCheck:
        port: {{ .Values.service.containerPort }}
        requestPath: {{ .Values.probes.readinessPath }}
  targetRef:
    group: ""
    kind: Service
    name: {{ .Release.Name }}
{{- end -}}
