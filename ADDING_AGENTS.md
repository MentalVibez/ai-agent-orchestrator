# Adding New Agents - Step-by-Step Guide

This guide will walk you through creating and registering a new agent in the AI Agent Orchestrator.

## 📋 Overview

An agent is a specialized component that handles specific types of tasks. Each agent:
- Inherits from `BaseAgent`
- Implements an `execute()` method
- Uses an LLM provider for intelligent responses
- Has specific capabilities
- Returns structured `AgentResult` objects
- **NEW**: Can use tools for file access, code search, and more
- **NEW**: Benefits from dynamic, context-aware prompt generation
- **NEW**: Automatically sandboxed with resource limits

## 🎯 Step-by-Step Instructions

### Step 1: Create the Agent File

Create a new file in `app/agents/` directory with a descriptive name.

**Example**: For a "Code Review Agent", create `app/agents/code_review.py`

```bash
touch app/agents/code_review.py
```

### Step 2: Import Required Modules

At the top of your new agent file, import the necessary modules:

```python
"""Code Review Agent for analyzing and reviewing code."""

from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentResult
from app.llm.base import LLMProvider
```

### Step 3: Create Your Agent Class

Create a class that inherits from `BaseAgent`:

```python
class CodeReviewAgent(BaseAgent):
    """Agent specialized in code review and analysis."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the Code Review Agent.

        Args:
            llm_provider: LLM provider instance
        """
        super().__init__(
            agent_id="code_review",  # Unique identifier (lowercase, underscores)
            name="Code Review Agent",  # Human-readable name
            description="Analyzes code, provides reviews, and suggests improvements",
            llm_provider=llm_provider,
            capabilities=[
                "code_analysis",
                "code_review",
                "bug_detection",
                "performance_optimization",
                "security_audit"
            ]
        )
```

**Key Points:**
- `agent_id`: Must be unique, lowercase, use underscores (e.g., `code_review`, `system_monitoring`)
- `name`: Human-readable display name
- `description`: What the agent does
- `capabilities`: List of strings describing what the agent can do

### Step 4: Implement the `execute()` Method

This is the core method that handles task execution:

```python
    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Execute a code review task.

        Args:
            task: Code review task description
            context: Optional context (e.g., code snippet, language, file path)

        Returns:
            AgentResult with review results
        """
        try:
            context = context or {}
            
            # Build system prompt for code review
            system_prompt = """You are an expert code reviewer. Analyze code for:
            - Bugs and potential issues
            - Performance optimizations
            - Security vulnerabilities
            - Code quality and best practices
            - Suggest improvements
            
            Be specific, actionable, and constructive."""
            
            # Build user prompt with task and context
            user_prompt = f"Code Review Task: {task}\n\n"
            
            if context:
                user_prompt += "Context Information:\n"
                for key, value in context.items():
                    user_prompt += f"- {key}: {value}\n"
                user_prompt += "\n"
            
            user_prompt += """Please provide:
            1. Code analysis summary
            2. Identified issues (bugs, security, performance)
            3. Code quality assessment
            4. Specific improvement recommendations"""
            
            # Generate response using LLM
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2  # Lower temperature for more focused technical responses
            )
            
            # Format output
            output = {
                "summary": response[:200] + "..." if len(response) > 200 else response,
                "full_review": response,
                "review_type": self._identify_review_type(task),
                "context_used": context
            }
            
            return self._format_result(
                success=True,
                output=output,
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "context_keys": list(context.keys()) if context else []
                }
            )
            
        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"Code review failed: {str(e)}",
                metadata={
                    "agent_id": self.agent_id,
                    "task": task
                }
            )
```

**Key Components:**
- **System Prompt**: Defines the agent's role and expertise
- **User Prompt**: Combines the task with context information
- **LLM Call**: Uses `self._generate_response()` to get LLM response
- **Output Formatting**: Structures the response
- **Error Handling**: Returns formatted error result on failure

### Step 5: Add Helper Methods (Optional)

You can add private helper methods for your agent's specific logic:

```python
    def _identify_review_type(self, task: str) -> str:
        """Identify the type of code review needed."""
        task_lower = task.lower()
        
        if any(keyword in task_lower for keyword in ['security', 'vulnerability', 'exploit']):
            return "security_review"
        elif any(keyword in task_lower for keyword in ['performance', 'optimize', 'speed']):
            return "performance_review"
        elif any(keyword in task_lower for keyword in ['bug', 'error', 'fix']):
            return "bug_detection"
        else:
            return "general_review"
```

### Step 6: Register the Agent

Open `app/core/services.py` and add your agent to the registration:

```python
# At the top, add your import
from app.agents.code_review import CodeReviewAgent

# In the initialize() method, register your agent
def initialize(self) -> None:
    """Initialize all services."""
    if self._initialized:
        return
    
    # Initialize LLM Manager
    self._llm_manager = LLMManager()
    llm_provider = self._llm_manager.initialize_provider()
    
    # Initialize Agent Registry
    self._agent_registry = AgentRegistry()
    
    # Register agents
    network_agent = NetworkDiagnosticsAgent(llm_provider=llm_provider)
    self._agent_registry.register(network_agent)
    
    # Register your new agent
    code_review_agent = CodeReviewAgent(llm_provider=llm_provider)
    self._agent_registry.register(code_review_agent)
    
    # ... rest of initialization
```

### Step 7: Update Orchestrator Routing (Optional)

If you want the orchestrator to automatically route tasks to your agent, update `app/core/orchestrator.py`:

```python
async def route_task(
    self,
    task: str,
    context: Optional[Dict[str, Any]] = None
) -> AgentResult:
    # ... existing code ...
    
    # Code review keywords
    code_keywords = ['code', 'review', 'analyze', 'bug', 'security', 'optimize']
    if not selected_agent and any(keyword in task_lower for keyword in code_keywords):
        selected_agent = self.agent_registry.get("code_review")
    
    # ... rest of routing logic ...
```

### Step 8: Test Your Agent

#### Test via API

```bash
# Start the server
uvicorn app.main:app --reload

# Test listing agents (should include your new agent)
curl -H "X-API-Key: your-api-key" \
     http://localhost:8000/api/v1/agents

# Test your agent directly
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Review this code for security vulnerabilities",
    "context": {
      "code": "def login(username, password):\n    query = f\"SELECT * FROM users WHERE username={username}\"",
      "language": "python"
    }
  }' \
  http://localhost:8000/api/v1/orchestrate
```

#### Test via Python

```python
from app.agents.code_review import CodeReviewAgent
from app.llm.bedrock import BedrockProvider

# Create LLM provider
llm_provider = BedrockProvider()

# Create agent
agent = CodeReviewAgent(llm_provider=llm_provider)

# Execute task
import asyncio
result = asyncio.run(agent.execute(
    task="Review this code for bugs",
    context={"code": "def add(a, b): return a + b"}
))

print(result.success)
print(result.output)
```

## 📝 Complete Example: Code Review Agent

Here's a complete example agent file:

```python
"""Code Review Agent for analyzing and reviewing code."""

from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentResult
from app.llm.base import LLMProvider


class CodeReviewAgent(BaseAgent):
    """Agent specialized in code review and analysis."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the Code Review Agent.

        Args:
            llm_provider: LLM provider instance
        """
        super().__init__(
            agent_id="code_review",
            name="Code Review Agent",
            description="Analyzes code, provides reviews, and suggests improvements",
            llm_provider=llm_provider,
            capabilities=[
                "code_analysis",
                "code_review",
                "bug_detection",
                "performance_optimization",
                "security_audit"
            ]
        )

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Execute a code review task.

        Args:
            task: Code review task description
            context: Optional context (e.g., code snippet, language, file path)

        Returns:
            AgentResult with review results
        """
        try:
            context = context or {}
            
            # Build system prompt
            system_prompt = """You are an expert code reviewer. Analyze code for:
            - Bugs and potential issues
            - Performance optimizations
            - Security vulnerabilities
            - Code quality and best practices
            - Suggest improvements
            
            Be specific, actionable, and constructive."""
            
            # Build user prompt
            user_prompt = f"Code Review Task: {task}\n\n"
            
            if context:
                user_prompt += "Context Information:\n"
                for key, value in context.items():
                    user_prompt += f"- {key}: {value}\n"
                user_prompt += "\n"
            
            user_prompt += """Please provide:
            1. Code analysis summary
            2. Identified issues (bugs, security, performance)
            3. Code quality assessment
            4. Specific improvement recommendations"""
            
            # Generate response
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2
            )
            
            # Format output
            output = {
                "summary": response[:200] + "..." if len(response) > 200 else response,
                "full_review": response,
                "review_type": self._identify_review_type(task),
                "context_used": context
            }
            
            return self._format_result(
                success=True,
                output=output,
                metadata={
                    "agent_id": self.agent_id,
                    "task": task,
                    "context_keys": list(context.keys()) if context else []
                }
            )
            
        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"Code review failed: {str(e)}",
                metadata={
                    "agent_id": self.agent_id,
                    "task": task
                }
            )
    
    def _identify_review_type(self, task: str) -> str:
        """Identify the type of code review needed."""
        task_lower = task.lower()
        
        if any(keyword in task_lower for keyword in ['security', 'vulnerability', 'exploit']):
            return "security_review"
        elif any(keyword in task_lower for keyword in ['performance', 'optimize', 'speed']):
            return "performance_review"
        elif any(keyword in task_lower for keyword in ['bug', 'error', 'fix']):
            return "bug_detection"
        else:
            return "general_review"
```

## ✅ Checklist

When adding a new agent, make sure you:

- [ ] Created agent file in `app/agents/`
- [ ] Inherited from `BaseAgent`
- [ ] Implemented `execute()` method
- [ ] Added proper docstrings
- [ ] Defined unique `agent_id`
- [ ] Listed capabilities
- [ ] Added error handling
- [ ] Registered agent in `app/core/services.py`
- [ ] Updated orchestrator routing (optional)
- [ ] Tested the agent via API
- [ ] Verified agent appears in `/api/v1/agents` endpoint

## 🎯 Best Practices

### 1. **Agent ID Naming**
- Use lowercase
- Use underscores for separation
- Be descriptive but concise
- Examples: `code_review`, `system_monitoring`, `log_analysis`

### 2. **Capabilities**
- List specific, actionable capabilities
- Use consistent naming
- Examples: `code_analysis`, `bug_detection`, `security_audit`

### 3. **Error Handling**
- Always wrap execution in try/except
- Return formatted error results
- Include context in error metadata

### 4. **System Prompts**
- Be specific about the agent's role
- Include what to analyze
- Specify output format expectations

### 5. **Temperature Settings**
- Lower temperature (0.2-0.3) for technical/analytical tasks
- Higher temperature (0.7-0.9) for creative tasks
- Default: 0.7

### 6. **Output Formatting**
- Include a summary (first 200 chars)
- Include full response
- Add metadata for context
- Use consistent structure

## 🔍 Troubleshooting

### Agent Not Appearing in List

**Problem**: Agent doesn't show up in `/api/v1/agents`

**Solutions**:
1. Check that agent is registered in `app/core/services.py`
2. Verify import statement is correct
3. Restart the server
4. Check logs for import errors

### Agent Not Being Selected

**Problem**: Orchestrator doesn't route tasks to your agent

**Solutions**:
1. Update routing keywords in `app/core/orchestrator.py`
2. Use specific agent IDs in requests: `{"agent_ids": ["your_agent_id"]}`
3. Check agent capabilities match task keywords

### LLM Errors

**Problem**: Agent fails with LLM provider errors

**Solutions**:
1. Check AWS credentials are configured
2. Verify Bedrock model access
3. Check retry logic is working
4. Review error logs for specific error codes

## 📚 Additional Resources

- **Base Agent**: See `app/agents/base.py` for available methods
- **Existing Agents**: See `app/agents/network_diagnostics.py` for reference
- **Agent Result Model**: See `app/models/agent.py` for response structure
- **LLM Provider**: See `app/llm/bedrock.py` for LLM usage examples

## 🚀 Quick Start Template

Copy this template to create a new agent quickly:

```python
"""Your Agent Name - Brief description."""

from typing import Dict, Any, Optional
from app.agents.base import BaseAgent
from app.models.agent import AgentResult
from app.llm.base import LLMProvider


class YourAgentName(BaseAgent):
    """Agent specialized in [your specialization]."""

    def __init__(self, llm_provider: LLMProvider):
        super().__init__(
            agent_id="your_agent_id",
            name="Your Agent Name",
            description="What your agent does",
            llm_provider=llm_provider,
            capabilities=["capability1", "capability2"]
        )

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        try:
            context = context or {}
            
            system_prompt = """Your system prompt here"""
            
            user_prompt = f"Task: {task}\n\n"
            if context:
                for key, value in context.items():
                    user_prompt += f"- {key}: {value}\n"
            
            response = await self._generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.7
            )
            
            output = {
                "summary": response[:200] + "..." if len(response) > 200 else response,
                "full_response": response,
                "context_used": context
            }
            
            return self._format_result(
                success=True,
                output=output,
                metadata={"agent_id": self.agent_id, "task": task}
            )
            
        except Exception as e:
            return self._format_result(
                success=False,
                output={},
                error=f"Execution failed: {str(e)}",
                metadata={"agent_id": self.agent_id, "task": task}
            )
```

## 🎉 You're Done!

Your agent is now ready to use. Test it, iterate on the prompts, and add it to your orchestrator routing if needed!

