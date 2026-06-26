{{/* Common labels */}}
{{- define "airealtime.labels" -}}
app.kubernetes.io/name: airealtime
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "airealtime.selectorLabels" -}}
app.kubernetes.io/name: airealtime
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
