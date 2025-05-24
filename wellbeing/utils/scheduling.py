# wellbeing/utils/scheduling.py - Advanced Scheduling System

from datetime import datetime, timedelta
from bson.objectid import ObjectId
from wellbeing import mongo
import uuid
import json

def get_therapist_available_slots(therapist, days_ahead=7, crisis_level='normal'):
    """
    Get actual available time slots for a therapist
    Returns real appointment times, not just suggestions
    """
    availability = therapist.get('availability', {})
    if not availability:
        return generate_default_slots(crisis_level)
    
    available_slots = []
    base_date = datetime.now()
    
    # Crisis cases get immediate slots (next 2 days)
    if crisis_level == 'high':
        days_ahead = 2
        priority_hours = [9, 11, 14, 16]  # Priority time slots
    else:
        priority_hours = None
    
    for i in range(1, days_ahead + 1):
        check_date = base_date + timedelta(days=i)
        weekday = check_date.strftime('%A').lower()
        
        if weekday in availability:
            day_slots = availability[weekday]
            
            for time_range in day_slots:
                # Parse time range (e.g., "09:00-17:00")
                if '-' in time_range:
                    start_time, end_time = time_range.split('-')
                    slots = generate_time_slots(check_date, start_time, end_time, priority_hours)
                    available_slots.extend(slots)
    
    # Filter out already booked slots
    available_slots = filter_booked_slots(therapist['_id'], available_slots)
    
    # Return top 6 slots for selection
    return available_slots[:6]

def generate_time_slots(date, start_time, end_time, priority_hours=None):
    """
    Generate specific appointment slots for a day
    """
    slots = []
    start_hour = int(start_time.split(':')[0])
    end_hour = int(end_time.split(':')[0])
    
    # Generate hourly slots
    for hour in range(start_hour, end_hour):
        if priority_hours and hour not in priority_hours:
            continue
            
        for minute in [0, 30]:  # 30-minute intervals
            if hour == end_hour - 1 and minute == 30:
                break  # Don't go past end time
                
            slot_time = datetime.combine(date.date(), datetime.min.time().replace(hour=hour, minute=minute))
            
            # Only future slots
            if slot_time > datetime.now():
                slots.append({
                    'datetime': slot_time,
                    'date': slot_time.strftime('%Y-%m-%d'),
                    'time': slot_time.strftime('%I:%M %p'),
                    'day_name': slot_time.strftime('%A'),
                    'formatted': slot_time.strftime('%A, %B %d at %I:%M %p')
                })
    
    return slots

def filter_booked_slots(therapist_id, slots):
    """
    Remove slots that are already booked
    """
    # Get existing appointments for this therapist
    existing_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'status': {'$in': ['confirmed', 'scheduled']},
        'datetime': {'$gte': datetime.now()}
    }))
    
    booked_times = [apt.get('datetime') for apt in existing_appointments if apt.get('datetime')]
    
    # Filter out booked slots
    available_slots = []
    for slot in slots:
        slot_datetime = slot['datetime']
        
        # Check if this slot conflicts with existing appointments
        is_available = True
        for booked_time in booked_times:
            if abs((slot_datetime - booked_time).total_seconds()) < 3600:  # 1 hour buffer
                is_available = False
                break
        
        if is_available:
            available_slots.append(slot)
    
    return available_slots

def generate_default_slots(crisis_level='normal'):
    """
    Generate default slots when therapist availability is not specified
    """
    slots = []
    base_date = datetime.now()
    days_ahead = 2 if crisis_level == 'high' else 5
    
    for i in range(1, days_ahead + 1):
        check_date = base_date + timedelta(days=i)
        
        # Skip weekends for default slots
        if check_date.weekday() >= 5:
            continue
            
        # Default time slots
        default_times = ['10:00', '14:00', '16:00'] if crisis_level == 'high' else ['09:00', '11:00', '14:00', '16:00']
        
        for time_str in default_times:
            hour, minute = map(int, time_str.split(':'))
            slot_datetime = datetime.combine(check_date.date(), datetime.min.time().replace(hour=hour, minute=minute))
            
            if slot_datetime > datetime.now():
                slots.append({
                    'datetime': slot_datetime,
                    'date': slot_datetime.strftime('%Y-%m-%d'),
                    'time': slot_datetime.strftime('%I:%M %p'),
                    'day_name': slot_datetime.strftime('%A'),
                    'formatted': slot_datetime.strftime('%A, %B %d at %I:%M %p')
                })
    
    return slots[:6]

def create_google_meet_link():
    """
    Generate a Google Meet link
    In production, you'd use Google Calendar API, but for demo we'll create a mock link
    """
    meeting_id = str(uuid.uuid4())[:12]
    # This would be a real Google Meet link in production
    meet_link = f"https://meet.google.com/{meeting_id}"
    
    return {
        'meet_link': meet_link,
        'meeting_id': meeting_id,
        'dial_in': f"+1-555-{meeting_id[-4:]}-{meeting_id[-8:-4]}",
        'created_at': datetime.now()
    }

def schedule_appointment_automatically(student_id, therapist, selected_slot, appointment_type='virtual', crisis_level='normal'):
    """
    Create a fully scheduled appointment with Google Meet link
    """
    # Generate Google Meet link for virtual appointments
    meeting_info = None
    if appointment_type == 'virtual':
        meeting_info = create_google_meet_link()
    
    # Create the appointment
    appointment = {
        'student_id': ObjectId(student_id),
        'therapist_id': therapist['_id'],
        'datetime': selected_slot['datetime'],
        'date': selected_slot['date'],
        'time': selected_slot['time'],
        'formatted_time': selected_slot['formatted'],
        'type': appointment_type,
        'status': 'confirmed',  # Automatically confirmed!
        'priority': 'urgent' if crisis_level == 'high' else 'normal',
        'meeting_info': meeting_info,
        'notes': f'Automatically scheduled {appointment_type} session',
        'created_at': datetime.now(),
        'auto_scheduled': True
    }
    
    # Save to database
    result = mongo.db.appointments.insert_one(appointment)
    
    # Update therapist's booked slots
    update_therapist_schedule(therapist['_id'], selected_slot['datetime'])
    
    return result.inserted_id, appointment

def update_therapist_schedule(therapist_id, booked_datetime):
    """
    Mark time slot as booked for the therapist
    """
    mongo.db.therapists.update_one(
        {'_id': therapist_id},
        {
            '$push': {
                'booked_slots': {
                    'datetime': booked_datetime,
                    'booked_at': datetime.now()
                }
            },
            '$inc': {'total_sessions': 1}
        }
    )

def send_appointment_confirmation(student_id, therapist, appointment):
    """
    Send confirmation with all appointment details
    """
    confirmation = {
        'type': 'appointment_confirmation',
        'student_id': ObjectId(student_id),
        'therapist_id': therapist['_id'],
        'appointment_id': appointment.get('_id'),
        'subject': f'Appointment Confirmed with {therapist["name"]}',
        'message': create_confirmation_message(therapist, appointment),
        'created_at': datetime.now(),
        'status': 'sent'
    }
    
    mongo.db.notifications.insert_one(confirmation)

def create_confirmation_message(therapist, appointment):
    """
    Create a professional confirmation message
    """
    meeting_info = appointment.get('meeting_info', {})
    
    message = f"""
    🎉 Your therapy session is confirmed!
    
    📅 When: {appointment['formatted_time']}
    👨‍⚕️ Therapist: {therapist['name']}
    📍 Type: {appointment['type'].title()} Session
    """
    
    if meeting_info:
        message += f"""
        
    💻 Join your session:
    🔗 Google Meet: {meeting_info['meet_link']}
    📞 Dial-in: {meeting_info['dial_in']}
    
    💡 Tips for your session:
    • Join 5 minutes early to test your connection
    • Find a quiet, private space
    • Have a notepad ready for any insights
        """
    
    message += f"""
    
    ❓ Need to reschedule? Contact us anytime.
    🆘 Crisis support: Available 24/7 at 988
    
    We're here to support you! 💙
    """
    
    return message.strip()

def get_next_best_slot(therapist, crisis_level='normal'):
    """
    Get the absolute next best available slot for immediate booking
    """
    available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
    
    if available_slots:
        # For crisis cases, return the earliest slot
        if crisis_level == 'high':
            return available_slots[0]
        else:
            # For normal cases, return a slot that's not too immediate (at least 4 hours ahead)
            four_hours_from_now = datetime.now() + timedelta(hours=4)
            
            for slot in available_slots:
                if slot['datetime'] >= four_hours_from_now:
                    return slot
            
            # If no slot is 4+ hours ahead, return the first available
            return available_slots[0]
    
    return None

def auto_schedule_best_time(student_id, therapist, appointment_type='virtual', crisis_level='normal'):
    """
    Automatically schedule the best available time slot
    """
    best_slot = get_next_best_slot(therapist, crisis_level)
    
    if best_slot:
        appointment_id, appointment = schedule_appointment_automatically(
            student_id, therapist, best_slot, appointment_type, crisis_level
        )
        
        # Send confirmation
        send_appointment_confirmation(student_id, therapist, appointment)
        
        return appointment_id, appointment
    
    return None, None