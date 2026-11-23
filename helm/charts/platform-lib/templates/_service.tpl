{{/* ClusterIP only – LoadBalancer / NodePort are blocked by the namespace quota (D8). */}}
{{- define "platform-lib.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
spec:
  type: ClusterIP
  selector:
    {{- include "platform-lib.selector" . | nindent 4 }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: http
{{- end -}}
