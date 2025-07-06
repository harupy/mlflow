#!/bin/bash

set -e

# Build MLflow wheel first
echo "Building MLflow wheel..."
rm -rf dist build mlflow.egg-info
python -m build --wheel

# Get the wheel filename
WHEEL_FILE=$(ls dist/mlflow-*.whl | head -n 1)
echo "Built wheel: $WHEEL_FILE"

# Build the Docker image
echo "Building Docker image..."
DOCKER_BUILDKIT=1 docker build -f Dockerfile.protos -t mlflow-proto-builder .

trap 'echo "Cleaning up Docker image..."; docker rmi mlflow-proto-builder' EXIT

# Run the container in detached mode
echo "Starting container with proto generation..."
CONTAINER_ID=$(docker run -d mlflow-proto-builder)

# Copy generated files directly from the container
echo "Copying generated proto files from container..."
docker cp $CONTAINER_ID:/mlflow/mlflow/protos/. ./mlflow/protos/
docker cp $CONTAINER_ID:/mlflow/mlflow/java/. ./mlflow/java/

# Stop and remove the container
echo "Cleaning up container..."
docker stop $CONTAINER_ID
docker rm $CONTAINER_ID

echo "Proto generation complete!"
echo "Generated files have been copied to mlflow/protos/"
