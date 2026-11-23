{{- define "platform-lib.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "platform-lib.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicas }}
  {{- end }}
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      {{- include "platform-lib.selector" . | nindent 6 }}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: "25%"
  template:
    metadata:
      labels:
        {{- include "platform-lib.labels" . | nindent 8 }}
      annotations:
        checksum/config: {{ include "platform-lib.configmap" . | sha256sum }}
    spec:
      serviceAccountName: {{ required "serviceAccount.name is required (created by Terraform, D8)" .Values.serviceAccount.name }}
      securityContext:
        {{- include "platform-lib.podSecurityContext" . | nindent 8 }}
      {{- if .Values.isolation.dedicatedNodes }}
      {{- include "platform-lib.placement" . | nindent 6 }}
      {{- end }}
      {{- if .Values.database.enabled }}
      initContainers:
        {{- include "platform-lib.sqlProxy" . | nindent 8 }}
      {{- end }}
      containers:
        - name: app
          image: {{ include "platform-lib.image" .Values.image }}
          ports:
            - name: http
              containerPort: {{ .Values.service.containerPort }}
          env:
            {{- include "platform-lib.env" (dict "root" . "dbUser" .Values.database.user) | nindent 12 }}
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
          startupProbe:
            httpGet:
              path: {{ .Values.probes.livenessPath }}
              port: http
            failureThreshold: 30
            periodSeconds: 5
          readinessProbe:
            httpGet:
              path: {{ .Values.probes.readinessPath }}
              port: http
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: {{ .Values.probes.livenessPath }}
              port: http
            periodSeconds: 20
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
{{- end -}}
