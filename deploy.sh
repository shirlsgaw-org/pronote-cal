#!/bin/bash

# AWS Lambda Deployment Script for Pronote to Google Calendar Sync
# This script packages and deploys the Lambda function using AWS SAM

set -e  # Exit on any error

# Configuration
FUNCTION_NAME="pronote-calendar-sync"
STACK_NAME="pronote-cal-stack"
S3_BUCKET=""  # Set this to your deployment bucket
AWS_REGION="us-east-1"
PYTHON_VERSION="3.11"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    echo_info "Checking prerequisites..."
    
    if ! command_exists aws; then
        echo_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    if ! command_exists sam; then
        echo_error "AWS SAM CLI is not installed. Please install it first."
        echo_info "Install with: pip install aws-sam-cli"
        exit 1
    fi
    
    if ! command_exists python3; then
        echo_error "Python 3 is not installed."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        echo_error "AWS credentials not configured. Run 'aws configure' first."
        exit 1
    fi
    
    echo_info "Prerequisites check passed"
}

# Validate environment variables
validate_env_vars() {
    echo_info "Validating required environment variables..."
    
    required_vars=(
        "PRONOTE_URL"
        "PRONOTE_USERNAME" 
        "PRONOTE_PASSWORD"
        "GOOGLE_CALENDAR_ID"
        "GOOGLE_CREDENTIALS_SECRET_NAME"
    )
    
    missing_vars=()
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo_error "Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            echo_error "  - $var"
        done
        echo_info "Set these variables before deployment:"
        echo_info "  export PRONOTE_URL='https://your-pronote-instance.com'"
        echo_info "  export PRONOTE_USERNAME='your_username'"
        echo_info "  export PRONOTE_PASSWORD='your_password'"
        echo_info "  export GOOGLE_CALENDAR_ID='your_calendar_id@gmail.com'"
        echo_info "  export GOOGLE_CREDENTIALS_SECRET_NAME='google-calendar-credentials'"
        exit 1
    fi
    
    echo_info "Environment variables validation passed"
}

# Set S3 bucket for deployment
set_s3_bucket() {
    if [[ -z "$S3_BUCKET" ]]; then
        echo_warn "S3_BUCKET not set. Attempting to create one..."
        ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
        S3_BUCKET="sam-deployments-${ACCOUNT_ID}-${AWS_REGION}"
        
        echo_info "Using S3 bucket: $S3_BUCKET"
        
        # Create bucket if it doesn't exist
        if ! aws s3 ls "s3://$S3_BUCKET" >/dev/null 2>&1; then
            echo_info "Creating S3 bucket: $S3_BUCKET"
            if [[ "$AWS_REGION" == "us-east-1" ]]; then
                aws s3 mb "s3://$S3_BUCKET"
            else
                aws s3 mb "s3://$S3_BUCKET" --region "$AWS_REGION"
            fi
        fi
    fi
}

# Build the SAM application
build_sam() {
    echo_info "Building SAM application..."
    sam build --use-container
    echo_info "Build completed"
}

# Deploy the SAM application
deploy_sam() {
    echo_info "Deploying SAM application..."
    
    # Deploy with parameters
    sam deploy \
        --stack-name "$STACK_NAME" \
        --s3-bucket "$S3_BUCKET" \
        --capabilities CAPABILITY_IAM \
        --region "$AWS_REGION" \
        --parameter-overrides \
            PronoteUrl="$PRONOTE_URL" \
            PronoteUsername="$PRONOTE_USERNAME" \
            PronotePassword="$PRONOTE_PASSWORD" \
            GoogleCalendarId="$GOOGLE_CALENDAR_ID" \
            GoogleCredentialsSecretName="$GOOGLE_CREDENTIALS_SECRET_NAME" \
        --confirm-changeset
    
    echo_info "Deployment completed"
}

# Get deployment outputs
get_outputs() {
    echo_info "Getting deployment outputs..."
    
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
}

# Create Google Calendar credentials secret
setup_google_credentials() {
    echo_info "Setting up Google Calendar credentials..."
    
    if [[ ! -f "google-credentials.json" ]]; then
        echo_warn "google-credentials.json not found"
        echo_info "Please follow these steps:"
        echo_info "1. Go to Google Cloud Console"
        echo_info "2. Enable Calendar API"
        echo_info "3. Create a service account"
        echo_info "4. Download the credentials JSON file as 'google-credentials.json'"
        echo_info "5. Run this script again"
        return 1
    fi
    
    # Create or update the secret
    if aws secretsmanager describe-secret \
        --secret-id "$GOOGLE_CREDENTIALS_SECRET_NAME" \
        --region "$AWS_REGION" >/dev/null 2>&1; then
        
        echo_info "Updating existing secret..."
        aws secretsmanager update-secret \
            --secret-id "$GOOGLE_CREDENTIALS_SECRET_NAME" \
            --region "$AWS_REGION" \
            --secret-string file://google-credentials.json
    else
        echo_info "Creating new secret..."
        aws secretsmanager create-secret \
            --name "$GOOGLE_CREDENTIALS_SECRET_NAME" \
            --region "$AWS_REGION" \
            --description "Google Calendar API credentials for Pronote sync" \
            --secret-string file://google-credentials.json
    fi
    
    echo_info "Google credentials secret configured"
}

# Test the deployed function
test_function() {
    echo_info "Testing deployed function..."
    
    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --region "$AWS_REGION" \
        --payload '{"source": "manual-test"}' \
        response.json
    
    if [[ -f "response.json" ]]; then
        echo_info "Function response:"
        cat response.json
        rm response.json
    fi
}

# Main deployment function
main() {
    echo_info "Starting deployment of Pronote Calendar Sync Lambda"
    echo_info "Function: $FUNCTION_NAME"
    echo_info "Stack: $STACK_NAME"
    echo_info "Region: $AWS_REGION"
    echo ""
    
    check_prerequisites
    validate_env_vars
    set_s3_bucket
    
    # Ask if user wants to setup Google credentials
    read -p "Do you want to setup Google Calendar credentials? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        setup_google_credentials
    fi
    
    build_sam
    deploy_sam
    get_outputs
    
    # Ask if user wants to test the function
    read -p "Do you want to test the deployed function? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        test_function
    fi
    
    echo_info "Deployment completed successfully!"
    echo_info "Your Lambda function is ready to sync Pronote homework to Google Calendar"
}

# Handle script arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "build")
        check_prerequisites
        build_sam
        ;;
    "test")
        test_function
        ;;
    "clean")
        echo_info "Cleaning up..."
        rm -rf .aws-sam/
        echo_info "Cleanup completed"
        ;;
    "delete")
        echo_warn "This will delete the entire stack. Are you sure? (type 'yes' to confirm)"
        read confirmation
        if [[ "$confirmation" == "yes" ]]; then
            aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$AWS_REGION"
            echo_info "Stack deletion initiated"
        else
            echo_info "Deletion cancelled"
        fi
        ;;
    *)
        echo "Usage: $0 [deploy|build|test|clean|delete]"
        echo "  deploy - Full deployment (default)"
        echo "  build  - Build only"
        echo "  test   - Test deployed function"
        echo "  clean  - Clean build artifacts"
        echo "  delete - Delete the stack"
        exit 1
        ;;
esac