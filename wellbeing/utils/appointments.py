"""
Appointment utility functions for the wellbeing chatbot system
"""
from datetime import datetime
from bson import ObjectId


def has_active_appointment(user_id, mongo_db):
    """
    Check if user has any active (future) appointments
    Returns: (has_appointment, appointment_details)
    """
    current_time = datetime.now()
    
    # Find any future appointments for this user
    active_appointment = mongo_db.appointments.find_one({
        'student_id': ObjectId(user_id),
        'datetime': {'$gt': current_time},
        'status': {'$nin': ['cancelled', 'completed']}  # Exclude cancelled/completed
    })
    
    if active_appointment:
        return True, active_appointment
    return False, None


def can_schedule_appointment(user_id, mongo_db):
    """
    Check if user can schedule a new appointment
    Returns: (can_schedule, reason)
    """
    has_active, existing_appointment = has_active_appointment(user_id, mongo_db)
    
    if has_active:
        formatted_time = existing_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
        reason = f"You already have an appointment scheduled for {formatted_time}. Please complete or cancel it before scheduling a new one."
        return False, reason
    
    return True, "You can schedule a new appointment."


def can_schedule_or_reschedule(user_id, mongo_db):
    """
    Check if user can schedule, with option to reschedule existing
    Returns: (can_schedule, has_existing, existing_appointment, message)
    """
    has_active, existing_appointment = has_active_appointment(user_id, mongo_db)
    
    if has_active:
        formatted_time = existing_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
        message = f"You have an appointment on {formatted_time}. You can reschedule by cancelling it first."
        return False, True, existing_appointment, message
    
    return True, False, None, "You can schedule a new appointment."


def can_schedule_emergency(user_id, crisis_level, mongo_db):
    """
    Check if user can schedule with emergency override for crisis situations
    Returns: (can_schedule, reason)
    """
    if crisis_level == 'crisis':
        return True, "Emergency appointment allowed for crisis situation."
    
    return can_schedule_appointment(user_id, mongo_db)


def can_schedule_with_grace_period(user_id, mongo_db, grace_hours=24):
    """
    Check if user can schedule with grace period (can reschedule if appointment is X hours away)
    Returns: (can_schedule, reason)
    """
    has_active, existing_appointment = has_active_appointment(user_id, mongo_db)
    
    if has_active:
        hours_until = (existing_appointment['datetime'] - datetime.now()).total_seconds() / 3600
        
        if hours_until > grace_hours:
            formatted_time = existing_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
            reason = f"You can reschedule since your appointment on {formatted_time} is more than {grace_hours} hours away."
            return True, reason
        else:
            formatted_time = existing_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
            reason = f"You have an appointment on {formatted_time}. You cannot reschedule within {grace_hours} hours of the appointment."
            return False, reason
    
    return True, "You can schedule a new appointment."


def is_zoom_integrated(zoom_meeting_id):
    """
    Check if zoom meeting ID represents a real Zoom integration
    Handles both string and integer zoom_meeting_id values
    """
    if not zoom_meeting_id:
        return False
    return not str(zoom_meeting_id).startswith('fallback')


def get_user_appointment_status(user_id, mongo_db):
    """
    Get comprehensive appointment status for a user
    Returns: dict with appointment information
    """
    has_active, active_appointment = has_active_appointment(user_id, mongo_db)
    
    status = {
        'has_active_appointment': has_active,
        'active_appointment': active_appointment,
        'can_schedule': not has_active,
        'total_appointments': 0,
        'completed_appointments': 0,
        'upcoming_appointments': 0
    }
    
    # Get appointment statistics
    all_appointments = list(mongo_db.appointments.find({'student_id': ObjectId(user_id)}))
    status['total_appointments'] = len(all_appointments)
    
    current_time = datetime.now()
    for apt in all_appointments:
        if apt.get('status') == 'completed' or apt.get('datetime') and apt['datetime'] < current_time:
            status['completed_appointments'] += 1
        elif apt.get('datetime') and apt['datetime'] > current_time and apt.get('status') not in ['cancelled']:
            status['upcoming_appointments'] += 1
    
    if active_appointment:
        # Add formatted time and countdown
        status['active_appointment']['formatted_time'] = active_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
        time_diff = (active_appointment['datetime'] - current_time).total_seconds() / 60
        status['active_appointment']['time_diff_minutes'] = time_diff
        
        # Add Zoom integration status
        zoom_id = active_appointment.get('zoom_meeting_id', '')
        status['active_appointment']['zoom_integrated'] = is_zoom_integrated(zoom_id)
    
    return status