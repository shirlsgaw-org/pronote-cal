#!/usr/bin/env python3
"""
Local testing script for the Pronote to Calendar sync Lambda function.
Run this in PyCharm to test without deploying to AWS.
"""

import os
import json
import logging
from datetime import datetime

# Set up environment variables for local testing
os.environ['PRONOTE_CREDENTIALS_SECRET_NAME'] = 'pronote-credentials'
os.environ['GOOGLE_CREDENTIALS_SECRET_NAME'] = 'google-calendar-credentials'
os.environ['GOOGLE_CALENDAR_ID'] = 'your-calendar-id@gmail.com'  # Replace with your actual calendar ID
os.environ['AWS_REGION'] = 'us-west-2'
os.environ['LOG_LEVEL'] = 'DEBUG'
os.environ['DRY_RUN'] = 'true'  # Safe mode - won't create actual calendar events
os.environ['EXAM_SYNC_ENABLED'] = 'true'
os.environ['EXAM_LOOKBACK_DAYS'] = '60'
os.environ['STUDY_REMINDERS_ENABLED'] = 'true'

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import your Lambda function
from lambda_function import lambda_handler

def test_lambda_locally():
    """Test the Lambda function locally."""
    print("🧪 Starting local test of Pronote sync Lambda function...")
    print(f"📅 Test started at: {datetime.now()}")
    print("=" * 60)
    
    # Create a mock event and context
    mock_event = {}
    
    class MockContext:
        def __init__(self):
            self.function_name = "pronote-homework-sync-local-test"
            self.function_version = "$LATEST"
            self.invoked_function_arn = "arn:aws:lambda:local:test:function:pronote-homework-sync-local-test"
            self.memory_limit_in_mb = 256
            self.remaining_time_in_millis = 300000
            self.log_group_name = "/aws/lambda/local-test"
            self.log_stream_name = "local-test-stream"
            self.aws_request_id = "local-test-12345"
    
    mock_context = MockContext()
    
    try:
        # Call the Lambda handler
        result = lambda_handler(mock_event, mock_context)
        
        print("\n" + "=" * 60)
        print("✅ Lambda function completed successfully!")
        print("📊 Results:")
        print(json.dumps(json.loads(result['body']), indent=2))
        
        return result
        
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ Lambda function failed with error: {str(e)}")
        print(f"📋 Error type: {type(e).__name__}")
        import traceback
        print("🔍 Full traceback:")
        traceback.print_exc()
        return None

def test_pronote_client_only():
    """Test just the Pronote client without calendar operations."""
    print("🧪 Testing Pronote client only...")
    
    try:
        from config import Config
        from pronote_client import PronoteClient
        
        config = Config()
        pronote_client = PronoteClient.from_config(config)
        
        print("📚 Testing homework fetch...")
        homework_list = pronote_client.get_homework(days_ahead=7)
        print(f"Found {len(homework_list)} homework assignments")
        
        if config.exam_sync_enabled:
            print("🎓 Testing exam fetch...")
            exams_list = pronote_client.get_exams(days_back=60)
            print(f"Found {len(exams_list)} exam records")
            
            # Print sample exam data
            if exams_list:
                print("\n📋 Sample exam data:")
                for i, exam in enumerate(exams_list[:3]):  # Show first 3
                    print(f"  {i+1}. {exam['subject']}: {exam['description']} on {exam['exam_date']}")
        
        pronote_client.close()
        print("✅ Pronote client test completed successfully!")
        
    except Exception as e:
        print(f"❌ Pronote client test failed: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Pronote Lambda Local Testing")
    print("Choose test mode:")
    print("1. Test Pronote client only (safer)")
    print("2. Test full Lambda function (requires AWS credentials)")
    
    try:
        choice = input("Enter choice (1 or 2): ").strip()
        
        if choice == "1":
            test_pronote_client_only()
        elif choice == "2":
            test_lambda_locally()
        else:
            print("Invalid choice. Running Pronote client test...")
            test_pronote_client_only()
            
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()