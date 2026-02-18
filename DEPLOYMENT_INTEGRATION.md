# Deployment Integration Guide

This guide shows how to integrate the AI Agent Orchestrator with your existing portfolio chatbot infrastructure.

## 🎯 Integration Overview

Your existing stack has:
- ✅ Chatbot Lambda (Node.js) - RAG-based Q&A
- ✅ Indexer Lambda - Document processing
- ✅ API Gateway - `/chat` endpoint
- ✅ DynamoDB - Vector storage
- ✅ S3 - Document storage
- ✅ Bedrock access - Claude 3 Haiku + Titan Embed

**Adding:**
- 🆕 Orchestrator Lambda (Python) - Specialized agent coordination
- 🆕 API Gateway - `/api/v1/*` endpoints
- 🆕 DynamoDB table - Orchestrator state (optional)
- 🆕 Secrets Manager - API key storage

## 📋 Prerequisites

1. **Existing Stack Deployed**
   ```bash
   # Verify your existing stack is running
   aws cloudformation describe-stacks --stack-name portfolio-chatbot-backend
   ```

2. **Python 3.11 Lambda Package**
   - Your orchestrator code packaged as ZIP
   - Dependencies included

3. **AWS CLI Configured**
   ```bash
   aws configure
   ```

## 🚀 Deployment Steps

### Step 1: Package Orchestrator Lambda

```bash
# Create deployment package
cd /path/to/ai-agent-orchestrator

# Install dependencies
pip install -r requirements.txt -t ./package

# Copy application code
cp -r app ./package/
cp app/main.py ./package/

# Create ZIP
cd package
zip -r ../orchestrator-lambda.zip .
cd ..
```

### Step 2: Upload to S3

```bash
# Create S3 bucket for Lambda code (if not exists)
aws s3 mb s3://your-lambda-code-bucket --region us-east-1

# Upload Lambda package
aws s3 cp orchestrator-lambda.zip s3://your-lambda-code-bucket/orchestrator-lambda.zip
```

### Step 3: Deploy Orchestrator Stack

```bash
# Deploy the orchestrator stack
aws cloudformation create-stack \
  --stack-name ai-agent-orchestrator \
  --template-body file://cloudformation/orchestrator-stack.yaml \
  --parameters \
    ParameterKey=CodeS3Bucket,ParameterValue=your-lambda-code-bucket \
    ParameterKey=CodeS3Key,ParameterValue=orchestrator-lambda.zip \
    ParameterKey=CORSOrigins,ParameterValue="https://yourdomain.com,https://www.yourdomain.com" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# Wait for stack creation
aws cloudformation wait stack-create-complete \
  --stack-name ai-agent-orchestrator \
  --region us-east-1
```

### Step 4: Get API Endpoint and Key

```bash
# Get API endpoint
aws cloudformation describe-stacks \
  --stack-name ai-agent-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`OrchestratorApiEndpoint`].OutputValue' \
  --output text

# Get API key ID
API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name ai-agent-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`OrchestratorApiKeyId`].OutputValue' \
  --output text)

# Get actual API key value
aws apigateway get-api-key \
  --api-key $API_KEY_ID \
  --include-value \
  --query 'value' \
  --output text
```

### Step 5: Update Chatbot Lambda (Optional Integration)

If you want the chatbot to call the orchestrator, update your chatbot Lambda:

```javascript
// Add to chatbot Lambda
const callOrchestrator = async (task, context) => {
  const orchestratorEndpoint = process.env.ORCHESTRATOR_ENDPOINT;
  const orchestratorApiKey = process.env.ORCHESTRATOR_API_KEY;
  
  if (!orchestratorEndpoint || !orchestratorApiKey) {
    return null;
  }
  
  try {
    const response = await fetch(`${orchestratorEndpoint}/api/v1/orchestrate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': orchestratorApiKey
      },
      body: JSON.stringify({
        task: task,
        context: context
      })
    });
    
    if (response.ok) {
      return await response.json();
    }
  } catch (error) {
    console.error('Orchestrator call failed:', error);
  }
  
  return null;
};

// In your handler, detect when to use orchestrator
const shouldUseOrchestrator = (question) => {
  const keywords = ['network', 'system', 'diagnose', 'troubleshoot', 'monitor'];
  return keywords.some(keyword => question.toLowerCase().includes(keyword));
};

// Update handler
exports.handler = async (event) => {
  const body = JSON.parse(event.body || '{}');
  const question = body.question;
  
  // Check if orchestrator should handle this
  if (shouldUseOrchestrator(question)) {
    const orchestratorResult = await callOrchestrator(question, {});
    if (orchestratorResult && orchestratorResult.useOrchestrator) {
      return {
        statusCode: 200,
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "https://yourdomain.com" },
        body: JSON.stringify({
          success: true,
          answer: orchestratorResult.result.message,
          source: 'orchestrator'
        })
      };
    }
  }
  
  // Continue with existing RAG logic...
};
```

### Step 6: Update Chatbot Stack (Add Environment Variables)

Update your existing CloudFormation stack to add orchestrator endpoint:

```yaml
# Add to PortfolioChatbotLambda Environment Variables
Environment:
  Variables:
    TABLE_NAME: !Ref PortfolioVectorDB
    ORCHESTRATOR_ENDPOINT: !ImportValue ai-agent-orchestrator-OrchestratorApiEndpoint
    ORCHESTRATOR_API_KEY: !Sub "{{resolve:secretsmanager:${OrchestratorApiKeySecret}:SecretString:api_key}}"
```

Or manually update via AWS Console:
1. Go to Lambda → Your Chatbot Function
2. Configuration → Environment variables
3. Add:
   - `ORCHESTRATOR_ENDPOINT`: Your orchestrator API endpoint
   - `ORCHESTRATOR_API_KEY`: Your API key

## 🔗 CloudFront Integration

### Option 1: Add API Origin to Existing CloudFront

Update your CloudFront distribution to route `/api/*` to the orchestrator API:

```bash
# Get your CloudFront distribution ID
CLOUDFRONT_ID="YOUR_CLOUDFRONT_DISTRIBUTION_ID"  # Replace with your actual CloudFront distribution ID

# Get orchestrator API endpoint
ORCHESTRATOR_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name ai-agent-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`OrchestratorApiEndpoint`].OutputValue' \
  --output text)

# Update CloudFront distribution (requires getting current config first)
# This is complex - use AWS Console or CloudFormation
```

### Option 2: Use API Gateway Custom Domain

```bash
# Request ACM certificate for api.yourdomain.com
aws acm request-certificate \
  --domain-name api.yourdomain.com \
  --validation-method DNS \
  --region us-east-1

# Create custom domain in API Gateway
aws apigateway create-domain-name \
  --domain-name api.yourdomain.com \
  --certificate-arn <certificate-arn> \
  --endpoint-configuration types=REGIONAL
```

## 🧪 Testing

### Test Orchestrator API Directly

```bash
# Get API endpoint and key
ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name ai-agent-orchestrator \
  --query 'Stacks[0].Outputs[?OutputKey==`OrchestratorApiEndpoint`].OutputValue' \
  --output text)

API_KEY=$(aws apigateway get-api-key \
  --api-key $(aws cloudformation describe-stacks \
    --stack-name ai-agent-orchestrator \
    --query 'Stacks[0].Outputs[?OutputKey==`OrchestratorApiKeyId`].OutputValue' \
    --output text) \
  --include-value \
  --query 'value' \
  --output text)

# Test health endpoint
curl -H "x-api-key: $API_KEY" \
  "${ENDPOINT}/api/v1/health"

# Test orchestrate endpoint
curl -X POST \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task": "Check network connectivity to google.com", "context": {}}' \
  "${ENDPOINT}/api/v1/orchestrate"
```

### Test from Chatbot

Update your frontend to call the orchestrator when needed, or test via the chatbot Lambda.

## 📊 Cost Estimation

### Additional Costs (Orchestrator)

```
Lambda (1M requests):     ~$0.20/month
API Gateway:              ~$3.50/month
DynamoDB (state):         ~$0.25/month (minimal)
Secrets Manager:          ~$0.40/month
CloudWatch Logs:          ~$0.50/month
─────────────────────────────────
Total Additional:         ~$4.85/month
```

### Combined Infrastructure

```
Existing Chatbot:         ~$5-15/month
Orchestrator:             ~$5/month
Bedrock Usage:            ~$10-50/month (variable)
─────────────────────────────────
Total:                    ~$20-70/month
```

## 🔐 Security Recommendations

### 1. **Update CORS in Chatbot Lambda**

Change from `"*"` to specific origin:

```javascript
headers: {
  "Access-Control-Allow-Origin": "https://yourdomain.com",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-API-Key"
}
```

### 2. **Add API Key to Chatbot API Gateway**

Update your existing API Gateway to require API keys:

```yaml
# Add to your existing stack
PortfolioChatbotApiKey:
  Type: AWS::ApiGateway::ApiKey
  Properties:
    Name: !Sub "${AWS::StackName}-ChatbotApiKey"
    Enabled: true

PortfolioChatbotUsagePlan:
  Type: AWS::ApiGateway::UsagePlan
  Properties:
    ApiStages:
      - ApiId: !Ref PortfolioChatbotApi
        Stage: production
    Throttle:
      RateLimit: 100
      BurstLimit: 200
```

### 3. **Use Secrets Manager for All Keys**

Store all API keys in Secrets Manager, not environment variables.

## 🐛 Troubleshooting

### Lambda Not Invoking

```bash
# Check Lambda logs
aws logs tail /aws/lambda/ai-agent-orchestrator-OrchestratorHandler --follow

# Check API Gateway logs
aws apigateway get-gateway-responses --rest-api-id <api-id>
```

### API Key Not Working

```bash
# Verify API key is linked to usage plan
aws apigateway get-usage-plan-keys \
  --usage-plan-id <usage-plan-id>

# Test API key
curl -H "x-api-key: YOUR_KEY" \
  "https://YOUR_API.execute-api.us-east-1.amazonaws.com/production/api/v1/health"
```

### CORS Issues

- Verify CORS origins match your domain exactly
- Check OPTIONS method is configured
- Verify headers in Lambda response

## 📝 Next Steps

1. ✅ Deploy orchestrator stack
2. ✅ Test API endpoints
3. ✅ Integrate with chatbot (optional)
4. ✅ Update CloudFront (optional)
5. ✅ Add monitoring/alarms
6. ✅ Update deployment scripts

## 🔄 Updating the Stack

```bash
# Update Lambda code
aws s3 cp orchestrator-lambda-v2.zip s3://your-lambda-code-bucket/orchestrator-lambda.zip

# Update stack
aws cloudformation update-stack \
  --stack-name ai-agent-orchestrator \
  --template-body file://cloudformation/orchestrator-stack.yaml \
  --parameters \
    ParameterKey=CodeS3Bucket,ParameterValue=your-lambda-code-bucket \
    ParameterKey=CodeS3Key,ParameterValue=orchestrator-lambda.zip \
  --capabilities CAPABILITY_NAMED_IAM
```

## 📚 Related Documentation

- `EXISTING_INFRASTRUCTURE_ANALYSIS.md` - Analysis of your current stack
- `cloudformation/orchestrator-stack.yaml` - Orchestrator CloudFormation template
- `DEPLOYMENT.md` - General deployment guide
- `INTEGRATION_GUIDE.md` - Chatbot integration guide

