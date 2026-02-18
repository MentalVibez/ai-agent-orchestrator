# Integration Guide for yourdomain.com Chatbot

This guide explains how to integrate the AI Agent Orchestrator into your yourdomain.com chatbot to enhance its capabilities with specialized agents.

## 🎯 Use Case: Chatbot Enhancement

Your chatbot can leverage the orchestrator to:
- **Route complex queries** to specialized agents (network diagnostics, system monitoring, etc.)
- **Handle multi-step workflows** that require coordination between agents
- **Provide specialized IT diagnostics** beyond general conversation
- **Maintain separation** between conversational AI and specialized task agents

## 🏗️ Integration Architecture

```
┌─────────────────────────────────────────┐
│   yourdomain.com Chatbot (Frontend)   │
│   - User interacts with chatbot          │
│   - Detects when to use orchestrator     │
└──────────────┬───────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Your Backend (yourdomain.com/api)    │
│   - Chatbot logic                        │
│   - Routes to orchestrator when needed   │
│   - Stores API key securely              │
└──────────────┬───────────────────────────┘
               │ HTTPS + API Key
               ▼
┌─────────────────────────────────────────┐
│   Orchestrator API (api.yourdomain.com)│
│   - Specialized agent coordination       │
│   - Returns structured results           │
└─────────────────────────────────────────┘
```

## 📋 Setup Checklist

### 1. **Deploy the Orchestrator API**
   - [ ] Set up subdomain: `api.yourdomain.com`
   - [ ] Configure SSL certificate
   - [ ] Deploy using Docker or direct Python
   - [ ] Set environment variables (see below)

### 2. **Configure Environment Variables**
   - [ ] Generate API key for your backend
   - [ ] Configure AWS Bedrock credentials
   - [ ] Set CORS to allow your domain
   - [ ] Configure rate limits

### 3. **Create Backend Proxy**
   - [ ] Add API route to your existing backend
   - [ ] Store orchestrator API key securely
   - [ ] Implement request routing logic
   - [ ] Handle errors and timeouts

### 4. **Integrate with Chatbot**
   - [ ] Detect when to use orchestrator
   - [ ] Format user queries for orchestrator
   - [ ] Display agent results in chatbot UI
   - [ ] Handle multi-step workflows

## 🔧 Step-by-Step Integration

### Step 1: Deploy Orchestrator API

Follow the `DEPLOYMENT.md` guide to deploy the API. Key points:

```bash
# On your server
cd /path/to/ai-agent-orchestrator
cp env.template .env

# Edit .env with your settings
nano .env
```

**Critical Environment Variables:**
```bash
# Generate a strong API key for your backend to use
API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Allow your domain
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Your AWS credentials for Bedrock
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
```

### Step 2: Create Backend Proxy Endpoint

Add this to your existing backend (Node.js/Express example):

```javascript
// routes/orchestrator.js
const express = require('express');
const router = express.Router();
const axios = require('axios');

const ORCHESTRATOR_API_URL = process.env.ORCHESTRATOR_API_URL || 'https://api.yourdomain.com';
const ORCHESTRATOR_API_KEY = process.env.ORCHESTRATOR_API_KEY; // Set in your backend .env

// Proxy endpoint for chatbot to use
router.post('/chatbot/orchestrate', async (req, res) => {
  try {
    const { message, context } = req.body;
    
    // Determine if message needs orchestrator
    const needsOrchestrator = shouldUseOrchestrator(message);
    
    if (!needsOrchestrator) {
      return res.json({ 
        useOrchestrator: false,
        message: 'Handled by regular chatbot' 
      });
    }
    
    // Call orchestrator API
    const response = await axios.post(
      `${ORCHESTRATOR_API_URL}/api/v1/orchestrate`,
      {
        task: message,
        context: context || {}
      },
      {
        headers: {
          'X-API-Key': ORCHESTRATOR_API_KEY,
          'Content-Type': 'application/json'
        },
        timeout: 30000 // 30 second timeout
      }
    );
    
    res.json({
      useOrchestrator: true,
      result: response.data
    });
    
  } catch (error) {
    console.error('Orchestrator error:', error.message);
    res.status(500).json({
      error: 'Failed to process with orchestrator',
      message: error.message
    });
  }
});

// Helper function to detect if orchestrator should be used
function shouldUseOrchestrator(message) {
  const lowerMessage = message.toLowerCase();
  
  // Keywords that indicate specialized agent needs
  const orchestratorKeywords = [
    'network', 'connectivity', 'ping', 'dns', 'latency',
    'system', 'monitor', 'cpu', 'memory', 'disk',
    'log', 'error', 'troubleshoot', 'diagnose',
    'infrastructure', 'deploy', 'configure'
  ];
  
  return orchestratorKeywords.some(keyword => 
    lowerMessage.includes(keyword)
  );
}

module.exports = router;
```

**Python/Flask Example:**
```python
# routes/orchestrator.py
from flask import Blueprint, request, jsonify
import requests
import os

orchestrator_bp = Blueprint('orchestrator', __name__)

ORCHESTRATOR_API_URL = os.getenv('ORCHESTRATOR_API_URL', 'https://api.yourdomain.com')
ORCHESTRATOR_API_KEY = os.getenv('ORCHESTRATOR_API_KEY')

@orchestrator_bp.route('/chatbot/orchestrate', methods=['POST'])
def orchestrate():
    data = request.json
    message = data.get('message', '')
    context = data.get('context', {})
    
    # Check if orchestrator should be used
    if not should_use_orchestrator(message):
        return jsonify({
            'useOrchestrator': False,
            'message': 'Handled by regular chatbot'
        })
    
    try:
        # Call orchestrator API
        response = requests.post(
            f'{ORCHESTRATOR_API_URL}/api/v1/orchestrate',
            json={
                'task': message,
                'context': context
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
    except requests.exceptions.RequestException as e:
        return jsonify({
            'error': 'Failed to process with orchestrator',
            'message': str(e)
        }), 500

def should_use_orchestrator(message):
    keywords = [
        'network', 'connectivity', 'ping', 'dns', 'latency',
        'system', 'monitor', 'cpu', 'memory', 'disk',
        'log', 'error', 'troubleshoot', 'diagnose',
        'infrastructure', 'deploy', 'configure'
    ]
    return any(keyword in message.lower() for keyword in keywords)
```

### Step 3: Integrate with Chatbot Frontend

Update your chatbot frontend to use the backend proxy:

```javascript
// chatbot.js or similar
async function handleChatbotMessage(userMessage) {
  try {
    // First, try regular chatbot
    let response = await callRegularChatbot(userMessage);
    
    // Check if we should use orchestrator
    const orchestratorResponse = await fetch('/api/chatbot/orchestrate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message: userMessage,
        context: {
          // Add any relevant context
          user_id: getCurrentUserId(),
          session_id: getSessionId()
        }
      })
    });
    
    const orchestratorData = await orchestratorResponse.json();
    
    if (orchestratorData.useOrchestrator) {
      // Use orchestrator result
      return formatOrchestratorResponse(orchestratorData.result);
    }
    
    // Use regular chatbot response
    return response;
    
  } catch (error) {
    console.error('Chatbot error:', error);
    return { error: 'Sorry, I encountered an error. Please try again.' };
  }
}

function formatOrchestratorResponse(result) {
  // Format the orchestrator response for chatbot display
  if (result.agents && result.agents.length > 0) {
    const agentResults = result.agents
      .map(agent => `**${agent.agent_id}**: ${agent.result.summary}`)
      .join('\n\n');
    
    return {
      message: `I've analyzed your request using specialized agents:\n\n${agentResults}`,
      type: 'orchestrator',
      raw: result
    };
  }
  
  return {
    message: result.message || 'Processing complete.',
    type: 'orchestrator',
    raw: result
  };
}
```

### Step 4: Enhanced Chatbot Flow

Create a more sophisticated routing system:

```javascript
// Enhanced chatbot with smart routing
class EnhancedChatbot {
  constructor() {
    this.orchestratorEnabled = true;
  }
  
  async processMessage(userMessage, conversationHistory = []) {
    // Analyze message intent
    const intent = await this.analyzeIntent(userMessage);
    
    // Route based on intent
    if (intent.requiresSpecializedAgent) {
      return await this.useOrchestrator(userMessage, intent);
    }
    
    // Use regular chatbot
    return await this.useRegularChatbot(userMessage, conversationHistory);
  }
  
  async analyzeIntent(message) {
    // Simple keyword-based (you can enhance with ML)
    const lowerMessage = message.toLowerCase();
    
    const intents = {
      network: ['network', 'connectivity', 'ping', 'dns', 'latency', 'connection'],
      system: ['system', 'monitor', 'cpu', 'memory', 'disk', 'performance'],
      logs: ['log', 'error', 'exception', 'debug', 'trace'],
      infrastructure: ['deploy', 'infrastructure', 'server', 'configure', 'setup']
    };
    
    for (const [intent, keywords] of Object.entries(intents)) {
      if (keywords.some(keyword => lowerMessage.includes(keyword))) {
        return {
          type: intent,
          requiresSpecializedAgent: true,
          confidence: 0.8
        };
      }
    }
    
    return {
      type: 'general',
      requiresSpecializedAgent: false,
      confidence: 0.9
    };
  }
  
  async useOrchestrator(message, intent) {
    try {
      const response = await fetch('/api/chatbot/orchestrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          context: {
            intent: intent.type,
            timestamp: new Date().toISOString()
          }
        })
      });
      
      const data = await response.json();
      
      if (data.useOrchestrator) {
        return this.formatAgentResponse(data.result);
      }
      
      // Fallback to regular chatbot
      return await this.useRegularChatbot(message);
      
    } catch (error) {
      console.error('Orchestrator error:', error);
      return {
        message: "I'm having trouble with specialized analysis. Let me try a general response...",
        fallback: true
      };
    }
  }
  
  formatAgentResponse(result) {
    // Format for chatbot display
    if (result.agents && result.agents.length > 0) {
      const formatted = result.agents.map(agent => {
        return {
          agent: agent.agent_id,
          summary: agent.result.summary,
          details: agent.result.details,
          status: agent.status
        };
      });
      
      return {
        message: this.createUserFriendlyMessage(formatted),
        agents: formatted,
        type: 'agent_response'
      };
    }
    
    return {
      message: result.message || 'Analysis complete.',
      type: 'agent_response'
    };
  }
  
  createUserFriendlyMessage(agentResults) {
    const summaries = agentResults
      .map(a => `• ${a.agent}: ${a.summary}`)
      .join('\n');
    
    return `I've analyzed your request using specialized tools:\n\n${summaries}`;
  }
  
  async useRegularChatbot(message, history) {
    // Your existing chatbot logic
    // ...
  }
}
```

## 🔐 Security Best Practices

### 1. **Never Expose API Key in Frontend**
   - ✅ Store API key in backend environment variables
   - ✅ Use backend proxy (as shown above)
   - ❌ Never put API key in client-side JavaScript

### 2. **Environment Variables for Backend**
```bash
# Your backend .env file
ORCHESTRATOR_API_URL=https://api.yourdomain.com
ORCHESTRATOR_API_KEY=your-generated-api-key-here
```

### 3. **Rate Limiting**
   - The orchestrator has built-in rate limiting
   - Consider additional rate limiting in your backend proxy
   - Monitor usage to adjust limits

## 📊 Example Use Cases

### Use Case 1: Network Diagnostics Query

**User:** "Can you check if example.com is reachable?"

**Chatbot Flow:**
1. Detects "network" keyword
2. Routes to orchestrator
3. Network Diagnostics Agent analyzes
4. Returns formatted result

**Response:**
```
I've analyzed the network connectivity:

• Network Diagnostics Agent: 
  - example.com is reachable
  - Response time: 45ms
  - DNS resolution: successful
  - SSL certificate: valid
```

### Use Case 2: System Monitoring Query

**User:** "What's the current system load?"

**Chatbot Flow:**
1. Detects "system" keyword
2. Routes to orchestrator
3. System Monitoring Agent checks metrics
4. Returns formatted result

### Use Case 3: General Conversation

**User:** "Hello, how are you?"

**Chatbot Flow:**
1. No specialized keywords detected
2. Uses regular chatbot
3. Normal conversation flow

## 🧪 Testing the Integration

### Test Backend Proxy
```bash
curl -X POST http://localhost:3000/api/chatbot/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check network connectivity to google.com",
    "context": {}
  }'
```

### Test Orchestrator Directly (for debugging)
```bash
curl -X POST https://api.yourdomain.com/api/v1/orchestrate \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Check network connectivity to google.com",
    "context": {}
  }'
```

## 🔄 Deployment Workflow

1. **Deploy Orchestrator API** (once)
   - Set up on `api.yourdomain.com`
   - Configure environment variables
   - Test endpoints

2. **Update Your Backend** (when integrating)
   - Add proxy endpoint
   - Set environment variables
   - Test integration

3. **Update Chatbot Frontend** (when integrating)
   - Add orchestrator routing logic
   - Update UI to show agent results
   - Test user flows

## 📝 Next Steps

1. ✅ Deploy orchestrator API following `DEPLOYMENT.md`
2. ✅ Add backend proxy endpoint to your existing backend
3. ✅ Update chatbot to detect when to use orchestrator
4. ✅ Test with sample queries
5. ✅ Monitor usage and adjust rate limits
6. ✅ Add more sophisticated intent detection (optional)

## 🆘 Troubleshooting

### Orchestrator not responding
- Check API is running: `curl https://api.yourdomain.com/api/v1/health`
- Verify API key in backend environment variables
- Check CORS settings

### Wrong agent being used
- Review intent detection logic
- Add more keywords to routing
- Consider using ML-based intent classification

### Timeout errors
- Increase timeout in backend proxy
- Check orchestrator response times
- Consider async processing for long-running tasks

