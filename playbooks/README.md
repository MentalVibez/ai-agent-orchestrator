# Ansible playbooks (DEX remediation)

Used by the **Ansible agent** for the open-source DEX MVP. The orchestrator runs these via workflow steps or direct orchestration.

- **restart_service.yml** – Restart a service (Linux or Windows). Pass `service_name` in extra_vars.
- **ping.yml** – No-op test playbook (ping localhost).

Run workflows with `input_data.playbook` and optional `input_data.extra_vars`, or call the Ansible agent with context `playbook`, `inventory`, `limit`, `extra_vars`.
