{{/*
Expand the name of the chart.
*/}}
{{- define "ai-agent-orchestrator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "ai-agent-orchestrator.fullname" -}}
{{- default .Chart.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "ai-agent-orchestrator.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "ai-agent-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "ai-agent-orchestrator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ai-agent-orchestrator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Full image reference: registry/repository:tag
*/}}
{{- define "ai-agent-orchestrator.image" -}}
{{ .Values.image.registry }}/{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end }}

{{/*
Namespace name
*/}}
{{- define "ai-agent-orchestrator.namespace" -}}
{{ .Values.namespace.name | default "ai-agent-orchestrator" }}
{{- end }}
