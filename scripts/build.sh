#!/bin/bash
# Build Docker image for production deployment

set -e

echo "=========================================="
echo "Building Polars Analysis Platform"
echo "=========================================="

# Get version from environment or default
VERSION=${VERSION:-latest}

echo "Building image: polars-analysis:${VERSION}"

# Build the Docker image
docker build -t polars-analysis:${VERSION} .

echo ""
echo "=========================================="
echo "Build complete!"
echo "=========================================="
echo ""
echo "Image: polars-analysis:${VERSION}"
docker images | grep polars-analysis | head -n 1

echo ""
echo "To run the image:"
echo "  docker-compose up -d"
echo ""
echo "Or manually:"
echo "  docker run -p 8000:8000 polars-analysis:${VERSION}"
