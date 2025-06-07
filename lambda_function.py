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
    1. Loads Pronote credentials from AWS Secrets Manager
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
        
        # Initialize configuration (this will load credentials from Secrets Manager)
        logger.info("Initializing configuration...")
        config = Config()
        
        # Log configuration (excluding sensitive data)
        logger.info(f"Configuration loaded: {config.to_dict()}")
        
        # Initialize clients using the factory method
        logger.info("Initializing Pronote client from configuration...")
        pronote_client = PronoteClient.from_config(config)
        
        logger.info("Initializing Google Calendar client...")
        calendar_client = CalendarClient(
            calendar_id=config.google_calendar_id,
            credentials_secret_name=config.google_credentials_secret_name,
            aws_region=config.aws_region
        )
        
        # Fetch homework assignments from Pronote
        logger.info("Fetching homework assignments from Pronote")
        homework_list = pronote_client.get_homework(days_ahead=config.sync_days_ahead)
        logger.info(f"Found {len(homework_list)} homework assignments")
        
        # Process each homework assignment with hash-based idempotency
        events_created = 0
        events_updated = 0
        events_skipped = 0
        
        for homework in homework_list:
            try:
                content_hash = homework.get('content_hash')
                event_title = f"{homework['subject']}: {homework['description']}"
                
                if not content_hash:
                    logger.warning(f"No content hash for homework: {event_title}")
                    continue
                
                # Check if event with this hash already exists
                existing_event = calendar_client.event_exists_by_hash(content_hash)
                
                if existing_event:
                    # Event exists - check if we need to update it
                    existing_title = existing_event.get('summary', '')
                    
                    if existing_title != event_title:
                        # Content has changed - update the event
                        logger.info(f"Updating existing event {content_hash[:8]}: {existing_title} -> {event_title}")
                        
                        success = calendar_client.update_event(
                            event_id=existing_event['id'],
                            title=event_title,
                            description=homework.get('detailed_description', ''),
                            due_date=homework['due_date'],
                            subject=homework['subject'],
                            duration_hours=config.event_duration_hours,
                            content_hash=content_hash,
                            assignment_type=homework.get('assignment_type', 'homework')
                        )
                        
                        if success:
                            events_updated += 1
                        else:
                            logger.warning(f"Failed to update event: {event_title}")
                    else:
                        # Event exists and is current - skip
                        logger.debug(f"Event already exists and is current: {event_title} (hash: {content_hash[:8]})")
                        events_skipped += 1
                else:
                    # No existing event - create new one
                    logger.info(f"Creating new event: {event_title} (hash: {content_hash[:8]})")
                    
                    event_id = calendar_client.create_event(
                        title=event_title,
                        description=homework.get('detailed_description', ''),
                        due_date=homework['due_date'],
                        subject=homework['subject'],
                        duration_hours=config.event_duration_hours,
                        content_hash=content_hash,
                        assignment_type=homework.get('assignment_type', 'homework')
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
                'events_updated': events_updated,
                'events_skipped': events_skipped,
                'total_homework': len(homework_list),
                'sync_days_ahead': config.sync_days_ahead,
                'dry_run': config.dry_run,
                'idempotency_method': 'content_hash',
                'timestamp': datetime.now().isoformat()
            })
        }
        
        logger.info(f"Sync completed: {events_created} created, {events_updated} updated, {events_skipped} skipped")
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
            'version': '2.0.0'
        })
    }