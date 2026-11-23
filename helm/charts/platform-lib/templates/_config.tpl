{{/* Customer-specific configuration from the tenant file (subscription `config`): data only, never templates or
     extra objects, so a tenant file cannot inject manifests (review X6). */}}
{{- define "platform-lib.configmap" -}}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
data:
  {{- range $k, $v := .Values.config }}
  {{ upper (replace "-" "_" $k) }}: {{ $v | quote }}
  {{- end }}
{{- end -}}
