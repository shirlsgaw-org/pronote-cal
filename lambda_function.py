import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import boto3
from botocore.exceptions import ClientError

from config import Config
from pronote_client import PronoteClient
from calendar_client import CalendarClient

# Configure logging for AWS CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for syncing Pronote homework to Google Calendar.
    
    This function:
    1. Authenticates with Pronote using environment variables
    2. Fetches homework assignments for the next 30 days
    3. Authenticates with Google Calendar API
    4. Creates calendar events for new homework
    5. Returns success/error status
    
    Args:
        event: AWS Lambda event object (from EventBridge/CloudWatch)
        context: AWS Lambda context object
        
    Returns:
        Dict containing status and message
    """
    try:
        logger.info(f"Starting homework sync at {datetime.now()}")
        
        # Initialize configuration
        config = Config()
        
        # Validate required environment variables
        required_env_vars = [
            'PRONOTE_URL', 'PRONOTE_USERNAME', 'PRONOTE_PASSWORD',
            'GOOGLE_CALENDAR_ID', 'GOOGLE_CREDENTIALS_SECRET_NAME'
        ]
        
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")
        
        # Initialize clients
        logger.info("Initializing Pronote client")
        pronote_client = PronoteClient(
            url=config.pronote_url,
            username=config.pronote_username,
            password=config.pronote_password
        )
        
        logger.info("Initializing Google Calendar client")
        calendar_client = CalendarClient(
            calendar_id=config.google_calendar_id,
            credentials_secret_name=config.google_credentials_secret_name
        )
        
        # Fetch homework assignments from Pronote
        logger.info("Fetching homework assignments from Pronote")
        homework_list = pronote_client.get_homework(days_ahead=30)
        logger.info(f"Found {len(homework_list)} homework assignments")
        
        # Process each homework assignment
        events_created = 0
        events_skipped = 0
        
        for homework in homework_list:
            try:
                # Check if event already exists (basic duplicate detection)
                event_title = f"{homework['subject']}: {homework['description']}"
                
                if calendar_client.event_exists(event_title, homework['due_date']):
                    logger.debug(f"Event already exists: {event_title}")
                    events_skipped += 1
                    continue
                
                # Create calendar event
                event_id = calendar_client.create_event(
                    title=event_title,
                    description=homework.get('detailed_description', ''),
                    due_date=homework['due_date'],
                    subject=homework['subject']
                )
                
                if event_id:
                    logger.info(f"Created event: {event_title} (ID: {event_id})")
                    events_created += 1
                else:
                    logger.warning(f"Failed to create event: {event_title}")
                    
            except Exception as e:
                logger.error(f"Error processing homework '{homework.get('description', 'Unknown')}': {str(e)}")
                continue
        
        # Prepare response
        response = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Homework sync completed successfully',
                'events_created': events_created,
                'events_skipped': events_skipped,
                'total_homework': len(homework_list),
                'timestamp': datetime.now().isoformat()
            })
        }
        
        logger.info(f"Sync completed: {events_created} created, {events_skipped} skipped")
        return response
        
    except Exception as e:
        error_message = f"Error during homework sync: {str(e)}"
        logger.error(error_message, exc_info=True)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': error_message,
                'timestamp': datetime.now().isoformat()
            })
        }
    
    finally:
        # Cleanup connections
        try:
            if 'pronote_client' in locals():
                pronote_client.close()
        except Exception as e:
            logger.warning(f"Error closing Pronote client: {str(e)}")

def health_check(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Health check endpoint for monitoring.
    
    Returns:
        Dict containing health status
    """
    return {
        'statusCode': 200,
        'body': json.dumps({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0'
        })
    }