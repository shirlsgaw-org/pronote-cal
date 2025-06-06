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
        """Initialize configuration from environment variables and AWS Secrets Manager."""
        self.logger = logging.getLogger(__name__)
        self._secrets_client = None
        self._pronote_credentials = None
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
        # Try both possible environment variable names
        calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '').strip()
        if not calendar_id:
            calendar_id = os.getenv('CALENDAR_ID', '').strip()
        return calendar_id
    
    @property
    def google_credentials_secret_name(self) -> str:
        """AWS Secrets Manager secret name containing Google API credentials."""
        return os.getenv('GOOGLE_CREDENTIALS_SECRET_NAME', '').strip()
    
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
    def event_prefix(self) -> str:
        """Prefix for homework events in calendar."""
        return os.getenv('EVENT_PREFIX', 'Homework')
    
    @property
    def duplicate_detection_hours(self) -> int:
        """Hours within which to check for duplicate events."""
        try:
            return int(os.getenv('DUPLICATE_DETECTION_HOURS', '24'))
        except ValueError:
            return 24
    
    def _validate_required_vars(self) -> None:
        """
        Validate that all required environment variables are set.
        
        Raises:
            ValueError: If any required environment variables are missing.
        """
        required_vars = [
            'PRONOTE_CREDENTIALS_SECRET_NAME',
            'GOOGLE_CREDENTIALS_SECRET_NAME'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var, '').strip()
            if not value:
                missing_vars.append(var)
        
        # Check for Google Calendar ID (either variable name)
        calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '').strip()
        if not calendar_id:
            calendar_id = os.getenv('CALENDAR_ID', '').strip()
        if not calendar_id:
            missing_vars.append('GOOGLE_CALENDAR_ID or CALENDAR_ID')
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def get_secret_name(self, service: str) -> str:
        """
        Get the AWS Secrets Manager secret name for a service.
        
        Args:
            service: Service name (e.g., 'google', 'pronote')
            
        Returns:
            Secret name for the service
        """
        if service.lower() == 'google':
            return self.google_credentials_secret_name
        elif service.lower() == 'pronote':
            return self.pronote_credentials_secret_name
        else:
            raise ValueError(f"Unknown service: {service}")
    
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
            'event_prefix': self.event_prefix,
            'duplicate_detection_hours': self.duplicate_detection_hours
        }