/**
 * Example Frontend Chatbot Integration
 * 
 * This shows how to integrate orchestrator into your chatbot frontend.
 * Replace your existing message handling with this enhanced version.
 */

class EnhancedChatbot {
  constructor() {
    this.orchestratorEnabled = true;
    this.backendUrl = '/api'; // Your backend API URL
  }

  /**
   * Main method to process user messages
   */
  async processMessage(userMessage, conversationHistory = []) {
    try {
      // First, try to use orchestrator if applicable
      if (this.orchestratorEnabled) {
        const orchestratorResult = await this.tryOrchestrator(userMessage);
        
        if (orchestratorResult.useOrchestrator) {
          return this.formatOrchestratorResponse(orchestratorResult.result);
        }
      }
      
      // Fallback to regular chatbot
      return await this.useRegularChatbot(userMessage, conversationHistory);
      
    } catch (error) {
      console.error('Chatbot error:', error);
      return {
        message: "I'm having trouble processing that. Let me try a general response...",
        error: true,
        fallback: true
      };
    }
  }

  /**
   * Try to use orchestrator for specialized tasks
   */
  async tryOrchestrator(message) {
    try {
      const response = await fetch(`${this.backendUrl}/chatbot/orchestrate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: message,
          context: {
            user_id: this.getCurrentUserId(),
            session_id: this.getSessionId(),
            timestamp: new Date().toISOString()
          }
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
      
    } catch (error) {
      console.error('Orchestrator call failed:', error);
      return { useOrchestrator: false };
    }
  }

  /**
   * Format orchestrator response for chatbot display
   */
  formatOrchestratorResponse(result) {
    if (!result || !result.results || result.results.length === 0) {
      return {
        message: result.message || 'Analysis complete.',
        type: 'orchestrator',
        raw: result
      };
    }

    // Format agent results for display
    const agentResults = result.results.map(agentResult => {
      return {
        agent: agentResult.agent_id || 'Unknown Agent',
        summary: agentResult.summary || 'No summary available',
        details: agentResult.details || {},
        status: agentResult.status || 'completed'
      };
    });

    // Create user-friendly message
    const message = this.createUserFriendlyMessage(agentResults, result);

    return {
      message: message,
      agents: agentResults,
      type: 'agent_response',
      raw: result,
      success: result.success !== false
    };
  }

  /**
   * Create user-friendly message from agent results
   */
  createUserFriendlyMessage(agentResults, fullResult) {
    if (agentResults.length === 0) {
      return fullResult.message || 'Analysis complete.';
    }

    if (agentResults.length === 1) {
      const agent = agentResults[0];
      return `I've analyzed your request using the ${agent.agent} agent:\n\n${agent.summary}`;
    }

    // Multiple agents
    const summaries = agentResults
      .map(a => `**${a.agent}**: ${a.summary}`)
      .join('\n\n');

    return `I've analyzed your request using ${agentResults.length} specialized agents:\n\n${summaries}`;
  }

  /**
   * Regular chatbot handler (your existing implementation)
   */
  async useRegularChatbot(message, history) {
    // Replace this with your existing chatbot API call
    try {
      const response = await fetch(`${this.backendUrl}/chatbot/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: message,
          history: history
        })
      });

      const data = await response.json();
      return {
        message: data.message || data.response || 'I received your message.',
        type: 'regular',
        raw: data
      };
    } catch (error) {
      return {
        message: "I'm sorry, I'm having trouble right now. Please try again.",
        error: true
      };
    }
  }

  /**
   * Helper methods (implement based on your app)
   */
  getCurrentUserId() {
    // Return current user ID from your auth system
    return localStorage.getItem('userId') || 'anonymous';
  }

  getSessionId() {
    // Return or generate session ID
    let sessionId = sessionStorage.getItem('chatbotSessionId');
    if (!sessionId) {
      sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      sessionStorage.setItem('chatbotSessionId', sessionId);
    }
    return sessionId;
  }
}

// Example usage in React/Vue/etc:
/*
const chatbot = new EnhancedChatbot();

async function handleUserMessage(userMessage) {
  const response = await chatbot.processMessage(userMessage);
  
  // Display in your UI
  displayMessage(response.message, response.type);
  
  // If it's an agent response, you might want to show additional details
  if (response.agents) {
    showAgentDetails(response.agents);
  }
}
*/

// Example usage in vanilla JavaScript:
/*
const chatbot = new EnhancedChatbot();

document.getElementById('send-button').addEventListener('click', async () => {
  const input = document.getElementById('message-input');
  const message = input.value;
  
  if (!message.trim()) return;
  
  // Show loading state
  showLoading();
  
  try {
    const response = await chatbot.processMessage(message);
    
    // Add to chat UI
    addMessageToChat('user', message);
    addMessageToChat('bot', response.message);
    
    // Clear input
    input.value = '';
  } catch (error) {
    addMessageToChat('bot', 'Sorry, something went wrong. Please try again.');
  } finally {
    hideLoading();
  }
});
*/

export default EnhancedChatbot;

