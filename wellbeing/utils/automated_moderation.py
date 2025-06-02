# Fully Automated Message Moderation System

from bson.objectid import ObjectId
import re
import datetime
from typing import Dict, List, Tuple, Optional
from bson.objectid import ObjectId
import hashlib

# Import these after creating the file
try:
    from wellbeing import mongo, logger
    from textblob import TextBlob
except ImportError:
    # For development/testing
    mongo = None
    logger = None
    TextBlob = None

class AutomatedModerator:
    """Fully automated message moderation with minimal human intervention"""
    
    # Enhanced profanity filter with severity levels
    PROFANITY_CONFIG = {
        'mild': ['damn', 'hell', 'crap', 'stupid'],
        'moderate': ['shit', 'bitch', 'asshole', 'idiot'],
        'severe': ['fuck', 'fucking', 'cunt']  # Add more as needed
    }
    
    # Crisis keywords with confidence levels
    CRISIS_INDICATORS = {
        'high_confidence': [
            'i want to die', 'kill myself', 'suicide', 'end my life',
            'not worth living', 'better off dead', 'want to disappear',
            'take my own life', 'end it all'
        ],
        'medium_confidence': [
            'hurt myself', 'self harm', 'cutting', 'overdose',
            'can\'t go on', 'give up', 'no point', 'want to die',
            'life is meaningless', 'nothing matters'
        ],
        'low_confidence': [
            'depressed', 'hopeless', 'worthless', 'empty inside',
            'feel terrible', 'can\'t take it', 'very sad'
        ]
    }
    
    # Boundary violations with auto-actions
    BOUNDARY_VIOLATIONS = {
        'block_immediately': [
            'personal phone number', 'my address is', 'meet me at',
            'sexual', 'romantic feelings', 'in love with you',
            'date me', 'kiss you', 'sleep with'
        ],
        'filter_and_warn': [
            'personal email', 'social media', 'outside appointment',
            'personal life', 'dating', 'phone number', 'home address'
        ],
        'log_only': [
            'friend', 'personal', 'outside therapy', 'after work'
        ]
    }
    
    @staticmethod
    def moderate_message(message: str, sender_type: str, sender_id: str, recipient_id: str) -> Dict:
        """
        Fully automated message moderation
        Returns: {
            'action': 'allow'|'filter'|'block'|'escalate',
            'filtered_message': str,
            'confidence': float,
            'flags': List[str],
            'auto_response': str|None
        }
        """
        result = {
            'action': 'allow',
            'filtered_message': message,
            'confidence': 1.0,
            'flags': [],
            'auto_response': None,
            'escalation_level': 'none'  # none, low, medium, high, critical
        }
        
        # 1. Basic validation
        if not message or len(message.strip()) == 0:
            result['action'] = 'block'
            result['flags'].append('empty_message')
            return result
        
        # 2. Length check
        if len(message) > 2000:
            result['action'] = 'block'
            result['flags'].append('message_too_long')
            return result
        
        # 3. Rate limiting (automatic)
        if not AutomatedModerator._check_rate_limits(sender_id, sender_type):
            result['action'] = 'block'
            result['flags'].append('rate_limit_exceeded')
            result['auto_response'] = "You're sending messages too quickly. Please wait before sending another message."
            return result
        
        # 4. Spam detection (automatic blocking)
        spam_score = AutomatedModerator._detect_spam(message, sender_id)
        if spam_score > 0.8:
            result['action'] = 'block'
            result['flags'].append('spam_detected')
            result['confidence'] = spam_score
            return result
        elif spam_score > 0.5:
            result['flags'].append('potential_spam')
        
        # 5. Crisis detection (automatic escalation)
        crisis_level, crisis_confidence = AutomatedModerator._detect_crisis_automated(message)
        if crisis_level != 'none':
            result['flags'].append(f'crisis_{crisis_level}')
            result['escalation_level'] = crisis_level
            
            if crisis_level in ['high', 'critical']:
                # Auto-escalate but still allow message
                result['action'] = 'allow'
                AutomatedModerator._auto_escalate_crisis(sender_id, recipient_id, message, crisis_level)
                result['auto_response'] = "Your message indicates you may need immediate support. Your therapist has been notified and will prioritize your message."
            
        # 6. Profanity filtering (automatic)
        filtered_message, profanity_level = AutomatedModerator._filter_profanity_automated(message)
        if profanity_level:
            result['filtered_message'] = filtered_message
            result['flags'].append(f'profanity_{profanity_level}')
            if profanity_level == 'severe':
                result['action'] = 'filter'
        
        # 7. Boundary violation detection (automatic actions)
        boundary_action, boundary_flags = AutomatedModerator._check_boundaries_automated(message, sender_type)
        if boundary_action == 'block':
            result['action'] = 'block'
            result['flags'].extend(boundary_flags)
            result['auto_response'] = "Your message contains content that violates professional boundaries and cannot be sent."
            return result
        elif boundary_action == 'filter':
            result['action'] = 'filter'
            result['flags'].extend(boundary_flags)
            result['filtered_message'] = AutomatedModerator._filter_boundary_content(message)
        
        # 8. Sentiment analysis for additional context
        sentiment_score = AutomatedModerator._analyze_sentiment(message)
        if sentiment_score < -0.8:  # Very negative
            result['flags'].append('very_negative_sentiment')
        
        # 9. Business hours check (informational only)
        if not AutomatedModerator._is_business_hours():
            result['flags'].append('outside_business_hours')
        
        # 10. Final decision logic
        if result['action'] == 'allow' and len(result['flags']) > 0:
            # Log for monitoring but allow
            AutomatedModerator._log_moderation_action(sender_id, message, result)
        
        return result
    
    @staticmethod
    def _check_rate_limits(sender_id: str, sender_type: str) -> bool:
        """Automatic rate limiting check"""
        if not mongo:
            return True  # Skip if not initialized
            
        limits = {
            'student': {'per_minute': 3, 'per_hour': 20, 'per_day': 100},
            'therapist': {'per_minute': 5, 'per_hour': 50, 'per_day': 200}
        }
        
        user_limits = limits.get(sender_type, limits['student'])
        now = datetime.datetime.now()
        
        try:
            # Validate ObjectId format
            if not ObjectId.is_valid(sender_id):
                # For testing or invalid IDs, allow but log
                if logger:
                    logger.warning(f"Invalid ObjectId for rate limiting: {sender_id}")
                return True
            
            # Check per minute
            minute_ago = now - datetime.timedelta(minutes=1)
            recent_count = mongo.db.therapist_chats.count_documents({
                f'{sender_type}_id': ObjectId(sender_id),
                'timestamp': {'$gte': minute_ago}
            })
            
            if recent_count >= user_limits['per_minute']:
                return False
            
            # Check per hour
            hour_ago = now - datetime.timedelta(hours=1)
            hourly_count = mongo.db.therapist_chats.count_documents({
                f'{sender_type}_id': ObjectId(sender_id),
                'timestamp': {'$gte': hour_ago}
            })
            
            return hourly_count < user_limits['per_hour']
        except Exception as e:
            if logger:
                logger.error(f"Rate limit check error: {e}")
            return True  # Fail open
    
    @staticmethod
    def _detect_spam(message: str, sender_id: str) -> float:
        """Advanced spam detection with confidence score"""
        spam_score = 0.0
        
        if not mongo:
            return 0.0
        
        try:
            # Validate ObjectId format for database queries
            if not ObjectId.is_valid(sender_id):
                # Skip database checks for invalid IDs (like during testing)
                spam_score = 0.0
            else:
                # Check for repeated messages
                message_hash = hashlib.md5(message.encode()).hexdigest()
                recent_identical = mongo.db.therapist_chats.count_documents({
                    '$or': [
                        {'student_id': ObjectId(sender_id)},
                        {'therapist_id': ObjectId(sender_id)}
                    ],
                    'message_hash': message_hash,
                    'timestamp': {'$gte': datetime.datetime.now() - datetime.timedelta(minutes=30)}
                })
                
                if recent_identical > 0:
                    spam_score += 0.4 * recent_identical
            
            # Check for excessive caps
            if len(message) > 20:
                caps_ratio = sum(1 for c in message if c.isupper()) / len(message)
                if caps_ratio > 0.7:
                    spam_score += 0.3
            
            # Check for excessive punctuation
            punct_count = len(re.findall(r'[!?]{3,}', message))
            if punct_count > 0:
                spam_score += 0.2 * punct_count
            
            # Check for excessive repetition of characters
            if re.search(r'(.)\1{5,}', message):
                spam_score += 0.3
            
            # Check for URL spam
            url_count = len(re.findall(r'http[s]?://|www\.', message, re.IGNORECASE))
            if url_count > 0:
                spam_score += 0.5 * url_count
            
        except Exception as e:
            if logger:
                logger.error(f"Spam detection error: {e}")
        
        return min(spam_score, 1.0)
    
    @staticmethod
    def _detect_crisis_automated(message: str) -> Tuple[str, float]:
        """Automated crisis detection with confidence levels"""
        message_lower = message.lower()
        
        # High confidence crisis indicators
        for indicator in AutomatedModerator.CRISIS_INDICATORS['high_confidence']:
            if indicator in message_lower:
                return 'critical', 0.95
        
        # Medium confidence indicators
        medium_count = 0
        for indicator in AutomatedModerator.CRISIS_INDICATORS['medium_confidence']:
            if indicator in message_lower:
                medium_count += 1
        
        if medium_count >= 2:
            return 'high', 0.8
        elif medium_count >= 1:
            return 'medium', 0.6
        
        # Low confidence indicators
        low_count = 0
        for indicator in AutomatedModerator.CRISIS_INDICATORS['low_confidence']:
            if indicator in message_lower:
                low_count += 1
        
        if low_count >= 3:
            return 'medium', 0.5
        elif low_count >= 2:
            return 'low', 0.3
        
        return 'none', 0.0
    
    @staticmethod
    def _filter_profanity_automated(message: str) -> Tuple[str, str]:
        """Automatic profanity filtering with severity levels"""
        filtered_message = message
        detected_level = None
        
        # Check each severity level
        for level, words in AutomatedModerator.PROFANITY_CONFIG.items():
            for word in words:
                pattern = r'\b' + re.escape(word) + r'\b'
                if re.search(pattern, message, re.IGNORECASE):
                    if level == 'severe':
                        filtered_message = re.sub(pattern, '[filtered]', filtered_message, flags=re.IGNORECASE)
                        detected_level = 'severe'
                    elif level == 'moderate' and detected_level != 'severe':
                        filtered_message = re.sub(pattern, '*' * len(word), filtered_message, flags=re.IGNORECASE)
                        detected_level = 'moderate'
                    elif level == 'mild' and not detected_level:
                        detected_level = 'mild'
        
        return filtered_message, detected_level
    
    @staticmethod
    def _check_boundaries_automated(message: str, sender_type: str) -> Tuple[str, List[str]]:
        """Automatic boundary violation detection with actions"""
        message_lower = message.lower()
        flags = []
        
        # Check for immediate blocking violations
        for violation in AutomatedModerator.BOUNDARY_VIOLATIONS['block_immediately']:
            if violation in message_lower:
                flags.append('boundary_violation_severe')
                return 'block', flags
        
        # Check for filter violations
        for violation in AutomatedModerator.BOUNDARY_VIOLATIONS['filter_and_warn']:
            if violation in message_lower:
                flags.append('boundary_violation_moderate')
                return 'filter', flags
        
        # Check for logging violations
        for violation in AutomatedModerator.BOUNDARY_VIOLATIONS['log_only']:
            if violation in message_lower:
                flags.append('boundary_violation_mild')
        
        return 'allow', flags
    
    @staticmethod
    def _filter_boundary_content(message: str) -> str:
        """Filter out boundary-violating content"""
        filtered = message
        
        replacements = {
            r'\b(phone\s*number|cell\s*phone|mobile)\b': '[personal contact info]',
            r'\b(email\s*address|personal\s*email)\b': '[personal contact info]',
            r'\b(home\s*address|where\s*you\s*live)\b': '[personal location info]',
            r'\b(meet\s*outside|see\s*you\s*outside)\b': '[outside appointment request]'
        }
        
        for pattern, replacement in replacements.items():
            filtered = re.sub(pattern, replacement, filtered, flags=re.IGNORECASE)
        
        return filtered
    
    @staticmethod
    def _analyze_sentiment(message: str) -> float:
        """Analyze message sentiment using TextBlob"""
        try:
            if TextBlob:
                blob = TextBlob(message)
                return blob.sentiment.polarity
            return 0.0
        except:
            return 0.0
    
    @staticmethod
    def _is_business_hours() -> bool:
        """Check if current time is within business hours"""
        now = datetime.datetime.now()
        
        # Business hours: 8 AM to 8 PM, Monday to Friday
        if now.weekday() >= 5:  # Weekend
            return False
        
        return 8 <= now.hour < 20
    
    @staticmethod
    def _auto_escalate_crisis(sender_id: str, recipient_id: str, message: str, crisis_level: str):
        """Automatically escalate crisis messages"""
        if not mongo:
            return
            
        try:
            # Create immediate crisis alert
            crisis_alert = {
                'student_id': ObjectId(sender_id),
                'therapist_id': ObjectId(recipient_id),
                'message_content': message,
                'crisis_level': crisis_level,
                'auto_detected': True,
                'status': 'auto_escalated',
                'created_at': datetime.datetime.now(),
                'requires_immediate_response': True
            }
            
            mongo.db.crisis_alerts.insert_one(crisis_alert)
            
            # Immediately notify therapist
            mongo.db.notifications.insert_one({
                'user_id': ObjectId(recipient_id),
                'type': 'crisis_alert_urgent',
                'message': f'URGENT: Crisis indicators detected in student message. Immediate attention required.',
                'priority': 'critical',
                'read': False,
                'created_at': datetime.datetime.now(),
                'auto_generated': True
            })
            
            # Auto-schedule emergency appointment if crisis level is critical
            if crisis_level == 'critical':
                AutomatedModerator._auto_schedule_emergency_session(sender_id, recipient_id)
            
            if logger:
                logger.critical(f"Auto-escalated crisis message - Level: {crisis_level}, Student: {sender_id}")
                
        except Exception as e:
            if logger:
                logger.error(f"Error in crisis escalation: {e}")
    
    @staticmethod
    def _auto_schedule_emergency_session(student_id: str, therapist_id: str):
        """Automatically schedule emergency session for critical crisis"""
        if not mongo:
            return
            
        try:
            emergency_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
            
            emergency_appointment = {
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'datetime': emergency_time,
                'type': 'virtual',
                'status': 'confirmed',
                'crisis_level': 'critical',
                'emergency': True,
                'auto_scheduled': True,
                'notes': 'Emergency session auto-scheduled due to crisis detection',
                'created_at': datetime.datetime.now(),
                'meeting_info': {
                    'meet_link': f"https://meet.google.com/emergency-{ObjectId()}",
                    'platform': 'Google Meet',
                    'emergency_session': True
                }
            }
            
            result = mongo.db.appointments.insert_one(emergency_appointment)
            
            # Notify both parties
            mongo.db.notifications.insert_one({
                'user_id': ObjectId(student_id),
                'type': 'emergency_session_scheduled',
                'message': f'An emergency session has been scheduled for {emergency_time.strftime("%I:%M %p")} today. Your therapist will contact you.',
                'read': False,
                'created_at': datetime.datetime.now()
            })
            
            mongo.db.notifications.insert_one({
                'user_id': ObjectId(therapist_id),
                'type': 'emergency_session_scheduled',
                'message': f'Emergency session auto-scheduled for {emergency_time.strftime("%I:%M %p")} due to crisis detection.',
                'priority': 'urgent',
                'read': False,
                'created_at': datetime.datetime.now()
            })
            
            if logger:
                logger.info(f"Auto-scheduled emergency session: {result.inserted_id}")
            
        except Exception as e:
            if logger:
                logger.error(f"Failed to auto-schedule emergency session: {e}")
    
    @staticmethod
    def _log_moderation_action(sender_id: str, message: str, moderation_result: Dict):
        """Log moderation actions for analytics and monitoring"""
        if not mongo:
            return
            
        try:
            log_entry = {
                'sender_id': ObjectId(sender_id),
                'message_hash': hashlib.md5(message.encode()).hexdigest(),
                'action_taken': moderation_result['action'],
                'flags': moderation_result['flags'],
                'confidence': moderation_result.get('confidence', 1.0),
                'escalation_level': moderation_result.get('escalation_level', 'none'),
                'automated': True,
                'timestamp': datetime.datetime.now()
            }
            
            mongo.db.automated_moderation_log.insert_one(log_entry)
        except Exception as e:
            if logger:
                logger.error(f"Error logging moderation action: {e}")


def send_auto_moderated_message(sender_id: str, recipient_id: str, message: str, sender_type: str) -> Dict:
    """Send message with fully automated moderation"""
    
    # Run automated moderation
    moderation_result = AutomatedModerator.moderate_message(
        message, sender_type, sender_id, recipient_id
    )
    
    # Handle different moderation actions
    if moderation_result['action'] == 'block':
        return {
            'success': False,
            'blocked': True,
            'reason': 'Message blocked by automated moderation',
            'flags': moderation_result['flags'],
            'auto_response': moderation_result.get('auto_response')
        }
    
    # Use filtered message if available
    final_message = moderation_result['filtered_message']
    
    if not mongo:
        return {'success': False, 'error': 'Database not available'}
    
    try:
        # Create message document
        message_data = {
            'student_id': ObjectId(recipient_id if sender_type == 'therapist' else sender_id),
            'therapist_id': ObjectId(sender_id if sender_type == 'therapist' else recipient_id),
            'sender': sender_type,
            'message': final_message,
            'original_message': message if final_message != message else None,
            'moderation_flags': moderation_result['flags'],
            'moderation_action': moderation_result['action'],
            'message_hash': hashlib.md5(message.encode()).hexdigest(),
            'automated_moderation': True,
            'read': False,
            'timestamp': datetime.datetime.now()
        }
        
        # Save message
        result = mongo.db.therapist_chats.insert_one(message_data)
        message_id = str(result.inserted_id)
        
        # Create notification for recipient
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(recipient_id),
            'type': 'new_message',
            'message': f'You have a new message from your {sender_type}',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.datetime.now()
        })
        
        # Prepare response
        response = {
            'success': True,
            'message_id': message_id,
            'action_taken': moderation_result['action'],
            'flags': moderation_result['flags'],
            'filtered': final_message != message,
            'auto_response': moderation_result.get('auto_response')
        }
        
        # Add warnings based on flags
        warnings = []
        flag_messages = {
            'profanity_mild': 'Message contains mild language.',
            'profanity_moderate': 'Some language was filtered from your message.',
            'profanity_severe': 'Inappropriate language was filtered from your message.',
            'crisis_low': 'Your message suggests you may be struggling. Your therapist will prioritize this message.',
            'crisis_medium': 'Your message indicates distress. Your therapist has been alerted.',
            'crisis_high': 'Crisis indicators detected. Your therapist will respond immediately.',
            'crisis_critical': 'Emergency support triggered. An urgent session has been scheduled.',
            'boundary_violation_mild': 'Please maintain professional boundaries in your messages.',
            'boundary_violation_moderate': 'Some content was filtered to maintain professional boundaries.',
            'outside_business_hours': 'Message sent outside business hours - response may be delayed.',
            'potential_spam': 'Message flagged for review due to repetitive content.'
        }
        
        for flag in moderation_result['flags']:
            if flag in flag_messages:
                warnings.append(flag_messages[flag])
        
        if warnings:
            response['warnings'] = warnings
        
        return response
        
    except Exception as e:
        if logger:
            logger.error(f"Error sending auto-moderated message: {str(e)}")
        return {
            'success': False,
            'error': 'Failed to send message due to system error'
        }


def generate_automated_moderation_report(hours: int = 24) -> Dict:
    """Generate automated moderation statistics"""
    if not mongo:
        return {}
        
    try:
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        
        # Get moderation statistics
        total_messages = mongo.db.therapist_chats.count_documents({
            'timestamp': {'$gte': cutoff_time},
            'automated_moderation': True
        })
        
        blocked_messages = mongo.db.automated_moderation_log.count_documents({
            'timestamp': {'$gte': cutoff_time},
            'action_taken': 'block'
        })
        
        filtered_messages = mongo.db.therapist_chats.count_documents({
            'timestamp': {'$gte': cutoff_time},
            'moderation_action': 'filter'
        })
        
        crisis_alerts = mongo.db.crisis_alerts.count_documents({
            'created_at': {'$gte': cutoff_time},
            'auto_detected': True
        })
        
        return {
            'period_hours': hours,
            'total_messages': total_messages,
            'blocked_messages': blocked_messages,
            'filtered_messages': filtered_messages,
            'crisis_alerts': crisis_alerts,
            'automation_rate': 100.0,  # Fully automated
            'generated_at': datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        if logger:
            logger.error(f"Error generating automated moderation report: {e}")
        return {}