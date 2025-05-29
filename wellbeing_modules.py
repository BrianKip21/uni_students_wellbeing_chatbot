# =============================================================================
# WELLBEING ASSISTANT - MODULAR SYSTEM ARCHITECTURE
# =============================================================================

import re
import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import hashlib
import secrets

# =============================================================================
# 1. LICENSE VALIDATION SYSTEM
# =============================================================================

class LicenseValidator:
    """Handles therapist license validation with pattern-based generation for development"""
    
    # License patterns by region/type
    LICENSE_PATTERNS = {
        'kenya_clinical': r'^KE-CL-\d{6}$',  # KE-CL-123456
        'kenya_counseling': r'^KE-CO-\d{6}$',  # KE-CO-123456
        'international': r'^INT-\d{8}$',      # INT-12345678
        'provisional': r'^PROV-\d{4}-[A-Z]{2}$'  # PROV-2024-KE
    }
    
    @classmethod
    def generate_license(cls, license_type: str = 'kenya_clinical') -> str:
        """Generate valid license number for development/testing"""
        if license_type == 'kenya_clinical':
            return f"KE-CL-{random.randint(100000, 999999)}"
        elif license_type == 'kenya_counseling':
            return f"KE-CO-{random.randint(100000, 999999)}"
        elif license_type == 'international':
            return f"INT-{random.randint(10000000, 99999999)}"
        elif license_type == 'provisional':
            year = datetime.now().year
            code = ''.join(random.choices(string.ascii_uppercase, k=2))
            return f"PROV-{year}-{code}"
        else:
            return f"KE-CL-{random.randint(100000, 999999)}"
    
    @classmethod
    def validate_license(cls, license_number: str) -> Dict[str, any]:
        """Validate license number and return details"""
        license_number = license_number.strip().upper()
        
        for license_type, pattern in cls.LICENSE_PATTERNS.items():
            if re.match(pattern, license_number):
                return {
                    'valid': True,
                    'type': license_type,
                    'license_number': license_number,
                    'issued_date': datetime.now() - timedelta(days=random.randint(30, 1000)),
                    'expires_date': datetime.now() + timedelta(days=random.randint(365, 1095)),
                    'status': 'active'
                }
        
        return {
            'valid': False,
            'error': 'Invalid license format',
            'accepted_formats': list(cls.LICENSE_PATTERNS.keys())
        }

# =============================================================================
# 2. CRISIS DETECTION SYSTEM
# =============================================================================

@dataclass
class CrisisAssessment:
    level: str  # 'low', 'medium', 'high', 'critical'
    risk_factors: List[str]
    recommended_action: str
    urgency_score: int  # 1-10
    requires_immediate_attention: bool

class CrisisDetector:
    """Enhanced crisis detection with keyword analysis and severity scoring"""
    
    CRISIS_KEYWORDS = {
        'critical': [
            'suicide', 'kill myself', 'end my life', 'want to die', 
            'not worth living', 'better off dead', 'end it all'
        ],
        'high': [
            'hopeless', 'worthless', 'hurt myself', 'self-harm', 
            'cutting', 'can\'t go on', 'overwhelming', 'trapped'
        ],
        'medium': [
            'depressed', 'anxious', 'stressed', 'exhausted',
            'struggling', 'difficult', 'hard to cope'
        ]
    }
    
    CRISIS_INDICATORS = {
        'suicidal_thoughts': 10,
        'self_harm': 9,
        'harm_others': 10,
        'substance_crisis': 7,
        'eating_crisis': 6,
        'severe_depression': 8,
        'panic_attacks': 6
    }
    
    @classmethod
    def assess_crisis_level(cls, assessment_data: Dict) -> CrisisAssessment:
        """Comprehensive crisis assessment"""
        risk_factors = []
        urgency_score = 0
        
        # Check severity rating (1-10)
        severity = int(assessment_data.get('severity', 0))
        urgency_score += severity
        
        # Check crisis indicators from form
        crisis_indicators = assessment_data.get('crisis_indicators', [])
        for indicator in crisis_indicators:
            if indicator in cls.CRISIS_INDICATORS:
                urgency_score += cls.CRISIS_INDICATORS[indicator]
                risk_factors.append(indicator.replace('_', ' ').title())
        
        # Analyze description text
        description = assessment_data.get('description', '').lower()
        for level, keywords in cls.CRISIS_KEYWORDS.items():
            for keyword in keywords:
                if keyword in description:
                    if level == 'critical':
                        urgency_score += 8
                    elif level == 'high':
                        urgency_score += 5
                    elif level == 'medium':
                        urgency_score += 2
                    risk_factors.append(f"Language indicating {level} risk")
                    break
        
        # Duration factor
        duration = assessment_data.get('duration', '')
        if duration in ['less_than_week', '1-2_weeks']:
            urgency_score += 2  # Recent onset can indicate crisis
        
        # Determine crisis level
        if urgency_score >= 15:
            level = 'critical'
            action = 'Immediate intervention required - contact emergency services'
            immediate = True
        elif urgency_score >= 10:
            level = 'high'
            action = 'Priority appointment within 24 hours'
            immediate = True
        elif urgency_score >= 6:
            level = 'medium'
            action = 'Schedule appointment within 1 week'
            immediate = False
        else:
            level = 'low'
            action = 'Regular appointment scheduling'
            immediate = False
        
        return CrisisAssessment(
            level=level,
            risk_factors=risk_factors,
            recommended_action=action,
            urgency_score=urgency_score,
            requires_immediate_attention=immediate
        )

# =============================================================================
# 3. THERAPIST MATCHING SYSTEM
# =============================================================================

class TherapistMatcher:
    """Smart therapist matching based on specializations, availability, and crisis level"""
    
    @classmethod
    def find_best_match(cls, student_data: Dict, crisis_level: str) -> Optional[Dict]:
        """Find the best therapist match for student needs"""
        from app import mongo  # Import here to avoid circular imports
        
        # Build matching criteria
        primary_concern = student_data.get('primary_concern')
        gender_preference = student_data.get('therapist_gender', 'no_preference')
        appointment_type = student_data.get('appointment_type', 'virtual')
        
        # Base query
        query = {
            'status': 'active',
            'current_students': {'$lt': '$max_students'}
        }
        
        # Add specialization filter
        if primary_concern and primary_concern != 'other':
            query['specializations'] = {'$in': [primary_concern]}
        
        # Add gender preference
        if gender_preference != 'no_preference':
            query['gender'] = gender_preference
        
        # Crisis-specific filters
        if crisis_level in ['high', 'critical']:
            query['emergency_hours'] = True
        
        # Get potential matches
        therapists = list(mongo.db.therapists.find(query))
        
        if not therapists:
            # Fallback: Remove strict filters for emergency cases
            if crisis_level in ['high', 'critical']:
                fallback_query = {
                    'status': 'active',
                    'current_students': {'$lt': '$max_students'},
                    'emergency_hours': True
                }
                therapists = list(mongo.db.therapists.find(fallback_query))
        
        if not therapists:
            return None
        
        # Score and rank therapists
        scored_therapists = []
        for therapist in therapists:
            score = cls._calculate_match_score(therapist, student_data, crisis_level)
            scored_therapists.append((score, therapist))
        
        # Sort by score (highest first)
        scored_therapists.sort(key=lambda x: x[0], reverse=True)
        
        return scored_therapists[0][1] if scored_therapists else None
    
    @classmethod
    def _calculate_match_score(cls, therapist: Dict, student_data: Dict, crisis_level: str) -> int:
        """Calculate matching score for therapist-student pair"""
        score = 0
        
        # Specialization match
        primary_concern = student_data.get('primary_concern')
        if primary_concern in therapist.get('specializations', []):
            score += 10
        
        # Crisis handling capability
        if crisis_level in ['high', 'critical'] and therapist.get('emergency_hours'):
            score += 15
        
        # Workload factor (prefer less busy therapists)
        current_load = therapist.get('current_students', 0)
        max_students = therapist.get('max_students', 20)
        if current_load < max_students * 0.7:  # Less than 70% capacity
            score += 5
        
        # Experience factor
        total_sessions = therapist.get('total_sessions', 0)
        if total_sessions > 100:
            score += 3
        
        # Rating factor
        rating = therapist.get('rating', 0)
        if rating >= 4.5:
            score += 5
        elif rating >= 4.0:
            score += 3
        
        # Gender preference match
        gender_pref = student_data.get('therapist_gender', 'no_preference')
        if gender_pref != 'no_preference' and therapist.get('gender') == gender_pref:
            score += 5
        
        return score

# =============================================================================
# 4. GOOGLE MEET INTEGRATION
# =============================================================================

class GoogleMeetManager:
    """Handles Google Meet link generation and management"""
    
    @classmethod
    def create_meeting(cls, appointment_data: Dict) -> Dict:
        """Create Google Meet link for appointment"""
        # In production, integrate with Google Calendar API
        # For development, generate mock meeting data
        
        meeting_id = cls._generate_meeting_id()
        meet_link = f"https://meet.google.com/{meeting_id}"
        
        # Generate dial-in info
        dial_in = f"+254-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        pin = f"{random.randint(100000, 999999)}"
        
        return {
            'meet_link': meet_link,
            'meeting_id': meeting_id,
            'dial_in': dial_in,
            'dial_in_pin': pin,
            'host_key': secrets.token_urlsafe(16),
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=2)).isoformat()
        }
    
    @classmethod
    def _generate_meeting_id(cls) -> str:
        """Generate Google Meet-style meeting ID"""
        # Format: xxx-xxxx-xxx
        part1 = ''.join(random.choices(string.ascii_lowercase, k=3))
        part2 = ''.join(random.choices(string.ascii_lowercase, k=4))
        part3 = ''.join(random.choices(string.ascii_lowercase, k=3))
        return f"{part1}-{part2}-{part3}"

# =============================================================================
# 5. APPOINTMENT SCHEDULING SYSTEM
# =============================================================================

class AppointmentScheduler:
    """Intelligent appointment scheduling based on availability and urgency"""
    
    @classmethod
    def schedule_appointment(cls, student_id: str, therapist: Dict, 
                           crisis_level: str, appointment_type: str = 'virtual') -> Tuple[Optional[str], Optional[Dict]]:
        """Schedule appointment automatically"""
        from app import mongo
        from bson import ObjectId
        
        # Get available slots
        available_slots = cls._get_available_slots(therapist, crisis_level)
        
        if not available_slots:
            return None, None
        
        # Select best slot based on urgency
        selected_slot = cls._select_optimal_slot(available_slots, crisis_level)
        
        # Create meeting info
        meeting_info = GoogleMeetManager.create_meeting({
            'student_id': student_id,
            'therapist_id': str(therapist['_id']),
            'appointment_type': appointment_type
        })
        
        # Create appointment document
        appointment = {
            'student_id': ObjectId(student_id),
            'therapist_id': therapist['_id'],
            'datetime': selected_slot['datetime'],
            'formatted_time': selected_slot['formatted'],
            'type': appointment_type,
            'status': 'confirmed',
            'crisis_level': crisis_level,
            'meeting_info': meeting_info,
            'created_at': datetime.now(),
            'notes': f"Auto-scheduled due to {crisis_level} priority"
        }
        
        # Save to database
        result = mongo.db.appointments.insert_one(appointment)
        appointment['_id'] = result.inserted_id
        
        return str(result.inserted_id), appointment
    
    @classmethod
    def _get_available_slots(cls, therapist: Dict, crisis_level: str) -> List[Dict]:
        """Get available appointment slots for therapist"""
        slots = []
        now = datetime.now()
        
        # For crisis cases, look at next 24-48 hours
        if crisis_level in ['high', 'critical']:
            days_ahead = 2
            start_hour = now.hour + 1  # Can schedule within hours
        else:
            days_ahead = 14  # Regular scheduling up to 2 weeks
            start_hour = 9  # Business hours only
        
        availability = therapist.get('availability', {})
        
        for day_offset in range(days_ahead):
            check_date = now + timedelta(days=day_offset)
            day_name = check_date.strftime('%A').lower()
            
            if day_name in availability:
                day_availability = availability[day_name]
                start_time = datetime.strptime(day_availability['start'], '%H:%M').time()
                end_time = datetime.strptime(day_availability['end'], '%H:%M').time()
                
                # Generate hourly slots
                current_time = datetime.combine(check_date.date(), start_time)
                end_datetime = datetime.combine(check_date.date(), end_time)
                
                while current_time < end_datetime:
                    if current_time > now:  # Only future slots
                        # Check if slot is available (not booked)
                        if cls._is_slot_available(therapist['_id'], current_time):
                            slots.append({
                                'datetime': current_time,
                                'formatted': current_time.strftime('%A, %B %d at %I:%M %p'),
                                'day_name': day_name.title(),
                                'date': current_time.strftime('%Y-%m-%d'),
                                'time': current_time.strftime('%I:%M %p')
                            })
                    
                    current_time += timedelta(hours=1)
        
        return slots[:10]  # Limit to first 10 available slots
    
    @classmethod
    def _is_slot_available(cls, therapist_id: str, slot_datetime: datetime) -> bool:
        """Check if appointment slot is available"""
        from app import mongo
        
        # Check for existing appointments in this time slot
        existing = mongo.db.appointments.find_one({
            'therapist_id': therapist_id,
            'datetime': slot_datetime,
            'status': {'$in': ['confirmed', 'suggested']}
        })
        
        return existing is None
    
    @classmethod
    def _select_optimal_slot(cls, slots: List[Dict], crisis_level: str) -> Dict:
        """Select the best available slot based on urgency"""
        if crisis_level in ['high', 'critical']:
            # Take earliest available slot
            return min(slots, key=lambda x: x['datetime'])
        else:
            # Prefer slots during business hours (9 AM - 5 PM)
            business_hours_slots = [
                slot for slot in slots 
                if 9 <= slot['datetime'].hour <= 17
            ]
            
            if business_hours_slots:
                return business_hours_slots[0]
            else:
                return slots[0]

# =============================================================================
# 6. NOTIFICATION SYSTEM
# =============================================================================

class NotificationManager:
    """Handle email notifications and SMS alerts"""
    
    @classmethod
    def send_appointment_confirmation(cls, student_email: str, appointment: Dict, therapist: Dict):
        """Send appointment confirmation email"""
        # In production, integrate with email service (SendGrid, etc.)
        print(f"📧 Sending confirmation to {student_email}")
        print(f"Appointment: {appointment['formatted_time']}")
        print(f"Therapist: {therapist['name']}")
        print(f"Meeting Link: {appointment['meeting_info']['meet_link']}")
    
    @classmethod
    def send_crisis_alert(cls, crisis_assessment: CrisisAssessment, student_data: Dict):
        """Send crisis alerts to appropriate personnel"""
        if crisis_assessment.level == 'critical':
            print(f"🚨 CRITICAL ALERT: Student requires immediate intervention")
            print(f"Risk factors: {', '.join(crisis_assessment.risk_factors)}")
            # In production: Send to crisis team, campus security, etc.

# =============================================================================
# 7. MAIN WORKFLOW ORCHESTRATOR
# =============================================================================

class WellbeingAssistant:
    """Main orchestrator for the wellbeing assistant workflow"""
    
    @classmethod
    def process_student_intake(cls, intake_data: Dict) -> Dict:
        """Complete intake processing workflow"""
        try:
            # Step 1: Crisis Assessment
            crisis_assessment = CrisisDetector.assess_crisis_level(intake_data)
            
            # Step 2: Send crisis alerts if needed
            if crisis_assessment.requires_immediate_attention:
                NotificationManager.send_crisis_alert(crisis_assessment, intake_data)
            
            # Step 3: Find matching therapist
            therapist = TherapistMatcher.find_best_match(intake_data, crisis_assessment.level)
            
            if not therapist:
                return {
                    'success': False,
                    'error': 'No available therapist found',
                    'crisis_level': crisis_assessment.level
                }
            
            # Step 4: Schedule appointment
            appointment_id, appointment = AppointmentScheduler.schedule_appointment(
                intake_data['student_id'],
                therapist,
                crisis_assessment.level,
                intake_data.get('appointment_type', 'virtual')
            )
            
            if not appointment_id:
                return {
                    'success': False,
                    'error': 'Failed to schedule appointment',
                    'therapist': therapist,
                    'crisis_level': crisis_assessment.level
                }
            
            # Step 5: Send confirmations
            student_email = intake_data.get('student_email', 'student@university.edu')
            NotificationManager.send_appointment_confirmation(student_email, appointment, therapist)
            
            return {
                'success': True,
                'appointment_id': appointment_id,
                'appointment': appointment,
                'therapist': therapist,
                'crisis_assessment': crisis_assessment,
                'meeting_link': appointment['meeting_info']['meet_link']
            }
            
        except Exception as e:
            print(f"Error in intake processing: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'crisis_level': 'unknown'
            }

# =============================================================================
# 8. TESTING UTILITIES
# =============================================================================

class TestDataGenerator:
    """Generate test data for development"""
    
    @classmethod
    def create_mock_therapist(cls, license_type: str = 'kenya_clinical') -> Dict:
        """Create mock therapist for testing"""
        license_number = LicenseValidator.generate_license(license_type)
        
        return {
            'name': f"Dr. {random.choice(['Sarah', 'Michael', 'Grace', 'David'])} {random.choice(['Smith', 'Johnson', 'Wanjiku', 'Kariuki'])}",
            'email': f"therapist{random.randint(1000, 9999)}@university.edu",
            'license_number': license_number,
            'specializations': random.sample(['anxiety', 'depression', 'academic_stress', 'trauma_therapy'], 2),
            'gender': random.choice(['male', 'female']),
            'max_students': random.randint(15, 30),
            'current_students': random.randint(5, 15),
            'emergency_hours': random.choice([True, False]),
            'rating': round(random.uniform(3.5, 5.0), 1),
            'availability': {
                'monday': {'start': '09:00', 'end': '17:00'},
                'wednesday': {'start': '10:00', 'end': '18:00'},
                'friday': {'start': '08:00', 'end': '16:00'}
            },
            'status': 'active',
            'created_at': datetime.now()
        }
    
    @classmethod
    def create_mock_student_intake(cls) -> Dict:
        """Create mock student intake for testing"""
        concerns = ['anxiety', 'depression', 'academic_stress', 'relationships']
        
        return {
            'student_id': f"student_{random.randint(1000, 9999)}",
            'student_email': f"student{random.randint(1000, 9999)}@student.university.edu",
            'primary_concern': random.choice(concerns),
            'description': "I've been feeling overwhelmed with coursework and experiencing anxiety about my future.",
            'severity': random.randint(4, 8),
            'duration': random.choice(['1_month', '2-3_months', '6_months']),
            'previous_therapy': 'never',
            'therapist_gender': 'no_preference',
            'appointment_type': 'virtual',
            'crisis_indicators': [],
            'emergency_contact_name': 'Jane Doe',
            'emergency_contact_phone': '+254712345678',
            'emergency_contact_relationship': 'Parent'
        }

# =============================================================================
# USAGE EXAMPLE
# =============================================================================
if __name__ == "__main__":
    # Test the system
    print("🧪 Testing Wellbeing Assistant System")
    print("=" * 50)
    
    # Generate test data
    mock_intake = TestDataGenerator.create_mock_student_intake()
    print(f"📝 Mock Student Intake: {mock_intake['primary_concern']} (Severity: {mock_intake['severity']})")
    
    # Test license generation
    license_num = LicenseValidator.generate_license('kenya_clinical')
    validation = LicenseValidator.validate_license(license_num)
    print(f"🏥 Generated License: {license_num} ({'Valid' if validation['valid'] else 'Invalid'})")
    
    # Test crisis detection
    crisis = CrisisDetector.assess_crisis_level(mock_intake)
    print(f"⚠️  Crisis Level: {crisis.level} (Score: {crisis.urgency_score})")
    
    # Test Google Meet generation
    meeting = GoogleMeetManager.create_meeting({'test': 'data'})
    print(f"📹 Generated Meeting: {meeting['meet_link']}")
    
    print("\n✅ System modules tested successfully!")
    print("Ready for integration into Flask application.")