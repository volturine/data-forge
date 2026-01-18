# Deployment Guide

Deploy the Polars-FastAPI-Svelte Analysis Platform to production.

## Overview

The application consists of two parts:
- **Backend**: FastAPI server with Polars compute engine
- **Frontend**: SvelteKit static SPA

## Production Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.13+ |
| Node.js | 18+ |
| Database | SQLite (file-based) |
| Storage | File system for uploads/results |
| Memory | 2GB+ recommended |
| CPU | 2+ cores recommended |

## Deployment Options

### Option 1: Single Server (Recommended)

Deploy both backend and frontend on a single server.

#### 1. Prepare the Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install UV (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

#### 2. Deploy Backend

```bash
# Create deployment directory
sudo mkdir -p /opt/polars-fastapi-svelte
sudo chown $USER:$USER /opt/polars-fastapi-svelte
cd /opt/polars-fastapi-svelte

# Clone repository
git clone https://github.com/your-org/polars-fastapi-svelte.git .
git checkout main

# Install dependencies
cd backend
uv sync --extra dev

# Create environment file
cp .env.example .env
# Edit .env with production settings

# Run migrations
./migrate.sh upgrade

# Create systemd service
sudo cat > /etc/systemd/system/polars-api.service << EOF
[Unit]
Description=Polars FastAPI Backend
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/polars-fastapi-svelte/backend
Environment="PATH=/opt/polars-fastapi-svelte/backend/.venv/bin"
Environment="PYTHONPATH=/opt/polars-fastapi-svelte/backend"
ExecStart=/opt/polars-fastapi-svelte/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Start the service
sudo systemctl daemon-reload
sudo systemctl enable polars-api
sudo systemctl start polars-api
sudo systemctl status polars-api
```

#### 3. Deploy Frontend

```bash
cd /opt/polars-fastapi-svelte/frontend

# Install dependencies
npm ci

# Build for production
npm run build

# Create frontend systemd service
sudo cat > /etc/systemd/system/polars-frontend.service << EOF
[Unit]
Description=Polars Frontend Static Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/polars-fastapi-svelte/frontend
ExecStart=npx serve -s build -l 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Start the service
sudo systemctl daemon-reload
sudo systemctl enable polars-frontend
sudo systemctl start polars-frontend
sudo systemctl status polars-frontend
```

#### 4. Configure Reverse Proxy (Nginx)

```bash
# Install Nginx
sudo apt install -y nginx

# Create Nginx configuration
sudo cat > /etc/nginx/sites-available/polars-app << EOF
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Backend docs
    location /docs {
        proxy_pass http://localhost:8000/docs;
    }

    # Uploaded files
    location /uploads/ {
        alias /opt/polars-fastapi-svelte/data/uploads/;
    }

    # Results files
    location /results/ {
        alias /opt/polars-fastapi-svelte/data/results/;
    }
}
EOF

# Enable site and test
sudo ln -s /etc/nginx/sites-available/polars-app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 5. Secure with HTTPS

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is automatic
```

### Option 2: Docker Deployment

Containerize the application with Docker.

#### 1. Create Dockerfile

```dockerfile
# backend/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /usr/local/bin/uv /usr/local/bin/uv

# Copy requirements and install
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy application
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

```dockerfile
# frontend/Dockerfile
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV API_URL=http://localhost:8000
RUN npm run build

FROM node:18-alpine
WORKDIR /app
COPY --from=builder /app/build ./build
RUN npm install -g serve
EXPOSE 3000
CMD ["serve", "-s", "build", "-l", "3000"]
```

#### 2. Create Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./database:/app/database
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///./database/app.db
      - UPLOAD_DIR=/app/data/uploads
      - RESULTS_DIR=/app/data/results
      - MAX_UPLOAD_SIZE=10GB
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./data/uploads:/var/www/uploads:ro
      - ./data/results:/var/www/results:ro
    depends_on:
      - backend
      - frontend
    restart: unless-stopped
```

#### 3. Create Nginx Config for Docker

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://frontend:3000;
        }

        location /api/ {
            proxy_pass http://backend:8000/api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        location /docs {
            proxy_pass http://backend:8000/docs;
        }

        location /uploads/ {
            alias /var/www/uploads/;
        }

        location /results/ {
            alias /var/www/results/;
        }
    }
}
```

#### 4. Deploy with Docker

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Environment Configuration

### Backend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./database/app.db` | Database connection |
| `UPLOAD_DIR` | `./data/uploads` | Upload storage path |
| `RESULTS_DIR` | `./data/results` | Results storage path |
| `MAX_UPLOAD_SIZE` | `10GB` | Max file upload size |
| `COMPUTE_TIMEOUT` | `300` | Computation timeout (seconds) |
| `ENGINE_IDLE_TIMEOUT` | `300` | Idle engine timeout (seconds) |
| `DEBUG` | `false` | Enable debug logging |

### Frontend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |

## Directory Structure

```
/opt/polars-fastapi-svelte/
├── backend/
│   ├── .venv/              # Python virtual environment
│   ├── database/           # SQLite database
│   ├── data/
│   │   ├── uploads/        # Uploaded files
│   │   └── results/        # Result files
│   ├── main.py
│   └── pyproject.toml
├── frontend/
│   ├── build/              # Production build
│   ├── node_modules/
│   └── package.json
└── nginx.conf
```

## Monitoring

### Health Checks

```bash
# Check backend health
curl http://localhost:8000/api/v1/health

# Expected response:
# {"status": "ok", "version": "1.0.0"}
```

### Log Locations

| Service | Log Location |
|---------|-------------|
| Backend | Systemd journal: `journalctl -u polars-api` |
| Frontend | Systemd journal: `journalctl -u polars-frontend` |
| Nginx | `/var/log/nginx/` |

### Monitoring Commands

```bash
# Check service status
systemctl status polars-api
systemctl status polars-frontend

# Check resource usage
htop
df -h
du -sh /opt/polars-fastapi-svelte/data/*

# Check disk space
df -h /opt
```

## Backup and Recovery

### Backup Database

```bash
# Create backup
cp /opt/polars-fastapi-svelte/backend/database/app.db /backup/app.db.$(date +%Y%m%d)

# Restore from backup
cp /backup/app.db.20240101 /opt/polars-fastapi-svelte/backend/database/app.db
```

### Backup Data Files

```bash
# Backup uploads and results
tar -czf /backup/data.$(date +%Y%m%d).tar.gz /opt/polars-fastapi-svelte/data/
```

## Scaling Considerations

### Horizontal Scaling

For high availability, consider:
- Multiple backend instances behind a load balancer
- Shared storage (NFS, S3) for uploads/results
- Database clustering (not recommended for SQLite)

### Vertical Scaling

Increase resources:
- More CPU cores for Polars computations
- More RAM for larger datasets
- SSD storage for faster I/O

## Troubleshooting

### Backend Won't Start

```bash
# Check port availability
netstat -tlnp | grep 8000

# Check logs
journalctl -u polars-api -n 100

# Verify Python environment
cd /opt/polars-fastapi-svelte/backend
source .venv/bin/activate
python main.py
```

### Frontend Not Loading

```bash
# Check port availability
netstat -tlnp | grep 3000

# Check build directory exists
ls -la /opt/polars-fastapi-svelte/frontend/build/

# Check logs
journalctl -u polars-frontend -n 100
```

### Database Locked

```bash
# Check for running processes
ps aux | grep python

# Restart services
systemctl restart polars-api
```

## See Also

- [Getting Started](./getting-started.md) - Initial setup
- [Development Workflow](./development-workflow.md) - Development setup
- [Testing](./testing.md) - Running tests
- [Configuration](../reference/configuration.md) - Environment variables
