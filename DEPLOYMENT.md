# Deployment Guide for donsylvester.dev

This guide explains how to securely deploy the AI Agent Orchestrator API to your website without exposing sensitive information.

## 🏗️ Architecture Overview

The recommended deployment architecture separates concerns:

```
┌─────────────────────────────────────┐
│   Frontend (donsylvester.dev)       │
│   - Your website                    │
│   - Makes API calls to backend      │
└──────────────┬──────────────────────┘
               │ HTTPS + API Key
               ▼
┌─────────────────────────────────────┐
│   Backend API (api.donsylvester.dev)│
│   - FastAPI application              │
│   - Protected by API key             │
│   - Rate limited                     │
│   - Environment variables for secrets│
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│   LLM Providers (AWS Bedrock, etc.) │
│   - Credentials in environment vars  │
└─────────────────────────────────────┘
```

## 🔐 Security Features Implemented

1. **API Key Authentication** - All endpoints require a valid API key
2. **Rate Limiting** - Prevents abuse (default: 60 requests/minute)
3. **Security Headers** - XSS protection, content type sniffing prevention, etc.
4. **CORS Protection** - Only allows requests from configured origins
5. **Environment Variables** - All secrets stored in environment variables (never in code)

## 📋 Prerequisites

- Docker and Docker Compose (recommended)
- OR Python 3.11+ and virtual environment
- Domain name with DNS access (for subdomain setup)
- SSL certificate (Let's Encrypt recommended)

## 🚀 Deployment Options

### Option 1: Docker Deployment (Recommended)

#### Step 1: Prepare Environment Variables

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Generate a strong API key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

3. Edit `.env` and set:
   - `API_KEY` - The generated API key (you'll use this in your frontend)
   - `AWS_ACCESS_KEY_ID` - Your AWS access key
   - `AWS_SECRET_ACCESS_KEY` - Your AWS secret key
   - `CORS_ORIGINS` - Your frontend domain(s)
   - Other LLM provider settings as needed

**⚠️ IMPORTANT**: Never commit `.env` to git! It's already in `.gitignore`.

#### Step 2: Build and Run with Docker Compose

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the container
docker-compose down
```

#### Step 3: Set Up Reverse Proxy (Nginx)

Create an Nginx configuration file (e.g., `/etc/nginx/sites-available/api.donsylvester.dev`):

```nginx
server {
    listen 80;
    server_name api.donsylvester.dev;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.donsylvester.dev;

    # SSL Configuration (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/api.donsylvester.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.donsylvester.dev/privkey.pem;
    
    # SSL Security Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Proxy to FastAPI application
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/api.donsylvester.dev /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### Step 4: Set Up SSL Certificate

```bash
# Install Certbot
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.donsylvester.dev
```

### Option 2: Direct Python Deployment

#### Step 1: Set Up Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Step 2: Configure Environment Variables

Same as Docker option - create `.env` file with all required variables.

#### Step 3: Run with Production Server

```bash
# Using Gunicorn (recommended for production)
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Or using Uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Step 4: Set Up as Systemd Service

Create `/etc/systemd/system/ai-agent-orchestrator.service`:

```ini
[Unit]
Description=AI Agent Orchestrator API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/ai-agent-orchestrator
Environment="PATH=/path/to/ai-agent-orchestrator/venv/bin"
ExecStart=/path/to/ai-agent-orchestrator/venv/bin/gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable ai-agent-orchestrator
sudo systemctl start ai-agent-orchestrator
sudo systemctl status ai-agent-orchestrator
```

## 🌐 Frontend Integration

### Making API Calls from Your Website

In your frontend code (JavaScript/TypeScript), include the API key in the request headers:

```javascript
// Example: Fetch API
const response = await fetch('https://api.donsylvester.dev/api/v1/orchestrate', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'your-api-key-here' // The API_KEY from your .env
  },
  body: JSON.stringify({
    task: "Diagnose network connectivity issues",
    context: {
      hostname: "example.com",
      port: 443
    }
  })
});

const data = await response.json();
```

### ⚠️ Frontend Security Best Practices

**IMPORTANT**: Never expose your API key in client-side JavaScript if it's publicly accessible!

Instead, use one of these approaches:

1. **Backend Proxy** (Recommended)
   - Create a backend endpoint on your main website that proxies requests
   - Store the API key on your backend server
   - Your frontend calls your backend, which calls the API

2. **Environment-Specific Keys**
   - Use a different, less privileged API key for frontend
   - Implement additional rate limiting for public keys
   - Consider IP whitelisting

3. **Server-Side Rendering (SSR)**
   - Make API calls from your server-side code
   - API key never reaches the browser

## 🔍 Testing the Deployment

1. **Health Check**:
```bash
curl https://api.donsylvester.dev/api/v1/health
```

2. **Test with API Key**:
```bash
curl -H "X-API-Key: your-api-key" \
     -H "Content-Type: application/json" \
     https://api.donsylvester.dev/api/v1/agents
```

3. **Test Rate Limiting**:
```bash
# Make multiple rapid requests to see rate limiting in action
for i in {1..70}; do
  curl -H "X-API-Key: your-api-key" \
       https://api.donsylvester.dev/api/v1/health
done
```

## 📊 Monitoring and Logs

### Docker Logs
```bash
docker-compose logs -f api
```

### Systemd Logs
```bash
sudo journalctl -u ai-agent-orchestrator -f
```

### Application Logs
Configure logging level via `LOG_LEVEL` environment variable (DEBUG, INFO, WARNING, ERROR).

## 🔄 Updating the Application

1. Pull latest changes:
```bash
git pull origin main
```

2. Rebuild Docker container:
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

Or for systemd:
```bash
sudo systemctl restart ai-agent-orchestrator
```

## 🛡️ Security Checklist

- [ ] Strong API key generated and set in `.env`
- [ ] `.env` file is NOT committed to git
- [ ] SSL certificate installed and configured
- [ ] CORS origins configured correctly
- [ ] Rate limiting enabled
- [ ] API key authentication enabled (`REQUIRE_API_KEY=true`)
- [ ] Firewall configured (only allow ports 80, 443)
- [ ] Regular security updates applied
- [ ] Backups configured for environment variables
- [ ] Monitoring and alerting set up

## 🆘 Troubleshooting

### API returns 401 Unauthorized
- Check that `X-API-Key` header is included
- Verify `API_KEY` in `.env` matches the key in your request
- Check `REQUIRE_API_KEY` setting

### CORS errors
- Verify `CORS_ORIGINS` includes your frontend domain
- Check that the origin in the request matches exactly (including protocol)

### Rate limit errors
- Adjust `RATE_LIMIT_PER_MINUTE` in `.env`
- Check if you're making too many requests

### Connection refused
- Verify the application is running: `docker-compose ps` or `systemctl status`
- Check firewall rules
- Verify port 8000 is accessible

## 📚 Additional Resources

- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Docker Documentation](https://docs.docker.com/)
- [Nginx Configuration](https://nginx.org/en/docs/)
- [Let's Encrypt](https://letsencrypt.org/)

