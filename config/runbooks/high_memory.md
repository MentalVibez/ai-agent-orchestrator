# Runbook: High Memory Usage / Memory Leak

**Alert:** HighMemory / MemoryLeak
**Severity:** Warning (>85%) → Critical (>95%)
**Category:** Performance

## Symptoms
- System memory usage exceeds 85%
- Swap usage increasing continuously (memory leak indicator)
- Applications experiencing `OutOfMemoryError` or `malloc failure`
- System becoming slow or unresponsive
- OOM killer terminating processes (`dmesg | grep -i "oom"`)

## Diagnostic Steps
1. Check memory overview: `free -h`
2. Find top memory consumers: `ps aux --sort=-%mem | head -20`
3. Check for memory leaks (growing RSS over time): `watch -n5 'ps aux --sort=-%mem | head -10'`
4. Check swap usage trend: `vmstat 5 10`
5. Review OOM killer events: `sudo dmesg | grep -E "oom|killed" | tail -20`

## Automated Remediation (Ansible: clear_cache.yml)
The `clear_cache` playbook:
1. Identifies the top 5 memory consumers
2. Clears the Linux page cache (safe, OS re-populates as needed):
   `echo 3 > /proc/sys/vm/drop_caches`
3. Clears application-specific caches (Redis FLUSHDB if configured)
4. Terminates any zombie processes consuming memory

## Manual Steps
```bash
# Check memory in detail
free -h && cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree"

# Find memory-hungry processes
ps aux --sort=-%mem | awk 'NR<=10{print $0}'

# Clear OS page cache (safe — data is not lost)
sudo sync
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'

# If a specific app is leaking, restart it
sudo systemctl restart <suspected-service>

# Check Java heap if applicable
jmap -heap <pid>
```

## Memory Leak Identification
A process has a memory leak if its `RSS` (Resident Set Size) grows continuously:
```bash
# Monitor a process's memory over time
PID=$(pgrep -f myapp)
while true; do
  ps -p $PID -o pid,rss,vsz,comm --no-headers
  sleep 30
done
```

## Prevention
- Set memory limits in systemd unit files: `MemoryLimit=2G`
- Configure JVM heap limits: `-Xmx2g -Xms512m`
- Use Docker `--memory=2g` to enforce container limits
- Enable swap but monitor swap usage — sustained swap usage = memory leak
- Alert at 75% memory to give time to investigate before crisis

## Escalation
If memory usage returns to >90% within 1 hour after cache clearing:
1. Capture heap dump of suspected process
2. Restart the leaking service (data loss risk — assess first)
3. Escalate to Tier 2/Dev team with heap dump and process history
