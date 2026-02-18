# AWS Infrastructure Analysis - yourdomain.com

Based on your deployment script, here's an analysis of your current AWS infrastructure and recommendations for integrating the AI Agent Orchestrator.

## 🔍 Current Infrastructure (From Deployment Script)

### Existing Services

1. **S3 Bucket**: `yourdomain.com`
   - Static website hosting
   - Used for frontend deployment
   - Region: `us-east-1`

2. **CloudFront Distribution**: `YOUR_CLOUDFRONT_DISTRIBUTION_ID`
   - CDN for static content
   - CloudFront URL: `YOUR_CLOUDFRONT_URL.cloudfront.net` (or your custom domain)
   - Custom domain: `yourdomain.com`

3. **AWS Account**: Active (verified via `aws sts get-caller-identity`)

### Current Architecture

```
User Request
   ↓
CloudFront (YOUR_CLOUDFRONT_DISTRIBUTION_ID)
   ↓
S3 Bucket (yourdomain.com)
   ↓
Static Website (HTML/CSS/JS)
```

## 📊 Infrastructure Assessment

### ✅ What's Working Well

1. **Static Site Deployment**
   - ✅ Automated deployment script
   - ✅ Proper cache control headers
   - ✅ CloudFront CDN for performance
   - ✅ Cache invalidation on deploy

2. **Security**
   - ✅ AWS credentials check
   - ✅ Deployment confirmation prompt
   - ✅ Proper file exclusions

3. **Best Practices**
   - ✅ Different cache policies for different file types
   - ✅ Content-Type headers set correctly
   - ✅ Cleanup of dev files before deploy

### ⚠️ Areas for Improvement

1. **No API Backend Infrastructure**
   - Current setup is static-only
   - No compute resources for API
   - Need to add API infrastructure

2. **No Secrets Management**
   - API keys not stored in AWS
   - No Secrets Manager or Parameter Store usage

3. **No Monitoring**
   - No CloudWatch alarms
   - No error tracking
   - No performance monitoring

4. **No SSL Certificate Management**
   - CloudFront handles SSL, but no ACM certificate visible in script

## 🏗️ Recommended Infrastructure for Orchestrator API

### Option 1: Add API to Existing Setup (Recommended)

```
User Request (yourdomain.com)
   ↓
CloudFront Distribution
   ├── /api/* → API Gateway → Lambda
   └── /* → S3 (static site)
   ↓
API Gateway
   ↓
Lambda Function (Orchestrator API)
   ↓
AWS Bedrock
```

**Pros:**
- Serverless (low cost)
- Scales automatically
- No server management
- Integrates with existing CloudFront

**Cons:**
- Lambda cold starts
- 15-minute timeout limit
- May need refactoring

### Option 2: Separate API Subdomain

```
User Request (yourdomain.com)
   ↓
CloudFront → S3 (static site)

User Request (api.yourdomain.com)
   ↓
Application Load Balancer
   ↓
ECS Fargate (Orchestrator API)
   ↓
AWS Bedrock
```

**Pros:**
- Separation of concerns
- Better for long-running tasks
- More control
- Can use existing VPC (if any)

**Cons:**
- Higher cost (~$60-100/month)
- More complex setup
- Need separate DNS/SSL

### Option 3: EC2 Instance (Simple)

```
User Request (yourdomain.com)
   ↓
CloudFront → S3 (static site)

User Request (api.yourdomain.com)
   ↓
EC2 Instance (Orchestrator API)
   ↓
AWS Bedrock
```

**Pros:**
- Simple setup
- Low cost (~$30/month)
- Full control

**Cons:**
- Single point of failure
- Manual scaling
- Server management

## 🔧 Integration Recommendations

### 1. **Update Deployment Script**

Add API deployment section to your existing script:

```bash
# Add to deploy.sh

# API Configuration
API_STACK_NAME="orchestrator-api"
API_REGION="us-east-1"

# Deploy API (if using Lambda)
if [ "$DEPLOY_API" = "true" ]; then
    echo -e "${YELLOW}🚀 Deploying API...${NC}"
    cd api
    sam build
    sam deploy --stack-name "${API_STACK_NAME}" --region "${API_REGION}"
    cd ..
    echo -e "${GREEN}✓ API deployment complete${NC}"
fi
```

### 2. **CloudFront Configuration**

Add API origin to CloudFront:

```json
{
  "Origins": {
    "Items": [
      {
        "Id": "S3-yourdomain.com",
        "DomainName": "yourdomain.com.s3.amazonaws.com",
        "S3OriginConfig": {
          "OriginAccessIdentity": ""
        }
      },
      {
        "Id": "API-Orchestrator",
        "DomainName": "api.yourdomain.com",
        "CustomOriginConfig": {
          "HTTPPort": 443,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "https-only"
        }
      }
    ]
  },
  "CacheBehaviors": {
    "Items": [
      {
        "PathPattern": "/api/*",
        "TargetOriginId": "API-Orchestrator",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
        "CachedMethods": ["GET", "HEAD"],
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" // CachingDisabled
      }
    ]
  }
}
```

### 3. **DNS Configuration**

Add API subdomain:

```bash
# Route 53 or DNS provider
api.yourdomain.com → ALB or API Gateway endpoint
```

### 4. **SSL Certificate**

Request ACM certificate for `api.yourdomain.com`:

```bash
aws acm request-certificate \
  --domain-name api.yourdomain.com \
  --validation-method DNS \
  --region us-east-1
```

## 🔐 Security Enhancements

### 1. **Secrets Management**

Store API keys in AWS Secrets Manager:

```bash
# Store orchestrator API key
aws secretsmanager create-secret \
  --name orchestrator/api-key \
  --secret-string "your-api-key-here" \
  --region us-east-1

# Store AWS credentials (if not using IAM roles)
aws secretsmanager create-secret \
  --name orchestrator/aws-credentials \
  --secret-string '{"access_key_id":"...","secret_access_key":"..."}' \
  --region us-east-1
```

### 2. **IAM Roles**

Create IAM role for API service:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:orchestrator/*"
      ]
    }
  ]
}
```

### 3. **WAF Rules** (Optional but Recommended)

Add Web Application Firewall to CloudFront:

```bash
aws wafv2 create-web-acl \
  --scope CLOUDFRONT \
  --default-action Allow={} \
  --rules file://waf-rules.json \
  --name orchestrator-waf
```

## 📊 Cost Estimation

### Current Costs (Static Site)
```
S3 Storage:          ~$0.10/month (minimal)
CloudFront:          ~$1-5/month (depending on traffic)
Data Transfer:       ~$1-10/month
─────────────────────────────────
Total:               ~$2-15/month
```

### With Orchestrator API

#### Option 1: Lambda (Serverless)
```
Lambda:              ~$0.20/month (1M requests)
API Gateway:         ~$3.50/month
Bedrock Usage:       ~$10-50/month (variable)
─────────────────────────────────
Additional:          ~$13.70-53.70/month
Total:               ~$15-70/month
```

#### Option 2: ECS Fargate
```
ECS Fargate:         ~$60/month (2 tasks)
ALB:                 ~$20/month
Bedrock Usage:       ~$10-50/month
─────────────────────────────────
Additional:          ~$90-130/month
Total:               ~$105-145/month
```

#### Option 3: EC2
```
EC2 t3.medium:       ~$30/month
EBS:                 ~$2/month
Bedrock Usage:       ~$10-50/month
─────────────────────────────────
Additional:          ~$42-82/month
Total:               ~$57-97/month
```

## 🛠️ Implementation Steps

### Step 1: Choose API Deployment Method
- [ ] Lambda (serverless, recommended for start)
- [ ] ECS Fargate (production, high availability)
- [ ] EC2 (simple, cost-effective)

### Step 2: Set Up API Infrastructure
- [ ] Create API subdomain (api.yourdomain.com)
- [ ] Request SSL certificate (ACM)
- [ ] Deploy API service
- [ ] Configure IAM roles/permissions

### Step 3: Update CloudFront
- [ ] Add API origin
- [ ] Configure cache behaviors
- [ ] Set up path patterns (/api/*)

### Step 4: Configure Secrets
- [ ] Store API keys in Secrets Manager
- [ ] Update application to use secrets
- [ ] Test secret retrieval

### Step 5: Set Up Monitoring
- [ ] CloudWatch log groups
- [ ] CloudWatch alarms
- [ ] Cost alerts

### Step 6: Update Deployment Script
- [ ] Add API deployment section
- [ ] Add secrets management
- [ ] Add health checks

## 📝 Updated Deployment Script Template

Here's how to enhance your existing script:

```bash
#!/bin/bash

# ... existing code ...

# API Deployment Section
DEPLOY_API=${DEPLOY_API:-false}

if [ "$DEPLOY_API" = "true" ]; then
    echo ""
    echo -e "${YELLOW}🚀 Deploying Orchestrator API...${NC}"
    
    # Deploy Lambda function
    cd api
    sam build
    sam deploy \
        --stack-name orchestrator-api \
        --region "${AWS_REGION}" \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides \
            BedrockRegion="${AWS_REGION}" \
            ApiKeySecretName="orchestrator/api-key"
    
    # Get API endpoint
    API_ENDPOINT=$(aws cloudformation describe-stacks \
        --stack-name orchestrator-api \
        --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
        --output text)
    
    echo -e "${GREEN}✓ API deployed: ${API_ENDPOINT}${NC}"
    cd ..
fi

# Update CloudFront with API origin (if needed)
# ... CloudFront update commands ...
```

## 🔍 Security Review of Current Script

### ✅ Good Practices
- ✅ AWS credentials check
- ✅ Deployment confirmation
- ✅ Proper file exclusions
- ✅ Cache control headers

### ⚠️ Recommendations
1. **Add Error Handling**
   ```bash
   # Add more error checks
   if ! aws s3 ls "s3://${S3_BUCKET}" &> /dev/null; then
       echo -e "${RED}❌ S3 bucket not accessible${NC}"
       exit 1
   fi
   ```

2. **Add Rollback Capability**
   ```bash
   # Save previous version before deploy
   aws s3 sync "s3://${S3_BUCKET}" "s3://${S3_BUCKET}-backup/$(date +%Y%m%d-%H%M%S)/"
   ```

3. **Add Logging**
   ```bash
   # Log deployment
   LOG_FILE="deploy-$(date +%Y%m%d-%H%M%S).log"
   exec > >(tee -a "$LOG_FILE") 2>&1
   ```

4. **Validate CloudFront ID**
   ```bash
   if ! aws cloudfront get-distribution --id "${CLOUDFRONT_ID}" &> /dev/null; then
       echo -e "${RED}❌ CloudFront distribution not found${NC}"
       exit 1
   fi
   ```

## 🎯 Next Steps

1. **Run Infrastructure Assessment**
   ```bash
   python scripts/aws_infrastructure_check.py
   ```

2. **Review Current Resources**
   - Check S3 bucket configuration
   - Review CloudFront settings
   - Verify IAM permissions

3. **Plan API Integration**
   - Choose deployment method (Lambda recommended)
   - Design API architecture
   - Plan DNS/SSL setup

4. **Implement Gradually**
   - Start with Lambda deployment
   - Test API endpoints
   - Integrate with CloudFront
   - Add monitoring

## 📚 Additional Resources

- See `AWS_INFRASTRUCTURE_REVIEW.md` for detailed infrastructure options
- See `DEPLOYMENT.md` for orchestrator deployment guide
- See `INTEGRATION_GUIDE.md` for chatbot integration

