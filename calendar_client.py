import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pytz

# AWS imports with error handling
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print(f"AWS SDK import error: {e}")
    raise ImportError("boto3 is required for AWS operations")

# Google API imports with graceful error handling
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as e:
    print(f"Google API client import error: {e}")
    raise ImportError("Google API client libraries are required. Check requirements.txt and deployment package.")

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
        
        # Set up timezones
        self.paris_tz = pytz.timezone('Europe/Paris')
        self.pst_tz = pytz.timezone('US/Pacific')
    
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
                    subject: str, duration_hours: int = 2, content_hash: str = None,
                    assignment_type: str = 'homework') -> Optional[str]:
        """
        Create a homework event in Google Calendar with content hash for idempotency.
        
        Args:
            title: Event title
            description: Event description
            due_date: Due date for the homework
            subject: Subject name
            duration_hours: Event duration in hours
            content_hash: SHA256 hash for idempotency
            assignment_type: Type of assignment (homework, test, etc.)
            
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
                        'source': 'pronote',
                        'pronote_hash': content_hash or '',
                        'assignment_type': assignment_type,
                        'subject': subject,
                        'due_date': due_date.isoformat(),
                        'created_by': 'lambda',
                        'sync_version': '2.0'
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
    
    def create_exam_event(self, title: str, description: str, exam_date: datetime.date, 
                         subject: str, duration_hours: int = 2, content_hash: str = None,
                         teacher: str = None, coefficient: str = None) -> Optional[str]:
        """
        Create an exam event in Google Calendar with distinctive styling.
        
        Args:
            title: Event title
            description: Event description
            exam_date: Date of the exam
            subject: Subject name
            duration_hours: Event duration in hours
            content_hash: SHA256 hash for idempotency
            teacher: Teacher name
            coefficient: Exam coefficient
            
        Returns:
            Event ID if successful, None otherwise
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot create exam event: authentication failed")
        
        try:
            # Set exam events for 10:00 AM on the exam date (Europe/Paris time)
            event_start = datetime.combine(exam_date, datetime.min.time().replace(hour=10))
            event_end = event_start + timedelta(hours=duration_hours)
            
            # Build detailed description
            exam_description = f"🎓 EXAMEN - {description}\n\nSubject: {subject}\nExam Date: {exam_date}"
            if teacher:
                exam_description += f"\nTeacher: {teacher}"
            if coefficient:
                exam_description += f"\nCoefficient: {coefficient}"
            
            # Create event object with exam-specific styling
            event = {
                'summary': f"🎓 {title}",
                'description': exam_description,
                'start': {
                    'dateTime': event_start.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'end': {
                    'dateTime': event_end.isoformat(),
                    'timeZone': 'Europe/Paris',
                },
                'colorId': self._get_exam_color_for_subject(subject),
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 60},    # 1 hour before
                        {'method': 'popup', 'minutes': 1440},  # 1 day before
                        {'method': 'popup', 'minutes': 10080}, # 1 week before
                    ],
                },
                'extendedProperties': {
                    'private': {
                        'source': 'pronote',
                        'pronote_hash': content_hash or '',
                        'assignment_type': 'exam',
                        'subject': subject,
                        'exam_date': exam_date.isoformat(),
                        'teacher': teacher or '',
                        'coefficient': str(coefficient) if coefficient else '',
                        'created_by': 'lambda',
                        'sync_version': '2.0'
                    }
                }
            }
            
            # Create the event
            created_event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event
            ).execute()
            
            event_id = created_event.get('id')
            logger.info(f"Created exam event: {title} (ID: {event_id})")
            return event_id
            
        except Exception as e:
            logger.error(f"Error creating exam event: {str(e)}")
            return None

    def create_study_reminder_events(self, exam_title: str, exam_date: datetime.date, 
                                   subject: str, content_hash_base: str) -> List[str]:
        """
        Create daily study reminder events for the week before an exam at 4:00 PM PST.
        
        Args:
            exam_title: Title of the exam
            exam_date: Date of the exam
            subject: Subject name
            content_hash_base: Base hash for generating unique hashes for each reminder
            
        Returns:
            List of created event IDs
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot create study reminders: authentication failed")
        
        created_events = []
        
        # Create reminders for 7 days before the exam
        for days_before in range(1, 8):  # 1-7 days before
            try:
                reminder_date = exam_date - timedelta(days=days_before)
                
                # Skip if reminder date is in the past
                if reminder_date < datetime.now().date():
                    continue
                
                # Create PST time at 4:00 PM
                pst_time = self.pst_tz.localize(
                    datetime.combine(reminder_date, datetime.min.time().replace(hour=16))
                )
                
                # Convert to UTC for Google Calendar
                utc_start = pst_time.astimezone(pytz.UTC)
                utc_end = utc_start + timedelta(minutes=15)  # 15-minute reminder
                
                # Generate title based on days remaining
                if days_before == 1:
                    reminder_title = f"🔔 Final review: {subject} exam tomorrow"
                else:
                    reminder_title = f"🔔 Study reminder: {subject} exam in {days_before} days"
                
                # Generate unique content hash for this reminder
                reminder_hash = self._generate_reminder_hash(content_hash_base, days_before)
                
                # Build reminder description
                reminder_description = f"📚 Study reminder for upcoming exam\n\nExam: {exam_title}\nSubject: {subject}\nExam Date: {exam_date}\nDays remaining: {days_before}"
                
                # Create reminder event
                event = {
                    'summary': reminder_title,
                    'description': reminder_description,
                    'start': {
                        'dateTime': utc_start.isoformat(),
                        'timeZone': 'UTC',
                    },
                    'end': {
                        'dateTime': utc_end.isoformat(),
                        'timeZone': 'UTC',
                    },
                    'colorId': self._get_reminder_color(),
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 0},   # At event time
                            {'method': 'popup', 'minutes': 15},  # 15 minutes before
                        ],
                    },
                    'extendedProperties': {
                        'private': {
                            'source': 'pronote',
                            'pronote_hash': reminder_hash,
                            'assignment_type': 'study_reminder',
                            'subject': subject,
                            'exam_date': exam_date.isoformat(),
                            'days_before': str(days_before),
                            'parent_exam_hash': content_hash_base,
                            'created_by': 'lambda',
                            'sync_version': '2.0'
                        }
                    }
                }
                
                # Create the reminder event
                created_event = self.service.events().insert(
                    calendarId=self.calendar_id,
                    body=event
                ).execute()
                
                event_id = created_event.get('id')
                created_events.append(event_id)
                logger.info(f"Created study reminder: {reminder_title} (ID: {event_id})")
                
            except Exception as e:
                logger.error(f"Error creating study reminder for {days_before} days before {exam_title}: {str(e)}")
                continue
        
        return created_events
    
    def _generate_reminder_hash(self, base_hash: str, days_before: int) -> str:
        """
        Generate a unique hash for a study reminder based on the exam hash and days before.
        
        Args:
            base_hash: Base exam content hash
            days_before: Number of days before exam
            
        Returns:
            Unique hash for the reminder
        """
        import hashlib
        content = f"reminder|{base_hash}|{days_before}"
        hash_object = hashlib.sha256(content.encode('utf-8'))
        return hash_object.hexdigest()
    
    def _convert_paris_to_pst(self, paris_dt: datetime) -> datetime:
        """
        Convert a datetime from Europe/Paris timezone to US/Pacific.
        
        Args:
            paris_dt: Datetime in Europe/Paris timezone
            
        Returns:
            Datetime in US/Pacific timezone
        """
        # Localize to Paris timezone if naive
        if paris_dt.tzinfo is None:
            paris_dt = self.paris_tz.localize(paris_dt)
        
        # Convert to PST
        pst_dt = paris_dt.astimezone(self.pst_tz)
        return pst_dt
    
    def event_exists_by_hash(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """
        Check if an event with the given content hash already exists.
        
        Args:
            content_hash: SHA256 hash to search for
            
        Returns:
            Existing event data if found, None otherwise
        """
        if not self._authenticated:
            if not self.authenticate():
                return None
        
        try:
            logger.debug(f"Searching for event with hash: {content_hash[:8]}...")
            
            # Search for events with pronote source in extended time range
            now = datetime.now()
            start_time = now - timedelta(days=90)  # Look back 90 days
            end_time = now + timedelta(days=90)   # Look ahead 90 days
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
                singleEvents=True,
                maxResults=2500,  # Increase limit to catch more events
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Check each event for matching hash
            for event in events:
                extended_props = event.get('extendedProperties', {}).get('private', {})
                
                # Check if this is a Pronote event with matching hash
                if (extended_props.get('source') == 'pronote' and 
                    extended_props.get('pronote_hash') == content_hash):
                    
                    logger.debug(f"Found existing event with hash {content_hash[:8]}: {event.get('summary')}")
                    return {
                        'id': event.get('id'),
                        'summary': event.get('summary'),
                        'start': event.get('start'),
                        'end': event.get('end'),
                        'extended_properties': extended_props
                    }
            
            logger.debug(f"No existing event found with hash: {content_hash[:8]}")
            return None
            
        except HttpError as e:
            logger.error(f"Error searching for events by hash: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error in event_exists_by_hash: {str(e)}")
            return None
    
    def update_event(self, event_id: str, title: str, description: str, due_date: datetime.date,
                    subject: str, duration_hours: int = 2, content_hash: str = None,
                    assignment_type: str = 'homework') -> bool:
        """
        Update an existing calendar event.
        
        Args:
            event_id: Google Calendar event ID
            title: Updated event title
            description: Updated event description
            due_date: Updated due date
            subject: Subject name
            duration_hours: Event duration in hours
            content_hash: Updated content hash
            assignment_type: Type of assignment
            
        Returns:
            True if update successful, False otherwise
        """
        if not self._authenticated:
            if not self.authenticate():
                return False
        
        try:
            # Convert due date to datetime for the event
            event_start = datetime.combine(due_date, datetime.min.time().replace(hour=18))
            event_end = event_start + timedelta(hours=duration_hours)
            
            # Update event object
            updated_event = {
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
                'extendedProperties': {
                    'private': {
                        'source': 'pronote',
                        'pronote_hash': content_hash or '',
                        'assignment_type': assignment_type,
                        'subject': subject,
                        'due_date': due_date.isoformat(),
                        'updated_by': 'lambda',
                        'sync_version': '2.0',
                        'last_updated': datetime.now().isoformat()
                    }
                }
            }
            
            # Update the event
            updated_event_result = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=updated_event
            ).execute()
            
            logger.info(f"Updated calendar event: {title} (ID: {event_id})")
            return True
            
        except HttpError as e:
            logger.error(f"Google Calendar API error updating event: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error updating event: {str(e)}")
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
    
    def _get_exam_color_for_subject(self, subject: str) -> str:
        """
        Get a distinctive color ID for exam events based on subject.
        Uses brighter/more prominent colors than homework.
        
        Args:
            subject: Subject name
            
        Returns:
            Google Calendar color ID for exams
        """
        # Exam color mapping (using more prominent colors)
        exam_color_map = {
            'mathématiques': '11',  # Red (prominent)
            'français': '3',        # Purple (prominent)
            'anglais': '5',         # Yellow (prominent)
            'histoire': '8',        # Gray (prominent)
            'géographie': '8',      # Gray (prominent)
            'sciences': '10',       # Green (bright)
            'physique': '10',       # Green (bright)
            'chimie': '10',         # Green (bright)
            'eps': '6',             # Orange (bright)
            'arts': '6',            # Orange (bright)
            'technologie': '9',     # Blue (bright)
        }
        
        subject_lower = subject.lower()
        for key, color in exam_color_map.items():
            if key in subject_lower:
                return color
        
        return '11'  # Default to red for exams (prominent)
    
    def _get_reminder_color(self) -> str:
        """
        Get color ID for study reminder events.
        
        Returns:
            Google Calendar color ID for study reminders
        """
        return '7'  # Cyan/Light Blue for study reminders
    
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
                if extended_props.get('source') == 'pronote':
                    homework_events.append({
                        'id': event.get('id'),
                        'title': event.get('summary'),
                        'start': event.get('start', {}).get('dateTime'),
                        'subject': extended_props.get('subject'),
                        'due_date': extended_props.get('due_date'),
                        'pronote_hash': extended_props.get('pronote_hash'),
                        'assignment_type': extended_props.get('assignment_type')
                    })
            
            return homework_events
            
        except Exception as e:
            logger.error(f"Error getting upcoming events: {str(e)}")
            return []