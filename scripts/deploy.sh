#!/bin/bash
# Deploy the application using Docker Compose

set -e

echo "=========================================="
echo "Deploying Polars Analysis Platform"
echo "=========================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Warning: .env file not found"
    echo "Copying .env.example to .env..."
    cp .env.example .env
    echo "Please review and update .env with your configuration"
    exit 1
fi

echo "1. Building Docker image..."
docker-compose build

echo ""
echo "2. Stopping existing containers..."
docker-compose down

echo ""
echo "3. Starting new containers..."
docker-compose up -d

echo ""
echo "4. Waiting for application to start..."
sleep 5

echo ""
echo "5. Checking health..."
docker-compose ps

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Application is running at: http://localhost:8000"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop:"
echo "  docker-compose down"
echo ""
echo "To check status:"
echo "  curl http://localhost:8000/health"
