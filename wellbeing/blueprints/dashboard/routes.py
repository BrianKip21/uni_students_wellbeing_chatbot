# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timezone, timedelta
import csv
import io
import uuid
import json
from functools import wraps
from typing import Dict, List, Optional, Tuple, Any
from wellbeing.blueprints.dashboard import dashboard_bp
from wellbeing.utils.decorators import login_required
from wellbeing.utils.automated_moderation import send_auto_moderated_message, AutomatedModerator
from wellbeing import mongo, logger
from wellbeing.models.user import find_user_by_id, update_user_settings

from wellbeing.utils.mental_health import (
    detect_crisis_level,
    assign_therapist_immediately,
    validate_intake_form
)

from wellbeing.utils.scheduling import (
    get_therapist_available_slots,
    auto_schedule_best_time,
    create_enhanced_fallback_meeting_link,
    schedule_appointment_automatically,
    update_zoom_meeting_in_appointment,
    cancel_zoom_meeting_in_appointment,
    refresh_zoom_meeting_for_appointment
)

from wellbeing.utils.zoom_integration import (
    create_zoom_therapy_meeting,
    update_zoom_meeting,
    cancel_zoom_meeting
)

from wellbeing.utils.appointments import (
    has_active_appointment,
    can_schedule_appointment,
    can_schedule_or_reschedule,
    is_zoom_integrated,
    get_user_appointment_status
)

# ===== CONSTANTS AND CONFIGURATION =====
APPOINTMENT_CONSTRAINTS = {
    'MIN_ADVANCE_HOURS': 1,
    'MAX_ADVANCE_DAYS': 14,
    'SESSION_JOIN_WINDOW_MINUTES': 15,
    'SESSION_END_BUFFER_MINUTES': 90
}

BUSINESS_HOURS = {
    'start': 9,
    'end': 17,
    'weekdays_only': True
}

# Database field formats based on actual structure:
# - license_number: "KE-CL-123456" (Kenya Clinical License)
# - phone: "+254712345678" (Kenyan format with country code)
# - rating: Integer (5, not 5.0)
# - years_experience: Integer (0, 1, 2, etc.)

# ===== HELPER DECORATORS =====
def student_required(f):
    """Decorator to ensure user is a student"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or session.get('role') != 'student':
            flash('Student access required.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def validate_appointment_access(f):
    """Decorator to validate appointment access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        appointment_id = kwargs.get('appointment_id') or request.json.get('appointment_id')
        if appointment_id:
            appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            if not appointment:
                return jsonify({'error': 'Appointment not found'}), 404
            
            user_id = ObjectId(session['user'])
            if appointment.get('student_id') != user_id and appointment.get('user_id') != user_id:
                return jsonify({'error': 'Access denied'}), 403
                
            kwargs['appointment'] = appointment
        return f(*args, **kwargs)
    return decorated_function

# ===== HELPER FUNCTIONS =====
def format_therapist_display_name(therapist: Dict[str, Any]) -> str:
    """Format therapist name with license for display"""
    name = therapist.get('name', 'Unknown Therapist')
    license_number = therapist.get('license_number', '')
    if license_number:
        return f"{name} (License: {license_number})"
    return name

def validate_license_format(license_number: str) -> bool:
    """Validate license number format (e.g., "KE-CL-123456")"""
    if not license_number:
        return False
    
    # Kenya Clinical License pattern: KE-CL-XXXXXX
    import re
    pattern = r'^KE-[A-Z]{2}-\d{6}$'
    return bool(re.match(pattern, license_number))

def get_therapist_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """Get therapist by license number or _id with validation"""
    try:
        # First try by license number (preferred)
        therapist = mongo.db.therapists.find_one({'license_number': identifier})
        if therapist:
            return therapist
        
        # Fallback to _id for backward compatibility
        if ObjectId.is_valid(identifier):
            therapist = mongo.db.therapists.find_one({'_id': ObjectId(identifier)})
            return therapist
        
        return None
    except Exception as e:
        logger.error(f"Error finding therapist by identifier {identifier}: {str(e)}")
        return None

# ===== ENHANCED APPOINTMENT CREATION =====
class AppointmentManager:
    """
    Centralized appointment management with improved error handling
    
    Note: 
    - Uses therapist['_id'] for internal database operations
    - Uses therapist['license_number'] for user-facing operations and API endpoints
    - Maintains backward compatibility for existing therapist_id references
    """
    
    @staticmethod
    def create_appointment_with_zoom(
        student_id: str, 
        therapist: Dict[str, Any], 
        appointment_slot: Dict[str, Any], 
        crisis_level: str = 'normal'
    ) -> Tuple[Optional[ObjectId], Optional[Dict], bool]:
        """
        Enhanced appointment creation with comprehensive error handling
        
        Returns:
            Tuple of (appointment_id, appointment_doc, zoom_success)
        """
        try:
            # Normalize student_id
            if isinstance(student_id, str):
                student_id = ObjectId(student_id)
            elif isinstance(student_id, dict) and '_id' in student_id:
                student_id = ObjectId(student_id['_id'])
            
            # Get participant information
            student = mongo.db.users.find_one({'_id': student_id})
            if not student:
                logger.error(f"Student not found: {student_id}")
                return None, None, False
            
            # Prepare appointment data
            meeting_id = str(uuid.uuid4())[:12].replace('-', '')
            appointment_data = {
                'student_id': student_id,
                'user_id': student_id,  # Backward compatibility
                'therapist_id': therapist['_id'],
                'datetime': appointment_slot['datetime'],
                'formatted_time': appointment_slot.get('formatted', 
                    appointment_slot['datetime'].strftime('%A, %B %d at %I:%M %p')),
                'type': 'virtual',
                'status': 'confirmed',
                'crisis_level': crisis_level,
                'notes': f'Auto-scheduled virtual session - Priority: {crisis_level}',
                'created_at': datetime.utcnow(),
                'auto_scheduled': True,
                'meeting_id': meeting_id,
                'student_name': student.get('name', student.get('username', 'Student')),
                'therapist_name': therapist.get('name', therapist.get('username', 'Therapist'))
            }
            
            # Create Zoom meeting
            zoom_success = AppointmentManager._create_zoom_meeting(
                appointment_data, student, therapist, appointment_slot
            )
            
            # Fallback meeting info if Zoom fails
            if not appointment_data.get('meeting_info'):
                appointment_data['meeting_info'] = create_enhanced_fallback_meeting_link(
                    f"Therapy Session - {crisis_level.title()}",
                    appointment_slot['datetime']
                )
            
            # Insert appointment
            result = mongo.db.appointments.insert_one(appointment_data)
            appointment_id = result.inserted_id
            
            appointment_data['appointment_id'] = appointment_id
            appointment_data['_id'] = appointment_id
            appointment_data['zoom_integrated'] = zoom_success
            
            logger.info(f"Created appointment {appointment_id} with Zoom: {zoom_success}")
            return appointment_id, appointment_data, zoom_success
            
        except Exception as e:
            logger.error(f"Error creating appointment: {str(e)}")
            return None, None, False
    
    @staticmethod
    def _create_zoom_meeting(
        appointment_data: Dict[str, Any], 
        student: Dict[str, Any], 
        therapist: Dict[str, Any], 
        appointment_slot: Dict[str, Any]
    ) -> bool:
        """Create Zoom meeting with proper error handling"""
        try:
            student_email = student.get('email')
            therapist_email = therapist.get('email')
            
            if not student_email or not therapist_email:
                logger.warning("Missing email addresses for Zoom meeting")
                return False
            
            zoom_appointment_data = {
                'datetime': appointment_slot['datetime'],
                'crisis_level': appointment_data['crisis_level'],
                'notes': appointment_data['notes'],
                'appointment_id': appointment_data['meeting_id']
            }
            
            zoom_success, zoom_result = create_zoom_therapy_meeting(
                zoom_appointment_data, student_email, therapist_email
            )
            
            if zoom_success and zoom_result.get('created_method') == 'zoom_oauth':
                appointment_data.update({
                    'zoom_meeting_id': zoom_result.get('zoom_meeting_id'),
                    'meeting_info': {
                        'meet_link': zoom_result.get('meet_link'),
                        'host_link': zoom_result.get('host_link'),
                        'platform': 'Zoom',
                        'meeting_password': zoom_result.get('meeting_password'),
                        'dial_in': zoom_result.get('dial_in'),
                        'meeting_uuid': zoom_result.get('meeting_uuid'),
                        'created_method': 'zoom_oauth'
                    }
                })
                return True
            else:
                if zoom_result:
                    appointment_data['meeting_info'] = {
                        'meet_link': zoom_result.get('meet_link'),
                        'host_link': zoom_result.get('host_link', zoom_result.get('meet_link')),
                        'platform': zoom_result.get('platform', 'Zoom (Fallback)'),
                        'meeting_password': zoom_result.get('meeting_password'),
                        'dial_in': zoom_result.get('dial_in'),
                        'created_method': 'fallback'
                    }
                return False
                
        except Exception as e:
            logger.error(f"Zoom meeting creation error: {str(e)}")
            return False

# ===== MAIN DASHBOARD ROUTE =====
@dashboard_bp.route('/dashboard')
@login_required
@student_required
def index():
    """Enhanced dashboard with better error handling and data organization"""
    try:
        user_id = ObjectId(session['user'])
        user = find_user_by_id(user_id)
        
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Handle view redirection
        settings = user.get('settings', {})
        requested_view = request.args.get('view')
        
        if not requested_view and settings.get('default_view') != 'dashboard':
            view_response = _handle_view_redirection(settings.get('default_view'))
            if view_response:
                return view_response
        
        # Initialize user progress (ensure it doesn't return or interrupt flow)
        _initialize_user_progress(user_id, user)
        
        # Get dashboard data
        dashboard_data = _get_dashboard_data(user_id, user)
        
        return render_template('dashboard.html', **dashboard_data)
        
    except Exception as e:
        logger.error(f"Dashboard error for user {session.get('user')}: {str(e)}")
        flash('Unable to load dashboard. Please try again.', 'error')
        return redirect(url_for('auth.login'))


def _handle_view_redirection(default_view: str):
    """Handle redirection based on default view setting"""
    if default_view == 'calendar':
        return redirect(url_for('tracking.index'))
    elif default_view == 'list':
        return redirect(url_for('tracking.list_view'))
    return None

def _initialize_user_progress(user_id: ObjectId, user: Dict[str, Any]):
    """Initialize user progress if it doesn't exist"""
    if 'progress' not in user:
        default_progress = {'meditation': 0, 'exercise': 0}
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'progress': default_progress}}
        )
        user['progress'] = default_progress

def _get_dashboard_data(user_id: ObjectId, user: Dict[str, Any]) -> Dict[str, Any]:
    """Get all dashboard data in organized format"""
    # Basic user data
    recent_chats = list(mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1).limit(5))
    recommended_resources = list(mongo.db.resources.find().limit(2))
    latest_mood = mongo.db.moods.find_one({"user_id": str(user_id)}, sort=[("timestamp", -1)])
    
    # Intake and therapist data
    intake_completed = mongo.db.intake_assessments.find_one({'student_id': user_id})
    assigned_therapist = _get_assigned_therapist(user)
    
    # Appointment data
    appointment_status = get_user_appointment_status(user_id, mongo.db)
    next_appointment = _get_next_appointment(user_id, assigned_therapist, appointment_status)
    all_appointments = _get_all_appointments(user_id, assigned_therapist)
    
    # Categorize appointments
    now = datetime.now()
    upcoming_appointments = [
        apt for apt in all_appointments 
        if apt.get('datetime') and apt['datetime'] > now and apt.get('status') not in ['cancelled', 'completed']
    ]
    past_appointments = [
        apt for apt in all_appointments 
        if apt.get('datetime') and (apt['datetime'] <= now or apt.get('status') in ['cancelled', 'completed'])
    ]
    
    return {
        'user': user,
        'settings': user.get('settings', {}),
        'datetime': datetime,
        'recent_chats': recent_chats,
        'resources': recommended_resources,
        'latest_mood': latest_mood,
        'assigned_therapist': assigned_therapist,
        'intake_status': {
            'completed': bool(intake_completed),
            'has_therapist': bool(assigned_therapist)
        },
        'intake_completed': intake_completed,
        'next_appointment': next_appointment,
        'appointment_status': appointment_status,
        'booking_status': {
            'can_book': appointment_status['can_schedule'],
            'has_active': appointment_status['has_active_appointment'],
            'total_appointments': appointment_status['total_appointments'],
            'completed_appointments': appointment_status['completed_appointments'],
            'upcoming_appointments': len(upcoming_appointments)
        },
        'upcoming_appointments': upcoming_appointments,
        'past_appointments': past_appointments,
        'has_active_appointment': appointment_status['has_active_appointment'],
        'active_appointment': appointment_status.get('active_appointment')
    }

def _get_assigned_therapist(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get assigned therapist with proper error handling"""
    if not user.get('assigned_therapist_id'):
        return None
    
    therapist = mongo.db.therapists.find_one({'_id': user['assigned_therapist_id']})
    if not therapist:
        return None
    
    return {
        'therapist_id': therapist['_id'],
        'license_id': therapist['license_number'], 
        'therapist_name': therapist['name'],
        'therapist': therapist,
        'status': 'active'
    }

def _get_next_appointment(
    user_id: ObjectId, 
    assigned_therapist: Optional[Dict[str, Any]], 
    appointment_status: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Get next appointment with proper formatting"""
    if not assigned_therapist:
        return None
    
    next_appointment = None
    
    if appointment_status['has_active_appointment']:
        next_appointment = appointment_status['active_appointment']
    else:
        next_appointment = mongo.db.appointments.find_one({
            'student_id': user_id,
            'status': {'$in': ['confirmed', 'suggested']},
            'datetime': {'$gte': datetime.now()}
        }, sort=[('datetime', 1)])
    
    if next_appointment:
        # Format appointment
        if 'formatted_time' not in next_appointment and next_appointment.get('datetime'):
            next_appointment['formatted_time'] = next_appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
        
        next_appointment['zoom_integrated'] = is_zoom_integrated(next_appointment.get('zoom_meeting_id'))
        
        # Calculate time difference
        if next_appointment.get('datetime'):
            time_diff = (next_appointment['datetime'] - datetime.now()).total_seconds() / 60
            next_appointment['time_diff_minutes'] = time_diff
    
    return next_appointment

def _get_all_appointments(user_id: ObjectId, assigned_therapist: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Get all appointments with proper formatting"""
    if not assigned_therapist:
        return []
    
    raw_appointments = list(mongo.db.appointments.find({
        'student_id': user_id,
        'therapist_id': assigned_therapist['therapist_id']  # Keep using _id for database queries
    }).sort('datetime', -1))
    
    appointments = []
    for apt in raw_appointments:
        # Format appointment
        if apt.get('datetime'):
            apt['formatted_time'] = apt['datetime'].strftime('%A, %B %d at %I:%M %p')
            apt['date'] = apt['datetime']
        else:
            apt['formatted_time'] = 'Time to be confirmed'
        
        apt['zoom_integrated'] = is_zoom_integrated(apt.get('zoom_meeting_id'))
        # Add license reference for user-facing operations
        apt['therapist_license'] = assigned_therapist['license_id']
        appointments.append(apt)
    
    return appointments
# ===== APPOINTMENT BOOKING ROUTES =====
@dashboard_bp.route('/book-appointment', methods=['GET', 'POST'])
@login_required
@student_required
def book_appointment():
    """Enhanced appointment booking with better validation"""
    user_id = session['user']
    user = find_user_by_id(ObjectId(user_id))
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    assigned_therapist = _get_assigned_therapist(user)
    if not assigned_therapist:
        flash('You need to be assigned a therapist before booking appointments.', 'error')
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'GET':
        return _handle_book_appointment_get(user, assigned_therapist)
    
    return _handle_book_appointment_post(user_id, user, assigned_therapist)

def _handle_book_appointment_get(user: Dict[str, Any], assigned_therapist: Dict[str, Any]):
    """Handle GET request for booking appointment"""
    user_id = str(user['_id'])
    can_schedule, reason = can_schedule_appointment(user_id, mongo.db)
    
    if not can_schedule:
        flash(reason, 'warning')
        return redirect(url_for('dashboard.index'))
    
    min_datetime = (datetime.now() + timedelta(hours=APPOINTMENT_CONSTRAINTS['MIN_ADVANCE_HOURS'])).strftime('%Y-%m-%dT%H:%M')
    
    return render_template('book_appointment.html',
                         user=user,
                         assigned_therapist=assigned_therapist,
                         min_datetime=min_datetime)

def _handle_book_appointment_post(user_id: str, user: Dict[str, Any], assigned_therapist: Dict[str, Any]):
    """Handle POST request for booking appointment"""
    # Validate scheduling ability
    can_schedule, reason = can_schedule_appointment(user_id, mongo.db)
    if not can_schedule:
        flash(reason, 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Get and validate form data
        appointment_datetime = request.form.get('appointment_datetime')
        crisis_level = request.form.get('crisis_level', 'normal')
        notes = request.form.get('notes', '')
        
        appointment_dt = datetime.strptime(appointment_datetime, '%Y-%m-%dT%H:%M')
        
        # Validate timing
        min_time = datetime.now() + timedelta(hours=APPOINTMENT_CONSTRAINTS['MIN_ADVANCE_HOURS'])
        if appointment_dt <= min_time:
            flash(f'Please select a time at least {APPOINTMENT_CONSTRAINTS["MIN_ADVANCE_HOURS"]} hour(s) in the future.', 'error')
            return _handle_book_appointment_get(user, assigned_therapist)
        
        # Final validation check
        can_schedule, reason = can_schedule_appointment(user_id, mongo.db)
        if not can_schedule:
            flash(reason, 'error')
            return redirect(url_for('dashboard.index'))
        
        # Create appointment
        appointment_slot = {
            'datetime': appointment_dt,
            'formatted': appointment_dt.strftime('%A, %B %d at %I:%M %p')
        }
        
        appointment_id, appointment_doc, zoom_success = AppointmentManager.create_appointment_with_zoom(
            user_id, assigned_therapist['therapist'], appointment_slot, crisis_level
        )
        
        if appointment_id:
            # Update with additional data
            mongo.db.appointments.update_one(
                {'_id': appointment_id},
                {'$set': {
                    'notes': notes,
                    'created_by': 'student',
                    'booking_method': 'manual'
                }}
            )
            
            success_message = ('✅ Appointment scheduled successfully! Zoom meeting created and details sent.' 
                             if zoom_success else 
                             '✅ Appointment scheduled successfully! Meeting details available in your dashboard.')
            flash(success_message, 'success')
            return redirect(url_for('dashboard.index'))
        else:
            flash('Failed to schedule appointment. Please try again.', 'error')
            
    except ValueError as e:
        flash('Invalid date format. Please try again.', 'error')
        logger.error(f"Date parsing error: {str(e)}")
    except Exception as e:
        logger.error(f"Error booking appointment for user {user_id}: {str(e)}")
        flash('An error occurred while scheduling. Please try again.', 'error')
    
    return _handle_book_appointment_get(user, assigned_therapist)

# ===== APPOINTMENT MANAGEMENT ROUTES =====
@dashboard_bp.route('/cancel-appointment', methods=['POST'])
@login_required
@student_required
def cancel_appointment():
    """Enhanced appointment cancellation with atomic operations"""
    user_id = session['user']
    
    try:
        data = request.get_json() or {}
        appointment_id = data.get('appointment_id')
        cancellation_reason = data.get('reason', 'Cancelled by student').strip()[:200]
        
        # Validate appointment ID if provided
        if appointment_id and not ObjectId.is_valid(appointment_id):
            return jsonify({'success': False, 'message': 'Invalid appointment ID format'}), 400
        
        # Build query
        query = {
            'student_id': ObjectId(user_id),
            'status': {'$nin': ['cancelled', 'completed']}
        }
        
        if appointment_id:
            query['_id'] = ObjectId(appointment_id)
        else:
            query['datetime'] = {'$gt': datetime.now()}
        
        # Atomic update
        update_data = {
            'status': 'cancelled',
            'cancelled_at': datetime.now(),
            'cancelled_by': 'student',
            'cancellation_reason': cancellation_reason,
            'last_modified': datetime.now()
        }
        
        result = mongo.db.appointments.update_one(query, {'$set': update_data})
        
        if result.modified_count == 0:
            return jsonify({'success': False, 'message': 'No active appointment found to cancel'}), 404
        
        # Handle Zoom cancellation asynchronously
        if appointment_id:
            _handle_zoom_cancellation_async(appointment_id)
        
        logger.info(f"Student {user_id} cancelled appointment {appointment_id or '(all future)'}")
        return jsonify({'success': True, 'message': 'Appointment cancelled successfully'})
        
    except Exception as e:
        logger.error(f"Error cancelling appointment for user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred'}), 500

def _handle_zoom_cancellation_async(appointment_id: str):
    """Handle Zoom meeting cancellation asynchronously"""
    try:
        appointment = mongo.db.appointments.find_one(
            {'_id': ObjectId(appointment_id)},
            {'zoom_meeting_id': 1}
        )
        
        if appointment and appointment.get('zoom_meeting_id'):
            if not str(appointment['zoom_meeting_id']).startswith('fallback'):
                from threading import Thread
                Thread(target=cancel_zoom_meeting_in_appointment, args=(appointment_id,)).start()
    except Exception as e:
        logger.error(f"Error handling Zoom cancellation: {str(e)}")

@dashboard_bp.route('/reschedule-appointment', methods=['POST'])
@login_required
@student_required
def reschedule_appointment():
    """Cancel current appointment to allow rescheduling"""
    user_id = session['user']
    
    try:
        result = mongo.db.appointments.update_one(
            {
                'student_id': ObjectId(user_id),
                'datetime': {'$gt': datetime.now()},
                'status': {'$nin': ['cancelled', 'completed']}
            },
            {
                '$set': {
                    'status': 'cancelled',
                    'cancelled_at': datetime.now(),
                    'cancelled_by': 'student',
                    'cancellation_reason': 'rescheduled'
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"User {user_id} cancelled appointment for rescheduling")
            return jsonify({
                'success': True, 
                'message': 'Previous appointment cancelled. You can now schedule a new one.',
                'redirect_url': url_for('dashboard.book_appointment')
            })
        else:
            return jsonify({'success': False, 'message': 'No active appointment found to cancel.'})
            
    except Exception as e:
        logger.error(f"Error rescheduling appointment for user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while cancelling the appointment.'})

# ===== ENHANCED INTAKE ROUTES =====
@dashboard_bp.route('/student/intake', methods=['GET', 'POST'])
@student_required
def student_intake():
    """Enhanced intake with comprehensive validation and immediate scheduling"""
    if request.method == 'POST':
        return _handle_intake_submission()
    
    return render_template('student/intake.html')

def _handle_intake_submission():
    """Handle intake form submission with comprehensive processing"""
    try:
        user_id = session['user']
        can_schedule, reason = can_schedule_appointment(user_id, mongo.db)
        
        # Extract and validate form data
        form_data = _extract_intake_form_data()
        is_valid, errors = validate_intake_form(form_data)
        
        if not is_valid:
            for error in errors:
                flash(f'Please fix: {error}', 'error')
            return render_template('student/intake.html')
        
        # Process intake
        intake_data = _prepare_intake_data(form_data, user_id)
        crisis_result = detect_crisis_level(intake_data)
        crisis_level = crisis_result['level']
        
        # Find therapist
        therapist = assign_therapist_immediately(intake_data)
        
        if therapist:
            return _process_intake_with_therapist(intake_data, therapist, crisis_level, can_schedule, user_id)
        else:
            mongo.db.intake_assessments.insert_one(intake_data)
            flash('Assessment completed! We\'ll find you a therapist soon.', 'info')
            return redirect(url_for('dashboard.index'))
            
    except Exception as e:
        logger.error(f"Error in student intake: {str(e)}")
        flash('An error occurred during intake. Please try again.', 'error')
        return render_template('student/intake.html')

def _extract_intake_form_data() -> Dict[str, Any]:
    """Extract and clean form data"""
    return {
        'primary_concern': request.form.get('primary_concern'),
        'description': request.form.get('description'),
        'severity': request.form.get('severity'),
        'duration': request.form.get('duration'),
        'previous_therapy': request.form.get('previous_therapy'),
        'therapist_gender': request.form.get('therapist_gender'),
        'appointment_type': 'virtual',  # Force virtual
        'crisis_indicators': request.form.getlist('crisis_indicators'),
        'emergency_contact_name': request.form.get('emergency_contact_name'),
        'emergency_contact_phone': request.form.get('emergency_contact_phone'),
        'emergency_contact_relationship': request.form.get('emergency_contact_relationship')
    }

def _prepare_intake_data(form_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Prepare intake data for database insertion"""
    return {
        'student_id': ObjectId(user_id),
        **form_data,
        'severity': int(form_data['severity']),
        'created_at': datetime.now()
    }

def _process_intake_with_therapist(
    intake_data: Dict[str, Any], 
    therapist: Dict[str, Any], 
    crisis_level: str, 
    can_schedule: bool, 
    user_id: str
):
    """Process intake when therapist is available"""
    if crisis_level == 'high' or can_schedule:
        return _schedule_immediate_appointment(intake_data, therapist, crisis_level, user_id)
    else:
        return _assign_therapist_without_appointment(intake_data, therapist, user_id)

def _schedule_immediate_appointment(
    intake_data: Dict[str, Any], 
    therapist: Dict[str, Any], 
    crisis_level: str, 
    user_id: str
):
    """Schedule immediate appointment after intake"""
    available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
    
    if available_slots:
        selected_slot = available_slots[0]
        appointment_id, appointment_doc, zoom_success = AppointmentManager.create_appointment_with_zoom(
            user_id, therapist, selected_slot, crisis_level
        )
        
        if appointment_id:
            # Update intake and user records
            _update_records_with_appointment(intake_data, therapist, crisis_level, appointment_id, zoom_success, user_id)
            
            success_message = ('✅ Session scheduled! Zoom meeting created and details sent.' 
                             if zoom_success else 
                             '✅ Session scheduled! Meeting details available in your dashboard.')
            flash(success_message, 'success')
            
            return redirect(url_for('dashboard.appointment_confirmed', 
                                  appointment_id=str(appointment_id),
                                  crisis_level=crisis_level))
    
    # No slots available
    _update_records_without_appointment(intake_data, therapist, crisis_level, user_id)
    therapist_display = format_therapist_display_name(therapist)
    flash(f'Matched with {therapist_display}! They\'ll contact you to schedule.', 'success')
    return redirect(url_for('dashboard.match_results', 
                          license_id=therapist['license_number'],  # Use license_number
                          crisis_level=crisis_level))

def _assign_therapist_without_appointment(intake_data: Dict[str, Any], therapist: Dict[str, Any], user_id: str):
    """Assign therapist without scheduling appointment"""
    intake_data.update({
        'assigned_therapist_id': therapist['_id'],
        'crisis_level': 'normal',
        'auto_scheduled': False,
        'blocked_by_existing_appointment': True
    })
    mongo.db.intake_assessments.insert_one(intake_data)
    
    # Update user records
    _update_user_therapist_assignment(therapist, user_id)
    
    therapist_display = format_therapist_display_name(therapist)
    flash(f'Matched with {therapist_display}! Complete your current appointment before scheduling a new one.', 'info')
    return redirect(url_for('dashboard.index'))

def _update_records_with_appointment(
    intake_data: Dict[str, Any], 
    therapist: Dict[str, Any], 
    crisis_level: str, 
    appointment_id: ObjectId, 
    zoom_success: bool, 
    user_id: str
):
    """Update all records when appointment is scheduled - FIXED VERSION"""
    try:
        user_object_id = ObjectId(user_id)
        therapist_object_id = therapist['_id']
        
        # Update intake data
        intake_data.update({
            'assigned_therapist_id': therapist_object_id,
            'crisis_level': crisis_level,
            'appointment_id': appointment_id,
            'auto_scheduled': True,
            'zoom_integrated': zoom_success
        })
        mongo.db.intake_assessments.insert_one(intake_data)
        
        # Update student record
        mongo.db.students.update_one(
            {'_id': user_object_id},
            {'$set': {
                'assigned_therapist_id': therapist_object_id,
                'assignment_date': datetime.now(),
                'status': 'crisis' if crisis_level == 'high' else 'active',
                'intake_completed': True,
                'next_appointment_id': appointment_id
            }},
            upsert=True
        )
        
        # THIS IS THE KEY FIX - Create therapist assignment
        _update_user_therapist_assignment(therapist, user_id)
        
    except Exception as e:
        logger.error(f"Error updating records with appointment: {str(e)}")
        raise

def _update_records_without_appointment(
    intake_data: Dict[str, Any], 
    therapist: Dict[str, Any], 
    crisis_level: str, 
    user_id: str
):
    """Update records when no appointment is scheduled - FIXED VERSION"""
    try:
        user_object_id = ObjectId(user_id)
        therapist_object_id = therapist['_id']
        
        intake_data.update({
            'assigned_therapist_id': therapist_object_id,
            'crisis_level': crisis_level,
            'auto_scheduled': False
        })
        mongo.db.intake_assessments.insert_one(intake_data)
        
        # Update student record
        mongo.db.students.update_one(
            {'_id': user_object_id},
            {'$set': {
                'assigned_therapist_id': therapist_object_id,
                'assignment_date': datetime.now(),
                'status': crisis_level,
                'intake_completed': True
            }},
            upsert=True
        )
        
        # THIS IS THE KEY FIX - Create therapist assignment
        _update_user_therapist_assignment(therapist, user_id)
        
    except Exception as e:
        logger.error(f"Error updating records without appointment: {str(e)}")
        raise

def _update_user_therapist_assignment(therapist: Dict[str, Any], user_id: str):
    """Update user record with therapist assignment AND create therapist_assignments record"""
    try:
        user_object_id = ObjectId(user_id)
        therapist_object_id = therapist['_id']
        
        # Update user record
        mongo.db.users.update_one(
            {'_id': user_object_id},
            {'$set': {
                'assigned_therapist_id': therapist_object_id,
                'intake_completed': True,
                'assignment_date': datetime.now()
            }}
        )
        
        # Create or update therapist_assignments record (THIS WAS MISSING!)
        mongo.db.therapist_assignments.update_one(
            {
                'therapist_id': therapist_object_id,
                'student_id': user_object_id
            },
            {
                '$set': {
                    'therapist_id': therapist_object_id,
                    'student_id': user_object_id,
                    'status': 'active',
                    'auto_assigned': True,
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
            },
            upsert=True  # Create if doesn't exist
        )
        
        # Update therapist's current student count
        mongo.db.therapists.update_one(
            {'_id': therapist_object_id},
            {'$inc': {'current_students': 1}}
        )
        
        logger.info(f"Successfully created therapist assignment: therapist {therapist_object_id} -> student {user_object_id}")
        
    except Exception as e:
        logger.error(f"Error creating therapist assignment: {str(e)}")
        raise

def migrate_existing_student_assignments():
    """Migrate existing student-therapist assignments to therapist_assignments collection"""
    try:
        # Find all users with assigned therapists but no therapist_assignments record
        users_with_therapists = mongo.db.users.find({
            'assigned_therapist_id': {'$exists': True},
            'role': 'student'
        })
        
        migrated_count = 0
        for user in users_with_therapists:
            user_id = user['_id']
            therapist_id = user['assigned_therapist_id']
            
            # Check if assignment already exists
            existing_assignment = mongo.db.therapist_assignments.find_one({
                'therapist_id': therapist_id,
                'student_id': user_id
            })
            
            if not existing_assignment:
                # Create the missing assignment
                mongo.db.therapist_assignments.insert_one({
                    'therapist_id': therapist_id,
                    'student_id': user_id,
                    'status': 'active',
                    'auto_assigned': True,
                    'created_at': user.get('assignment_date', datetime.now()),
                    'updated_at': datetime.now()
                })
                migrated_count += 1
                logger.info(f"Migrated assignment: therapist {therapist_id} -> student {user_id}")
        
        logger.info(f"Migration complete: {migrated_count} assignments created")
        return migrated_count
        
    except Exception as e:
        logger.error(f"Error during migration: {str(e)}")
        return 0
    
@dashboard_bp.route('/api/migrate-assignments', methods=['POST'])
@login_required
def api_migrate_assignments():
    """API endpoint to migrate existing student assignments (admin only)"""
    try:
        # In production, add admin role check here
        migrated_count = migrate_existing_student_assignments()
        return jsonify({
            'success': True,
            'message': f'Successfully migrated {migrated_count} student assignments'
        })
    except Exception as e:
        logger.error(f"Error in migration API: {str(e)}")
        return jsonify({'error': 'Migration failed'}), 500

@dashboard_bp.route('/student/intake-assessment') 
@login_required
def intake_assessment():
    """Alternative route for intake assessment"""
    return redirect(url_for('dashboard.student_intake'))

# ===== THERAPIST ROUTES =====
@dashboard_bp.route('/student/therapist-info')
@login_required
@student_required
def therapist_info():
    """Enhanced therapist profile with comprehensive appointment management"""
    user_id = ObjectId(session['user'])
    
    try:
        user = _get_user_with_fallback(user_id)
        therapist = _get_therapist_with_defaults(user)
        appointments = _get_formatted_appointments(user_id, therapist)
        appointment_status = get_user_appointment_status(user_id, mongo.db)
        
        return render_template('student/therapist_info.html',
                             therapist=therapist,
                             appointments=appointments,
                             user=user,
                             appointment_status=appointment_status,
                             can_book_new=appointment_status['can_schedule'])
                             
    except Exception as e:
        logger.error(f"Error loading therapist info for {user_id}: {str(e)}")
        flash('Unable to load therapist information. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))

def _get_user_with_fallback(user_id: ObjectId) -> Dict[str, Any]:
    """Get user with fallback between collections"""
    user = mongo.db.students.find_one({'_id': user_id})
    if not user:
        user = mongo.db.users.find_one({'_id': user_id})
        if not user:
            raise ValueError('User profile not found')
    return user

def _get_therapist_with_defaults(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get therapist with proper defaults matching actual DB structure"""
    if not user.get('assigned_therapist_id'):
        return None
    
    therapist = mongo.db.therapists.find_one({'_id': user['assigned_therapist_id']})
    if not therapist:
        return None
    
    # Set defaults only for truly missing fields (based on actual DB structure)
    defaults = {
        'bio': '',
        'phone': '',
        'availability': {}
    }
    
    # Only set defaults for fields that don't exist
    for key, default_value in defaults.items():
        if key not in therapist:
            therapist[key] = default_value
    
    # Ensure numeric fields are proper types
    therapist['rating'] = int(therapist.get('rating', 5))
    therapist['total_sessions'] = int(therapist.get('total_sessions', 0))
    therapist['years_experience'] = int(therapist.get('years_experience', 0))
    therapist['max_students'] = int(therapist.get('max_students', 25))
    therapist['current_students'] = int(therapist.get('current_students', 0))
    
    # Ensure boolean fields
    therapist['emergency_hours'] = bool(therapist.get('emergency_hours', False))
    
    # Ensure arrays
    if 'specializations' not in therapist:
        therapist['specializations'] = []
    
    return therapist

def _get_formatted_appointments(user_id: ObjectId, therapist: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Get and format appointments"""
    if not therapist:
        return []
    
    raw_appointments = list(mongo.db.appointments.find({
        'student_id': user_id,
        'therapist_id': therapist['_id']
    }).sort('datetime', 1))
    
    appointments = []
    for apt in raw_appointments:
        apt['type'] = 'virtual'  # Force virtual
        
        # Format datetime
        if apt.get('datetime'):
            apt['formatted_time'] = apt['datetime'].strftime('%A, %B %d at %I:%M %p')
            apt['date'] = apt['datetime']
        else:
            apt['formatted_time'] = 'Time to be confirmed'
        
        apt['zoom_integrated'] = is_zoom_integrated(apt.get('zoom_meeting_id'))
        
        # Ensure meeting info exists
        _ensure_meeting_info(apt)
        appointments.append(apt)
    
    return appointments

def _ensure_meeting_info(appointment: Dict[str, Any]):
    """Ensure appointment has meeting info"""
    if not appointment.get('meeting_info'):
        # Try to refresh if it's a real Zoom meeting
        if (appointment.get('zoom_meeting_id') and 
            not str(appointment.get('zoom_meeting_id', '')).startswith('fallback')):
            refresh_success = refresh_zoom_meeting_for_appointment(appointment['_id'])
            if refresh_success:
                return
        
        # Create fallback meeting info
        meeting_info = create_enhanced_fallback_meeting_link(
            f"Therapy Session - {appointment.get('crisis_level', 'normal').title()}",
            appointment.get('datetime')
        )
        appointment['meeting_info'] = meeting_info
        
        # Update in database
        mongo.db.appointments.update_one(
            {'_id': appointment['_id']},
            {'$set': {'meeting_info': meeting_info, 'type': 'virtual'}}
        )

@dashboard_bp.route('/student/match-results/<license_id>')
@login_required  
def match_results(license_id):
    """Show therapist matching results after intake using license ID"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    # Find therapist by license number
    therapist = mongo.db.therapists.find_one({'license_number': license_id})
    crisis_level = request.args.get('crisis_level', 'normal')
    
    if not therapist:
        flash('Therapist not found', 'error')
        return redirect(url_for('dashboard.index'))
    
    # Update student record with assigned therapist (using _id for database operations)
    user_id = ObjectId(session['user'])
    mongo.db.students.update_one(
        {'_id': user_id},
        {'$set': {'assigned_therapist_id': therapist['_id']}},  # Use _id for database
        upsert=True
    )
    
    # Also update users collection for consistency
    mongo.db.users.update_one(
        {'_id': user_id},
        {'$set': {'assigned_therapist_id': therapist['_id']}}  # Use _id for database
    )
    
    # Flash appropriate message with formatted therapist name
    therapist_display = format_therapist_display_name(therapist)
    if crisis_level == 'high':
        flash(f'✅ Priority match found! You\'ve been assigned to {therapist_display} for immediate support.', 'success')
    else:
        flash(f'✅ Perfect match! You\'ve been assigned to {therapist_display} who specializes in your areas of concern.', 'success')
    
    # Direct to therapist info
    return redirect(url_for('dashboard.therapist_info'))

# ===== APPOINTMENT ROUTES =====
@dashboard_bp.route('/student/appointment-confirmed/<appointment_id>')
def appointment_confirmed(appointment_id):
    """Enhanced appointment confirmation with Zoom integration status"""
    
    print(f"🔍 Loading appointment confirmation for ID: {appointment_id}")
    
    if 'user' not in session:
        print("❌ User not in session")
        return redirect(url_for('auth.login'))
    
    try:
        # Handle different session data formats
        if isinstance(session['user'], dict):
            current_user_id = session['user']['_id']
        elif isinstance(session['user'], str):
            current_user_id = session['user']
        else:
            current_user_id = str(session['user'])
        
        current_user_object_id = ObjectId(current_user_id)
        appointment_object_id = ObjectId(appointment_id)
        
        print(f"👤 Current user ID: {current_user_object_id}")
        print(f"📅 Looking for appointment ID: {appointment_object_id}")
        
        # Get appointment details - check both user_id and student_id fields
        appointment = mongo.db.appointments.find_one({
            '_id': appointment_object_id,
            '$or': [
                {'user_id': current_user_object_id},
                {'student_id': current_user_object_id}
            ]
        })
        
        if not appointment:
            print("❌ Appointment not found or access denied")
            flash('Appointment not found or access denied', 'error')
            return redirect(url_for('dashboard.index'))
        
        print(f"✅ Found appointment: {appointment.get('formatted_time')}")
        
        # Get therapist details
        therapist = mongo.db.therapists.find_one({'_id': appointment['therapist_id']})
        if not therapist:
            # Create fallback therapist data
            therapist = {
                'name': 'Your Assigned Therapist',
                'rating': 5,
                'total_sessions': 0,
                'specializations': ['anxiety', 'depression'],
                'license_number': 'Licensed Professional',
                'years_experience': 0,
                'emergency_hours': True
            }
        else:
            # Ensure all required fields exist
            therapist.setdefault('rating', 5)
            therapist.setdefault('total_sessions', 0)
            therapist.setdefault('specializations', [])
            therapist.setdefault('license_number', 'Licensed Professional')
            therapist.setdefault('years_experience', 0)
            therapist.setdefault('emergency_hours', False)
        
        # Ensure appointment has required fields
        if not appointment.get('formatted_time'):
            if appointment.get('datetime'):
                appointment['formatted_time'] = appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
            else:
                appointment['formatted_time'] = 'Time to be confirmed'
        
        # Check Zoom integration status
        zoom_integrated = is_zoom_integrated(appointment.get('zoom_meeting_id'))
        
        # Ensure virtual appointments have meeting info
        if appointment.get('type') == 'virtual' and not appointment.get('meeting_info'):
            # Try to refresh Zoom meeting if possible
            if appointment.get('zoom_meeting_id') and not str(appointment['zoom_meeting_id']).startswith('fallback'):
                refresh_success = refresh_zoom_meeting_for_appointment(appointment['_id'])
                if refresh_success:
                    # Reload appointment to get updated meeting info
                    appointment = mongo.db.appointments.find_one({'_id': appointment_object_id})
                    zoom_integrated = True
                    print("✅ Refreshed Zoom meeting info")
            
            # If still no meeting info, create fallback
            if not appointment.get('meeting_info'):
                meeting_info = create_enhanced_fallback_meeting_link(
                    f"Therapy Session - {appointment.get('crisis_level', 'normal').title()}",
                    appointment.get('datetime')
                )
                appointment['meeting_info'] = meeting_info
                
                # Update in database
                mongo.db.appointments.update_one(
                    {'_id': ObjectId(appointment_id)},
                    {'$set': {'meeting_info': meeting_info}}
                )
        
        # Get crisis level
        crisis_level = request.args.get('crisis_level', appointment.get('crisis_level', 'normal'))
        
        print(f"✅ Rendering confirmation page with Zoom status: {zoom_integrated}")
        
        return render_template('student/appointment_confirmed.html',
                             appointment=appointment,
                             therapist=therapist,
                             crisis_level=crisis_level,
                             zoom_integrated=zoom_integrated)
                             
    except Exception as e:
        print(f"❌ Error loading appointment confirmation: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading appointment details', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/student/join-session/<appointment_id>')
@login_required
@student_required
@validate_appointment_access
def join_session(appointment_id, appointment=None):
    """Enhanced session joining with comprehensive validation"""
    try:
        # Validate session timing
        timing_valid, timing_message = _validate_session_timing(appointment)
        if not timing_valid:
            flash(timing_message, 'warning' if 'wait' in timing_message else 'info')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Get meeting link
        meet_link = _get_meeting_link(appointment)
        if not meet_link:
            flash('No meeting link available. Contact your therapist.', 'error')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Log session access
        _log_session_access(appointment_id)
        
        logger.info(f"User {session['user']} joining session {appointment_id}")
        return redirect(meet_link)
        
    except Exception as e:
        logger.error(f"Error joining session: {str(e)}")
        flash('Unable to join session. Please try again.', 'error')
        return redirect(url_for('dashboard.therapist_info'))

def _validate_session_timing(appointment: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate if session can be joined based on timing"""
    if not appointment.get('datetime'):
        return True, ""  # Allow joining if no specific time
    
    session_time = appointment['datetime']
    now = datetime.now()
    time_diff = (session_time - now).total_seconds() / 60  # minutes
    
    if time_diff > APPOINTMENT_CONSTRAINTS['SESSION_JOIN_WINDOW_MINUTES']:
        return False, f'Session starts in {int(time_diff)} minutes. Please wait.'
    elif time_diff < -APPOINTMENT_CONSTRAINTS['SESSION_END_BUFFER_MINUTES']:
        return False, 'This session has ended.'
    
    return True, ""

def _get_meeting_link(appointment: Dict[str, Any]) -> Optional[str]:
    """Get meeting link with refresh attempt"""
    meeting_info = appointment.get('meeting_info', {})
    meet_link = meeting_info.get('meet_link')
    
    if not meet_link:
        # Try to refresh Zoom meeting
        if (appointment.get('zoom_meeting_id') and 
            not str(appointment['zoom_meeting_id']).startswith('fallback')):
            refresh_success = refresh_zoom_meeting_for_appointment(appointment['_id'])
            if refresh_success:
                # Reload appointment
                updated_appointment = mongo.db.appointments.find_one({'_id': appointment['_id']})
                meet_link = updated_appointment.get('meeting_info', {}).get('meet_link')
    
    return meet_link

def _log_session_access(appointment_id: str):
    """Log session access for analytics"""
    mongo.db.appointments.update_one(
        {'_id': ObjectId(appointment_id)},
        {
            '$set': {'last_joined': datetime.now()},
            '$inc': {'join_count': 1}
        }
    )

@dashboard_bp.route('/student/book-specific-slot', methods=['POST'])
@student_required
def book_specific_slot():
    """Enhanced slot booking with license ID support"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    try:
        # Check if user can schedule (one meeting at a time policy)
        can_schedule, reason = can_schedule_appointment(session['user'], mongo.db)
        
        if not can_schedule:
            flash(reason, 'error')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Get form data - support both license_id and therapist_id
        license_id = request.form.get('license_id') or request.form.get('therapist_id')
        selected_date = request.form.get('selected_date')
        selected_time = request.form.get('selected_time')
        
        if not all([license_id, selected_date, selected_time]):
            flash('Please select a valid time slot', 'error')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Get therapist using the helper function
        therapist = get_therapist_by_identifier(license_id)
        if not therapist:
            flash('Therapist not found', 'error')
            return redirect(url_for('dashboard.index'))
        
        # Parse datetime
        selected_datetime = datetime.strptime(f"{selected_date} {selected_time}", "%Y-%m-%d %I:%M %p")
        selected_slot = {
            'datetime': selected_datetime,
            'formatted': selected_datetime.strftime('%A, %B %d at %I:%M %p')
        }
        
        # Create appointment with OAuth Zoom integration
        appointment_id, appointment_doc, zoom_success = AppointmentManager.create_appointment_with_zoom(
            session['user'], therapist, selected_slot, 'normal'
        )
        
        if appointment_id:
            if zoom_success:
                flash('✅ Virtual session scheduled! Zoom meeting created successfully.', 'success')
            else:
                flash('✅ Virtual session scheduled! Meeting details available below.', 'success')
            
            return redirect(url_for('dashboard.appointment_confirmed', 
                                  appointment_id=str(appointment_id)))
        else:
            flash('Failed to schedule virtual session. Please try again.', 'error')
            return redirect(url_for('dashboard.therapist_info'))
            
    except Exception as e:
        logger.error(f"Error booking slot: {str(e)}")
        flash('Error scheduling appointment. Please try again.', 'error')
        return redirect(url_for('dashboard.therapist_info'))
    
# ===== API ROUTES =====

@dashboard_bp.route('/api/auto-schedule-appointment', methods=['POST'])
@login_required
@student_required
def api_auto_schedule_appointment():
    """Enhanced API endpoint for auto-scheduling with better validation"""
    try:
        user_id = session['user']
        
        # Debug logging
        logger.info(f"Auto-schedule request from user {user_id}")
        
        # Check if user can schedule
        can_schedule, reason = can_schedule_appointment(user_id, mongo.db)
        if not can_schedule:
            logger.warning(f"Cannot schedule for user {user_id}: {reason}")
            return jsonify({'error': reason}), 400
        
        # Get license_id from form data (supporting both license_id and therapist_id)
        license_id = request.form.get('license_id') or request.form.get('therapist_id')
        crisis_level = request.form.get('crisis_level', 'normal')
        
        logger.info(f"Received license_id: {license_id}, crisis_level: {crisis_level}")
        
        if not license_id:
            return jsonify({'error': 'Therapist license ID is required'}), 400
        
        # Get therapist using the helper function
        therapist = get_therapist_by_identifier(license_id)
        if not therapist:
            logger.error(f"Therapist not found for license_id: {license_id}")
            return jsonify({'error': 'Therapist not found'}), 404
        
        logger.info(f"Found therapist: {therapist['name']} (License: {therapist['license_number']})")
        
        # Get available slots
        available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
        if not available_slots:
            return jsonify({'error': 'No available slots found'}), 400
        
        logger.info(f"Found {len(available_slots)} available slots")
        
        # Create appointment
        selected_slot = available_slots[0]
        appointment_id, appointment_doc, zoom_success = AppointmentManager.create_appointment_with_zoom(
            user_id, therapist, selected_slot, crisis_level
        )
        
        if appointment_id:
            logger.info(f"Successfully created appointment {appointment_id} with Zoom: {zoom_success}")
            return jsonify({
                'success': True,
                'appointment_id': str(appointment_id),
                'scheduled_time': selected_slot['datetime'].isoformat(),
                'formatted_time': appointment_doc['formatted_time'],
                'zoom_integrated': zoom_success,
                'meeting_link': appointment_doc.get('meeting_info', {}).get('meet_link'),
                'therapist_license': therapist['license_number']
            })
        else:
            logger.error(f"Failed to create appointment for user {user_id}")
            return jsonify({'error': 'Failed to create appointment'}), 500
            
    except Exception as e:
        logger.error(f"Auto-scheduling error for user {session.get('user')}: {str(e)}")
        return jsonify({'error': f'Scheduling failed: {str(e)}'}), 500

@dashboard_bp.route('/api/therapist-availability/<license_id>')
@login_required
def get_therapist_availability(license_id):
    """Get real-time therapist availability by license ID"""
    try:
        therapist = get_therapist_by_identifier(license_id)
        if not therapist:
            return jsonify({'error': 'Therapist not found'}), 404
        
        crisis_level = request.args.get('crisis_level', 'normal')
        available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
        
        slots_data = [
            {
                'date': slot['date'],
                'time': slot['time'],
                'formatted': slot['formatted'],
                'day_name': slot['day_name']
            }
            for slot in available_slots
        ]
        
        return jsonify({
            'therapist_name': therapist['name'],
            'license_number': therapist['license_number'],  # Format: "KE-CL-123456"
            'email': therapist['email'],
            'specializations': therapist.get('specializations', []),
            'rating': therapist.get('rating', 5),
            'phone': therapist.get('phone', ''),
            'emergency_hours': therapist.get('emergency_hours', False),
            'available_slots': slots_data,
            'total_slots': len(slots_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting therapist availability: {str(e)}")
        return jsonify({'error': 'Unable to get availability'}), 500

@dashboard_bp.route('/api/upcoming-session')
def get_upcoming_session():
    """Get student's next upcoming session with Zoom integration status"""
    
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Find next appointment
        next_appointment = mongo.db.appointments.find_one({
            'student_id': ObjectId(session['user']),
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed'
        }, sort=[('datetime', 1)])
        
        if next_appointment:
            therapist = mongo.db.therapists.find_one({'_id': next_appointment['therapist_id']})
            zoom_integrated = is_zoom_integrated(next_appointment.get('zoom_meeting_id'))
            
            return jsonify({
                'has_upcoming': True,
                'appointment': {
                    'id': str(next_appointment['_id']),
                    'datetime': next_appointment['datetime'].isoformat(),
                    'formatted_time': next_appointment.get('formatted_time', 'Time TBD'),
                    'therapist_name': therapist['name'] if therapist else 'N/A',
                    'therapist_license': therapist.get('license_number', 'N/A') if therapist else 'N/A',
                    'type': next_appointment.get('type', 'virtual'),
                    'meeting_link': next_appointment.get('meeting_info', {}).get('meet_link'),
                    'zoom_integrated': zoom_integrated
                }
            })
        
        return jsonify({'has_upcoming': False})
        
    except Exception as e:
        logger.error(f"Error getting upcoming session: {str(e)}")
        return jsonify({'error': 'Unable to get upcoming session'}), 500

@dashboard_bp.route('/api/appointment-status/<appointment_id>')
@login_required
@validate_appointment_access
def get_appointment_status(appointment_id, appointment=None):
    """Get detailed appointment status"""
    try:
        therapist = mongo.db.therapists.find_one({'_id': appointment['therapist_id']})
        zoom_integrated = is_zoom_integrated(appointment.get('zoom_meeting_id'))
        
        status_data = {
            'appointment_id': str(appointment['_id']),
            'status': appointment.get('status'),
            'datetime': appointment['datetime'].isoformat() if appointment.get('datetime') else None,
            'formatted_time': appointment.get('formatted_time'),
            'therapist_name': therapist['name'] if therapist else 'Unknown',
            'therapist_license': therapist.get('license_number', 'Unknown') if therapist else 'Unknown',
            'meeting_link': appointment.get('meeting_info', {}).get('meet_link'),
            'zoom_integrated': zoom_integrated,
            'can_join': False
        }
        
        # Check if session can be joined
        if appointment.get('datetime'):
            now = datetime.now()
            time_diff = (appointment['datetime'] - now).total_seconds() / 60
            status_data['can_join'] = (-APPOINTMENT_CONSTRAINTS['SESSION_JOIN_WINDOW_MINUTES'] <= 
                                     time_diff <= APPOINTMENT_CONSTRAINTS['SESSION_END_BUFFER_MINUTES'])
            status_data['time_until_session'] = int(time_diff) if time_diff > 0 else None
        
        return jsonify(status_data)
        
    except Exception as e:
        logger.error(f"Error getting appointment status: {str(e)}")
        return jsonify({'error': 'Failed to get appointment status'}), 500
    
# ===== ENHANCED API ROUTES =====

@dashboard_bp.route('/api/reschedule-appointment', methods=['POST'])
@login_required
def api_reschedule_appointment():
    """API endpoint to reschedule an appointment with OAuth Zoom integration"""
    
    try:
        appointment_id = request.json.get('appointment_id')
        new_datetime_str = request.json.get('new_datetime')
        
        if not appointment_id or not new_datetime_str:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Parse new datetime
        new_datetime = datetime.fromisoformat(new_datetime_str.replace('Z', '+00:00'))
        
        # Get existing appointment
        appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
        if not appointment:
            return jsonify({'error': 'Appointment not found'}), 404
        
        # Update appointment in database
        update_data = {
            'datetime': new_datetime,
            'formatted_time': new_datetime.strftime('%A, %B %d at %I:%M %p'),
            'updated_at': datetime.utcnow()
        }
        
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': update_data}
        )
        
        # Update OAuth Zoom meeting if integrated
        zoom_success = False
        if appointment.get('zoom_meeting_id') and not str(appointment['zoom_meeting_id']).startswith('fallback'):
            zoom_success = update_zoom_meeting_in_appointment(ObjectId(appointment_id), new_datetime)
            
            if not zoom_success:
                logger.warning(f"Failed to update OAuth Zoom meeting for appointment {appointment_id}")
        
        return jsonify({
            'success': True,
            'message': 'Appointment rescheduled successfully',
            'zoom_updated': zoom_success,
            'new_time': update_data['formatted_time']
        })
        
    except Exception as e:
        logger.error(f"Error rescheduling appointment: {str(e)}")
        return jsonify({'error': 'Failed to reschedule appointment'}), 500

@dashboard_bp.route('/api/cancel-appointment', methods=['POST'])
@login_required
def api_cancel_appointment():
    """API endpoint to cancel an appointment with OAuth Zoom integration"""
    
    try:
        appointment_id = request.json.get('appointment_id')
        cancellation_reason = request.json.get('reason', 'Student cancellation')
        
        if not appointment_id:
            return jsonify({'error': 'Appointment ID required'}), 400
        
        # Get existing appointment
        appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
        if not appointment:
            return jsonify({'error': 'Appointment not found'}), 404
        
        # Update appointment status
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {
                    'status': 'cancelled',
                    'cancellation_reason': cancellation_reason,
                    'cancelled_at': datetime.utcnow()
                }
            }
        )
        
        # Cancel OAuth Zoom meeting if integrated
        zoom_success = False
        if appointment.get('zoom_meeting_id') and not str(appointment['zoom_meeting_id']).startswith('fallback'):
            zoom_success = cancel_zoom_meeting_in_appointment(ObjectId(appointment_id))
            
            if not zoom_success:
                logger.warning(f"Failed to cancel OAuth Zoom meeting for appointment {appointment_id}")
        
        return jsonify({
            'success': True,
            'message': 'Appointment cancelled successfully',
            'zoom_cancelled': zoom_success
        })
        
    except Exception as e:
        logger.error(f"Error cancelling appointment: {str(e)}")
        return jsonify({'error': 'Failed to cancel appointment'}), 500

@dashboard_bp.route('/api/zoom-integration-status')
@login_required
def get_zoom_integration_status():
    """Get the status of OAuth Zoom integration for the system"""
    
    try:
        from wellbeing.utils.zoom_integration import ZoomMeetingManager
        
        zoom_manager = ZoomMeetingManager()
        has_credentials = bool(zoom_manager.client_id and zoom_manager.client_secret and zoom_manager.account_id)
        
        # Test OAuth functionality
        test_result = None
        if has_credentials:
            try:
                token = zoom_manager.get_access_token()
                test_result = bool(token)
            except Exception as e:
                test_result = False
                logger.error(f"OAuth Zoom integration test failed: {str(e)}")
        
        return jsonify({
            'zoom_credentials_available': has_credentials,
            'zoom_oauth_functional': test_result,
            'fallback_mode': not has_credentials or not test_result
        })
        
    except Exception as e:
        logger.error(f"Error checking OAuth Zoom integration: {str(e)}")
        return jsonify({
            'zoom_credentials_available': False,
            'zoom_oauth_functional': False,
            'fallback_mode': True,
            'error': str(e)
        }), 500

@dashboard_bp.route('/api/refresh-zoom-meeting', methods=['POST'])
@login_required
def refresh_zoom_meeting():
    """Refresh OAuth Zoom meeting for an appointment"""
    
    try:
        appointment_id = request.json.get('appointment_id')
        
        if not appointment_id:
            return jsonify({'error': 'Appointment ID required'}), 400
        
        # Refresh the Zoom meeting
        success = refresh_zoom_meeting_for_appointment(ObjectId(appointment_id))
        
        if success:
            # Get updated appointment
            appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            meeting_info = appointment.get('meeting_info', {})
            
            return jsonify({
                'success': True,
                'message': 'Zoom meeting refreshed successfully',
                'meeting_link': meeting_info.get('meet_link'),
                'zoom_integrated': True
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to refresh Zoom meeting',
                'zoom_integrated': False
            })
        
    except Exception as e:
        logger.error(f"Error refreshing Zoom meeting: {str(e)}")
        return jsonify({'error': 'Failed to refresh Zoom meeting'}), 500

@dashboard_bp.route('/api/therapist-profile/<license_id>')
@login_required
def get_therapist_profile(license_id):
    """Get complete therapist profile by license ID"""
    
    try:
        therapist = get_therapist_by_identifier(license_id)
        if not therapist:
            return jsonify({'error': 'Therapist not found'}), 404
        
        # Format therapist data for API response
        profile_data = {
            'id': str(therapist['_id']),
            'license_number': therapist['license_number'],
            'name': therapist['name'],
            'email': therapist['email'],
            'phone': therapist.get('phone', ''),
            'gender': therapist.get('gender', ''),
            'bio': therapist.get('bio', ''),
            'specializations': therapist.get('specializations', []),
            'rating': therapist.get('rating', 5),
            'total_sessions': therapist.get('total_sessions', 0),
            'years_experience': therapist.get('years_experience', 0),
            'emergency_hours': therapist.get('emergency_hours', False),
            'max_students': therapist.get('max_students', 25),
            'current_students': therapist.get('current_students', 0),
            'availability': therapist.get('availability', {}),
            'status': therapist.get('status', 'active'),
            'created_at': therapist.get('created_at').isoformat() if therapist.get('created_at') else None
        }
        
        return jsonify({
            'success': True,
            'therapist': profile_data
        })
        
    except Exception as e:
        logger.error(f"Error getting therapist profile: {str(e)}")
        return jsonify({'error': 'Unable to get therapist profile'}), 500

@dashboard_bp.route('/api/validate-appointment-time', methods=['POST'])
@login_required
def validate_appointment_time():
    """Validate if appointment time is available and within constraints"""
    
    try:
        data = request.get_json()
        license_id = data.get('license_id')
        proposed_datetime = data.get('datetime')
        
        if not license_id or not proposed_datetime:
            return jsonify({'error': 'License ID and datetime are required'}), 400
        
        # Parse datetime
        appointment_dt = datetime.fromisoformat(proposed_datetime)
        
        # Get therapist
        therapist = get_therapist_by_identifier(license_id)
        if not therapist:
            return jsonify({'error': 'Therapist not found'}), 404
        
        # Validate timing constraints
        now = datetime.now()
        min_advance = now + timedelta(hours=APPOINTMENT_CONSTRAINTS['MIN_ADVANCE_HOURS'])
        max_advance = now + timedelta(days=APPOINTMENT_CONSTRAINTS['MAX_ADVANCE_DAYS'])
        
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        if appointment_dt <= min_advance:
            validation_result['valid'] = False
            validation_result['errors'].append(f'Appointment must be at least {APPOINTMENT_CONSTRAINTS["MIN_ADVANCE_HOURS"]} hours in the future')
        
        if appointment_dt > max_advance:
            validation_result['valid'] = False
            validation_result['errors'].append(f'Appointment cannot be more than {APPOINTMENT_CONSTRAINTS["MAX_ADVANCE_DAYS"]} days in the future')
        
        # Check business hours
        if BUSINESS_HOURS['weekdays_only'] and appointment_dt.weekday() >= 5:
            validation_result['warnings'].append('Weekend appointments may have limited availability')
        
        hour = appointment_dt.hour
        if hour < BUSINESS_HOURS['start'] or hour >= BUSINESS_HOURS['end']:
            validation_result['warnings'].append('Appointment is outside normal business hours')
        
        # Check for conflicts
        existing_appointment = mongo.db.appointments.find_one({
            'therapist_id': therapist['_id'],
            'datetime': {
                '$gte': appointment_dt - timedelta(minutes=30),
                '$lte': appointment_dt + timedelta(minutes=30)
            },
            'status': {'$nin': ['cancelled', 'completed']}
        })
        
        if existing_appointment:
            validation_result['valid'] = False
            validation_result['errors'].append('Therapist is not available at this time')
        
        return jsonify(validation_result)
        
    except Exception as e:
        logger.error(f"Error validating appointment time: {str(e)}")
        return jsonify({'error': 'Unable to validate appointment time'}), 500

# ===== UTILITY FUNCTIONS =====

def find_next_available_slot(therapist_id: str) -> Optional[datetime]:
    """Find the next available appointment slot for a therapist"""
    
    try:
        # Get existing appointments for this therapist
        existing_appointments = list(mongo.db.appointments.find({
            'therapist_id': ObjectId(therapist_id),
            'status': {'$in': ['confirmed', 'suggested']},
            'datetime': {'$gte': datetime.now()}
        }))
        
        # Extract busy times
        busy_times = [apt['datetime'] for apt in existing_appointments]
        
        # Start looking from tomorrow
        current_date = datetime.now() + timedelta(days=1)
        
        for day_offset in range(APPOINTMENT_CONSTRAINTS['MAX_ADVANCE_DAYS']):
            check_date = current_date + timedelta(days=day_offset)
            
            # Skip weekends if configured
            if BUSINESS_HOURS['weekdays_only'] and check_date.weekday() >= 5:
                continue
                
            # Check each hour in business hours
            for start_hour in range(BUSINESS_HOURS['start'], BUSINESS_HOURS['end']):
                slot_time = check_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
                
                # Check if this slot is available (not within 1 hour of existing appointments)
                slot_available = True
                for busy_time in busy_times:
                    time_diff = abs((slot_time - busy_time).total_seconds()) / 3600  # Convert to hours
                    if time_diff < 1:  # Less than 1 hour difference
                        slot_available = False
                        break
                
                if slot_available:
                    return slot_time
        
        # If no slot found, return a default time (next Monday at 2 PM)
        next_monday = datetime.now() + timedelta(days=(7 - datetime.now().weekday()))
        return next_monday.replace(hour=14, minute=0, second=0, microsecond=0)
        
    except Exception as e:
        logger.error(f"Error finding next available slot: {str(e)}")
        return None

def force_virtual_meetings():
    """Helper function to ensure all appointments are virtual with Zoom integration status"""
    try:
        # Update any existing appointments to be virtual
        result = mongo.db.appointments.update_many(
            {},  # All appointments
            {
                '$set': {
                    'type': 'virtual',
                    'virtual_only_policy': True
                }
            }
        )
        
        # Ensure all virtual appointments have meeting_info
        appointments_without_meeting = mongo.db.appointments.find({
            'type': 'virtual',
            'meeting_info': {'$exists': False}
        })
        
        for apt in appointments_without_meeting:
            meeting_info = create_enhanced_fallback_meeting_link(
                f"Therapy Session - {apt.get('crisis_level', 'normal').title()}",
                apt.get('datetime')
            )
            mongo.db.appointments.update_one(
                {'_id': apt['_id']},
                {'$set': {'meeting_info': meeting_info}}
            )
        
        logger.info(f"Updated {result.modified_count} appointments to virtual with Zoom integration")
        
    except Exception as e:
        logger.error(f"Error forcing virtual meetings: {str(e)}")

def migrate_to_zoom_integration():
    """Helper function to migrate existing appointments to use Zoom integration"""
    try:
        # Find appointments with Google Meet links
        google_meet_appointments = mongo.db.appointments.find({
            'meeting_info.platform': {'$in': ['Google Meet', 'Google Calendar']}
        })
        
        migrated_count = 0
        for apt in google_meet_appointments:
            # Try to create a new Zoom meeting for this appointment
            if apt.get('student_id') and apt.get('therapist_id'):
                student = mongo.db.users.find_one({'_id': apt['student_id']})
                therapist = mongo.db.therapists.find_one({'_id': apt['therapist_id']})
                
                if student and therapist and student.get('email') and therapist.get('email'):
                    # Create OAuth Zoom meeting
                    zoom_appointment_data = {
                        'datetime': apt.get('datetime', datetime.now() + timedelta(hours=1)),
                        'crisis_level': apt.get('crisis_level', 'normal'),
                        'notes': apt.get('notes', 'Migrated appointment'),
                        'appointment_id': str(apt['_id'])
                    }
                    
                    try:
                        success, result = create_zoom_therapy_meeting(
                            zoom_appointment_data, 
                            student['email'], 
                            therapist['email']
                        )
                        
                        if success and result.get('created_method') == 'zoom_oauth':
                            # Update appointment with Zoom info
                            mongo.db.appointments.update_one(
                                {'_id': apt['_id']},
                                {
                                    '$set': {
                                        'zoom_meeting_id': result.get('zoom_meeting_id'),
                                        'meeting_info': {
                                            'meet_link': result.get('meet_link'),
                                            'host_link': result.get('host_link'),
                                            'platform': 'Zoom',
                                            'meeting_password': result.get('meeting_password'),
                                            'dial_in': result.get('dial_in'),
                                            'meeting_uuid': result.get('meeting_uuid'),
                                            'created_method': 'migration'
                                        },
                                        'zoom_integrated': True,
                                        'migrated_to_zoom': True,
                                        'migration_date': datetime.utcnow()
                                    }
                                }
                            )
                            migrated_count += 1
                            logger.info(f"Migrated appointment {apt['_id']} to OAuth Zoom")
                    except Exception as e:
                        logger.error(f"Failed to migrate appointment {apt['_id']}: {str(e)}")
        
        logger.info(f"Successfully migrated {migrated_count} appointments to OAuth Zoom integration")
        return migrated_count
        
    except Exception as e:
        logger.error(f"Error during Zoom migration: {str(e)}")
        return 0

def cleanup_expired_appointments():
    """Clean up expired and old appointments"""
    try:
        # Mark appointments as completed if they're more than 2 hours past
        cutoff_time = datetime.now() - timedelta(hours=2)
        
        result = mongo.db.appointments.update_many(
            {
                'datetime': {'$lt': cutoff_time},
                'status': 'confirmed'
            },
            {
                '$set': {
                    'status': 'completed',
                    'auto_completed': True,
                    'completed_at': datetime.now()
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Auto-completed {result.modified_count} expired appointments")
        
        return result.modified_count
        
    except Exception as e:
        logger.error(f"Error cleaning up expired appointments: {str(e)}")
        return 0

def get_system_health_status():
    """Get system health status for monitoring"""
    try:
        status = {
            'database_connection': True,
            'zoom_integration': False,
            'total_appointments': 0,
            'active_appointments': 0,
            'total_therapists': 0,
            'active_therapists': 0,
            'total_students': 0,
            'timestamp': datetime.now().isoformat()
        }
        
        # Test database connection
        try:
            status['total_appointments'] = mongo.db.appointments.count_documents({})
            status['active_appointments'] = mongo.db.appointments.count_documents({
                'status': 'confirmed',
                'datetime': {'$gte': datetime.now()}
            })
            status['total_therapists'] = mongo.db.therapists.count_documents({})
            status['active_therapists'] = mongo.db.therapists.count_documents({'status': 'active'})
            status['total_students'] = mongo.db.users.count_documents({'role': 'student'})
        except Exception as e:
            status['database_connection'] = False
            logger.error(f"Database health check failed: {str(e)}")
        
        # Test Zoom integration
        try:
            from wellbeing.utils.zoom_integration import ZoomMeetingManager
            zoom_manager = ZoomMeetingManager()
            if zoom_manager.client_id and zoom_manager.client_secret:
                status['zoom_integration'] = True
        except Exception as e:
            logger.error(f"Zoom integration health check failed: {str(e)}")
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting system health status: {str(e)}")
        return {'error': str(e), 'timestamp': datetime.now().isoformat()}

# ===== ADMIN/DEBUG ROUTES (for development) =====
@dashboard_bp.route('/api/system-health')
@login_required
def api_system_health():
    """Get system health status (admin only in production)"""
    # In production, add admin role check here
    try:
        health_status = get_system_health_status()
        return jsonify(health_status)
    except Exception as e:
        logger.error(f"Error getting system health: {str(e)}")
        return jsonify({'error': 'Unable to get system health'}), 500

@dashboard_bp.route('/api/cleanup-appointments', methods=['POST'])
@login_required
def api_cleanup_appointments():
    """Clean up expired appointments (admin only in production)"""
    # In production, add admin role check here
    try:
        cleaned_count = cleanup_expired_appointments()
        return jsonify({
            'success': True,
            'message': f'Cleaned up {cleaned_count} expired appointments'
        })
    except Exception as e:
        logger.error(f"Error cleaning up appointments: {str(e)}")
        return jsonify({'error': 'Unable to clean up appointments'}), 500

@dashboard_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Handle form submission (for profile updates)
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Basic validation
            errors = []
            
            # Names cannot be changed
            if first_name and first_name != user.get('first_name', ''):
                errors.append('First name cannot be changed.')
                
            if last_name and last_name != user.get('last_name', ''):
                errors.append('Last name cannot be changed.')
            
            # Email cannot be changed
            if email and email != user.get('email', ''):
                errors.append('Email cannot be changed.')
            
            # Password validation - always require current password verification
            if new_password or confirm_password:
                from werkzeug.security import check_password_hash, generate_password_hash
                
                # First check if current password was provided
                if not current_password:
                    errors.append('Current password is required to change your password.')
                else:
                    # Verify current password is correct before allowing password change
                    if not check_password_hash(user.get('password', ''), current_password):
                        errors.append('Current password is incorrect.')
                    else:
                        # Current password is correct, now validate the new password
                        if not new_password:
                            errors.append('New password is required.')
                        elif len(new_password) < 8:
                            errors.append('New password must be at least 8 characters.')
                        
                        if new_password != confirm_password:
                            errors.append('New passwords do not match.')
            
            # If there are validation errors, flash them and redirect
            if errors:
                for error in errors:
                    flash(error, 'error')
                return redirect(url_for('dashboard.profile'))
            
            # Prepare update data
            update_data = {}
            
            # Password change (only if current password is provided and verified)
            if current_password and new_password and check_password_hash(user.get('password', ''), current_password):
                update_data['password'] = generate_password_hash(new_password)
            
            # Update user data if there are changes
            if update_data:
                mongo.db.users.update_one(
                    {'_id': user_id},
                    {'$set': update_data}
                )
                flash('Password updated successfully!', 'success')
                
                # Refresh user data after update
                user = find_user_by_id(user_id)
            else:
                flash('No changes detected.', 'info')
                
        except Exception as e:
            logger.error(f"Profile update error: {e}")
            flash('An error occurred while updating your profile.', 'error')
    
    # Create options for statistics or additional info
    activity_stats = {
        'login_count': user.get('login_count', 0),
        'last_login': user.get('last_login', 'Never'),
        'registration_date': user.get('created_at', 'Unknown')
    }
    
    # Get user's recent activity (mood entries and other tracked actions)
    recent_activity = list(mongo.db.moods.find(
        {"user_id": str(user_id)}
    ).sort("timestamp", -1).limit(5))

    settings = mongo.db.settings.find_one()
    
    return render_template('profile.html', 
                          user=user, 
                          stats=activity_stats,
                          activity=recent_activity,
                          settings=settings)

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings page."""
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get or initialize user settings
    user_settings = user.get('settings', {})
    
    # Default settings if none exist
    if not user_settings:
        user_settings = {
            'text_size': 'md',
            'contrast': 'normal',
            'theme_mode': 'light',
            'widgets': ['mood_tracker', 'quick_actions', 'resources', 'progress'],
            'default_view': 'dashboard',
            'reminder_time': '09:00',
            'checkin_frequency': 'weekdays'
        }
        
        # Update user with default settings
        update_user_settings(user_id, user_settings)
    
    # Handle form submissions
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        try:
            if form_type == 'accessibility':
                # Update accessibility settings
                user_settings['text_size'] = request.form.get('text_size')
                user_settings['contrast'] = request.form.get('contrast')
                flash('Accessibility settings updated successfully!', 'success')
            
            elif form_type == 'theme':
                # Update theme settings
                user_settings['theme_mode'] = request.form.get('theme_mode')
                flash('Theme settings updated successfully!', 'success')
            
            elif form_type == 'dashboard':
                # Update dashboard settings
                widgets = request.form.getlist('widgets')
                if not widgets:
                    # Ensure at least one widget is selected
                    widgets = ['mood_tracker']
                
                user_settings['widgets'] = widgets
                user_settings['default_view'] = request.form.get('default_view')
                flash('Dashboard settings updated successfully!', 'success')
            
            elif form_type == 'reminders':
                # Update reminder settings
                user_settings['reminder_time'] = request.form.get('reminder_time')
                user_settings['checkin_frequency'] = request.form.get('checkin_frequency')
                flash('Reminder settings updated successfully!', 'success')
            
            # Save updated settings to database
            update_user_settings(user_id, user_settings)
            
        except Exception as e:
            logger.error(f"Settings update error: {e}")
            flash('An error occurred while updating settings.', 'error')
    
    return render_template('settings.html', user=user, settings=user_settings)


@dashboard_bp.route('/download_data')
@login_required
def download_data():
    """Download user data in CSV format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Create CSV file in memory
        memory_file = io.StringIO()
        writer = csv.writer(memory_file)
        
        # Write user profile data
        writer.writerow(['Profile Information'])
        writer.writerow(['First Name', 'Last Name', 'Email', 'Student ID', 'Role', 'Created At'])
        writer.writerow([
            user.get('first_name', ''),
            user.get('last_name', ''),
            user.get('email', ''),
            user.get('student_id', ''),
            user.get('role', ''),
            user.get('created_at', datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write mood data
        writer.writerow(['Mood Tracking History'])
        writer.writerow(['Date', 'Mood', 'Notes'])
        
        moods = mongo.db.moods.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for mood in moods:
            writer.writerow([
                mood.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                mood.get('mood', ''),
                mood.get('context', '')
            ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write chat history
        writer.writerow(['Recent Conversations'])
        writer.writerow(['Date', 'Message'])
        
        chats = mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for chat in chats:
            writer.writerow([
                chat.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                chat.get('message', '')
            ])
        
        # Prepare response
        memory_file.seek(0)
        return Response(
            memory_file.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    
    except Exception as e:
        logger.error(f"Data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/download_data_json')
@login_required
def download_data_json():
    """Download user data in JSON format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Helper function to handle ObjectId and datetime serialization
        def json_serial(obj):
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # Create a copy of user data without password
        user_data = {k: v for k, v in user.items() if k != 'password'}
        
        # Get mood data
        moods = list(mongo.db.moods.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Get chat data
        chats = list(mongo.db.chats.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Combine all data
        export_data = {
            'profile': user_data,
            'moods': moods,
            'chats': chats
        }
        
        # Convert to JSON
        json_data = json.dumps(export_data, default=json_serial, indent=4)
        
        # Prepare response
        return Response(
            json_data,
            mimetype="application/json",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.json"}
        )
    
    except Exception as e:
        logger.error(f"JSON data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))
@dashboard_bp.route('/student_resources')
@login_required
def student_resources():
    """Student resources page."""
    # Get user from database
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get user settings
    settings = user.get('settings', {})
    
    # Handle search query if present
    search_query = request.args.get('query', '').strip()
    
    # Get category/type filter if present
    resource_type = request.args.get('type', '')
    
    try:
        # Build query for resources
        query = {}
        
        if search_query:
            # Search in title and description
            query['$or'] = [
                {'title': {'$regex': search_query, '$options': 'i'}},
                {'description': {'$regex': search_query, '$options': 'i'}}
            ]
        
        if resource_type:
            query['resource_type'] = resource_type
        
        # Get resources (sorted by most recently added)
        resources = list(mongo.db.resources.find(query).sort('created_at', -1))
        
        # Get unique resource types for filtering
        resource_types = mongo.db.resources.distinct('resource_type')
        
        # Log this page visit
        mongo.db.user_activity.insert_one({
            'user_id': str(user_id),
            'activity_type': 'resource_page_view',
            'timestamp': datetime.now()  # Fixed: removed the extra datetime
        })
    
    except Exception as e:
        logger.error(f"Error fetching student resources: {e}")
        flash('An error occurred while loading resources.', 'error')
        resources = []
        resource_types = []
    
    return render_template(
        'student_resources.html',
        user=user,
        settings=settings,
        resources=resources,
        resource_types=resource_types,
        search_query=search_query,
        selected_type=resource_type
    )


@dashboard_bp.route('/student_resources/<resource_id>')
@login_required
def student_resource_detail(resource_id):
    """Detail page for a specific student resource."""
    # Get user from database
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get user settings
    settings = user.get('settings', {})
    
    try:
        # Get the specific resource
        resource = mongo.db.resources.find_one({'_id': ObjectId(resource_id)})
        
        if not resource:
            flash('Resource not found.', 'error')
            return redirect(url_for('dashboard.student_resources'))
        
        # Get related resources (same resource type, up to 3)
        if resource.get('resource_type'):
            related_resources = list(mongo.db.resources.find({
                'resource_type': resource.get('resource_type'),
                '_id': {'$ne': ObjectId(resource_id)}
            }).limit(3))
        else:
            related_resources = list(mongo.db.resources.find({
                '_id': {'$ne': ObjectId(resource_id)}
            }).limit(3))
        
        # Log this resource view
        mongo.db.user_activity.insert_one({
            'user_id': str(user_id),
            'activity_type': 'resource_view',
            'resource_id': resource_id,
            'timestamp': datetime.now()  # Fixed: removed the extra datetime
        })
        
    except Exception as e:
        logger.error(f"Error fetching resource details: {e}")
        flash('An error occurred while loading the resource.', 'error')
        return redirect(url_for('dashboard.student_resources'))
    
    return render_template(
        'student_resource_detail.html',
        user=user,
        settings=settings,
        resource=resource,
        related_resources=related_resources
    )


@dashboard_bp.route('/chat')
@login_required
@student_required
def student_chat():
    """Student chat with assigned therapist"""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get assigned therapist
    assigned_therapist = _get_assigned_therapist(user)
    if not assigned_therapist:
        flash('You need to complete intake and be assigned a therapist before chatting.', 'warning')
        return redirect(url_for('dashboard.index'))
    
    therapist_id = assigned_therapist['therapist_id']
    
    # Get chat history
    chat_history = list(mongo.db.therapist_chats.find({
        'student_id': user_id,
        'therapist_id': therapist_id
    }).sort('timestamp', 1))
    
    # Mark therapist messages as read
    mongo.db.therapist_chats.update_many(
        {
            'student_id': user_id,
            'therapist_id': therapist_id,
            'sender': 'therapist',
            'read': False
        },
        {'$set': {'read': True, 'read_at': datetime.now()}}
    )
    
    # Get upcoming appointments
    upcoming_appointments = list(mongo.db.appointments.find({
        'student_id': user_id,
        'therapist_id': therapist_id,
        'datetime': {'$gte': datetime.now()},
        'status': 'confirmed'
    }).sort('datetime', 1))
    
    # Get shared resources
    shared_resources = list(mongo.db.shared_resources.find({
        'student_id': user_id,
        'therapist_id': therapist_id
    }).sort('shared_at', -1).limit(10))
    
    return render_template('student/chat.html',
                         user=user,
                         therapist=assigned_therapist['therapist'],
                         chat_history=chat_history,
                         upcoming_appointments=upcoming_appointments,
                         shared_resources=shared_resources)

@dashboard_bp.route('/send-message-to-therapist', methods=['POST'])
@login_required
@student_required
def send_message_to_therapist():
    """Send message with fully automated moderation - no manual approval needed"""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        return jsonify({'success': False, 'error': 'User not found'})
    
    # Get assigned therapist
    assigned_therapist = _get_assigned_therapist(user)
    if not assigned_therapist:
        return jsonify({'success': False, 'error': 'No therapist assigned'})
    
    therapist_id = str(assigned_therapist['therapist_id'])
    message = request.form.get('message', '').strip()
    
    if not message:
        return jsonify({'success': False, 'error': 'Message cannot be empty'})
    
    try:
        # Send through automated moderation (instant decision)
        result = send_auto_moderated_message(
            sender_id=str(user_id),
            recipient_id=therapist_id,
            message=message,
            sender_type='student'
        )
        
        if not result['success']:
            # Message was blocked by automation
            response = {
                'success': False,
                'blocked': result.get('blocked', False),
                'error': result.get('reason', 'Message could not be sent'),
                'auto_response': result.get('auto_response')
            }
            
            # Log the blocking for user feedback
            if result.get('flags'):
                logger.info(f"Student message blocked - User: {user_id}, Flags: {result['flags']}")
            
            return jsonify(response)
        
        # Message sent successfully (may have been filtered)
        response = {
            'success': True,
            'message': {
                'id': result['message_id'],
                'content': message,  # Show original to user
                'timestamp': datetime.now().strftime('%I:%M %p | %b %d'),
                'was_filtered': result.get('filtered', False)
            }
        }
        
        # Add automated responses and warnings
        notifications = []
        
        if result.get('auto_response'):
            notifications.append({
                'type': 'info',
                'message': result['auto_response']
            })
        
        if result.get('warnings'):
            for warning in result['warnings']:
                notifications.append({
                    'type': 'warning',
                    'message': warning
                })
        
        if result.get('filtered'):
            notifications.append({
                'type': 'info',
                'message': 'Some content was automatically filtered for appropriateness.'
            })
        
        if notifications:
            response['notifications'] = notifications
        
        # Special handling for crisis detection
        flags = result.get('flags', [])
        if any('crisis' in flag for flag in flags):
            response['crisis_detected'] = True
            response['priority_message'] = True
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Automated message send error: {e}")
        return jsonify({
            'success': False, 
            'error': 'An error occurred while sending the message'
        })

@dashboard_bp.route('/api/chat-status')
@login_required
@student_required
def get_chat_status():
    """Get chat status and unread message count"""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    assigned_therapist = _get_assigned_therapist(user)
    if not assigned_therapist:
        return jsonify({
            'has_therapist': False,
            'unread_messages': 0
        })
    
    therapist_id = assigned_therapist['therapist_id']
    
    # Count unread messages from therapist
    unread_count = mongo.db.therapist_chats.count_documents({
        'student_id': user_id,
        'therapist_id': therapist_id,
        'sender': 'therapist',
        'read': False
    })
    
    return jsonify({
        'has_therapist': True,
        'therapist_name': assigned_therapist['therapist_name'],
        'unread_messages': unread_count
    })

@dashboard_bp.route('/api/get-recent-messages')
@login_required
@student_required  
def get_recent_messages():
    """Get recent chat messages for real-time updates"""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    assigned_therapist = _get_assigned_therapist(user)
    if not assigned_therapist:
        return jsonify({'messages': []})
    
    therapist_id = assigned_therapist['therapist_id']
    since = request.args.get('since')
    
    query = {
        'student_id': user_id,
        'therapist_id': therapist_id
    }
    
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query['timestamp'] = {'$gt': since_dt}
        except:
            pass
    
    messages = list(mongo.db.therapist_chats.find(query).sort('timestamp', -1).limit(20))
    
    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            'id': str(msg['_id']),
            'sender': msg['sender'],
            'message': msg['message'],
            'timestamp': msg['timestamp'].isoformat(),
            'formatted_time': msg['timestamp'].strftime('%I:%M %p | %b %d')
        })
    
    return jsonify({'messages': formatted_messages})
@dashboard_bp.route('/api/moderation-status')
@login_required
def get_moderation_status():
    """Get real-time moderation status for user"""
    user_id = str(session['user'])
    user_type = 'student' if session.get('role') == 'student' else 'therapist'
    
    try:
        # Check if user can send messages right now
        can_send = AutomatedModerator._check_rate_limits(user_id, user_type)
        
        # Get recent moderation actions for this user
        recent_actions = list(mongo.db.automated_moderation_log.find({
            'sender_id': ObjectId(user_id),
            'timestamp': {'$gte': datetime.now() - timedelta(hours=1)}
        }).sort('timestamp', -1).limit(5))
        
        # Count messages in last hour
        hour_ago = datetime.now() - timedelta(hours=1)
        recent_message_count = mongo.db.therapist_chats.count_documents({
            f'{user_type}_id': ObjectId(user_id),
            'timestamp': {'$gte': hour_ago}
        })
        
        # Check for any active crisis alerts
        active_crisis = mongo.db.crisis_alerts.find_one({
            'student_id': ObjectId(user_id) if user_type == 'student' else None,
            'therapist_id': ObjectId(user_id) if user_type == 'therapist' else None,
            'status': {'$in': ['auto_escalated', 'pending_review']},
            'created_at': {'$gte': datetime.now() - timedelta(hours=24)}
        })
        
        status = {
            'can_send_message': can_send,
            'rate_limit_status': 'ok' if can_send else 'limited',
            'messages_sent_last_hour': recent_message_count,
            'recent_flags': [action.get('flags', []) for action in recent_actions],
            'has_active_crisis_alert': bool(active_crisis),
            'business_hours': AutomatedModerator._is_business_hours(),
            'system_status': 'automated_moderation_active'
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error getting moderation status: {e}")
        return jsonify({
            'can_send_message': True,  # Fail open
            'rate_limit_status': 'unknown',
            'system_status': 'error'
        })
