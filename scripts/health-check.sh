#!/bin/bash
# Check health of the deployed application

set -e

HOST=${1:-localhost}
PORT=${2:-8000}

echo "Checking health of application at ${HOST}:${PORT}..."
echo ""

# Basic health check
echo "1. Liveness check (/health):"
curl -s "http://${HOST}:${PORT}/health" | python3 -m json.tool || echo "Failed"

echo ""
echo ""

# Readiness check
echo "2. Readiness check (/health/ready):"
curl -s "http://${HOST}:${PORT}/health/ready" | python3 -m json.tool || echo "Failed"

echo ""
echo ""

# Startup check
echo "3. Startup check (/health/startup):"
curl -s "http://${HOST}:${PORT}/health/startup" | python3 -m json.tool || echo "Failed"

echo ""
