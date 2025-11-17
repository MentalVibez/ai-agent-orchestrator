# AI Agent Orchestrator

A multi-agent backend system that coordinates specialized LLM-powered agents to handle complex IT diagnostics and IT engineering workflows through a single HTTP API.

## Overview

The AI Agent Orchestrator is a FastAPI-based system that enables coordination of multiple specialized AI agents for IT operations. Each agent is designed to handle specific types of tasks (network diagnostics, system monitoring, log analysis, infrastructure management) and can work independently or collaboratively through the orchestrator.

## Architecture

### Core Components

- **Orchestrator**: Routes tasks to appropriate agents and coordinates multi-agent workflows
- **Agent Registry**: Manages available agents and their capabilities
- **Workflow Executor**: Executes multi-step workflows involving multiple agents
- **LLM Manager**: Manages LLM provider selection and initialization
- **Message Bus**: Enables agent-to-agent communication

### Agents

- **Network Diagnostics Agent**: Handles network connectivity, latency, routing, and DNS issues
- **System Monitoring Agent**: Monitors CPU, memory, disk usage, and processes
- **Log Analysis Agent**: Analyzes logs, detects errors, and provides troubleshooting insights
- **Infrastructure Agent**: Handles provisioning, configuration management, and deployment

### LLM Providers

- **AWS Bedrock** (Primary): Claude 3 Haiku - Low-cost, serverless option
- **OpenAI**: GPT-3.5-turbo - Alternative provider
- **Ollama**: Local/open-source models - Free, self-hosted option

## Setup

### Prerequisites

- Python 3.9 or higher
- pip or poetry for dependency management
- AWS credentials (if using Bedrock)
- OpenAI API key (if using OpenAI)
- Ollama installed locally (if using Ollama)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
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

4. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Environment Variables

Key environment variables to configure:

- `LLM_PROVIDER`: Provider to use (bedrock, openai, ollama)
- `AWS_REGION`: AWS region for Bedrock
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `OPENAI_API_KEY`: OpenAI API key (if using OpenAI)
- `CORS_ORIGINS`: Comma-separated list of allowed origins

## Running the Application

### Development Mode

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Documentation: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Health Check

```http
GET /api/v1/health
```

Returns the health status of the application.

### Orchestrate Task

```http
POST /api/v1/orchestrate
Content-Type: application/json

{
  "task": "Diagnose network connectivity issues",
  "context": {
    "hostname": "example.com",
    "port": 443
  }
}
```

Submits a task to the orchestrator for execution by appropriate agents.

### List Agents

```http
GET /api/v1/agents
```

Returns a list of all available agents and their capabilities.

### Get Agent Details

```http
GET /api/v1/agents/{agent_id}
```

Returns detailed information about a specific agent.

### Execute Workflow

```http
POST /api/v1/workflows
Content-Type: application/json

{
  "workflow_id": "network_diagnostics_workflow",
  "input_data": {
    "target": "example.com"
  }
}
```

Executes a predefined multi-step workflow.

## Usage Examples

### Example 1: Network Diagnostics

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/orchestrate",
    json={
        "task": "Check connectivity to example.com on port 443",
        "context": {
            "hostname": "example.com",
            "port": 443
        }
    }
)

result = response.json()
print(result)
```

### Example 2: System Monitoring

```python
response = requests.post(
    "http://localhost:8000/api/v1/orchestrate",
    json={
        "task": "Monitor CPU and memory usage",
        "context": {
            "duration": 60,
            "interval": 5
        }
    }
)
```

### Example 3: Log Analysis

```python
response = requests.post(
    "http://localhost:8000/api/v1/orchestrate",
    json={
        "task": "Analyze error logs and identify root cause",
        "context": {
            "log_file": "/var/log/app/error.log",
            "time_range": "last_24_hours"
        }
    }
)
```

## Project Structure

```
ai-agent-orchestrator/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   └── v1/
│   │       └── routes/         # API route handlers
│   ├── core/
│   │   ├── config.py           # Configuration management
│   │   ├── orchestrator.py     # Orchestration engine
│   │   ├── agent_registry.py   # Agent registry
│   │   ├── workflow_executor.py # Workflow executor
│   │   └── messaging.py        # Message bus
│   ├── agents/
│   │   ├── base.py             # Base agent class
│   │   ├── network_diagnostics.py
│   │   ├── system_monitoring.py
│   │   ├── log_analysis.py
│   │   └── infrastructure.py
│   ├── llm/
│   │   ├── base.py             # LLM provider interface
│   │   ├── bedrock.py          # AWS Bedrock provider
│   │   ├── openai.py           # OpenAI provider
│   │   ├── ollama.py           # Ollama provider
│   │   └── manager.py          # LLM manager
│   ├── models/
│   │   ├── agent.py            # Agent data models
│   │   ├── workflow.py         # Workflow data models
│   │   └── request.py          # API request/response models
│   └── workflows/
│       └── examples/           # Example workflow definitions
├── config/
│   ├── agents.yaml             # Agent configurations
│   └── llm.yaml                # LLM provider configurations
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Development

### Implementing Agents

All agents inherit from `BaseAgent` and must implement the `execute` method:

```python
from app.agents.base import BaseAgent
from app.models.agent import AgentResult

class MyAgent(BaseAgent):
    async def execute(self, task: str, context: Optional[Dict] = None) -> AgentResult:
        # Implement agent logic here
        result = await self._generate_response(prompt)
        return self._format_result(success=True, output=result)
```

### Implementing LLM Providers

All LLM providers inherit from `LLMProvider` and must implement:

- `generate()`: Generate text response
- `stream()`: Stream text response
- `generate_with_metadata()`: Generate response with usage metadata

### Adding Workflows

Workflows are defined as YAML or JSON files in the `app/workflows/` directory. Each workflow consists of multiple steps that can be executed by different agents.

## Configuration

### Agent Configuration

Edit `config/agents.yaml` to configure agent capabilities and settings.

### LLM Configuration

Edit `config/llm.yaml` to configure LLM provider settings and defaults.

## Testing

```bash
# Run tests (when implemented)
pytest
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Specify your license here]

## Support

For issues and questions, please open an issue on the repository.

