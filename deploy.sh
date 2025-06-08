#!/bin/bash

# Deployment script for pronote-homework-sync-dev Lambda function
set -e

FUNCTION_NAME="pronote-homework-sync-dev"
IMAGE_NAME="pronote-lambda"

# Auto-detect the region where the function exists
echo "🔍 Finding function region..."
REGION=$(aws lambda get-function --function-name $FUNCTION_NAME --query 'Configuration.FunctionArn' --output text 2>/dev/null | cut -d: -f4)

if [ -z "$REGION" ]; then
    echo "❌ Function $FUNCTION_NAME not found. Checking all regions..."
    # Try common regions
    for region in us-west-2 us-east-1 eu-west-1 eu-central-1; do
        echo "  Checking region: $region"
        if aws lambda get-function --function-name $FUNCTION_NAME --region $region --query 'Configuration.FunctionArn' --output text >/dev/null 2>&1; then
            REGION=$region
            echo "  ✅ Found function in region: $REGION"
            break
        fi
    done
fi

if [ -z "$REGION" ]; then
    echo "❌ Function $FUNCTION_NAME not found in any common region."
    echo "💡 Make sure the function exists and you have proper AWS credentials."
    exit 1
fi

echo "📍 Using region: $REGION"

echo "🚀 Starting deployment of $FUNCTION_NAME..."

# Build the Docker image with platform specification for Lambda
echo "📦 Building Docker image for Lambda..."
docker build --platform linux/amd64 -t $IMAGE_NAME .

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

# Get the image digest (SHA) instead of using the tag
echo "🔍 Getting image digest..."
IMAGE_DIGEST=$(aws ecr describe-images \
    --repository-name $IMAGE_NAME \
    --region $REGION \
    --query 'imageDetails[0].imageDigest' \
    --output text)

if [ -z "$IMAGE_DIGEST" ] || [ "$IMAGE_DIGEST" = "None" ]; then
    echo "❌ Failed to get image digest"
    exit 1
fi

IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$IMAGE_NAME@$IMAGE_DIGEST"
echo "📦 Using image URI with digest: $IMAGE_URI"

# Update Lambda function with digest-based URI
echo "🔄 Updating Lambda function..."
aws lambda update-function-code \
    --function-name $FUNCTION_NAME \
    --image-uri $IMAGE_URI \
    --region $REGION

# Wait for update to complete
echo "⏳ Waiting for function update to complete..."
aws lambda wait function-updated --function-name $FUNCTION_NAME --region $REGION

echo "✅ Deployment completed successfully!"
echo "🧪 You can now test with: aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' response.json"