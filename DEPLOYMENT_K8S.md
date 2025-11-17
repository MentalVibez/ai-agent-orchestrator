# Kubernetes Deployment Guide

This guide explains how to deploy the AI Agent Orchestrator to a Kubernetes cluster.

## Prerequisites

- Kubernetes cluster (1.20+)
- kubectl configured to access your cluster
- Docker image built and pushed to a container registry
- Persistent volume support (for database)

## Quick Start

1. **Build and push Docker image**:
   ```bash
   docker build -t your-registry/ai-agent-orchestrator:latest .
   docker push your-registry/ai-agent-orchestrator:latest
   ```

2. **Update image in deployment.yaml**:
   ```yaml
   image: your-registry/ai-agent-orchestrator:latest
   ```

3. **Create secrets**:
   ```bash
   # Copy the example secret file
   cp k8s/secret.yaml.example k8s/secret.yaml
   
   # Edit with your actual secrets
   nano k8s/secret.yaml
   
   # Create the secret
   kubectl apply -f k8s/secret.yaml
   ```

4. **Deploy the application**:
   ```bash
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/pvc.yaml
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/service.yaml
   kubectl apply -f k8s/hpa.yaml
   ```

5. **Verify deployment**:
   ```bash
   kubectl get pods -l app=ai-agent-orchestrator
   kubectl get svc ai-agent-orchestrator
   ```

## Configuration

### ConfigMap

The `configmap.yaml` contains non-sensitive configuration. Update it with your settings:

```bash
kubectl edit configmap orchestrator-config
```

### Secrets

Sensitive data should be stored in Kubernetes secrets. Create your secret:

```bash
kubectl create secret generic orchestrator-secrets \
  --from-literal=API_KEY=your-api-key \
  --from-literal=AWS_ACCESS_KEY_ID=your-key \
  --from-literal=AWS_SECRET_ACCESS_KEY=your-secret
```

### Resource Limits

Adjust resource requests and limits in `deployment.yaml` based on your workload:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

## Scaling

### Horizontal Pod Autoscaling (HPA)

The HPA is configured to scale based on CPU and memory usage:
- Min replicas: 3
- Max replicas: 10
- CPU target: 70%
- Memory target: 80%

Adjust these values in `hpa.yaml` as needed.

### Manual Scaling

```bash
kubectl scale deployment ai-agent-orchestrator --replicas=5
```

## Health Checks

The deployment includes:
- **Liveness probe**: Restarts unhealthy pods
- **Readiness probe**: Routes traffic only to ready pods

Both probes check `/api/v1/health` endpoint.

## Persistent Storage

The database is stored in a PersistentVolumeClaim. To use a different storage class:

```yaml
storageClassName: your-storage-class
```

## Service Types

The service is configured as `LoadBalancer`. For cloud providers:
- AWS: Creates an ELB
- GCP: Creates a Load Balancer
- Azure: Creates a Load Balancer

For internal-only access, change to `ClusterIP`:

```yaml
type: ClusterIP
```

## Monitoring

### View Logs

```bash
# All pods
kubectl logs -l app=ai-agent-orchestrator

# Specific pod
kubectl logs <pod-name>

# Follow logs
kubectl logs -f -l app=ai-agent-orchestrator
```

### Check Pod Status

```bash
kubectl get pods -l app=ai-agent-orchestrator
kubectl describe pod <pod-name>
```

### Check Resource Usage

```bash
kubectl top pods -l app=ai-agent-orchestrator
```

## Updating

1. **Build new image**:
   ```bash
   docker build -t your-registry/ai-agent-orchestrator:v1.1.0 .
   docker push your-registry/ai-agent-orchestrator:v1.1.0
   ```

2. **Update deployment**:
   ```bash
   kubectl set image deployment/ai-agent-orchestrator \
     orchestrator=your-registry/ai-agent-orchestrator:v1.1.0
   ```

3. **Rollout status**:
   ```bash
   kubectl rollout status deployment/ai-agent-orchestrator
   ```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod events
kubectl describe pod <pod-name>

# Check logs
kubectl logs <pod-name>
```

### Database Issues

```bash
# Check PVC
kubectl get pvc orchestrator-db-pvc

# Check volume mounts
kubectl describe pod <pod-name> | grep -A 5 "Mounts"
```

### Service Not Accessible

```bash
# Check service
kubectl get svc ai-agent-orchestrator

# Check endpoints
kubectl get endpoints ai-agent-orchestrator

# Test from within cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://ai-agent-orchestrator/api/v1/health
```

## Production Considerations

1. **Use Ingress**: For HTTPS and domain routing
2. **Network Policies**: Restrict pod-to-pod communication
3. **Pod Security Policies**: Enforce security standards
4. **Resource Quotas**: Limit resource usage per namespace
5. **Backup Strategy**: Regular database backups
6. **Monitoring**: Integrate with Prometheus/Grafana
7. **Logging**: Centralized logging (ELK, Loki, etc.)

## Ingress Example

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ai-agent-orchestrator-ingress
spec:
  rules:
  - host: api.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: ai-agent-orchestrator
            port:
              number: 80
```

Apply with:
```bash
kubectl apply -f ingress.yaml
```

