"""Input validation and sanitization utilities."""

import re
from typing import Any, Dict, Optional
from app.core.exceptions import ValidationError


# Maximum request sizes
MAX_TASK_LENGTH = 10000  # 10KB for task description
MAX_CONTEXT_SIZE = 50000  # 50KB for context data
MAX_AGENT_IDS = 10  # Maximum number of agent IDs in a request


def validate_task(task: Optional[str]) -> str:
    """
    Validate and sanitize task description.

    Args:
        task: Task description to validate

    Returns:
        Sanitized task string

    Raises:
        ValidationError: If task is invalid
    """
    if not task:
        raise ValidationError(
            "Task description is required",
            field="task"
        )
    
    if not isinstance(task, str):
        raise ValidationError(
            "Task must be a string",
            field="task"
        )
    
    # Check length
    if len(task) > MAX_TASK_LENGTH:
        raise ValidationError(
            f"Task description exceeds maximum length of {MAX_TASK_LENGTH} characters",
            field="task",
            details={"max_length": MAX_TASK_LENGTH, "provided_length": len(task)}
        )
    
    # Check for empty or whitespace-only
    task = task.strip()
    if not task:
        raise ValidationError(
            "Task description cannot be empty",
            field="task"
        )
    
    # Basic sanitization - remove control characters except newlines and tabs
    task = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', task)
    
    return task


def validate_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate and sanitize context dictionary.

    Args:
        context: Context dictionary to validate

    Returns:
        Sanitized context dictionary

    Raises:
        ValidationError: If context is invalid
    """
    if context is None:
        return {}
    
    if not isinstance(context, dict):
        raise ValidationError(
            "Context must be a dictionary",
            field="context"
        )
    
    # Check size (rough estimate)
    context_str = str(context)
    if len(context_str) > MAX_CONTEXT_SIZE:
        raise ValidationError(
            f"Context data exceeds maximum size of {MAX_CONTEXT_SIZE} characters",
            field="context",
            details={"max_size": MAX_CONTEXT_SIZE, "provided_size": len(context_str)}
        )
    
    # Validate context keys and values
    sanitized = {}
    for key, value in context.items():
        # Validate key
        if not isinstance(key, str):
            raise ValidationError(
                "Context keys must be strings",
                field="context",
                details={"invalid_key": str(key)}
            )
        
        # Sanitize key (alphanumeric, underscore, hyphen)
        sanitized_key = re.sub(r'[^a-zA-Z0-9_-]', '_', key)
        
        # Validate value types
        if isinstance(value, (str, int, float, bool, type(None))):
            # Sanitize string values
            if isinstance(value, str):
                # Remove control characters
                value = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', value)
                # Limit string length
                if len(value) > 10000:
                    raise ValidationError(
                        f"Context value for '{key}' exceeds maximum length of 10000 characters",
                        field="context",
                        details={"key": key, "max_length": 10000}
                    )
            sanitized[sanitized_key] = value
        elif isinstance(value, (list, dict)):
            # Recursively validate nested structures (with depth limit)
            sanitized[sanitized_key] = _validate_nested(value, depth=0, max_depth=3)
        else:
            # Convert other types to string
            sanitized[sanitized_key] = str(value)
    
    return sanitized


def _validate_nested(data: Any, depth: int, max_depth: int) -> Any:
    """
    Recursively validate nested data structures.

    Args:
        data: Data to validate
        depth: Current depth
        max_depth: Maximum allowed depth

    Returns:
        Sanitized data

    Raises:
        ValidationError: If depth limit exceeded
    """
    if depth > max_depth:
        raise ValidationError(
            f"Nested data structure exceeds maximum depth of {max_depth}",
            field="context"
        )
    
    if isinstance(data, dict):
        return {k: _validate_nested(v, depth + 1, max_depth) for k, v in data.items()}
    elif isinstance(data, list):
        return [_validate_nested(item, depth + 1, max_depth) for item in data[:100]]  # Limit list size
    elif isinstance(data, str):
        # Sanitize string
        return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', data)
    else:
        return data


def validate_agent_ids(agent_ids: Optional[list]) -> list:
    """
    Validate agent IDs list.

    Args:
        agent_ids: List of agent IDs to validate

    Returns:
        Sanitized list of agent IDs

    Raises:
        ValidationError: If agent IDs are invalid
    """
    if agent_ids is None:
        return []
    
    if not isinstance(agent_ids, list):
        raise ValidationError(
            "Agent IDs must be a list",
            field="agent_ids"
        )
    
    if len(agent_ids) > MAX_AGENT_IDS:
        raise ValidationError(
            f"Maximum of {MAX_AGENT_IDS} agent IDs allowed per request",
            field="agent_ids",
            details={"max_agents": MAX_AGENT_IDS, "provided_count": len(agent_ids)}
        )
    
    # Validate each agent ID
    sanitized = []
    for agent_id in agent_ids:
        if not isinstance(agent_id, str):
            raise ValidationError(
                "Agent IDs must be strings",
                field="agent_ids",
                details={"invalid_id": str(agent_id)}
            )
        
        # Sanitize agent ID (alphanumeric, underscore, hyphen)
        sanitized_id = re.sub(r'[^a-zA-Z0-9_-]', '', agent_id)
        if sanitized_id != agent_id:
            raise ValidationError(
                f"Agent ID contains invalid characters: {agent_id}",
                field="agent_ids",
                details={"invalid_id": agent_id}
            )
        
        if not sanitized_id:
            raise ValidationError(
                "Agent ID cannot be empty",
                field="agent_ids"
            )
        
        sanitized.append(sanitized_id)
    
    return sanitized


def validate_workflow_id(workflow_id: Optional[str]) -> str:
    """
    Validate workflow ID.

    Args:
        workflow_id: Workflow ID to validate

    Returns:
        Sanitized workflow ID

    Raises:
        ValidationError: If workflow ID is invalid
    """
    if not workflow_id:
        raise ValidationError(
            "Workflow ID is required",
            field="workflow_id"
        )
    
    if not isinstance(workflow_id, str):
        raise ValidationError(
            "Workflow ID must be a string",
            field="workflow_id"
        )
    
    # Sanitize workflow ID
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', workflow_id)
    
    if not sanitized:
        raise ValidationError(
            "Workflow ID cannot be empty",
            field="workflow_id"
        )
    
    if len(sanitized) > 100:
        raise ValidationError(
            "Workflow ID exceeds maximum length of 100 characters",
            field="workflow_id"
        )
    
    return sanitized

