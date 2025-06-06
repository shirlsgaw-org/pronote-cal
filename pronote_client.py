import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import pronotepy
from pronotepy import Client

logger = logging.getLogger(__name__)

class PronoteClient:
    """
    Wrapper class for the Pronote API using pronotepy library.
    
    This client handles authentication, homework fetching, and connection management
    for the French Pronote school management system.
    """
    
    def __init__(self, url: str, username: str, password: str):
        """
        Initialize the Pronote client.
        
        Args:
            url: Pronote instance URL
            username: Student username
            password: Student password
        """
        self.url = url
        self.username = username
        self.password = password
        self.client: Optional[Client] = None
        self._authenticated = False
        
        # Log initialization (without sensitive data)
        logger.info(f"Initializing Pronote client for URL: {url}")
    
    @classmethod
    def from_config(cls, config):
        """
        Create PronoteClient instance from Config object.
        
        Args:
            config: Config instance with Pronote credentials
            
        Returns:
            PronoteClient instance
        """
        return cls(
            url=config.pronote_url,
            username=config.pronote_username,
            password=config.pronote_password
        )
    
    def authenticate(self) -> bool:
        """
        Authenticate with the Pronote server.
        
        Returns:
            True if authentication successful, False otherwise
            
        Raises:
            Exception: If authentication fails
        """
        try:
            logger.info(f"Authenticating with Pronote at {self.url}")
            
            # Create client and authenticate
            self.client = pronotepy.Client(
                self.url,
                username=self.username,
                password=self.password
            )
            
            if self.client.logged_in:
                self._authenticated = True
                logger.info(f"Successfully authenticated as {self.client.info.name}")
                return True
            else:
                logger.error("Authentication failed - client not logged in")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise Exception(f"Failed to authenticate with Pronote: {str(e)}")
    
    def get_homework(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch homework assignments for the specified number of days ahead.
        
        Args:
            days_ahead: Number of days ahead to fetch homework for
            
        Returns:
            List of homework dictionaries with standardized format
            
        Raises:
            Exception: If not authenticated or API call fails
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot fetch homework: authentication failed")
        
        try:
            logger.info(f"Fetching homework for next {days_ahead} days")
            
            # Calculate date range
            start_date = datetime.now().date()
            end_date = start_date + timedelta(days=days_ahead)
            
            # Fetch homework from Pronote
            homework_list = []
            
            # Get homework from the client
            # Note: pronotepy returns homework in a specific format
            raw_homework = self.client.homework(start_date, end_date)
            
            for hw in raw_homework:
                try:
                    # Standardize homework format
                    homework_item = self._standardize_homework(hw)
                    if homework_item:
                        homework_list.append(homework_item)
                        
                except Exception as e:
                    logger.warning(f"Error processing homework item: {str(e)}")
                    continue
            
            logger.info(f"Retrieved {len(homework_list)} homework assignments")
            return homework_list
            
        except Exception as e:
            logger.error(f"Error fetching homework: {str(e)}")
            raise Exception(f"Failed to fetch homework: {str(e)}")
    
    def _standardize_homework(self, hw) -> Optional[Dict[str, Any]]:
        """
        Convert Pronote homework object to standardized format.
        
        Args:
            hw: Raw homework object from pronotepy
            
        Returns:
            Standardized homework dictionary or None if invalid
        """
        try:
            # Extract basic information
            subject = getattr(hw, 'subject', {})
            subject_name = getattr(subject, 'name', 'Unknown Subject')
            
            # Get homework description
            description = getattr(hw, 'description', '').strip()
            if not description:
                description = 'Homework assignment'
            
            # Get due date
            due_date = getattr(hw, 'date', None)
            if not due_date:
                logger.warning("Homework item missing due date, skipping")
                return None
            
            # Convert to datetime if needed
            if isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid due date format: {due_date}")
                    return None
            
            # Get additional details
            background_color = getattr(hw, 'background_color', '#FFFFFF')
            done = getattr(hw, 'done', False)
            
            # Build standardized homework item
            homework_item = {
                'id': f"{subject_name}_{due_date}_{hash(description) % 10000}",
                'subject': subject_name,
                'description': description,
                'detailed_description': getattr(hw, 'description', ''),
                'due_date': due_date,
                'background_color': background_color,
                'done': done,
                'created_at': datetime.now().isoformat()
            }
            
            logger.debug(f"Standardized homework: {homework_item['subject']} - {homework_item['description']}")
            return homework_item
            
        except Exception as e:
            logger.error(f"Error standardizing homework: {str(e)}")
            return None
    
    def get_student_info(self) -> Dict[str, Any]:
        """
        Get student information from Pronote.
        
        Returns:
            Dictionary with student information
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot get student info: authentication failed")
        
        try:
            info = self.client.info
            return {
                'name': getattr(info, 'name', 'Unknown'),
                'class_name': getattr(info, 'class_name', 'Unknown'),
                'establishment': getattr(info, 'establishment', 'Unknown')
            }
        except Exception as e:
            logger.error(f"Error getting student info: {str(e)}")
            return {}
    
    def close(self) -> None:
        """
        Close the Pronote client connection.
        """
        try:
            if self.client and hasattr(self.client, 'close'):
                self.client.close()
                logger.debug("Pronote client connection closed")
        except Exception as e:
            logger.warning(f"Error closing Pronote client: {str(e)}")
        finally:
            self._authenticated = False
            self.client = None
    
    def __enter__(self):
        """Context manager entry."""
        self.authenticate()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()