"""Gunicorn configuration for production deployment."""

import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = 2048

# Worker processes
workers = int(os.getenv('WORKERS', '1'))
if workers == 0:
    # Auto mode: (2 * CPU cores) + 1
    workers = multiprocessing.cpu_count() * 2 + 1

worker_class = 'uvicorn.workers.UvicornWorker'
worker_connections = int(os.getenv('WORKER_CONNECTIONS', '1000'))
max_requests = 1000  # Restart worker after N requests to prevent memory leaks
max_requests_jitter = 50  # Add randomness to prevent all workers restarting at once

# Timeouts
timeout = int(os.getenv('TIMEOUT', '30'))
graceful_timeout = int(os.getenv('GRACEFUL_TIMEOUT', '10'))
keepalive = int(os.getenv('KEEPALIVE', '5'))

# Logging
accesslog = '-'  # Log to stdout
errorlog = '-'  # Log to stderr
loglevel = os.getenv('LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = os.getenv('APP_NAME', 'polars-analysis')

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
keyfile = os.getenv('SSL_KEYFILE', None)
certfile = os.getenv('SSL_CERTFILE', None)

print(f"""
===========================================
Gunicorn Configuration
===========================================
Bind: {bind}
Workers: {workers} ({worker_class})
Worker connections: {worker_connections}
Timeout: {timeout}s
Log level: {loglevel}
===========================================
""")
