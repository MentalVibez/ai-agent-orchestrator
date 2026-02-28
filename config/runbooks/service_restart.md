# Runbook: Service Restart and Recovery

**Alert:** ServiceDown / Service Not Responding
**Severity:** Warning → Critical (depends on service criticality)
**Category:** Service Availability

## Symptoms
- Systemd service in `failed` or `inactive` state
- Health check endpoint returning non-2xx response
- Docker container in `Exited` or `Dead` state
- Application users reporting "service unavailable"

## Diagnostic Steps
1. Check service status: `systemctl status <service-name>`
2. View recent logs: `journalctl -u <service-name> -n 50 --no-pager`
3. Check exit code: `systemctl show <service-name> --property=ExecMainCode`
4. Check resource limits: `systemctl show <service-name> --property=MemoryLimit,CPUQuota`
5. Verify dependencies are running: `systemctl list-dependencies <service-name>`

## Automated Remediation (Ansible: restart_service.yml)
The `restart_service` playbook:
1. Captures current service logs and status for audit
2. Attempts `systemctl restart <service>`
3. Waits 30 seconds for service to stabilize
4. Verifies service is `active (running)`
5. Runs a health check HTTP request if configured
6. Alerts if restart fails after 3 attempts

## Manual Steps
```bash
# Check why service failed
systemctl status myapp.service

# View last 100 lines of service log
journalctl -u myapp.service -n 100

# Restart the service
sudo systemctl restart myapp.service

# Enable auto-restart on failure (if not already set)
sudo systemctl edit myapp.service
# Add:
# [Service]
# Restart=always
# RestartSec=5s
sudo systemctl daemon-reload
sudo systemctl restart myapp.service
```

## Docker Container Recovery
```bash
# Check container status
docker ps -a | grep <container-name>

# View container logs
docker logs <container-name> --tail=100

# Restart container
docker restart <container-name>

# If container won't start, recreate it
docker-compose up -d <service-name>
```

## Prevention
- Configure `Restart=always` and `RestartSec=5` in systemd unit files
- Set memory limits to prevent OOM kills
- Use Docker health checks: `HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1`
- Monitor with Prometheus `up` metric and alert on absence

## Escalation
If service fails to stay up after 3 restarts within 10 minutes:
1. Check for code changes or deployments in the last hour
2. Review system resources (OOM events: `dmesg | grep -i oom`)
3. Escalate to Tier 2 with logs attached
