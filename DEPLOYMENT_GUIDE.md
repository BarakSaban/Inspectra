# Inspectra Kubernetes - Step-by-Step Deployment Guide

## Prerequisites (Install First)

### On Windows with Docker Desktop
1. **Docker Desktop**: https://www.docker.com/products/docker-desktop
   - Enable Kubernetes in settings: Settings → Kubernetes → Enable Kubernetes
   - Or use WSL2 backend for better performance

2. **kubectl**: 
   ```powershell
   choco install kubernetes-cli
   # or manually: https://kubernetes.io/docs/tasks/tools/install-kubectl-windows/
   ```

3. **Verify installation**:
   ```powershell
   docker --version
   kubectl version --client --short
   kubectl get svc -n default
   ```

## Part 1: Prepare the Repository

### Step 1: Update Secrets (MUST DO)
Edit `k8s/secrets.yaml`:
```yaml
INSPECTRA_SECRET: "your-super-secret-key-here"
INSPECTRA_ADMIN_PW: "YourAdminPassword123"
POSTGRES_USER: "inspectra_user"
POSTGRES_PASSWORD: "YourDBPassword456"
```

Generate secure values:
```powershell
# Generate random secret
[System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes((New-Guid).ToString())) -replace '[^a-zA-Z0-9]',''
```

### Step 2: Update TLS Secret (For local dev, skip this)
Edit `k8s/tls-secret.yaml`:
```yaml
tls.crt: "base64-encoded-certificate"
tls.key: "base64-encoded-private-key"
```

For local development, skip — we'll disable TLS on ingress.

## Part 2: Build Docker Images

### Option A: Build Backend Image Locally
```powershell
cd c:\Users\User\Documents\INSPECTRA\Git\Inspectra

# Build the backend image
docker build -f docker/backend/Dockerfile -t inspectra-backend:latest .

# Verify it built
docker images | grep inspectra-backend
```

### Option B: Use a Container Registry
```powershell
docker build -f docker/backend/Dockerfile -t myregistry.azurecr.io/inspectra-backend:latest .
docker push myregistry.azurecr.io/inspectra-backend:latest

# Update k8s/backend-deployment.yaml:
# Change: image: inspectra-backend:latest
# To:     image: myregistry.azurecr.io/inspectra-backend:latest
```

## Part 3: Deploy to Kubernetes

### Step 1: Enable Ingress (if using Minikube)
```powershell
# For Minikube only:
minikube addons enable ingress

# For Docker Desktop: ingress is built-in, already enabled
```

### Step 2: Create Namespace and Apply Manifests
```powershell
# Create namespace first
kubectl apply -f k8s/namespace.yaml

# Apply all manifests via kustomize
kubectl apply -k k8s

# Or apply individual manifests (without db-init-job yet)
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/postgres-pvc.yaml
kubectl apply -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/postgres-service.yaml
# ... etc (see kustomization.yaml for full list)
```

### Step 3: Wait for Postgres to be Ready
```powershell
# Watch Postgres pod startup
kubectl get pods -n inspectra -w
# Wait for postgres pod to show RUNNING and READY 1/1

# Or explicitly wait
kubectl wait --for=condition=ready pod -l app=inspectra-postgres -n inspectra --timeout=60s
```

### Step 4: Run Database Initialization (One-time)
```powershell
# Run the one-time database init job
kubectl apply -f k8s/db-init-job.yaml

# Watch the job complete
kubectl get jobs -n inspectra -w
# Job should show 1/1 COMPLETED

# Or wait explicitly
kubectl wait --for=condition=complete job/inspectra-db-init -n inspectra --timeout=60s

# Check the job logs to verify it succeeded
kubectl logs job/inspectra-db-init -n inspectra
```

### Step 5: Verify Backend Pods are Running
```powershell
kubectl get pods -n inspectra

# Should see:
# inspectra-backend-xxxxx     1/1     Running   0          2m
# inspectra-backend-xxxxx     1/1     Running   0          1m
# inspectra-postgres-xxxxx    1/1     Running   0          5m
# inspectra-redis-xxxxx      1/1     Running   0          3m
```

### Step 6: Check Ingress Configuration
```powershell
kubectl get ingress -n inspectra
kubectl describe ingress inspectra-ingress -n inspectra
```

## Part 4: Access the Application

### For Local Development (Docker Desktop)

#### Option A: Via Ingress (Recommended)
```powershell
# Get the ingress IP
kubectl get ingress -n inspectra
# Should show: 127.0.0.1 or localhost

# Add to hosts file (as Administrator):
# C:\Windows\System32\drivers\etc\hosts
127.0.0.1 inspectra.local

# Access in browser:
# http://inspectra.local (or https if TLS is configured)
```

#### Option B: Via NodePort Fallback (No ingress needed)
```powershell
# Apply the nodeport service
kubectl apply -f k8s/local-nodeport.yaml

# Get the node IP
kubectl config view | grep server
# Extract the IP (e.g., 127.0.0.1 for Docker Desktop)

# Access in browser:
# http://127.0.0.1:30080
```

### For Production (Cloud)
```powershell
# Get the external IP of your ingress controller
kubectl get ingress -n inspectra -o wide

# Map your domain to that IP in your DNS provider
# Access: https://yourdomain.com
```

## Part 5: Verify Everything Works

### Check Logs
```powershell
# Backend logs
kubectl logs deployment/inspectra-backend -n inspectra -f

# Database pod logs
kubectl logs deployment/inspectra-postgres -n inspectra

# Job logs (after running)
kubectl logs job/inspectra-db-init -n inspectra
```

### Test Health Endpoints
```powershell
# Port-forward backend pod to test locally
kubectl port-forward svc/inspectra-backend 5000:5000 -n inspectra

# In another terminal:
curl http://localhost:5000/healthz
# Should return: {"status":"ok"}

curl http://localhost:5000/readyz
# Should return: {"status":"ready"}
```

### Database Verification
```powershell
# Port-forward Postgres
kubectl port-forward svc/postgres 5432:5432 -n inspectra

# Connect with a Postgres client (install: https://www.pgadmin.org/)
# Host: localhost
# Port: 5432
# User: inspectra_user (from k8s/secrets.yaml)
# Password: [Your password from secrets]
# Database: inspectra

# Verify tables were created:
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
```

## Part 6: Scale and Monitor

### Scale Backend Pods Manually
```powershell
# Scale to 4 pods
kubectl scale deployment inspectra-backend --replicas=4 -n inspectra

# Watch autoscaler do its magic
kubectl get hpa -n inspectra -w
```

### View Resource Usage
```powershell
# Install metrics-server (if not present)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# View resource metrics
kubectl top pods -n inspectra
kubectl top nodes
```

### Test Pod Failure Recovery
```powershell
# Delete a backend pod
kubectl delete pod inspectra-backend-xxxxx -n inspectra

# Watch: Another pod immediately starts to replace it
kubectl get pods -n inspectra -w
```

## Troubleshooting

### Pod stuck in CrashLoopBackOff
```powershell
# Check logs
kubectl logs pod/inspectra-backend-xxxxx -n inspectra

# Common issues:
# - DATABASE_HOST is wrong
# - Secrets aren't populated
# - Database isn't ready yet
```

### Ingress not responding
```powershell
# Check ingress controller status
kubectl get ingressclass
kubectl get pods -n ingress-nginx

# Check ingress configuration
kubectl describe ingress inspectra-ingress -n inspectra

# Test DNS
nslookup inspectra.local
ping inspectra.local
```

### Database init job failed
```powershell
# Check job status
kubectl describe job inspectra-db-init -n inspectra

# Check logs
kubectl logs job/inspectra-db-init -n inspectra

# Re-run if needed
kubectl delete job inspectra-db-init -n inspectra
kubectl apply -f k8s/db-init-job.yaml
```

## Cleanup

### Remove All Resources
```powershell
# Delete everything via kustomize
kubectl delete -k k8s

# Or manually
kubectl delete namespace inspectra
```

### Cleanup Local Images
```powershell
docker rmi inspectra-backend:latest
```

## Next Steps

1. Configure CI/CD pipeline to automate builds and deployments
2. Setup monitoring (Prometheus + Grafana)
3. Implement centralized logging (ELK Stack)
4. Setup persistent backups for database
5. Implement network policies and pod security policies
6. Plan disaster recovery strategy

