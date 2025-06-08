import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Pronote API imports with error handling
try:
    import pronotepy
    from pronotepy import Client
except ImportError as e:
    print(f"Pronote API import error: {e}")
    raise ImportError("pronotepy library is required. Check requirements.txt and deployment package.")

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
    
    def get_exams(self, days_back: int = 60) -> List[Dict[str, Any]]:
        """
        Fetch exam/evaluation data for the specified number of days back.
        
        Args:
            days_back: Number of days back to fetch exam data for
            
        Returns:
            List of exam dictionaries with standardized format
            
        Raises:
            Exception: If not authenticated or API call fails
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot fetch exams: authentication failed")
        
        try:
            logger.info(f"Fetching exams for past {days_back} days")
            
            # Calculate date range
            current_date = datetime.now().date()
            cutoff_date = current_date - timedelta(days=days_back)
            
            # Fetch exams from Pronote
            exams_list = []
            
            # Iterate through periods to get historical data
            for period in self.client.periods:
                # Skip periods that end before our cutoff date
                if period.end < cutoff_date:
                    continue
                
                try:
                    # Get evaluations (exam scheduling/metadata)
                    evaluations = period.evaluations
                    for evaluation in evaluations:
                        if evaluation.date >= cutoff_date:
                            exam_item = self._standardize_evaluation(evaluation)
                            if exam_item:
                                exams_list.append(exam_item)
                    
                    # Get grades that represent exam results
                    grades = period.grades
                    for grade in grades:
                        if grade.date >= cutoff_date and self._is_exam_grade(grade):
                            exam_item = self._standardize_exam_grade(grade)
                            if exam_item:
                                exams_list.append(exam_item)
                                
                except Exception as e:
                    logger.warning(f"Error processing period {period}: {str(e)}")
                    continue
            
            # Remove duplicates based on content hash
            unique_exams = {}
            for exam in exams_list:
                content_hash = exam.get('content_hash')
                if content_hash and content_hash not in unique_exams:
                    unique_exams[content_hash] = exam
            
            final_exams = list(unique_exams.values())
            logger.info(f"Retrieved {len(final_exams)} unique exam records")
            return final_exams
            
        except Exception as e:
            logger.error(f"Error fetching exams: {str(e)}")
            raise Exception(f"Failed to fetch exams: {str(e)}")

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
    
    def _standardize_evaluation(self, evaluation) -> Optional[Dict[str, Any]]:
        """
        Convert Pronote evaluation object to standardized exam format.
        
        Args:
            evaluation: Raw evaluation object from pronotepy
            
        Returns:
            Standardized exam dictionary or None if invalid
        """
        try:
            # Extract basic information
            subject = getattr(evaluation, 'subject', {})
            subject_name = getattr(subject, 'name', 'Unknown Subject')
            
            # Get evaluation details
            name = getattr(evaluation, 'name', '').strip()
            description = getattr(evaluation, 'description', '').strip()
            
            if not name:
                name = 'Evaluation'
            
            # Get exam date
            exam_date = getattr(evaluation, 'date', None)
            if not exam_date:
                logger.warning("Evaluation missing date, skipping")
                return None
            
            # Convert to datetime if needed
            if isinstance(exam_date, str):
                try:
                    exam_date = datetime.strptime(exam_date, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid exam date format: {exam_date}")
                    return None
            
            # Get additional details
            teacher = getattr(evaluation, 'teacher', 'Unknown Teacher')
            coefficient = getattr(evaluation, 'coefficient', 1)
            
            # Generate content hash for idempotency
            content_hash = self._generate_exam_content_hash(subject_name, exam_date, name, 'evaluation')
            
            # Build standardized exam item
            exam_item = {
                'id': f"eval_{subject_name}_{exam_date}_{content_hash[:8]}",
                'subject': subject_name,
                'description': name,
                'detailed_description': description,
                'exam_date': exam_date,
                'teacher': teacher,
                'coefficient': coefficient,
                'assignment_type': 'exam',
                'data_source': 'evaluation',
                'content_hash': content_hash,
                'created_at': datetime.now().isoformat()
            }
            
            logger.debug(f"Standardized evaluation: {exam_item['subject']} - {exam_item['description']} (hash: {content_hash[:8]})")
            return exam_item
            
        except Exception as e:
            logger.error(f"Error standardizing evaluation: {str(e)}")
            return None

    def _standardize_exam_grade(self, grade) -> Optional[Dict[str, Any]]:
        """
        Convert Pronote grade object (from exam) to standardized exam format.
        
        Args:
            grade: Raw grade object from pronotepy
            
        Returns:
            Standardized exam dictionary or None if invalid
        """
        try:
            # Extract basic information
            subject = getattr(grade, 'subject', {})
            subject_name = getattr(subject, 'name', 'Unknown Subject')
            
            # Get grade details
            grade_value = getattr(grade, 'grade', '')
            out_of = getattr(grade, 'out_of', '')
            comment = getattr(grade, 'comment', '').strip()
            
            # Get exam date
            exam_date = getattr(grade, 'date', None)
            if not exam_date:
                logger.warning("Grade missing date, skipping")
                return None
            
            # Convert to datetime if needed
            if isinstance(exam_date, str):
                try:
                    exam_date = datetime.strptime(exam_date, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid exam date format: {exam_date}")
                    return None
            
            # Generate description from grade info
            description = comment if comment else f"Examen {subject_name}"
            if grade_value and out_of:
                description += f" ({grade_value}/{out_of})"
            
            # Get additional details
            coefficient = getattr(grade, 'coefficient', '')
            average = getattr(grade, 'average', '')
            
            # Generate content hash for idempotency
            content_hash = self._generate_exam_content_hash(subject_name, exam_date, description, 'grade')
            
            # Build standardized exam item
            exam_item = {
                'id': f"grade_{subject_name}_{exam_date}_{content_hash[:8]}",
                'subject': subject_name,
                'description': description,
                'detailed_description': comment,
                'exam_date': exam_date,
                'grade': grade_value,
                'out_of': out_of,
                'coefficient': coefficient,
                'class_average': average,
                'assignment_type': 'exam',
                'data_source': 'grade',
                'content_hash': content_hash,
                'created_at': datetime.now().isoformat()
            }
            
            logger.debug(f"Standardized exam grade: {exam_item['subject']} - {exam_item['description']} (hash: {content_hash[:8]})")
            return exam_item
            
        except Exception as e:
            logger.error(f"Error standardizing exam grade: {str(e)}")
            return None

    def _generate_exam_content_hash(self, subject: str, exam_date, description: str, source_type: str) -> str:
        """
        Generate a SHA256 hash for exam content to ensure idempotency.
        
        Args:
            subject: Subject name
            exam_date: Exam date (date object)
            description: Exam description
            source_type: Source type ('evaluation' or 'grade')
            
        Returns:
            SHA256 hash string
        """
        # Normalize inputs for consistent hashing
        normalized_subject = subject.strip().lower()
        normalized_description = description.strip().lower()
        exam_date_str = exam_date.strftime('%Y-%m-%d') if hasattr(exam_date, 'strftime') else str(exam_date)
        
        # Create content string for hashing
        content = f"exam|{normalized_subject}|{exam_date_str}|{normalized_description}|{source_type}"
        
        # Generate SHA256 hash
        hash_object = hashlib.sha256(content.encode('utf-8'))
        content_hash = hash_object.hexdigest()
        
        logger.debug(f"Generated exam content hash {content_hash[:8]} for: {content[:50]}...")
        return content_hash

    def _is_exam_grade(self, grade) -> bool:
        """
        Determine if a grade is from an exam/test vs regular homework.
        
        Args:
            grade: Raw grade object from pronotepy
            
        Returns:
            True if grade is from an exam, False otherwise
        """
        # Keywords that indicate exams/tests
        exam_keywords = [
            'contrôle', 'devoir surveillé', 'ds', 'évaluation', 'test', 'examen',
            'interro', 'interrogation', 'bac', 'partiel', 'quiz', 'composition'
        ]
        
        # Check comment field for exam indicators
        comment = getattr(grade, 'comment', '').lower()
        
        # Check if any exam keywords are in the comment
        for keyword in exam_keywords:
            if keyword in comment:
                return True
        
        # Check coefficient - exams typically have higher coefficients
        try:
            coefficient = float(getattr(grade, 'coefficient', '0'))
            if coefficient >= 2.0:  # Assume exams have coefficient >= 2
                return True
        except (ValueError, TypeError):
            pass
        
        # Default to False for homework
        return False

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