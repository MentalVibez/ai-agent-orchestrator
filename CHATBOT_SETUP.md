# Quick Setup Checklist for donsylvester.dev Chatbot

## 🎯 What You Need to Set Up

### 1. **Infrastructure Setup** (One-time)

- [ ] **Subdomain**: Create `api.donsylvester.dev` DNS A record pointing to your server
- [ ] **SSL Certificate**: Set up Let's Encrypt SSL for `api.donsylvester.dev`
- [ ] **Server**: Ensure you have a server/VPS with Docker or Python 3.11+
- [ ] **Firewall**: Open ports 80, 443 (and optionally 8000 for direct access)

### 2. **Orchestrator API Deployment**

- [ ] **Clone/Deploy Repository**: 
  ```bash
  git clone https://github.com/MentalVibez/ai-agent-orchestrator.git
  cd ai-agent-orchestrator
  ```

- [ ] **Environment Variables**: Create `.env` file:
  ```bash
  cp env.template .env
  # Edit .env with your values
  ```

- [ ] **Generate API Key**:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  # Copy this to .env as API_KEY
  ```

- [ ] **Configure AWS Credentials** (if using Bedrock):
  - Set `AWS_ACCESS_KEY_ID`
  - Set `AWS_SECRET_ACCESS_KEY`
  - Set `AWS_REGION`

- [ ] **Set CORS Origins**:
  ```bash
  CORS_ORIGINS=https://donsylvester.dev,https://www.donsylvester.dev
  ```

- [ ] **Deploy with Docker**:
  ```bash
  docker-compose up -d
  ```

- [ ] **Test API**:
  ```bash
  curl https://api.donsylvester.dev/api/v1/health
  ```

### 3. **Backend Proxy Setup** (Your Existing Backend)

- [ ] **Add Environment Variables** to your backend `.env`:
  ```bash
  ORCHESTRATOR_API_URL=https://api.donsylvester.dev
  ORCHESTRATOR_API_KEY=<the-api-key-from-orchestrator-.env>
  ```

- [ ] **Create Proxy Endpoint** (see `INTEGRATION_GUIDE.md` for code examples)
  - Node.js/Express example provided
  - Python/Flask example provided

- [ ] **Test Proxy**:
  ```bash
  curl -X POST http://localhost:3000/api/chatbot/orchestrate \
    -H "Content-Type: application/json" \
    -d '{"message": "test network connectivity"}'
  ```

### 4. **Frontend Chatbot Integration**

- [ ] **Update Chatbot Logic** to detect when to use orchestrator
- [ ] **Add API Call** to your backend proxy endpoint
- [ ] **Format Agent Responses** for display in chatbot UI
- [ ] **Test User Flows** with sample queries

### 5. **Nginx Reverse Proxy** (If not using Docker directly)

- [ ] **Create Nginx Config** for `api.donsylvester.dev`
- [ ] **Set up SSL** with Let's Encrypt
- [ ] **Test HTTPS** access

## 🔑 Key Files to Configure

1. **Orchestrator `.env`** - Contains API key, AWS credentials, CORS settings
2. **Your Backend `.env`** - Contains orchestrator API URL and API key
3. **Nginx Config** - SSL and reverse proxy setup

## 📝 Environment Variables Summary

### Orchestrator API (.env)
```bash
API_KEY=<generate-strong-key>
CORS_ORIGINS=https://donsylvester.dev,https://www.donsylvester.dev
AWS_ACCESS_KEY_ID=<your-aws-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret>
AWS_REGION=us-east-1
LLM_PROVIDER=bedrock
REQUIRE_API_KEY=true
RATE_LIMIT_PER_MINUTE=60
```

### Your Backend (.env)
```bash
ORCHESTRATOR_API_URL=https://api.donsylvester.dev
ORCHESTRATOR_API_KEY=<same-as-orchestrator-api-key>
```

## 🚀 Quick Start Commands

```bash
# 1. Deploy orchestrator
cd ai-agent-orchestrator
cp env.template .env
# Edit .env with your values
docker-compose up -d

# 2. Test it works
curl -H "X-API-Key: your-key" \
     https://api.donsylvester.dev/api/v1/health

# 3. Add proxy to your backend (see INTEGRATION_GUIDE.md)

# 4. Update chatbot frontend (see INTEGRATION_GUIDE.md)
```

## ⚠️ Security Reminders

- ✅ Never commit `.env` files
- ✅ Never expose API key in frontend JavaScript
- ✅ Always use HTTPS in production
- ✅ Use backend proxy to hide API key
- ✅ Monitor rate limits and adjust as needed

## 📚 Next Steps

1. Read `INTEGRATION_GUIDE.md` for detailed code examples
2. Read `DEPLOYMENT.md` for detailed deployment instructions
3. Read `SECURITY.md` for security best practices

