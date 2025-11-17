# AWS Infrastructure Review & Recommendations

This document reviews AWS infrastructure requirements for the AI Agent Orchestrator and provides recommendations.

## 🔍 Current AWS Usage (From Codebase)

Based on the codebase analysis, you're currently using:

### ✅ Configured
- **AWS Bedrock** - For LLM services (Claude 3 Haiku)
  - Region: `us-east-1` (default)
  - Service: `bedrock-runtime`
  - Authentication: Access Key ID + Secret Access Key

### ❌ Not Found in Repository
- No Terraform files
- No CloudFormation templates
- No AWS CDK code
- No infrastructure-as-code definitions
- No AWS deployment configurations

## 📋 Required AWS Infrastructure

### 1. **AWS Bedrock Access** (Currently Used)

**Current Setup:**
- Using IAM user credentials (Access Key ID + Secret)
- Region: `us-east-1`

**Recommendations:**

#### Option A: IAM User (Current - Simple)
```yaml
IAM User:
  Name: bedrock-orchestrator-user
  Permissions:
    - bedrock:InvokeModel
    - bedrock:InvokeModelWithResponseStream
  Access Type: Programmatic access
  Security: 
    - MFA enabled (recommended)
    - Access key rotation policy
```

#### Option B: IAM Role (Recommended for EC2/ECS)
```yaml
IAM Role:
  Name: bedrock-orchestrator-role
  Trust Policy: EC2 or ECS service
  Permissions:
    - bedrock:InvokeModel
    - bedrock:InvokeModelWithResponseStream
  Benefits:
    - No credentials to manage
    - Automatic rotation
    - More secure
```

**Required IAM Policy:**
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
    }
  ]
}
```

### 2. **Compute Infrastructure** (For API Deployment)

**Options:**

#### Option A: EC2 Instance (Current Deployment Model)
```yaml
EC2 Instance:
  Type: t3.medium or t3.large
  OS: Ubuntu 22.04 LTS
  Storage: 20GB EBS
  Security Group:
    - Port 80 (HTTP)
    - Port 443 (HTTPS)
    - Port 22 (SSH) - restricted to your IP
  IAM Role: bedrock-orchestrator-role (if using roles)
  Cost: ~$30-60/month
```

#### Option B: ECS Fargate (Recommended for Production)
```yaml
ECS Cluster:
  Launch Type: Fargate
  Task Definition:
    CPU: 0.5 vCPU
    Memory: 1 GB
    Container: ai-agent-orchestrator
  Service:
    Desired Count: 2 (for high availability)
    Load Balancer: Application Load Balancer
  IAM Role: Task execution role + Bedrock access
  Cost: ~$40-80/month
```

#### Option C: Lambda + API Gateway (Serverless)
```yaml
Lambda Function:
  Runtime: Python 3.11
  Memory: 512 MB - 1 GB
  Timeout: 30 seconds
  IAM Role: Bedrock access
API Gateway:
  Type: REST API or HTTP API
  Authentication: API Key
  Rate Limiting: Built-in
  Cost: Pay per request (~$5-20/month for low traffic)
```

#### Option D: Elastic Beanstalk (Easiest)
```yaml
Elastic Beanstalk:
  Platform: Python 3.11
  Environment: Single instance or load balanced
  IAM Role: Bedrock access
  Cost: ~$30-60/month (EC2 costs)
```

### 3. **Networking** (If Using AWS)

#### VPC Configuration
```yaml
VPC:
  CIDR: 10.0.0.0/16
  Subnets:
    - Public: 10.0.1.0/24 (for load balancer)
    - Private: 10.0.2.0/24 (for compute)
  Internet Gateway: Required for public access
  NAT Gateway: Required if using private subnets
  Security Groups:
    - API Security Group:
        - Inbound: 80, 443 from 0.0.0.0/0
        - Outbound: All traffic
```

### 4. **Load Balancer** (For High Availability)

```yaml
Application Load Balancer:
  Type: Internet-facing
  Listeners:
    - HTTP (80) -> Redirect to HTTPS
    - HTTPS (443) -> Target group
  SSL Certificate: ACM certificate for api.donsylvester.dev
  Health Check: /api/v1/health
  Target Group:
    - Protocol: HTTP
    - Port: 8000
    - Health Check Path: /api/v1/health
```

### 5. **SSL/TLS Certificate**

```yaml
ACM Certificate:
  Domain: api.donsylvester.dev
  Validation: DNS or Email
  Region: us-east-1 (for ALB)
  Auto-renewal: Enabled
```

### 6. **Secrets Management** (Recommended)

```yaml
AWS Secrets Manager:
  Secrets:
    - orchestrator-api-key
    - aws-bedrock-credentials (if not using IAM roles)
  Rotation: Enabled
  Access: Via IAM policy
  Cost: ~$0.40/month per secret
```

**Alternative: Systems Manager Parameter Store**
```yaml
Parameter Store:
  Type: SecureString (encrypted)
  Parameters:
    - /orchestrator/api-key
    - /orchestrator/aws-credentials
  Cost: Free (standard parameters)
```

### 7. **Monitoring & Logging**

```yaml
CloudWatch:
  Log Groups:
    - /aws/ecs/orchestrator (if using ECS)
    - /aws/ec2/orchestrator (if using EC2)
  Metrics:
    - API request count
    - Response time
    - Error rate
    - Bedrock invocation metrics
  Alarms:
    - High error rate
    - High latency
    - Service down
  Cost: ~$5-10/month
```

### 8. **Database** (If Adding Persistence)

```yaml
RDS PostgreSQL:
  Instance: db.t3.micro (free tier eligible)
  Storage: 20GB
  Multi-AZ: No (for cost savings)
  Backup: 7 days retention
  Cost: ~$15/month (or free tier)
  
Alternative: DynamoDB:
  Table: orchestrator-state
  Billing: On-demand
  Cost: ~$5-15/month (low traffic)
```

### 9. **Caching** (Optional but Recommended)

```yaml
ElastiCache Redis:
  Node Type: cache.t3.micro
  Engine: Redis 7.x
  Use Cases:
    - Rate limiting
    - Session storage
    - Response caching
  Cost: ~$15/month
```

## 🏗️ Recommended Infrastructure Architecture

### Architecture Option 1: Simple EC2 (Current)
```
Internet
   ↓
Route 53 (DNS)
   ↓
EC2 Instance (Ubuntu)
   ├── Docker + Orchestrator API
   ├── Nginx (Reverse Proxy)
   └── Let's Encrypt SSL
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
- Manual updates

### Architecture Option 2: ECS Fargate (Recommended)
```
Internet
   ↓
Route 53 (DNS)
   ↓
Application Load Balancer
   ├── ACM SSL Certificate
   └── Health Checks
   ↓
ECS Fargate Service
   ├── Task 1 (Orchestrator)
   └── Task 2 (Orchestrator)
   ↓
AWS Bedrock
   ↓
CloudWatch (Logs & Metrics)
```

**Pros:**
- High availability
- Auto-scaling
- Managed service
- Easy updates

**Cons:**
- Higher cost (~$60-100/month)
- More complex setup

### Architecture Option 3: Serverless (Cost-Effective)
```
Internet
   ↓
Route 53 (DNS)
   ↓
API Gateway
   ├── API Key Authentication
   └── Rate Limiting
   ↓
Lambda Function
   ├── Orchestrator Logic
   └── IAM Role (Bedrock Access)
   ↓
AWS Bedrock
   ↓
CloudWatch (Logs & Metrics)
```

**Pros:**
- Very low cost (~$5-20/month)
- Auto-scaling
- Pay per request
- No server management

**Cons:**
- Cold starts
- 15-minute timeout limit
- May need refactoring

## 📊 Cost Estimation

### Option 1: EC2 (Simple)
```
EC2 t3.medium:        $30/month
EBS 20GB:             $2/month
Data Transfer:        $5/month
Bedrock Usage:        Variable (~$10-50/month)
─────────────────────────────────
Total:                ~$47-87/month
```

### Option 2: ECS Fargate
```
ECS Fargate (2 tasks): $60/month
ALB:                   $20/month
Data Transfer:         $5/month
Bedrock Usage:         Variable (~$10-50/month)
─────────────────────────────────
Total:                 ~$95-135/month
```

### Option 3: Serverless
```
Lambda (1M requests):  $0.20/month
API Gateway:           $3.50/month
Data Transfer:         $5/month
Bedrock Usage:          Variable (~$10-50/month)
─────────────────────────────────
Total:                 ~$18.70-58.70/month
```

## 🔐 Security Recommendations

### 1. **IAM Best Practices**
- [ ] Use IAM roles instead of access keys when possible
- [ ] Enable MFA for IAM users
- [ ] Rotate access keys regularly (90 days)
- [ ] Use least privilege principle
- [ ] Enable CloudTrail for audit logging

### 2. **Network Security**
- [ ] Use security groups (firewall rules)
- [ ] Restrict SSH access to your IP only
- [ ] Use private subnets for compute (if using VPC)
- [ ] Enable VPC Flow Logs

### 3. **Secrets Management**
- [ ] Store API keys in Secrets Manager or Parameter Store
- [ ] Encrypt secrets at rest
- [ ] Rotate secrets regularly
- [ ] Use IAM policies to restrict access

### 4. **Monitoring & Alerting**
- [ ] Enable CloudWatch alarms
- [ ] Set up SNS notifications for critical alerts
- [ ] Monitor Bedrock usage and costs
- [ ] Track API errors and latency

## 📝 Infrastructure Checklist

### Current Setup Review
- [ ] AWS Account configured
- [ ] AWS Bedrock access enabled
- [ ] IAM user/role with Bedrock permissions
- [ ] Region selected (us-east-1)
- [ ] Billing alerts configured

### For EC2 Deployment
- [ ] EC2 instance created
- [ ] Security groups configured
- [ ] Elastic IP assigned (optional)
- [ ] IAM role attached (if using roles)
- [ ] CloudWatch agent installed

### For ECS Deployment
- [ ] ECS cluster created
- [ ] Task definition created
- [ ] Service created
- [ ] Load balancer configured
- [ ] Target group configured
- [ ] IAM roles for tasks

### For Serverless
- [ ] Lambda function created
- [ ] API Gateway configured
- [ ] IAM role for Lambda
- [ ] Environment variables set
- [ ] API key configured

### Common Requirements
- [ ] Route 53 DNS configured
- [ ] ACM certificate issued
- [ ] CloudWatch log groups created
- [ ] Alarms configured
- [ ] Secrets stored securely

## 🛠️ Infrastructure as Code Recommendations

### Option 1: Terraform
```hcl
# terraform/main.tf
provider "aws" {
  region = "us-east-1"
}

module "orchestrator" {
  source = "./modules/orchestrator"
  # ... configuration
}
```

### Option 2: AWS CDK
```python
# infrastructure/app.py
from aws_cdk import App
from orchestrator_stack import OrchestratorStack

app = App()
OrchestratorStack(app, "ai-agent-orchestrator")
app.synth()
```

### Option 3: CloudFormation
```yaml
# cloudformation/orchestrator.yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  OrchestratorService:
    Type: AWS::ECS::Service
    # ... configuration
```

## 🔍 Review Questions

To properly review your AWS infrastructure, please provide:

1. **Current Deployment:**
   - Are you using EC2, ECS, Lambda, or other?
   - Which region?
   - What instance/service types?

2. **Networking:**
   - Do you have a VPC set up?
   - Are you using public or private subnets?
   - Do you have a load balancer?

3. **Security:**
   - How are you managing AWS credentials?
   - Are you using IAM roles or access keys?
   - Where are API keys stored?

4. **Monitoring:**
   - Do you have CloudWatch set up?
   - Are there any alarms configured?
   - How are you tracking costs?

5. **DNS & SSL:**
   - Is Route 53 configured?
   - Do you have an ACM certificate?
   - How is DNS managed?

## 📚 Next Steps

1. **Review Current Setup**: Use AWS Console to audit current resources
2. **Choose Architecture**: Select EC2, ECS, or Serverless based on needs
3. **Create Infrastructure as Code**: Use Terraform, CDK, or CloudFormation
4. **Set Up Monitoring**: Configure CloudWatch and alarms
5. **Implement Security**: Follow IAM and security best practices
6. **Cost Optimization**: Set up billing alerts and review costs

## 🆘 Need Help?

If you can share:
- Screenshots of your AWS Console
- Infrastructure-as-code files
- Current service configurations
- Cost breakdown

I can provide a more specific review and recommendations.

