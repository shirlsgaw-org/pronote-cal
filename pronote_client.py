import hashlib
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
        Convert Pronote homework object to standardized format with content hash.
        
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
            
            # Determine assignment type (homework vs test/exam)
            assignment_type = self._determine_assignment_type(hw, description)
            
            # Generate content hash for idempotency
            content_hash = self._generate_content_hash(subject_name, due_date, description)
            
            # Build standardized homework item
            homework_item = {
                'id': f"{subject_name}_{due_date}_{content_hash[:8]}",
                'subject': subject_name,
                'description': description,
                'detailed_description': getattr(hw, 'description', ''),
                'due_date': due_date,
                'background_color': background_color,
                'done': done,
                'assignment_type': assignment_type,
                'content_hash': content_hash,
                'created_at': datetime.now().isoformat()
            }
            
            logger.debug(f"Standardized homework: {homework_item['subject']} - {homework_item['description']} (hash: {content_hash[:8]})")
            return homework_item
            
        except Exception as e:
            logger.error(f"Error standardizing homework: {str(e)}")
            return None
    
    def _generate_content_hash(self, subject: str, due_date, description: str) -> str:
        """
        Generate a SHA256 hash for homework content to ensure idempotency.
        
        Args:
            subject: Subject name
            due_date: Due date (date object)
            description: Assignment description
            
        Returns:
            SHA256 hash string
        """
        # Normalize inputs for consistent hashing
        normalized_subject = subject.strip().lower()
        normalized_description = description.strip().lower()
        due_date_str = due_date.strftime('%Y-%m-%d') if hasattr(due_date, 'strftime') else str(due_date)
        
        # Create content string for hashing
        content = f"{normalized_subject}|{due_date_str}|{normalized_description}"
        
        # Generate SHA256 hash
        hash_object = hashlib.sha256(content.encode('utf-8'))
        content_hash = hash_object.hexdigest()
        
        logger.debug(f"Generated content hash {content_hash[:8]} for: {content[:50]}...")
        return content_hash
    
    def _determine_assignment_type(self, hw, description: str) -> str:
        """
        Determine the type of assignment (homework, test, exam).
        
        Args:
            hw: Raw homework object from pronotepy
            description: Assignment description
            
        Returns:
            Assignment type string
        """
        # Keywords that indicate tests/exams vs regular homework
        test_keywords = [
            'contrôle', 'devoir', 'examen', 'test', 'évaluation', 'ds', 'dm',
            'interro', 'interrogation', 'bac', 'partiel', 'quiz'
        ]
        
        description_lower = description.lower()
        
        # Check if any test keywords are in the description
        for keyword in test_keywords:
            if keyword in description_lower:
                return 'test'
        
        # Check for homework-specific indicators
        homework_keywords = ['exercice', 'devoir maison', 'homework', 'travail']
        for keyword in homework_keywords:
            if keyword in description_lower:
                return 'homework'
        
        # Default to homework if unclear
        return 'homework'
    
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