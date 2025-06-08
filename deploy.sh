#!/bin/bash

# Deployment script for pronote-homework-sync-dev Lambda function
set -e

FUNCTION_NAME="pronote-homework-sync-dev"
REGION="us-east-1"  # Change if your function is in a different region
IMAGE_NAME="pronote-lambda"

echo "🚀 Starting deployment of $FUNCTION_NAME..."

# Build the Docker image
echo "📦 Building Docker image..."
docker build -t $IMAGE_NAME .

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create ECR repository if it doesn't exist
echo "🏗️  Setting up ECR repository..."
aws ecr describe-repositories --repository-names $IMAGE_NAME --region $REGION >/dev/null 2>&1 || \
aws ecr create-repository --repository-name $IMAGE_NAME --region $REGION

# Get ECR login token
echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Tag and push image
echo "⬆️  Pushing image to ECR..."
docker tag $IMAGE_NAME:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$IMAGE_NAME:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$IMAGE_NAME:latest

# Update Lambda function
echo "🔄 Updating Lambda function..."
aws lambda update-function-code \
    --function-name $FUNCTION_NAME \
    --image-uri $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$IMAGE_NAME:latest \
    --region $REGION

# Wait for update to complete
echo "⏳ Waiting for function update to complete..."
aws lambda wait function-updated --function-name $FUNCTION_NAME --region $REGION

echo "✅ Deployment completed successfully!"
echo "🧪 You can now test with: aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' response.json"