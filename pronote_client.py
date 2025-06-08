import hashlib
import logging
from datetime import datetime, timedelta, date
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
    
    def get_exams(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch exam/evaluation data for the specified number of days ahead.
        
        Args:
            days_ahead: Number of days ahead to fetch exam data for (use negative values for testing with historical data)
            
        Returns:
            List of exam dictionaries with standardized format
            
        Raises:
            Exception: If not authenticated or API call fails
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot fetch exams: authentication failed")
        
        try:
            if days_ahead >= 0:
                logger.info(f"Fetching exams for next {days_ahead} days")
                start_date = datetime.now().date()
                end_date = start_date + timedelta(days=days_ahead)
            else:
                # Testing mode: negative value means look backward
                logger.info(f"Fetching exams for past {abs(days_ahead)} days (testing mode)")
                end_date = datetime.now().date()
                start_date = end_date + timedelta(days=days_ahead)  # days_ahead is negative
            
            # Fetch exams from Pronote
            exams_list = []
            
            # Iterate through periods to get data
            logger.info(f"Date range: {start_date} to {end_date}")
            logger.info(f"Found {len(self.client.periods)} periods to check")
            
            # Debug: Explore what other methods/properties are available
            client_attrs = [attr for attr in dir(self.client) if not attr.startswith('_')]
            logger.info(f"Client has {len(client_attrs)} public methods/attributes")
            logger.debug(f"Client methods/attributes: {client_attrs}")
            
            # Check for specific endpoints we're interested in
            interesting_attrs = ['lessons', 'grades', 'information_and_surveys', 'menu', 'discussions', 'absences']
            for attr in interesting_attrs:
                if hasattr(self.client, attr):
                    logger.info(f"✅ Found client.{attr}")
                    try:
                        value = getattr(self.client, attr)
                        if hasattr(value, '__len__'):
                            logger.info(f"  {attr} contains {len(value)} items")
                    except Exception as e:
                        logger.debug(f"  Error accessing {attr}: {e}")
                else:
                    logger.debug(f"❌ No client.{attr}")
            
            # Check if periods have other exam-related methods
            if self.client.periods:
                sample_period = self.client.periods[0]
                period_attrs = [attr for attr in dir(sample_period) if not attr.startswith('_')]
                logger.info(f"Period has {len(period_attrs)} public methods/attributes")
                logger.debug(f"Period methods/attributes: {period_attrs}")
                
                # Note: period.grades and period.averages exist but have parsing issues with this Pronote instance
                logger.info("✅ Found period.grades (skipped due to parsing issues in pronotepy)")
                logger.info("✅ Found period.averages (skipped due to parsing issues in pronotepy)")
                logger.debug("❌ No period.lessons (lessons are at client level)")
                        
            # Now let's explore the working endpoints we found
            logger.info("🔍 Exploring available endpoints...")
            
            # Check client.lessons for test/exam information
            try:
                logger.info("Checking client.lessons...")
                # lessons might require date parameters
                today = datetime.now().date()
                lessons_today = self.client.lessons(today)
                logger.info(f"Found {len(lessons_today)} lessons for today")
                
                # Check a broader date range
                lessons_week = self.client.lessons(start_date, end_date)
                logger.info(f"Found {len(lessons_week)} lessons in date range")
                
                # Look for lessons that might be exams
                for lesson in lessons_week[:10]:  # Sample first 10
                    # Properly extract subject name
                    lesson_subject_obj = getattr(lesson, 'subject', None)
                    if lesson_subject_obj and hasattr(lesson_subject_obj, 'name'):
                        lesson_subject = lesson_subject_obj.name
                    else:
                        lesson_subject = 'Unknown Subject'
                    
                    lesson_content = getattr(lesson, 'content', '')
                    lesson_start = getattr(lesson, 'start', None)
                    lesson_status = getattr(lesson, 'status', '')
                    
                    # Check if this might be a test/exam lesson
                    if lesson_content and any(keyword in lesson_content.lower() for keyword in 
                                            ['contrôle', 'test', 'évaluation', 'ds', 'interro', 'examen']):
                        logger.info(f"🎓 EXAM LESSON: {lesson_subject} - {lesson_content} at {lesson_start}")
                    else:
                        logger.debug(f"Lesson: {lesson_subject} - {lesson_content} at {lesson_start} (status: {lesson_status})")
                        
                    # Look specifically for math subjects
                    if lesson_subject and ('math' in lesson_subject.lower() or 'mathématiques' in lesson_subject.lower()):
                        logger.info(f"🔢 MATH LESSON: {lesson_subject} - {lesson_content} at {lesson_start}")
                    
            except Exception as e:
                logger.warning(f"Error exploring client.lessons: {e}")
                
            # Check client.information_and_surveys
            try:
                logger.info("Checking client.information_and_surveys...")
                info_surveys = self.client.information_and_surveys
                logger.info(f"Found {len(info_surveys)} information/survey items")
                
                for item in info_surveys[:3]:  # Sample first 3
                    item_title = getattr(item, 'title', 'No title')
                    item_content = getattr(item, 'content', 'No content')
                    logger.info(f"Info/Survey: {item_title} - {item_content[:100]}...")
                    
            except Exception as e:
                logger.warning(f"Error exploring client.information_and_surveys: {e}")
            
            for period in self.client.periods:
                # Convert period dates to date objects
                period_start = period.start
                if hasattr(period_start, 'date'):
                    period_start = period_start.date()
                period_end = period.end
                if hasattr(period_end, 'date'):
                    period_end = period_end.date()
                
                # Skip periods that don't overlap with our date range
                logger.debug(f"Period: {period_start} to {period_end}")
                if period_end < start_date or period_start > end_date:
                    logger.debug(f"Skipping period outside date range")
                    continue
                    
                logger.info(f"Processing period: {period_start} to {period_end}")
                
                try:
                    # Get evaluations (exam scheduling/metadata)
                    evaluations = period.evaluations
                    logger.info(f"Found {len(evaluations)} evaluations in this period")
                    for evaluation in evaluations:
                        try:
                            # Convert evaluation.date to date if it's a datetime
                            eval_date = evaluation.date
                            if eval_date is None:
                                continue
                            
                            # Handle different date formats
                            if isinstance(eval_date, str):
                                try:
                                    eval_date = datetime.strptime(eval_date, '%Y-%m-%d').date()
                                except ValueError:
                                    logger.warning(f"Skipping evaluation with invalid date format: {eval_date}")
                                    continue
                            elif hasattr(eval_date, 'date') and callable(getattr(eval_date, 'date')):
                                eval_date = eval_date.date()
                            elif not isinstance(eval_date, date):
                                logger.warning(f"Skipping evaluation with unsupported date type: {type(eval_date)}")
                                continue
                            
                            logger.debug(f"Evaluation date: {eval_date}, in range: {start_date <= eval_date <= end_date}")
                            if start_date <= eval_date <= end_date:
                                logger.info(f"Found exam in date range: {getattr(evaluation, 'name', 'Unknown')} on {eval_date}")
                                exam_item = self._standardize_evaluation(evaluation)
                                if exam_item:
                                    exams_list.append(exam_item)
                                else:
                                    logger.warning(f"Failed to standardize evaluation: {getattr(evaluation, 'name', 'Unknown')}")
                            else:
                                logger.debug(f"Skipping evaluation outside date range: {getattr(evaluation, 'name', 'Unknown')} on {eval_date}")
                        except Exception as eval_e:
                            logger.warning(f"Error processing evaluation: {str(eval_e)}")
                            continue
                                
                except Exception as e:
                    logger.warning(f"Error processing period {period}: {str(e)}")
                    continue
            
            # Also get test events from homework
            logger.info("Extracting test events from homework assignments...")
            test_events_from_homework = self.get_test_events_from_homework(days_ahead=days_ahead)
            
            # Combine evaluation-based exams and homework-based test events
            all_exams = exams_list + test_events_from_homework
            
            # Remove duplicates based on content hash
            unique_exams = {}
            for exam in all_exams:
                content_hash = exam.get('content_hash')
                if content_hash and content_hash not in unique_exams:
                    unique_exams[content_hash] = exam
            
            final_exams = list(unique_exams.values())
            logger.info(f"Retrieved {len(exams_list)} evaluation-based exams and {len(test_events_from_homework)} homework-based tests")
            logger.info(f"Total unique exam records: {len(final_exams)}")
            return final_exams
            
        except Exception as e:
            logger.error(f"Error fetching exams: {str(e)}")
            raise Exception(f"Failed to fetch exams: {str(e)}")

    def get_homework(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch homework assignments for the specified number of days ahead.
        
        Args:
            days_ahead: Number of days ahead to fetch homework for (use negative values for testing with historical data)
            
        Returns:
            List of homework dictionaries with standardized format
            
        Raises:
            Exception: If not authenticated or API call fails
        """
        if not self._authenticated:
            if not self.authenticate():
                raise Exception("Cannot fetch homework: authentication failed")
        
        try:
            if days_ahead >= 0:
                logger.info(f"Fetching homework for next {days_ahead} days")
                start_date = datetime.now().date()
                end_date = start_date + timedelta(days=days_ahead)
            else:
                # Testing mode: negative value means look backward
                logger.info(f"Fetching homework for past {abs(days_ahead)} days (testing mode)")
                end_date = datetime.now().date()
                start_date = end_date + timedelta(days=days_ahead)  # days_ahead is negative
            
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
            
            # Convert to date object consistently
            if isinstance(exam_date, str):
                try:
                    exam_date = datetime.strptime(exam_date, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid exam date format: {exam_date}")
                    return None
            elif hasattr(exam_date, 'date') and callable(getattr(exam_date, 'date')):
                # Convert datetime to date
                exam_date = exam_date.date()
            elif not isinstance(exam_date, date):
                logger.warning(f"Unsupported exam date type: {type(exam_date)}")
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
            'contrôle', 'devoir surveillé', 'examen', 'test', 'évaluation', 'ds', 'dm',
            'interro', 'interrogation', 'bac', 'partiel', 'quiz', 'brevet',
            'réviser pour', 'reviser pour', 'préparer pour', 'preparer pour',
            'evaluation de', 'évaluation de', 'test de', 'controle de', 'contrôle de'
        ]
        
        description_lower = description.lower()
        
        # First check for non-test keywords (administrative tasks)
        non_test_keywords = [
            'form', 'formulaire', 'complete this form', 'survey', 'vote', 'registration',
            'bring', 'apporter', 'rendre', 'submit', 'turn in', 'due before midnight',
            'tattoo', 'art show', 'favorite piece', 'please complete this form'
        ]
        
        for non_keyword in non_test_keywords:
            if non_keyword in description_lower:
                return 'homework'  # Force it to be homework, not a test
        
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
    
    def get_test_events_from_homework(self, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """
        Extract test/exam events from homework assignments.
        
        This looks for homework that appears to be test preparation or actual tests
        and converts them into exam-like events.
        
        Args:
            days_ahead: Number of days ahead to search (use negative for historical)
            
        Returns:
            List of exam-like dictionaries extracted from test-related homework
        """
        try:
            # Get all homework for the period
            homework_list = self.get_homework(days_ahead=days_ahead)
            
            test_events = []
            
            for hw in homework_list:
                assignment_type = hw.get('assignment_type', 'homework')
                
                if assignment_type == 'test':
                    # Convert test-related homework to exam event format
                    exam_event = {
                        'id': f"test_hw_{hw['id']}",
                        'subject': hw['subject'],
                        'description': hw['description'],
                        'detailed_description': hw['detailed_description'],
                        'exam_date': hw['due_date'],
                        'teacher': 'Unknown Teacher',  # Not available from homework
                        'coefficient': 1,  # Not available from homework
                        'assignment_type': 'exam',
                        'data_source': 'homework_test',
                        'content_hash': self._generate_exam_content_hash(
                            hw['subject'], 
                            hw['due_date'], 
                            hw['description'], 
                            'homework_test'
                        ),
                        'created_at': hw['created_at']
                    }
                    test_events.append(exam_event)
                    logger.info(f"Converted test homework to exam: {hw['subject']} - {hw['description']}")
            
            logger.info(f"Extracted {len(test_events)} test events from homework")
            return test_events
            
        except Exception as e:
            logger.error(f"Error extracting test events from homework: {str(e)}")
            return []
    
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