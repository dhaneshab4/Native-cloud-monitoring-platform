{{/*
Name helpers. `selectorLabels` is deliberately narrow — selectors are immutable
on a Deployment, so anything that changes between releases (version, chart
revision) must stay out of them or upgrades fail.
*/}}

{{- define "monitoring-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "monitoring-app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "monitoring-app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Kept identical to the pre-Helm kustomize manifests so an in-place
     migration does not orphan the existing Service selector. */}}
{{- define "monitoring-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "monitoring-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "monitoring-app.labels" -}}
helm.sh/chart: {{ include "monitoring-app.chart" . }}
{{ include "monitoring-app.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: cloud-native-monitoring
{{- end }}

{{- define "monitoring-app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "monitoring-app.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "monitoring-app.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{/*
The pod spec is shared verbatim by the Deployment and the Rollout. Argo Rollouts
reuses the Deployment pod template exactly, so factoring it out here guarantees
the two delivery modes cannot drift apart.
*/}}
{{- define "monitoring-app.podSpec" -}}
serviceAccountName: {{ include "monitoring-app.serviceAccountName" . }}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
securityContext:
  {{- toYaml .Values.podSecurityContext | nindent 2 }}
containers:
  - name: app
    image: {{ include "monitoring-app.image" . | quote }}
    imagePullPolicy: {{ .Values.image.pullPolicy }}
    ports:
      - name: http
        containerPort: 5000
        protocol: TCP
    envFrom:
      - configMapRef:
          name: {{ include "monitoring-app.fullname" . }}-config
    # Liveness uses /healthz so a degraded-but-running pod is not killed;
    # readiness uses /readyz so it is pulled from the Service instead.
    livenessProbe:
      httpGet: {path: /healthz, port: http}
      initialDelaySeconds: 10
      periodSeconds: 20
      failureThreshold: 3
    readinessProbe:
      httpGet: {path: /readyz, port: http}
      initialDelaySeconds: 5
      periodSeconds: 10
      failureThreshold: 2
    startupProbe:
      httpGet: {path: /healthz, port: http}
      periodSeconds: 2
      failureThreshold: 30
    resources:
      {{- toYaml .Values.resources | nindent 6 }}
    securityContext:
      {{- toYaml .Values.securityContext | nindent 6 }}
    volumeMounts:
      - name: tmp
        mountPath: /tmp
volumes:
  - name: tmp
    emptyDir: {}
{{- if .Values.topologySpreadEnabled }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "monitoring-app.selectorLabels" . | nindent 8 }}
{{- end }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
