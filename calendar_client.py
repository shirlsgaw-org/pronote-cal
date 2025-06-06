import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import boto3
from botocore.exceptions import ClientError
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

class CalendarClient:
    """
    Wrapper class for Google Calendar API operations.
    
    This client handles authentication via AWS Secrets Manager,
    event creation, duplicate detection, and calendar management.
    """
    
    def __init__(self, calendar_id: str, credentials_secret_name: str, aws_region: str = 'us-east-1'):
        """
        Initialize the Google Calendar client.
        
        Args:
            calendar_id: Google Calendar ID where events will be created
            credentials_secret_name: AWS Secrets Manager secret containing Google credentials
            aws_region: AWS region for Secrets Manager
        """
        self.calendar_id = calendar_id
        self.credentials_secret_name = credentials_secret_name
        self.aws_region = aws_region
        self.service = None
        self._authenticated = False
        
        # Initialize AWS Secrets Manager client
        self.secrets_client = boto3.client('secretsmanager', region_name=aws_region)
    
    def authenticate(self) -> bool:
        """
        Authenticate with Google Calendar API using credentials from AWS Secrets Manager.
        
        Returns:
            True if authentication successful, False otherwise
            
        Raises:
            Exception: If authentication fails
        """
        try:
            logger.info("Retrieving Google credentials from AWS Secrets Manager")
            
            # Get credentials from AWS Secrets Manager
            credentials_json = self._get_credentials_from_secrets_manager()
            
            # Create credentials object
            credentials = service_account.Credentials.from_service_account_info(
                credentials_json,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
            # Build the Calendar service
            self.service = build('calendar', 'v3', credentials=credentials)
            
            # Test authentication by getting calendar info
            calendar_info = self.service.calendars().get(calendarId=self.calendar_id).execute()
            logger.info(f"Successfully authenticated with calendar: {calendar_info.get('summary', self.calendar_id)}")
            
            self._authenticated = True
            return True
            
        except Exception as e:
            logger.error(f"Google Calendar authentication error: {str(e)}")
            raise Exception(f"Failed to authenticate with Google Calendar: {str(e)}")
    
    def _get_credentials_from_secrets_manager(self) -> Dict[str, Any]:
        """
        Retrieve Google API credentials from AWS Secrets Manager.
        
        Returns:
            Dictionary containing Google service account credentials
            
        Raises:
            Exception: If unable to retrieve or parse credentials
        """
        try:
            response = self.secrets_client.get_secret_value(SecretId=self.credentials_secret_name)
            credentials_json = json.loads(response['SecretString'])
            
            # Validate required fields
            required_fields = ['type', 'project_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in credentials_json]
            
            if missing_fields:
                raise ValueError(f"Missing required credential fields: {missing_fields}")
            
            return credentials_json
            
        except ClientError as e:
            logger.error(f"AWS Secrets Manager error: {str(e)}")
            raise Exception(f"Failed to retrieve credentials from Secrets Manager: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in credentials: {str(e)}")
            raise Exception(f"Invalid JSON format in credentials: {str(e)}")
    
    def create_event(self, title: str, description: str, due_date: datetime.date, 
                    subject: str, duration_hours: int = 2) -> Optional[str]:
        """
        Create a homework event in Google Calendar.
        
        Args:
            title: Event title
            description: Event description
            due_date: Due date for the homework
            subject: Subject name
            duration_hours: Event duration in hours
            
        Returns:
            Event ID if successful, None otherwise
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot create event: authentication failed")
        
        try:
            # Convert due date to datetime for the event
            # Set homework events for 18:00 (6 PM) on the due date
            event_start = datetime.combine(due_date, datetime.min.time().replace(hour=18))
            event_end = event_start + timedelta(hours=duration_hours)
            
            # Create event object
            event = {
                'summary': title,
                'description': f"{description}\n\nSubject: {subject}\nDue Date: {due_date}",
                'start': {
                    'dateTime': event_start.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': event_end.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'colorId': self._get_color_for_subject(subject),
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 60},  # 1 hour before
                        {'method': 'popup', 'minutes': 1440},  # 1 day before
                    ],
                },
                'extendedProperties': {
                    'private': {
                        'source': 'pronote-homework-sync',
                        'subject': subject,
                        'due_date': due_date.isoformat(),
                        'created_by': 'lambda'
                    }
                }
            }
            
            # Create the event
            created_event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event
            ).execute()
            
            event_id = created_event.get('id')
            event_link = created_event.get('htmlLink', '')
            
            logger.info(f"Created calendar event: {title} (ID: {event_id})")
            return event_id
            
        except HttpError as e:
            logger.error(f"Google Calendar API error creating event: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error creating event: {str(e)}")
            return None
    
    def event_exists(self, title: str, due_date: datetime.date, 
                    detection_hours: int = 24) -> bool:
        """
        Check if a similar event already exists to avoid duplicates.
        
        Args:
            title: Event title to check
            due_date: Due date of the homework
            detection_hours: Hours around the due date to check for duplicates
            
        Returns:
            True if similar event exists, False otherwise
        """
        if not self._authenticated:
            if not self.authenticate():
                return False
        
        try:
            # Define search time range
            start_time = datetime.combine(due_date, datetime.min.time()) - timedelta(hours=detection_hours)
            end_time = datetime.combine(due_date, datetime.min.time()) + timedelta(hours=detection_hours)
            
            # Search for events
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime',
                q=title.split(':')[0]  # Search by subject name
            ).execute()
            
            events = events_result.get('items', [])
            
            # Check for exact or similar matches
            for event in events:
                event_title = event.get('summary', '')
                if self._titles_match(title, event_title):
                    logger.debug(f"Found existing event: {event_title}")
                    return True
            
            return False
            
        except HttpError as e:
            logger.error(f"Error checking for existing events: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error in event_exists: {str(e)}")
            return False
    
    def _titles_match(self, title1: str, title2: str) -> bool:
        """
        Check if two event titles are similar enough to be considered duplicates.
        
        Args:
            title1: First title
            title2: Second title
            
        Returns:
            True if titles match, False otherwise
        """
        # Normalize titles for comparison
        norm_title1 = title1.lower().strip()
        norm_title2 = title2.lower().strip()
        
        # Exact match
        if norm_title1 == norm_title2:
            return True
        
        # Check if one title contains the other (for partial matches)
        if norm_title1 in norm_title2 or norm_title2 in norm_title1:
            return True
        
        # Extract subject and assignment parts
        if ':' in norm_title1 and ':' in norm_title2:
            subject1, assignment1 = norm_title1.split(':', 1)
            subject2, assignment2 = norm_title2.split(':', 1)
            
            # Same subject and similar assignment
            if subject1.strip() == subject2.strip():
                assignment1 = assignment1.strip()
                assignment2 = assignment2.strip()
                
                if assignment1 == assignment2:
                    return True
                
                # Check for partial assignment matches
                if len(assignment1) > 10 and len(assignment2) > 10:
                    if assignment1 in assignment2 or assignment2 in assignment1:
                        return True
        
        return False
    
    def _get_color_for_subject(self, subject: str) -> str:
        """
        Get a color ID for the subject.
        
        Args:
            subject: Subject name
            
        Returns:
            Google Calendar color ID
        """
        # Simple color mapping based on subject
        color_map = {
            'mathématiques': '11',  # Red
            'français': '3',        # Purple
            'anglais': '5',         # Yellow
            'histoire': '8',        # Gray
            'géographie': '8',      # Gray
            'sciences': '2',        # Green
            'physique': '2',        # Green
            'chimie': '2',          # Green
            'eps': '4',             # Orange
            'arts': '6',            # Orange
            'technologie': '9',     # Blue
        }
        
        subject_lower = subject.lower()
        for key, color in color_map.items():
            if key in subject_lower:
                return color
        
        return '1'  # Default blue
    
    def get_upcoming_events(self, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """
        Get upcoming homework events from the calendar.
        
        Args:
            days_ahead: Number of days ahead to fetch events
            
        Returns:
            List of upcoming events
        """
        if not self._authenticated:
            if not self.authenticate():
                return []
        
        try:
            now = datetime.now()
            end_time = now + timedelta(days=days_ahead)
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=now.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Filter for homework events
            homework_events = []
            for event in events:
                extended_props = event.get('extendedProperties', {}).get('private', {})
                if extended_props.get('source') == 'pronote-homework-sync':
                    homework_events.append({
                        'id': event.get('id'),
                        'title': event.get('summary'),
                        'start': event.get('start', {}).get('dateTime'),
                        'subject': extended_props.get('subject'),
                        'due_date': extended_props.get('due_date')
                    })
            
            return homework_events
            
        except Exception as e:
            logger.error(f"Error getting upcoming events: {str(e)}")
            return []