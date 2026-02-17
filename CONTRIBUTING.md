# Contributing to AI Agent Orchestrator

Thank you for your interest in contributing to AI Agent Orchestrator! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a Code of Conduct. By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/MentalVibez/ai-agent-orchestrator/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, etc.)
   - Relevant logs or error messages

### Suggesting Features

1. Check if the feature has already been suggested
2. Create a new issue with:
   - Clear description of the feature
   - Use case and motivation
   - Proposed implementation (if applicable)

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes**:
   - Follow the code style and conventions
   - Add tests for new functionality
   - Update documentation as needed
4. **Run tests**: `pytest tests/`
5. **Commit your changes**: Use clear, descriptive commit messages
6. **Push to your fork**: `git push origin feature/your-feature-name`
7. **Create a Pull Request** with:
   - Clear description of changes
   - Reference to related issues
   - Screenshots (if applicable)

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/MentalVibez/ai-agent-orchestrator.git
   cd ai-agent-orchestrator
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

5. Run tests:
   ```bash
   pytest tests/
   ```
   To run only unit tests (faster, no DB): `pytest tests/unit -v`

6. Optional – lint and type check:
   ```bash
   pip install ruff mypy
   ruff check app/ tests/
   mypy app/ --ignore-missing-imports
   ```

## Adding an MCP server

1. Edit `config/mcp_servers.yaml`: add an entry under `mcp_servers` with `name`, `transport: stdio`, `command`, `args`, and `enabled: true`.
2. Restart the app; the MCP client will connect at startup and discover tools.
3. In `config/agent_profiles.yaml`, set `allowed_mcp_servers: [your_server_id]` for any profile that should use it.

## Adding an agent profile

1. Edit `config/agent_profiles.yaml`: add an entry under `agent_profiles` with `name`, `description`, `role_prompt`, `allowed_mcp_servers` (list of MCP server ids or `[]` for legacy-only), and `enabled: true`.
2. Restart the app; new profiles appear in `GET /api/v1/agent-profiles` and can be used in `POST /api/v1/run` via `agent_profile_id`.

## Code Style

- Follow PEP 8 style guide
- Use type hints where appropriate
- Write docstrings for all public functions and classes
- Keep functions focused and small
- Use meaningful variable and function names

## Adding New Agents

See [ADDING_AGENTS.md](ADDING_AGENTS.md) for detailed instructions on adding new agents to the system.

## Testing

- Write tests for all new features
- Aim for >80% code coverage
- Run tests before submitting PRs
- Ensure all tests pass

## Documentation

- Update README.md if adding major features
- Add docstrings to new functions/classes
- Update relevant documentation files

## Questions?

Feel free to open an issue for questions or discussions.

Thank you for contributing! 🎉

