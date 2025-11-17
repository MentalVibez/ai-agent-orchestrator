"""
Example Backend Proxy for Python/Flask
 * 
 * This file shows how to integrate the orchestrator API into your existing backend.
 * Add this blueprint to your Flask application.
"""

from flask import Blueprint, request, jsonify
import requests
import os
from typing import Dict, Any

orchestrator_bp = Blueprint('orchestrator', __name__)

# Load from environment variables
ORCHESTRATOR_API_URL = os.getenv('ORCHESTRATOR_API_URL', 'https://api.donsylvester.dev')
ORCHESTRATOR_API_KEY = os.getenv('ORCHESTRATOR_API_KEY')

if not ORCHESTRATOR_API_KEY:
    print('Warning: ORCHESTRATOR_API_KEY not set. Orchestrator integration will not work.')


@orchestrator_bp.route('/chatbot/orchestrate', methods=['POST'])
def orchestrate():
    """
    Proxy endpoint for chatbot to use orchestrator.
    POST /api/chatbot/orchestrate
    """
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        message = data.get('message', '')
        context = data.get('context', {})
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Check if orchestrator should be used
        if not should_use_orchestrator(message):
            return jsonify({
                'useOrchestrator': False,
                'message': 'Handled by regular chatbot',
                'suggestion': 'This query can be handled by your regular chatbot'
            })
        
        # Call orchestrator API
        response = requests.post(
            f'{ORCHESTRATOR_API_URL}/api/v1/orchestrate',
            json={
                'task': message,
                'context': {
                    **context,
                    'source': 'chatbot',
                    'timestamp': __import__('datetime').datetime.utcnow().isoformat()
                }
            },
            headers={
                'X-API-Key': ORCHESTRATOR_API_KEY,
                'Content-Type': 'application/json'
            },
            timeout=30
        )
        response.raise_for_status()
        
        return jsonify({
            'useOrchestrator': True,
            'result': response.json()
        })
        
    except requests.exceptions.Timeout:
        return jsonify({
            'error': 'Orchestrator timeout',
            'message': 'The orchestrator service took too long to respond',
            'useOrchestrator': False
        }), 504
        
    except requests.exceptions.ConnectionError:
        return jsonify({
            'error': 'Orchestrator unavailable',
            'message': 'Cannot connect to orchestrator service',
            'useOrchestrator': False
        }), 503
        
    except requests.exceptions.HTTPError as e:
        return jsonify({
            'error': 'Orchestrator API error',
            'message': e.response.text if e.response else str(e),
            'useOrchestrator': False
        }), e.response.status_code if e.response else 500
        
    except Exception as e:
        return jsonify({
            'error': 'Internal error',
            'message': str(e),
            'useOrchestrator': False
        }), 500


@orchestrator_bp.route('/chatbot/agents', methods=['GET'])
def get_agents():
    """
    Get available agents from orchestrator.
    GET /api/chatbot/agents
    """
    try:
        response = requests.get(
            f'{ORCHESTRATOR_API_URL}/api/v1/agents',
            headers={
                'X-API-Key': ORCHESTRATOR_API_KEY
            },
            timeout=10
        )
        response.raise_for_status()
        return jsonify(response.json())
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to fetch agents',
            'message': str(e)
        }), 500


def should_use_orchestrator(message: str) -> bool:
    """
    Helper function to detect if orchestrator should be used.
    You can enhance this with ML-based intent classification.
    """
    lower_message = message.lower()
    
    # Keywords that indicate specialized agent needs
    orchestrator_keywords = [
        # Network-related
        'network', 'connectivity', 'ping', 'dns', 'latency', 'connection',
        'reachable', 'timeout', 'packet', 'route', 'traceroute',
        
        # System-related
        'system', 'monitor', 'cpu', 'memory', 'disk', 'performance',
        'load', 'usage', 'process', 'thread', 'resource',
        
        # Log-related
        'log', 'error', 'exception', 'debug', 'trace', 'troubleshoot',
        'diagnose', 'analyze logs', 'error log',
        
        # Infrastructure-related
        'infrastructure', 'deploy', 'server', 'configure', 'setup',
        'provision', 'environment',
        
        # General diagnostics
        'diagnose', 'troubleshoot', 'check', 'verify', 'test connection'
    ]
    
    return any(keyword in lower_message for keyword in orchestrator_keywords)


# Example usage in your Flask app:
# from examples.backend_proxy_python import orchestrator_bp
# app.register_blueprint(orchestrator_bp, url_prefix='/api')

