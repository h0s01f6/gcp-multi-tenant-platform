{{/* Workload name: the product. Unique because namespace = customer. */}}
{{- define "ps.name" -}}
{{- .Values.product | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "ps.labels" -}}
app.kubernetes.io/name: {{ include "ps.name" . }}
app.kubernetes.io/version: {{ .Values.version | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
platform.example.com/customer: {{ .Values.customer }}
platform.example.com/env: {{ .Values.env }}
platform.example.com/product: {{ .Values.product }}
{{- end -}}

{{- define "ps.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ps.name" . }}
platform.example.com/customer: {{ .Values.customer }}
{{- end -}}

{{- define "ps.image" -}}
{{- if .Values.image.digest -}}
{{ printf "%s/%s@%s" .Values.image.registry .Values.product .Values.image.digest }}
{{- else -}}
{{ printf "%s/%s:%s" .Values.image.registry .Values.product .Values.version }}
{{- end -}}
{{- end -}}

{{- define "ps.gsa" -}}
{{- if .Values.gcp.serviceAccountEmail -}}
{{ .Values.gcp.serviceAccountEmail }}
{{- else -}}
{{ printf "%s-sa@%s-%s-%s.iam.gserviceaccount.com" .Values.product .Values.gcp.projectPrefix .Values.customer .Values.env }}
{{- end -}}
{{- end -}}

{{- define "ps.hostname" -}}
{{- default (printf "%s.%s.%s.%s" .Values.product .Values.customer .Values.env .Values.route.domain) .Values.route.hostname -}}
{{- end -}}
