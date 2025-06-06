import os
from typing import Optional

class Config:
    """
    Configuration management for the Pronote to Google Calendar sync Lambda.
    
    This class centralizes all configuration settings and environment variable
    handling. It provides validation and default values where appropriate.
    """
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self._validate_required_vars()
    
    @property
    def pronote_url(self) -> str:
        """Pronote instance URL."""
        return os.getenv('PRONOTE_URL', '').strip()
    
    @property
    def pronote_username(self) -> str:
        """Pronote username."""
        return os.getenv('PRONOTE_USERNAME', '').strip()
    
    @property
    def pronote_password(self) -> str:
        """Pronote password."""
        return os.getenv('PRONOTE_PASSWORD', '').strip()
    
    @property
    def google_calendar_id(self) -> str:
        """Google Calendar ID where events will be created."""
        return os.getenv('GOOGLE_CALENDAR_ID', '').strip()
    
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
            'PRONOTE_URL',
            'PRONOTE_USERNAME', 
            'PRONOTE_PASSWORD',
            'GOOGLE_CALENDAR_ID',
            'GOOGLE_CREDENTIALS_SECRET_NAME'
        ]
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var, '').strip()
            if not value:
                missing_vars.append(var)
        
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
        else:
            raise ValueError(f"Unknown service: {service}")
    
    def to_dict(self) -> dict:
        """
        Convert configuration to dictionary (excluding sensitive data).
        
        Returns:
            Dictionary of non-sensitive configuration values
        """
        return {
            'pronote_url': self.pronote_url,
            'google_calendar_id': self.google_calendar_id,
            'aws_region': self.aws_region,
            'log_level': self.log_level,
            'sync_days_ahead': self.sync_days_ahead,
            'event_duration_hours': self.event_duration_hours,
            'timezone': self.timezone,
            'dry_run': self.dry_run,
            'event_prefix': self.event_prefix,
            'duplicate_detection_hours': self.duplicate_detection_hours
        }