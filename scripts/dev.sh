#!/bin/bash
# Start development environment with Docker Compose

set -e

echo "=========================================="
echo "Starting Development Environment"
echo "=========================================="

echo "Starting containers with hot-reload..."
docker-compose -f docker-compose.dev.yml up

echo ""
echo "Development environment stopped"
