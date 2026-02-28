# Runbook: Disk Space Cleanup

**Alert:** DiskFull / High Disk Usage (>85%)
**Severity:** Warning → Critical
**Category:** Storage

## Symptoms
- Disk usage exceeds 85% on one or more filesystems
- Applications failing to write logs or temp files
- Database write failures due to no space
- "No space left on device" errors in logs

## Diagnostic Steps
1. Identify the full filesystem: `df -h`
2. Find the largest directories: `du -sh /* 2>/dev/null | sort -rh | head -20`
3. Check for large log files: `find /var/log -size +100M -type f`
4. Check for orphaned Docker images/volumes: `docker system df`
5. Look for core dump files: `find / -name "core.*" -size +1M 2>/dev/null`

## Automated Remediation (Ansible: cleanup_disk.yml)
The `cleanup_disk` playbook performs the following steps:
1. Rotate and compress log files older than 7 days
2. Remove temporary files from `/tmp` older than 24 hours
3. Clear package manager cache (`apt clean` / `yum clean all`)
4. Remove orphaned Docker images (`docker image prune -f`)
5. Compress core dump files if found

## Manual Steps
```bash
# Clear systemd journal logs older than 7 days
sudo journalctl --vacuum-time=7d

# Clear apt cache
sudo apt-get clean

# Remove unused Docker resources
docker system prune -f

# Find and remove large temp files
find /tmp -type f -atime +1 -delete
```

## Prevention
- Configure `logrotate` for all application logs
- Set Docker log driver to `json-file` with `max-size: "50m"` and `max-file: "3"`
- Monitor disk trends — set alerts at 70% to allow lead time for cleanup
- Schedule weekly automated cleanup via cron or Ansible Tower

## Escalation
If disk usage returns to >90% within 24 hours after cleanup, escalate to Tier 2.
Check for runaway processes writing to disk continuously.
