import json
import logging
import os
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

class Config:
    """
    Configuration management for the Pronote to Google Calendar sync Lambda.
    
    This class centralizes all configuration settings and environment variable
    handling. It provides validation and default values where appropriate.
    """
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self.logger = logging.getLogger(__name__)
        self._secrets_client = None
        self._pronote_credentials = None
        self._google_credentials = None
        self._validate_required_vars()
    
    @property
    def secrets_client(self):
        """Get or create AWS Secrets Manager client."""
        if self._secrets_client is None:
            self._secrets_client = boto3.client('secretsmanager', region_name=self.aws_region)
        return self._secrets_client
    
    @property
    def pronote_credentials_secret_name(self) -> str:
        """AWS Secrets Manager secret name containing Pronote credentials."""
        return os.getenv('PRONOTE_CREDENTIALS_SECRET_NAME', '').strip()
    
    @property
    def google_credentials_secret_name(self) -> str:
        """AWS Secrets Manager secret name containing Google API credentials."""
        return os.getenv('GOOGLE_CREDENTIALS_SECRET_NAME', '').strip()
    
    def _get_pronote_credentials(self) -> Dict[str, str]:
        """
        Load Pronote credentials from AWS Secrets Manager.
        
        Returns:
            Dictionary containing url, username, and password
            
        Raises:
            Exception: If unable to retrieve or parse credentials
        """
        if self._pronote_credentials is not None:
            return self._pronote_credentials
            
        try:
            self.logger.info(f"Loading Pronote credentials from secret: {self.pronote_credentials_secret_name}")
            
            response = self.secrets_client.get_secret_value(SecretId=self.pronote_credentials_secret_name)
            credentials_json = json.loads(response['SecretString'])
            
            # Validate required fields
            required_fields = ['url', 'username', 'password']
            missing_fields = [field for field in required_fields if field not in credentials_json]
            
            if missing_fields:
                raise ValueError(f"Missing required Pronote credential fields: {missing_fields}")
            
            self._pronote_credentials = {
                'url': credentials_json['url'].strip(),
                'username': credentials_json['username'].strip(),
                'password': credentials_json['password'].strip()
            }
            
            self.logger.info("Successfully loaded Pronote credentials from Secrets Manager")
            return self._pronote_credentials
            
        except ClientError as e:
            error_msg = f"AWS Secrets Manager error loading Pronote credentials: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON format in Pronote credentials: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Failed to load Pronote credentials: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
    
    @property
    def pronote_url(self) -> str:
        """Pronote instance URL from Secrets Manager."""
        return self._get_pronote_credentials()['url']
    
    @property
    def pronote_username(self) -> str:
        """Pronote username from Secrets Manager."""
        return self._get_pronote_credentials()['username']
    
    @property
    def pronote_password(self) -> str:
        """Pronote password from Secrets Manager."""
        return self._get_pronote_credentials()['password']
    
    @property
    def google_calendar_id(self) -> str:
        """Google Calendar ID where events will be created."""
        return os.getenv('GOOGLE_CALENDAR_ID', '').strip()
    
    @property
    def aws_region(self) -> str:
        """AWS region for services like Secrets Manager."""
        return os.getenv('AWS_REGION', 'us-east-1')
    
    @property
    def log_level(self) -> str:
        """Logging level."""
        return os.getenv('LOG_LEVEL', 'INFO').upper()
    
    @property
    def sync_days_ahead(self) -> int:
        """Number of days ahead to sync homework assignments."""
        try:
            return int(os.getenv('SYNC_DAYS_AHEAD', '30'))
        except ValueError:
            return 30
    
    @property
    def event_duration_hours(self) -> int:
        """Default duration for homework events in hours."""
        try:
            return int(os.getenv('EVENT_DURATION_HOURS', '2'))
        except ValueError:
            return 2
    
    @property
    def timezone(self) -> str:
        """Timezone for calendar events."""
        return os.getenv('TIMEZONE', 'Europe/Paris')
    
    @property
    def dry_run(self) -> bool:
        """Whether to run in dry-run mode (no actual calendar events created)."""
        return os.getenv('DRY_RUN', 'false').lower() in ('true', '1', 'yes')
    
    @property
    def exam_sync_enabled(self) -> bool:
        """Whether to sync exam data in addition to homework."""
        return os.getenv('EXAM_SYNC_ENABLED', 'true').lower() in ('true', '1', 'yes')
    
    @property
    def exam_days_ahead(self) -> int:
        """Number of days ahead to fetch exam data (for testing with historical data, use negative values)."""
        try:
            return int(os.getenv('EXAM_DAYS_AHEAD', '-60'))
        except ValueError:
            return -60
    
    @property
    def study_reminders_enabled(self) -> bool:
        """Whether to create study reminder events for exams."""
        return os.getenv('STUDY_REMINDERS_ENABLED', 'true').lower() in ('true', '1', 'yes')
    
    @property
    def study_reminder_days_before(self) -> int:
        """Number of days before exam to start creating study reminders."""
        try:
            return int(os.getenv('STUDY_REMINDER_DAYS_BEFORE', '7'))
        except ValueError:
            return 7
    
    @property
    def study_reminder_time_pst(self) -> str:
        """Time in PST to create study reminders (24-hour format, e.g., '16:00')."""
        return os.getenv('STUDY_REMINDER_TIME_PST', '16:00')
    
    @property
    def exam_event_duration_hours(self) -> int:
        """Default duration for exam events in hours."""
        try:
            return int(os.getenv('EXAM_EVENT_DURATION_HOURS', '2'))
        except ValueError:
            return 2
    
    def _validate_required_vars(self) -> None:
        """
        Validate that all required environment variables are set.
        
        Raises:
            ValueError: If any required environment variables are missing.
        """
        required_vars = [
            'PRONOTE_CREDENTIALS_SECRET_NAME',
            'GOOGLE_CREDENTIALS_SECRET_NAME',
            'GOOGLE_CALENDAR_ID'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var, '').strip()
            if not value:
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def to_dict(self) -> dict:
        """
        Convert configuration to dictionary (excluding sensitive data).
        
        Returns:
            Dictionary of non-sensitive configuration values
        """
        try:
            # Only include pronote_url if credentials are successfully loaded
            pronote_url = self.pronote_url if self._pronote_credentials else "Not loaded"
        except Exception:
            pronote_url = "Error loading"
            
        return {
            'pronote_url': pronote_url,
            'google_calendar_id': self.google_calendar_id,
            'pronote_credentials_secret_name': self.pronote_credentials_secret_name,
            'google_credentials_secret_name': self.google_credentials_secret_name,
            'aws_region': self.aws_region,
            'log_level': self.log_level,
            'sync_days_ahead': self.sync_days_ahead,
            'event_duration_hours': self.event_duration_hours,
            'timezone': self.timezone,
            'dry_run': self.dry_run,
            'exam_sync_enabled': self.exam_sync_enabled,
            'exam_days_ahead': self.exam_days_ahead,
            'study_reminders_enabled': self.study_reminders_enabled,
            'study_reminder_days_before': self.study_reminder_days_before,
            'study_reminder_time_pst': self.study_reminder_time_pst,
            'exam_event_duration_hours': self.exam_event_duration_hours
        }