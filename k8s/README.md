# Inspectra Kubernetes Deployment

This folder contains production-ready manifests for Inspectra.

Key files:
- `namespace.yaml` - isolates resources in the `inspectra` namespace.
- `configmap.yaml` / `secrets.yaml` - runtime configuration and secret placeholders.
- `backend-*` - internal backend deployment and service.
- `ingress.yaml` - public ingress for the backend.
- `postgres-*` - Postgres database deployment, service, and PVC.
- `redis-*` - optional Redis deployment and service.
- `*-hpa.yaml` - autoscaling resources for the backend.
- `kustomization.yaml` - apply the full stack with `kubectl apply -k k8s`.
- `local-nodeport.yaml` - local fallback service for Minikube/Docker Desktop without ingress.

Local development:
1. Enable ingress:
   - Minikube: `minikube addons enable ingress`
   - Docker Desktop: enable Kubernetes and ingress in settings.
2. Apply manifests:
   - `kubectl apply -k k8s`
3. If using `local-nodeport.yaml`, apply the fallback service too.

Run the database init job once after the Postgres service is ready:
```bash
kubectl apply -f k8s/db-init-job.yaml
kubectl wait --for=condition=complete job/inspectra-db-init -n inspectra --timeout=120s
```

Replace placeholder secrets in `secrets.yaml` before production deployment.
