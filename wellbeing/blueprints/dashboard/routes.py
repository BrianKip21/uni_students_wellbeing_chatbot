from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timezone, timedelta
import csv
import io
import uuid
import json
from wellbeing.blueprints.dashboard import dashboard_bp
from wellbeing.utils.decorators import login_required
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
    create_google_meet_link,
    schedule_appointment_automatically
)

# ===== MAIN DASHBOARD ROUTE =====

@dashboard_bp.route('/dashboard') 
@login_required
def index():
    """Dashboard index page with user's overview and intake status"""
    
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Check if we should redirect based on default view
    requested_view = request.args.get('view')
    if not requested_view and settings.get('default_view') != 'dashboard':
        default_view = settings.get('default_view')
        if default_view == 'calendar':
            return redirect(url_for('tracking.index'))
        elif default_view == 'list':
            return redirect(url_for('tracking.list_view'))
    
    # Initialize progress if it doesn't exist
    if 'progress' not in user:
        user['progress'] = {
            'meditation': 0,
            'exercise': 0
        }
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'progress': user['progress']}}
        )
    
    # Fetch recent chats for the user
    recent_chats = list(mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1).limit(5))
    
    # Fetch recommended resources
    recommended_resources = list(mongo.db.resources.find().limit(2))
    
    # Get latest mood data
    latest_mood = mongo.db.moods.find_one({"user_id": str(user_id)}, sort=[("timestamp", -1)])
    
    # Check if student has completed intake assessment
    intake_completed = mongo.db.intake_assessments.find_one({
        'student_id': user_id
    })
    
    # Check for assigned therapist
    assigned_therapist = None
    if user.get('assigned_therapist_id'):
        therapist = mongo.db.therapists.find_one({'_id': user['assigned_therapist_id']})
        if therapist:
            assigned_therapist = {
                'therapist_id': therapist['_id'],
                'therapist_name': therapist['name'],
                'therapist': therapist,
                'status': 'active'
            }
    
    # Get next upcoming appointment
    next_appointment = None
    if assigned_therapist:
        next_appointment = mongo.db.appointments.find_one({
            'student_id': user_id,
            'status': {'$in': ['confirmed', 'suggested']},
            'datetime': {'$gte': datetime.now()}
        }, sort=[('datetime', 1)])
    
    # Intake status for dashboard display
    intake_status = {
        'completed': bool(intake_completed),
        'has_therapist': bool(assigned_therapist)
    }
    
    return render_template('dashboard.html',
                         user=user,
                         settings=settings,
                         recent_chats=recent_chats,
                         resources=recommended_resources,
                         latest_mood=latest_mood,
                         assigned_therapist=assigned_therapist,
                         intake_status=intake_status,
                         intake_completed=intake_completed,
                         next_appointment=next_appointment)

# ===== INTAKE ROUTES =====

@dashboard_bp.route('/student/intake', methods=['GET', 'POST'])
def student_intake():
    """Enhanced intake with immediate scheduling - VIRTUAL ONLY"""
    
    if 'user' not in session or session.get('role') != 'student':
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        # Get form data - FORCE virtual appointment type
        form_data = {
            'primary_concern': request.form.get('primary_concern'),
            'description': request.form.get('description'),
            'severity': request.form.get('severity'),
            'duration': request.form.get('duration'),
            'previous_therapy': request.form.get('previous_therapy'),
            'therapist_gender': request.form.get('therapist_gender'),
            'appointment_type': 'virtual',  # FORCE VIRTUAL - ignore user input
            'crisis_indicators': request.form.getlist('crisis_indicators'),
            'emergency_contact_name': request.form.get('emergency_contact_name'),
            'emergency_contact_phone': request.form.get('emergency_contact_phone'),
            'emergency_contact_relationship': request.form.get('emergency_contact_relationship')
        }
        
        # Validate form
        is_valid, errors = validate_intake_form(form_data)
        if not is_valid:
            for error in errors:
                flash(f'Please fix: {error}', 'error')
            return render_template('student/intake.html')
        
        # Prepare intake data
        intake_data = {
            'student_id': ObjectId(session['user']),
            **form_data,
            'severity': int(form_data['severity']),
            'created_at': datetime.now()
        }
        
        # Crisis detection
        crisis_result = detect_crisis_level(intake_data)
        crisis_level = crisis_result['level']
        
        # Find therapist immediately
        therapist = assign_therapist_immediately(intake_data)
        
        if therapist:
            # AUTO-SCHEDULE VIRTUAL APPOINTMENT
            appointment_id, appointment = auto_schedule_best_time(
                ObjectId(session['user']),
                therapist,
                'virtual',  # FORCE VIRTUAL
                crisis_level
            )
            
            if appointment_id:
                # Save everything to database
                intake_data['assigned_therapist_id'] = therapist['_id']
                intake_data['crisis_level'] = crisis_level
                intake_data['appointment_id'] = appointment_id
                intake_data['auto_scheduled'] = True
                mongo.db.intake_assessments.insert_one(intake_data)
                
                # Update student record
                mongo.db.students.update_one(
                    {'_id': ObjectId(session['user'])},
                    {
                        '$set': {
                            'assigned_therapist_id': therapist['_id'],
                            'assignment_date': datetime.now(),
                            'status': 'crisis' if crisis_level == 'high' else 'active',
                            'intake_completed': True,
                            'next_appointment_id': appointment_id
                        }
                    },
                    upsert=True
                )
                
                # Also update users collection
                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user'])},
                    {
                        '$set': {
                            'assigned_therapist_id': therapist['_id'],
                            'intake_completed': True
                        }
                    }
                )
                
                # Update therapist caseload
                mongo.db.therapists.update_one(
                    {'_id': therapist['_id']},
                    {'$inc': {'current_students': 1}}
                )
                
                # Redirect to appointment confirmation - NO ASSESSMENT
                return redirect(url_for('dashboard.appointment_confirmed', 
                                      appointment_id=str(appointment_id),
                                      crisis_level=crisis_level))
            else:
                # Couldn't auto-schedule, but therapist is assigned
                flash(f'Matched with {therapist["name"]}! They\'ll contact you to schedule.', 'success')
                return redirect(url_for('dashboard.match_results', 
                                      therapist_id=str(therapist['_id']),
                                      crisis_level=crisis_level))
        else:
            # No therapist available
            mongo.db.intake_assessments.insert_one(intake_data)
            flash('Assessment completed! We\'ll find you a therapist soon.', 'info')
            return redirect(url_for('dashboard.index'))
    
    return render_template('student/intake.html')

@dashboard_bp.route('/student/intake-assessment') 
@login_required
def intake_assessment():
    """Alternative route for intake assessment"""
    return redirect(url_for('dashboard.student_intake'))

# ===== THERAPIST ROUTES =====

@dashboard_bp.route('/student/therapist-info')
@login_required
def therapist_info():
    """Therapist profile page - NO ASSESSMENT CHECKS"""
    
    if 'user' not in session or session.get('role') != 'student':
        flash('Access denied. Please log in as a student.', 'error')
        return redirect(url_for('auth.login'))
    
    user_id = ObjectId(session['user'])
    
    try:
        # Get user data - try both collections
        user = mongo.db.students.find_one({'_id': user_id})
        if not user:
            user = mongo.db.users.find_one({'_id': user_id})
            if not user:
                flash('User profile not found. Please contact support.', 'error')
                return redirect(url_for('dashboard.index'))
        
        # Get therapist - NO ASSESSMENT CHECKS
        therapist = None
        if user.get('assigned_therapist_id'):
            therapist = mongo.db.therapists.find_one({'_id': user['assigned_therapist_id']})
            
            if therapist:
                # Add defaults for missing fields
                therapist.setdefault('rating', 5.0)
                therapist.setdefault('total_sessions', 0)
                therapist.setdefault('specializations', [])
                therapist.setdefault('years_experience', 'Verified')
                therapist.setdefault('emergency_hours', False)
                therapist.setdefault('bio', '')
                therapist.setdefault('license_number', 'Licensed Professional')
        
        # Get appointments - ENSURE ALL ARE VIRTUAL
        appointments = []
        if therapist:
            raw_appointments = list(mongo.db.appointments.find({
                'student_id': user_id,
                'therapist_id': therapist['_id']
            }).sort('datetime', 1))
            
            for apt in raw_appointments:
                # FORCE VIRTUAL TYPE
                apt['type'] = 'virtual'
                
                # Format datetime
                if apt.get('datetime'):
                    apt['formatted_time'] = apt['datetime'].strftime('%A, %B %d at %I:%M %p')
                    apt['date'] = apt['datetime']
                else:
                    apt['formatted_time'] = 'Time to be confirmed'
                
                # Ensure meeting_info exists for virtual appointments
                if not apt.get('meeting_info'):
                    apt['meeting_info'] = {
                        'meet_link': f"https://meet.google.com/session-{apt['_id']}",
                        'platform': 'Google Meet',
                        'dial_in': '+1-555-MEET-NOW',
                        'dial_in_pin': str(apt['_id'])[-6:]
                    }
                    # Update in database
                    mongo.db.appointments.update_one(
                        {'_id': apt['_id']},
                        {'$set': {'meeting_info': apt['meeting_info'], 'type': 'virtual'}}
                    )
                
                appointments.append(apt)
        
        return render_template('student/therapist_info.html',
                             therapist=therapist,
                             appointments=appointments,
                             user=user)
                             
    except Exception as e:
        logger.error(f"Error loading therapist info for {user_id}: {str(e)}")
        flash('Unable to load therapist information. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/student/match-results/<therapist_id>')
@login_required  
def match_results(therapist_id):
    """Show therapist matching results after intake - NO ASSESSMENT REDIRECT"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
    crisis_level = request.args.get('crisis_level', 'normal')
    
    if not therapist:
        flash('Therapist not found', 'error')
        return redirect(url_for('dashboard.index'))
    
    # Update student record with assigned therapist
    user_id = ObjectId(session['user'])
    mongo.db.students.update_one(
        {'_id': user_id},
        {'$set': {'assigned_therapist_id': ObjectId(therapist_id)}},
        upsert=True
    )
    
    # Also update users collection for consistency
    mongo.db.users.update_one(
        {'_id': user_id},
        {'$set': {'assigned_therapist_id': ObjectId(therapist_id)}}
    )
    
    # Flash appropriate message
    if crisis_level == 'high':
        flash(f'✅ Priority match found! You\'ve been assigned to {therapist["name"]} for immediate support.', 'success')
    else:
        flash(f'✅ Perfect match! You\'ve been assigned to {therapist["name"]} who specializes in your areas of concern.', 'success')
    
    # Direct to therapist info - NO ASSESSMENT
    return redirect(url_for('dashboard.therapist_info'))

# ===== APPOINTMENT ROUTES =====

@dashboard_bp.route('/student/appointment-confirmed/<appointment_id>')
def appointment_confirmed(appointment_id):
    """Show confirmed appointment with all details"""
    
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
        
        # Get appointment details
        appointment = mongo.db.appointments.find_one({
            '_id': appointment_object_id,
            'user_id': current_user_object_id  # Security: ensure user owns this appointment
        })
        
        if not appointment:
            print("❌ Appointment not found or access denied")
            # Let's check if the appointment exists at all
            any_appointment = mongo.db.appointments.find_one({'_id': appointment_object_id})
            if any_appointment:
                print(f"⚠️ Appointment exists but belongs to user: {any_appointment.get('user_id')}")
                print(f"⚠️ Current user: {current_user_object_id}")
            else:
                print("❌ Appointment doesn't exist in database at all")
            
            flash('Appointment not found or access denied', 'error')
            return redirect(url_for('dashboard.index'))
        
        print(f"✅ Found appointment: {appointment.get('formatted_time')}")
        
        # Get therapist details
        therapist = mongo.db.therapists.find_one({'_id': appointment['therapist_id']})
        if not therapist:
            # Create fallback therapist data
            therapist = {
                'name': 'Your Assigned Therapist',
                'rating': 5.0,
                'total_sessions': 0,
                'specializations': ['anxiety', 'depression'],
                'license_number': 'Licensed Professional',
                'years_experience': 'Verified',
                'emergency_hours': True
            }
        else:
            # Ensure all required fields exist
            therapist.setdefault('rating', 5.0)
            therapist.setdefault('total_sessions', 0)
            therapist.setdefault('specializations', [])
            therapist.setdefault('license_number', 'Licensed Professional')
            therapist.setdefault('years_experience', 'Verified')
            therapist.setdefault('emergency_hours', False)
        
        # Ensure appointment has required fields
        if not appointment.get('formatted_time'):
            if appointment.get('datetime'):
                appointment['formatted_time'] = appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
            else:
                appointment['formatted_time'] = 'Time to be confirmed'
        
        # Ensure virtual appointments have meeting info
        if appointment.get('type') == 'virtual' and not appointment.get('meeting_info'):
            import uuid
            meeting_id = str(uuid.uuid4())[:12].replace('-', '')
            appointment['meeting_info'] = {
                'meet_link': f'https://meet.google.com/session-{meeting_id}',
                'platform': 'Google Meet',
                'dial_in': '+1-555-MEET-NOW',
                'dial_in_pin': meeting_id[-6:]
            }
            # Update in database
            mongo.db.appointments.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$set': {'meeting_info': appointment['meeting_info']}}
            )
        
        # Get crisis level
        crisis_level = request.args.get('crisis_level', appointment.get('crisis_level', 'normal'))
        
        print(f"✅ Rendering confirmation page")
        
        return render_template('student/appointment_confirmed.html',
                             appointment=appointment,
                             therapist=therapist,
                             crisis_level=crisis_level)
                             
    except Exception as e:
        print(f"❌ Error loading appointment confirmation: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading appointment details', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/api/auto-schedule-appointment', methods=['POST'])
def auto_schedule_appointment():
    """API endpoint for auto-scheduling appointments"""
    
    print("🔍 Auto-schedule API called")
    
    if 'user' not in session:
        print("❌ User not in session")
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        therapist_id = request.form.get('therapist_id')
        crisis_level = request.form.get('crisis_level', 'normal')
        
        print(f"📋 Request data: therapist_id={therapist_id}, crisis_level={crisis_level}")
        
        # Debug session data structure
        print(f"🔍 Session user type: {type(session['user'])}")
        print(f"🔍 Session user content: {session['user']}")
        
        # Handle different session data formats
        if isinstance(session['user'], dict):
            # Session user is already a dictionary
            current_user_id = session['user']['_id']
        elif isinstance(session['user'], str):
            # Session user is a string (user ID)
            current_user_id = session['user']
        else:
            # Try to get the _id attribute if it's an object
            current_user_id = getattr(session['user'], '_id', str(session['user']))
        
        print(f"👤 Current user ID: {current_user_id}")
        
        if not therapist_id:
            print("❌ No therapist_id provided")
            return jsonify({'error': 'Therapist ID is required'}), 400
        
        # Create appointment
        from datetime import datetime, timedelta
        import uuid
        
        # Find next business day at 2 PM
        next_slot = datetime.now() + timedelta(days=1)
        while next_slot.weekday() >= 5:  # Skip weekends
            next_slot += timedelta(days=1)
        next_slot = next_slot.replace(hour=14, minute=0, second=0, microsecond=0)
        
        # Create unique meeting ID
        meeting_id = str(uuid.uuid4())[:12].replace('-', '')
        
        # Convert to ObjectIds
        current_user_object_id = ObjectId(current_user_id)
        therapist_object_id = ObjectId(therapist_id)
        
        print(f"🔑 User ObjectId: {current_user_object_id}")
        print(f"👨‍⚕️ Therapist ObjectId: {therapist_object_id}")
        
        # Create appointment document
        appointment_doc = {
            'user_id': current_user_object_id,
            'therapist_id': therapist_object_id,
            'datetime': next_slot,
            'formatted_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
            'type': 'virtual',
            'status': 'confirmed',
            'crisis_level': crisis_level,
            'notes': f'Auto-scheduled session - Priority: {crisis_level}',
            'meeting_info': {
                'meet_link': f'https://meet.google.com/auto-{meeting_id}',
                'platform': 'Google Meet',
                'dial_in': '+1-555-MEET-AUTO',
                'dial_in_pin': meeting_id[-6:]
            },
            'created_at': datetime.utcnow(),
            'auto_scheduled': True
        }
        
        print(f"📝 Creating appointment document")
        
        # Insert appointment
        result = mongo.db.appointments.insert_one(appointment_doc)
        appointment_id = result.inserted_id
        
        print(f"✅ Created appointment with ID: {appointment_id}")
        
        # Verify the appointment was created
        verification = mongo.db.appointments.find_one({
            '_id': appointment_id,
            'user_id': current_user_object_id
        })
        
        if verification:
            print(f"✅ Appointment verified in database")
        else:
            print(f"❌ Could not verify appointment in database")
        
        return jsonify({
            'success': True,
            'appointment_id': str(appointment_id),
            'scheduled_time': next_slot.isoformat(),
            'formatted_time': appointment_doc['formatted_time']
        })
            
    except Exception as e:
        print(f"❌ Auto-scheduling error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Scheduling failed: {str(e)}'}), 500

def find_next_available_slot(therapist_id):
    """Find the next available appointment slot for a therapist"""
    
    # Get existing appointments for this therapist
    existing_appointments = list(mongo.db.appointments.find({
        'therapist_id': ObjectId(therapist_id),
        'status': {'$in': ['confirmed', 'suggested']},
        'datetime': {'$gte': datetime.now()}
    }))
    
    # Extract busy times
    busy_times = [apt['datetime'] for apt in existing_appointments]
    
    # Default business hours: 9 AM to 5 PM, Monday to Friday
    business_hours = [(9, 17)]  # (start_hour, end_hour)
    
    # Start looking from tomorrow
    current_date = datetime.now() + timedelta(days=1)
    
    for day_offset in range(14):  # Look up to 2 weeks ahead
        check_date = current_date + timedelta(days=day_offset)
        
        # Skip weekends
        if check_date.weekday() >= 5:
            continue
            
        # Check each hour in business hours
        for start_hour in range(business_hours[0][0], business_hours[0][1]):
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

@dashboard_bp.route('/student/book-specific-slot', methods=['POST'])
def book_specific_slot():
    """Book a specific time slot - VIRTUAL ONLY"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    # Get form data
    therapist_id = request.form.get('therapist_id')
    selected_date = request.form.get('selected_date')
    selected_time = request.form.get('selected_time')
    # FORCE VIRTUAL - ignore any user input
    appointment_type = 'virtual'
    
    if not all([therapist_id, selected_date, selected_time]):
        flash('Please select a valid time slot', 'error')
        return redirect(url_for('dashboard.therapist_info'))
    
    # Get therapist
    therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
    if not therapist:
        flash('Therapist not found', 'error')
        return redirect(url_for('dashboard.index'))
    
    # Create slot object
    try:
        selected_datetime = datetime.strptime(f"{selected_date} {selected_time}", "%Y-%m-%d %I:%M %p")
        selected_slot = {
            'datetime': selected_datetime,
            'date': selected_date,
            'time': selected_time,
            'formatted': selected_datetime.strftime('%A, %B %d at %I:%M %p')
        }
        
        # Schedule VIRTUAL appointment
        appointment_id, appointment = schedule_appointment_automatically(
            session['user'], therapist, selected_slot, 'virtual'
        )
        
        if appointment_id:
            flash('✅ Virtual session scheduled successfully!', 'success')
            return redirect(url_for('dashboard.appointment_confirmed', 
                                  appointment_id=str(appointment_id)))
        else:
            flash('Failed to schedule virtual session. Please try again.', 'error')
            return redirect(url_for('dashboard.therapist_info'))
            
    except Exception as e:
        logger.error(f"Error booking slot: {str(e)}")
        flash('Error scheduling appointment. Please try again.', 'error')
        return redirect(url_for('dashboard.therapist_info'))

@dashboard_bp.route('/student/join-session/<appointment_id>')
def join_session(appointment_id):
    """Join a virtual therapy session"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    try:
        appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
        if not appointment:
            flash('Session not found', 'error')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Check if it's time for the session (within 15 minutes)
        if appointment.get('datetime'):
            session_time = appointment['datetime']
            now = datetime.now()
            time_diff = (session_time - now).total_seconds() / 60  # minutes
            
            if time_diff > 15:
                flash(f'Session starts in {int(time_diff)} minutes. Please wait.', 'info')
                return redirect(url_for('dashboard.therapist_info'))
            elif time_diff < -60:  # More than 1 hour past
                flash('This session has ended.', 'warning')
                return redirect(url_for('dashboard.therapist_info'))
        
        # Get meeting info
        meeting_info = appointment.get('meeting_info', {})
        if not meeting_info or not meeting_info.get('meet_link'):
            flash('No meeting link available. Contact your therapist.', 'error')
            return redirect(url_for('dashboard.therapist_info'))
        
        # Update appointment status
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': {'last_joined': datetime.now()}}
        )
        
        # Redirect to Google Meet
        return redirect(meeting_info['meet_link'])
        
    except Exception as e:
        logger.error(f"Error joining session: {str(e)}")
        flash('Unable to join session. Please try again.', 'error')
        return redirect(url_for('dashboard.therapist_info'))

# ===== API ROUTES =====

@dashboard_bp.route('/api/therapist-availability/<therapist_id>')
def get_therapist_availability(therapist_id):
    """API endpoint to get real-time therapist availability"""
    
    if 'user' not in session:
        return {'error': 'Not authenticated'}, 401
    
    try:
        therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
        if not therapist:
            return {'error': 'Therapist not found'}, 404
        
        crisis_level = request.args.get('crisis_level', 'normal')
        available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
        
        # Format for JSON response
        slots_data = []
        for slot in available_slots:
            slots_data.append({
                'date': slot['date'],
                'time': slot['time'],
                'formatted': slot['formatted'],
                'day_name': slot['day_name']
            })
        
        return {
            'therapist_name': therapist['name'],
            'available_slots': slots_data,
            'total_slots': len(slots_data)
        }
        
    except Exception as e:
        logger.error(f"Error getting therapist availability: {str(e)}")
        return {'error': 'Unable to get availability'}, 500

@dashboard_bp.route('/api/upcoming-session')
def get_upcoming_session():
    """Get student's next upcoming session"""
    
    if 'user' not in session:
        return {'error': 'Not authenticated'}, 401
    
    try:
        # Find next appointment
        next_appointment = mongo.db.appointments.find_one({
            'student_id': ObjectId(session['user']),
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed'
        }, sort=[('datetime', 1)])
        
        if next_appointment:
            therapist = mongo.db.therapists.find_one({'_id': next_appointment['therapist_id']})
            
            return {
                'has_upcoming': True,
                'appointment': {
                    'id': str(next_appointment['_id']),
                    'datetime': next_appointment['datetime'].isoformat(),
                    'formatted_time': next_appointment.get('formatted_time', 'Time TBD'),
                    'therapist_name': therapist['name'] if therapist else 'N/A',
                    'type': next_appointment.get('type', 'virtual'),
                    'meeting_link': next_appointment.get('meeting_info', {}).get('meet_link')
                }
            }
        
        return {'has_upcoming': False}
        
    except Exception as e:
        logger.error(f"Error getting upcoming session: {str(e)}")
        return {'error': 'Unable to get upcoming session'}, 500

# ===== UTILITY FUNCTIONS =====

def force_virtual_meetings():
    """Helper function to ensure all appointments are virtual"""
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
            meet_link = f"https://meet.google.com/auto-{apt['_id']}"
            mongo.db.appointments.update_one(
                {'_id': apt['_id']},
                {
                    '$set': {
                        'meeting_info': {
                            'meet_link': meet_link,
                            'platform': 'Google Meet',
                            'dial_in': '+1-555-MEET-NOW',
                            'dial_in_pin': str(apt['_id'])[-6:]
                        }
                    }
                }
            )
        
        logger.info(f"Updated {result.modified_count} appointments to virtual")
        
    except Exception as e:
        logger.error(f"Error forcing virtual meetings: {str(e)}")

# ===== TEST/DEBUG ROUTES (Remove in production) =====

@dashboard_bp.route('/test-appointment')
def test_appointment():
    """Test route to verify appointment template works"""
    
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    # Create test data
    test_appointment = {
        '_id': 'test123',
        'formatted_time': 'Monday, December 16 at 2:00 PM',
        'type': 'virtual',
        'datetime': datetime.now() + timedelta(days=1),
        'meeting_info': {
            'meet_link': 'https://meet.google.com/test-session',
            'platform': 'Google Meet',
            'dial_in': '+1-555-TEST-MEET',
            'dial_in_pin': '123456'
        },
        'therapist_id': ObjectId()
    }
    
    test_therapist = {
        'name': 'Dr. Test Therapist',
        'rating': 4.8,
        'total_sessions': 150,
        'specializations': ['anxiety', 'depression', 'trauma'],
        'license_number': 'TEST-12345',
        'years_experience': 8,
        'emergency_hours': True,
        'photo': None,
        'bio': 'This is a test therapist for debugging purposes.'
    }
    
    return render_template('student/appointment_confirmed.html',
                         appointment=test_appointment,
                         therapist=test_therapist,
                         crisis_level='normal')

@dashboard_bp.route('/debug-user-data')
def debug_user_data():
    """Debug route to check user data and identify redirect issues"""
    
    if 'user' not in session:
        return {'error': 'No user in session'}
    
    user_id = ObjectId(session['user'])
    
    try:
        # Get data from both collections
        user_data = mongo.db.users.find_one({'_id': user_id})
        student_data = mongo.db.students.find_one({'_id': user_id})
        
        # Convert ObjectIds to strings for JSON response
        if user_data:
            user_data['_id'] = str(user_data['_id'])
            if user_data.get('assigned_therapist_id'):
                user_data['assigned_therapist_id'] = str(user_data['assigned_therapist_id'])
        
        if student_data:
            student_data['_id'] = str(student_data['_id'])
            if student_data.get('assigned_therapist_id'):
                student_data['assigned_therapist_id'] = str(student_data['assigned_therapist_id'])
        
        return {
            'session_user': session.get('user'),
            'session_role': session.get('role'),
            'user_collection': user_data,
            'student_collection': student_data,
            'has_therapist_users': bool(user_data and user_data.get('assigned_therapist_id')),
            'has_therapist_students': bool(student_data and student_data.get('assigned_therapist_id')),
            'intake_completed': bool(mongo.db.intake_assessments.find_one({'student_id': user_id}))
        }
        
    except Exception as e:
        return {'error': str(e)}


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

