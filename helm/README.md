# Helm placeholder for Inspectra

This folder is reserved for future Helm chart work.
A production Helm chart should include:
- `Chart.yaml` and `values.yaml`
- templates for deployments, services, ingress, configmaps, secrets, and HPAs
- environment-specific overrides for `dev`, `staging`, and `prod`

For now, Kubernetes manifests are provided under `/k8s`.
