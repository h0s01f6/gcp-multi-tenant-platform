{{/* Schema migration before install/upgrade (Stage 2 §3.3): runs as the migration KSA -> <tenant>-<product>-<env>-mig
     GSA -> MySQL role r_<db>_ddl (D4). Only this tenant's database. */}}
{{- define "platform-lib.migration" -}}
{{- if and .Values.migration.enabled .Values.database.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-migrate
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-weight: "-5"
    helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded
spec:
  backoffLimit: {{ .Values.migration.backoffLimit }}
  activeDeadlineSeconds: {{ .Values.migration.timeoutSeconds }}
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        {{- include "platform-lib.labels" . | nindent 8 }}
    spec:
      restartPolicy: Never
      serviceAccountName: {{ required "serviceAccount.migrationName is required" .Values.serviceAccount.migrationName }}
      securityContext:
        {{- include "platform-lib.podSecurityContext" . | nindent 8 }}
      {{- if .Values.isolation.dedicatedNodes }}
      {{- include "platform-lib.placement" . | nindent 6 }}
      {{- end }}
      initContainers:
        {{- include "platform-lib.sqlProxy" . | nindent 8 }}
      containers:
        - name: migrate
          image: {{ include "platform-lib.image" .Values.image }}
          command:
            {{- toYaml .Values.migration.command | nindent 12 }}
          env:
            {{- include "platform-lib.env" (dict "root" . "dbUser" .Values.database.migrationUser) | nindent 12 }}
          resources:
            requests:
              cpu: {{ .Values.resources.cpu | quote }}
              memory: {{ .Values.resources.memory | quote }}
            limits:
              cpu: {{ .Values.resources.cpu | quote }}
              memory: {{ .Values.resources.memory | quote }}
          securityContext:
            {{- include "platform-lib.containerSecurityContext" . | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
{{- end }}
{{- end -}}
