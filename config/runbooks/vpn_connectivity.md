# Runbook: VPN / Network Connectivity Issues

**Alert:** NetworkDegraded / HighLatency / PacketLoss
**Severity:** Warning → Critical
**Category:** Connectivity

## Symptoms
- VPN client disconnecting or failing to reconnect
- Ping to internal resources showing high latency (>100ms) or packet loss (>1%)
- DNS resolution failures for internal domains
- Remote desktop/SSH sessions dropping unexpectedly
- Applications timing out when connecting to internal services

## Diagnostic Steps
1. Check basic connectivity: `ping -c 10 8.8.8.8`
2. Check DNS resolution: `nslookup internal-service.company.com`
3. Trace route to internal gateway: `traceroute 10.0.0.1`
4. Check VPN interface status (Linux): `ip addr show tun0`
5. Check VPN logs: `journalctl -u openvpn@client -n 50 --no-pager`
6. Check firewall rules: `sudo iptables -L -n | grep DROP`

## Automated Remediation (Ansible: reset_network_stack.yml)
The `reset_network_stack` playbook:
1. Flushes DNS cache (`systemd-resolve --flush-caches` or `ipconfig /flushdns` on Windows)
2. Restarts the network manager service
3. Reconnects VPN if the client service is configured
4. Re-runs diagnostic ping/DNS test to confirm recovery

## Manual Steps
```bash
# Linux: Reset DNS cache
sudo systemd-resolve --flush-caches
resolvectl flush-caches

# Linux: Restart NetworkManager
sudo systemctl restart NetworkManager

# Linux: Reconnect OpenVPN
sudo systemctl restart openvpn@client

# Linux: Check routing table
ip route show

# Test internal DNS
dig @<internal-dns-server> internal-hostname.company.com

# Test with specific MTU (diagnose MTU issues)
ping -M do -s 1472 -c 5 8.8.8.8
```

## Windows Specific Steps
```powershell
# Flush DNS
ipconfig /flushdns

# Reset TCP/IP stack
netsh int ip reset
netsh winsock reset

# Check VPN adapter
Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*VPN*" }

# Reconnect VPN (if using Cisco AnyConnect or similar)
# Usually requires GUI interaction — escalate to user
```

## Common Root Causes
| Symptom | Likely Cause |
|---|---|
| VPN drops after 8+ hours | Session timeout — reconfigure keepalive |
| DNS fails only on VPN | Split DNS misconfiguration |
| High latency to all hosts | ISP issue or overloaded VPN gateway |
| Packet loss only on WiFi | WiFi interference or driver issue |
| Works on cable, not WiFi | MTU mismatch on wireless interface |

## Prevention
- Configure VPN client with `keepalive 10 120` to prevent idle timeouts
- Use redundant VPN gateways with automatic failover
- Monitor VPN gateway load — alert at 80% capacity
- Set up Prometheus `probe_success` alerts for critical internal endpoints

## Escalation
If network issues affect multiple users simultaneously:
1. Check if VPN gateway is overloaded or down
2. Contact ISP if issue is external-facing
3. Escalate to network team with traceroute and ping results attached
