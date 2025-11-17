/**
 * Example Backend Proxy for Node.js/Express
 * 
 * This file shows how to integrate the orchestrator API into your existing backend.
 * Add this route to your Express application.
 */

const express = require('express');
const router = express.Router();
const axios = require('axios');

// Load from environment variables
const ORCHESTRATOR_API_URL = process.env.ORCHESTRATOR_API_URL || 'https://api.donsylvester.dev';
const ORCHESTRATOR_API_KEY = process.env.ORCHESTRATOR_API_KEY;

if (!ORCHESTRATOR_API_KEY) {
  console.warn('Warning: ORCHESTRATOR_API_KEY not set. Orchestrator integration will not work.');
}

/**
 * Proxy endpoint for chatbot to use orchestrator
 * POST /api/chatbot/orchestrate
 */
router.post('/chatbot/orchestrate', async (req, res) => {
  try {
    const { message, context } = req.body;
    
    if (!message) {
      return res.status(400).json({
        error: 'Message is required'
      });
    }
    
    // Determine if message needs orchestrator
    const needsOrchestrator = shouldUseOrchestrator(message);
    
    if (!needsOrchestrator) {
      return res.json({ 
        useOrchestrator: false,
        message: 'Handled by regular chatbot',
        suggestion: 'This query can be handled by your regular chatbot'
      });
    }
    
    // Call orchestrator API
    const response = await axios.post(
      `${ORCHESTRATOR_API_URL}/api/v1/orchestrate`,
      {
        task: message,
        context: {
          ...context,
          source: 'chatbot',
          timestamp: new Date().toISOString()
        }
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
    
    // Handle different error types
    if (error.response) {
      // API returned error
      return res.status(error.response.status).json({
        error: 'Orchestrator API error',
        message: error.response.data?.detail || error.message,
        useOrchestrator: false
      });
    } else if (error.request) {
      // Request made but no response
      return res.status(503).json({
        error: 'Orchestrator API unavailable',
        message: 'The orchestrator service is not responding',
        useOrchestrator: false
      });
    } else {
      // Error setting up request
      return res.status(500).json({
        error: 'Internal error',
        message: error.message,
        useOrchestrator: false
      });
    }
  }
});

/**
 * Helper function to detect if orchestrator should be used
 * You can enhance this with ML-based intent classification
 */
function shouldUseOrchestrator(message) {
  const lowerMessage = message.toLowerCase();
  
  // Keywords that indicate specialized agent needs
  const orchestratorKeywords = [
    // Network-related
    'network', 'connectivity', 'ping', 'dns', 'latency', 'connection',
    'reachable', 'timeout', 'packet', 'route', 'traceroute',
    
    // System-related
    'system', 'monitor', 'cpu', 'memory', 'disk', 'performance',
    'load', 'usage', 'process', 'thread', 'resource',
    
    // Log-related
    'log', 'error', 'exception', 'debug', 'trace', 'troubleshoot',
    'diagnose', 'analyze logs', 'error log',
    
    // Infrastructure-related
    'infrastructure', 'deploy', 'server', 'configure', 'setup',
    'provision', 'infrastructure', 'environment',
    
    // General diagnostics
    'diagnose', 'troubleshoot', 'check', 'verify', 'test connection'
  ];
  
  return orchestratorKeywords.some(keyword => 
    lowerMessage.includes(keyword)
  );
}

/**
 * Optional: Get available agents
 * GET /api/chatbot/agents
 */
router.get('/chatbot/agents', async (req, res) => {
  try {
    const response = await axios.get(
      `${ORCHESTRATOR_API_URL}/api/v1/agents`,
      {
        headers: {
          'X-API-Key': ORCHESTRATOR_API_KEY
        }
      }
    );
    
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching agents:', error.message);
    res.status(500).json({
      error: 'Failed to fetch agents',
      message: error.message
    });
  }
});

module.exports = router;

