# wellbeing/utils/mental_health.py 

from datetime import datetime, timedelta
from bson.objectid import ObjectId
from wellbeing import mongo

def detect_crisis_level(intake_data):
    """
    Simple crisis detection based on keywords and severity
    Returns: 'low', 'medium', or 'high'
    """
    description = intake_data.get('description', '').lower()
    severity = intake_data.get('severity', 0)
    crisis_indicators = intake_data.get('crisis_indicators', [])
    
    # High-risk keywords
    danger_words = ['suicide', 'kill myself', 'end my life', 'hurt myself', 'self-harm']
    
    # Check for immediate danger
    has_danger_words = any(word in description for word in danger_words)
    has_crisis_indicators = 'suicidal_thoughts' in crisis_indicators or 'harm_others' in crisis_indicators
    
    if severity >= 9 or has_danger_words or has_crisis_indicators:
        return {'level': 'high', 'keywords': [w for w in danger_words if w in description]}
    elif severity >= 7:
        return {'level': 'medium', 'keywords': []}
    else:
        return {'level': 'low', 'keywords': []}

def assign_therapist_immediately(intake_data):
    """
    Find and assign therapist right away
    Returns: therapist document or None
    """
    concern = intake_data.get('primary_concern')
    gender_pref = intake_data.get('therapist_gender', 'no_preference')
    
    # Step 1: Find therapists who specialize in the student's concern
    specialization_map = {
        'anxiety': 'anxiety',
        'depression': 'depression', 
        'academic_stress': 'academic_stress',
        'relationships': 'relationship_counseling',
        'trauma': 'trauma_therapy'
    }
    
    needed_specialization = specialization_map.get(concern, 'general_counseling')
    
    # Step 2: Build search criteria
    search_criteria = {
        'status': 'active',
        'specializations': needed_specialization
    }
    
    # Add gender preference if specified
    if gender_pref != 'no_preference':
        search_criteria['gender'] = gender_pref
    
    # Step 3: Find available therapists
    available_therapists = list(mongo.db.therapists.find(search_criteria))
    
    # Step 4: If no specialists available, find any therapist
    if not available_therapists:
        available_therapists = list(mongo.db.therapists.find({'status': 'active'}))
    
    # Step 5: Pick therapist with lowest caseload
    if available_therapists:
        best_therapist = min(available_therapists, 
                           key=lambda t: t.get('current_students', 0))
        return best_therapist
    
    return None

def create_immediate_appointment(student_id, therapist, crisis_level):
    """
    Create appointment suggestion right away
    """
    # Crisis cases get priority scheduling
    if crisis_level == 'high':
        priority = 'urgent'
        timeframe = 'within 4 hours'
    else:
        priority = 'normal'  
        timeframe = 'within 24 hours'
    
    appointment = {
        'student_id': ObjectId(student_id),
        'therapist_id': therapist['_id'],
        'status': 'suggested',
        'priority': priority,
        'timeframe': timeframe,
        'notes': f'Initial consultation - {priority} priority',
        'created_at': datetime.now()
    }
    
    # Save to database
    result = mongo.db.appointments.insert_one(appointment)
    return result.inserted_id

def update_student_with_therapist(student_id, therapist_id, crisis_level):
    """
    Update student record with assigned therapist
    """
    status = 'crisis' if crisis_level == 'high' else 'active'
    
    mongo.db.students.update_one(
        {'_id': ObjectId(student_id)},
        {
            '$set': {
                'assigned_therapist_id': therapist_id,
                'assignment_date': datetime.now(),
                'status': status,
                'intake_completed': True
            }
        }
    )

def update_therapist_caseload(therapist_id):
    """
    Increase therapist's current student count
    """
    mongo.db.therapists.update_one(
        {'_id': therapist_id},
        {'$inc': {'current_students': 1}}
    )

def send_crisis_alert(student_id, therapist_id):
    """
    Send alert for high-risk students
    """
    alert = {
        'type': 'crisis_alert',
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'message': 'High-risk student requires immediate attention',
        'created_at': datetime.now(),
        'status': 'active'
    }
    
    mongo.db.alerts.insert_one(alert)

# Simple validation function
def validate_intake_form(form_data):
    """
    Basic validation - check required fields
    """
    required_fields = ['primary_concern', 'description', 'severity', 'emergency_contact_name']
    missing_fields = []
    
    for field in required_fields:
        if not form_data.get(field):
            missing_fields.append(field.replace('_', ' ').title())
    
    # Check severity is a number between 1-10
    try:
        severity = int(form_data.get('severity', 0))
        if severity < 1 or severity > 10:
            missing_fields.append('Severity must be between 1-10')
    except:
        missing_fields.append('Severity must be a valid number')
    
    return len(missing_fields) == 0, missing_fields