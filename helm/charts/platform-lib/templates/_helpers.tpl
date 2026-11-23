{{/* Common labels: registry identity of the release (Stage 2 §0 labels). */}}
{{- define "platform-lib.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ required "image.version is required" .Values.image.version | quote }}
app.kubernetes.io/managed-by: Helm
tenant: {{ required "tenant is required" .Values.tenant }}
product: {{ required "product is required" .Values.product }}
env: {{ required "env is required" .Values.env }}
{{- end -}}

{{- define "platform-lib.selector" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Images only from the release/snapshot repository and by digest (D8 PlatformAllowedImages, D9). */}}
{{- define "platform-lib.image" -}}
{{ required "image repository is required" .repository }}@{{ required "image digest is required" .digest }}
{{- end -}}

{{/* Pod Security "restricted" (D8 namespace label) for every container. */}}
{{- define "platform-lib.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
runAsNonRoot: true
capabilities:
  drop:
    - ALL
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "platform-lib.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Enhanced / dedicated isolation tier: pods only on the tenant's own nodes (D8 PlatformTenantSeparation). */}}
{{- define "platform-lib.placement" -}}
{{- if .Values.isolation.dedicatedNodes }}
nodeSelector:
  {{ .Values.isolation.key }}: {{ .Values.tenant }}
tolerations:
  - key: {{ .Values.isolation.key }}
    operator: Equal
    value: {{ .Values.tenant }}
    effect: NoSchedule
{{- end }}
{{- end -}}

{{/* Cloud SQL Auth Proxy as a native sidecar: IAM database authentication, private IP (ADR-011, D4). */}}
{{- define "platform-lib.sqlProxy" -}}
- name: cloud-sql-proxy
  image: {{ include "platform-lib.image" .Values.cloudSqlProxy.image }}
  restartPolicy: Always
  args:
    - "--auto-iam-authn"
    - "--private-ip"
    - "--structured-logs"
    - "--port={{ .Values.database.port }}"
    - {{ required "database.instanceConnectionName is required" .Values.database.instanceConnectionName | quote }}
  resources:
    requests:
      cpu: {{ .Values.cloudSqlProxy.resources.cpu | quote }}
      memory: {{ .Values.cloudSqlProxy.resources.memory | quote }}
    limits:
      cpu: {{ .Values.cloudSqlProxy.resources.cpu | quote }}
      memory: {{ .Values.cloudSqlProxy.resources.memory | quote }}
  securityContext:
    {{- include "platform-lib.containerSecurityContext" . | nindent 4 }}
{{- end -}}

{{/* Environment: identifiers and references only – never secret values (D9: the app reads Secret Manager with its
     own Workload Identity). Called with (dict "root" $ "dbUser" <user>). */}}
{{- define "platform-lib.env" -}}
- name: TENANT
  value: {{ .root.Values.tenant | quote }}
- name: PRODUCT
  value: {{ .root.Values.product | quote }}
- name: ENVIRONMENT
  value: {{ .root.Values.env | quote }}
{{- if .root.Values.database.enabled }}
- name: DB_HOST
  value: "127.0.0.1"
- name: DB_PORT
  value: {{ .root.Values.database.port | quote }}
- name: DB_NAME
  value: {{ required "database.name is required" .root.Values.database.name | quote }}
- name: DB_USER
  value: {{ required "database user is required" .dbUser | quote }}
{{- end }}
{{- range $name, $ref := .root.Values.secrets }}
- name: {{ printf "SECRET_%s" (upper (replace "-" "_" $name)) }}
  value: {{ printf "%s/versions/latest" $ref | quote }}
{{- end }}
{{- range $purpose, $bucket := .root.Values.buckets }}
- name: {{ printf "BUCKET_%s" (upper (replace "-" "_" $purpose)) }}
  value: {{ $bucket | quote }}
{{- end }}
{{- end -}}
