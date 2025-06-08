import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Core imports with error handling
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print(f"AWS SDK import error: {e}")
    raise ImportError("boto3 is required for AWS Lambda execution")

# Local imports with graceful error handling
try:
    from config import Config
    from pronote_client import PronoteClient
    from calendar_client import CalendarClient
except ImportError as e:
    print(f"Local module import error: {e}")
    raise ImportError("Required local modules not found - check deployment package")

# Configure logging for AWS CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for syncing Pronote data to Google Calendar.
    
    This function:
    1. Loads Pronote credentials from AWS Secrets Manager
    2. Fetches homework assignments for the next 30 days
    3. Fetches historical exam data for the past 60 days (if enabled)
    4. Authenticates with Google Calendar API
    5. Creates calendar events for new homework and exams
    6. Creates study reminder events for exams (if enabled)
    7. Returns success/error status
    
    Args:
        event: AWS Lambda event object (from EventBridge/CloudWatch)
        context: AWS Lambda context object
        
    Returns:
        Dict containing status and message
    """
    try:
        logger.info(f"Starting Pronote to Calendar sync at {datetime.now()}")
        
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
        
        # Fetch exam data if enabled
        exams_list = []
        if config.exam_sync_enabled:
            logger.info("Fetching historical exam data from Pronote")
            exams_list = pronote_client.get_exams(days_back=config.exam_lookback_days)
            logger.info(f"Found {len(exams_list)} exam records")
        
        # Process each homework assignment with hash-based idempotency
        events_created = 0
        events_updated = 0
        events_skipped = 0
        
        # Track exam and reminder events separately
        exam_events_created = 0
        reminder_events_created = 0
        
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
        
        # Process exam events if enabled
        if config.exam_sync_enabled and exams_list:
            logger.info("Processing exam events")
            
            for exam in exams_list:
                try:
                    content_hash = exam.get('content_hash')
                    exam_title = f"{exam['subject']}: {exam['description']}"
                    
                    if not content_hash:
                        logger.warning(f"No content hash for exam: {exam_title}")
                        continue
                    
                    # Check if exam event already exists
                    existing_event = calendar_client.event_exists_by_hash(content_hash)
                    
                    if not existing_event:
                        # Create new exam event
                        logger.info(f"Creating new exam event: {exam_title} (hash: {content_hash[:8]})")
                        
                        event_id = calendar_client.create_exam_event(
                            title=exam_title,
                            description=exam.get('detailed_description', ''),
                            exam_date=exam['exam_date'],
                            subject=exam['subject'],
                            duration_hours=config.exam_event_duration_hours,
                            content_hash=content_hash,
                            teacher=exam.get('teacher'),
                            coefficient=exam.get('coefficient')
                        )
                        
                        if event_id:
                            logger.info(f"Created exam event: {exam_title} (ID: {event_id})")
                            exam_events_created += 1
                            
                            # Create study reminders if enabled and exam is in the future
                            if (config.study_reminders_enabled and 
                                exam['exam_date'] > datetime.now().date()):
                                
                                logger.info(f"Creating study reminders for exam: {exam_title}")
                                reminder_ids = calendar_client.create_study_reminder_events(
                                    exam_title=exam_title,
                                    exam_date=exam['exam_date'],
                                    subject=exam['subject'],
                                    content_hash_base=content_hash
                                )
                                
                                if reminder_ids:
                                    reminder_events_created += len(reminder_ids)
                                    logger.info(f"Created {len(reminder_ids)} study reminders for {exam_title}")
                        else:
                            logger.warning(f"Failed to create exam event: {exam_title}")
                    else:
                        # Exam event already exists
                        logger.debug(f"Exam event already exists: {exam_title} (hash: {content_hash[:8]})")
                        events_skipped += 1
                        
                except Exception as e:
                    logger.error(f"Error processing exam '{exam.get('description', 'Unknown')}': {str(e)}")
                    continue
        
        # Prepare response
        total_events_created = events_created + exam_events_created + reminder_events_created
        
        response = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Pronote to Calendar sync completed successfully',
                'homework_events_created': events_created,
                'homework_events_updated': events_updated,
                'homework_events_skipped': events_skipped,
                'exam_events_created': exam_events_created,
                'reminder_events_created': reminder_events_created,
                'total_events_created': total_events_created,
                'total_homework': len(homework_list),
                'total_exams': len(exams_list),
                'sync_days_ahead': config.sync_days_ahead,
                'exam_sync_enabled': config.exam_sync_enabled,
                'study_reminders_enabled': config.study_reminders_enabled,
                'exam_lookback_days': config.exam_lookback_days,
                'dry_run': config.dry_run,
                'idempotency_method': 'content_hash',
                'timestamp': datetime.now().isoformat()
            })
        }
        
        logger.info(f"Sync completed: {events_created} homework, {exam_events_created} exams, {reminder_events_created} reminders created; {events_updated} updated, {events_skipped} skipped")
        return response
        
    except Exception as e:
        error_message = f"Error during Pronote sync: {str(e)}"
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