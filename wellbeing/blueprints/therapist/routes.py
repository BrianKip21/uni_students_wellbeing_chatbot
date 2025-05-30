from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timedelta, timezone
import csv
import io
import json
import uuid
from wellbeing.blueprints.therapist import therapist_bp
from wellbeing.utils.decorators import therapist_required
from wellbeing import mongo, logger
from wellbeing.models.therapist import find_therapist_by_id, update_therapist_settings

@therapist_bp.route('/dashboard', methods=['GET', 'POST'])
@therapist_required
def index():
    """Enhanced therapist dashboard with auto-scheduling overview - Fully Automated."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get today's date
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get today's VIRTUAL appointments (all auto-confirmed)
    today_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'datetime': {
            '$gte': today,
            '$lt': today + timedelta(days=1)
        },
        'status': 'confirmed',
        'type': 'virtual'  # Only virtual
    }).sort('datetime', 1))
    
    # Add student details and ensure meeting links
    for appt in today_appointments:
        student = mongo.db.users.find_one({'_id': appt['user_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        
        # Ensure virtual meeting info exists
        if not appt.get('meeting_info'):
            appt['meeting_info'] = {
                'meet_link': f"https://meet.google.com/session-{appt['_id']}",
                'platform': 'Google Meet',
                'dial_in': '+1-555-MEET-NOW',
                'dial_in_pin': str(appt['_id'])[-6:]
            }
            mongo.db.appointments.update_one(
                {'_id': appt['_id']},
                {'$set': {'meeting_info': appt['meeting_info']}}
            )
    
    # Get recent auto-scheduled appointments (no confirmation needed)
    recent_auto_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'status': 'confirmed',
        'auto_scheduled': True,
        'created_at': {'$gte': today - timedelta(days=7)}  # Last 7 days
    }).sort('created_at', -1).limit(10))
    
    for req in recent_auto_appointments:
        student = mongo.db.users.find_one({'_id': req['user_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get crisis appointments (high priority)
    crisis_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'crisis_level': {'$in': ['high', 'critical']},
        'status': 'confirmed',
        'datetime': {'$gte': datetime.now()}
    }).sort('datetime', 1))
    
    for appt in crisis_appointments:
        student = mongo.db.users.find_one({'_id': appt['user_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get unread messages count
    unread_messages = mongo.db.therapist_chats.count_documents({
        'therapist_id': therapist_id,
        'sender': 'student',
        'read': False
    })
    
    # New student assignments (immediate AI matching)
    new_student_assignments = list(mongo.db.therapist_assignments.find({
        'therapist_id': therapist_id,
        'status': 'active',
        'created_at': {'$gte': today}  # Today's new assignments
    }).sort('created_at', -1))
    
    for assignment in new_student_assignments:
        student = mongo.db.users.find_one({'_id': assignment['student_id']})
        if student:
            assignment['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Enhanced statistics for automated system
    stats = {
        'total_students': mongo.db.therapist_assignments.count_documents({
            'therapist_id': therapist_id,
            'status': 'active'
        }),
        'virtual_sessions_today': len(today_appointments),
        'virtual_sessions_this_week': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'datetime': {
                '$gte': today - timedelta(days=today.weekday()),
                '$lt': today - timedelta(days=today.weekday()) + timedelta(days=7)
            },
            'status': 'confirmed',
            'type': 'virtual'
        }),
        'recent_auto_scheduled': len(recent_auto_appointments),
        'crisis_sessions': len(crisis_appointments),
        'auto_scheduled_today': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'auto_scheduled': True,
            'created_at': {'$gte': today}
        }),
        'rescheduled_today': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'auto_rescheduled': True,
            'updated_at': {'$gte': today}
        })
    }
    
    # Availability status for automated system
    availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id}) or {
        'auto_schedule_enabled': True,
        'max_daily_sessions': 8,
        'crisis_priority': True,
        'auto_reschedule_enabled': True,
        'suggest_alternative_enabled': True
    }
    
    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/dashboard.html',
                         current_date=datetime.now().strftime('%B %d, %Y'),
                         therapist=therapist,
                         today_appointments=today_appointments,
                         recent_auto_appointments=recent_auto_appointments,
                         crisis_appointments=crisis_appointments,
                         new_student_assignments=new_student_assignments,
                         unread_messages=unread_messages,
                         stats=stats,
                         availability=availability,
                         settings=settings)

@therapist_bp.route('/students')
@therapist_required
def students():
    """View assigned students with virtual session history."""
    try:
        therapist_id = ObjectId(session['user'])
        therapist = find_therapist_by_id(therapist_id)
        
        if not therapist:
            flash('Therapist not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Get all active student assignments
        assignments = list(mongo.db.therapist_assignments.find({
            'therapist_id': therapist_id,
            'status': 'active'
        }))
        
        logger.info(f"Found {len(assignments)} active assignments for therapist ID {therapist_id}")
        
        settings = mongo.db.settings.find_one() or {}
        
        # Get student details for each assignment
        students_data = []
        for assignment in assignments:
            try:
                student_id = assignment.get('student_id')
                if not student_id:
                    logger.warning(f"Assignment {assignment.get('_id')} has no student_id field")
                    continue
                    
                student = mongo.db.users.find_one({'_id': student_id})
                if not student:
                    logger.warning(f"Student with ID {student_id} not found")
                    continue
                
                # Get latest VIRTUAL appointment
                latest_appointment = mongo.db.appointments.find_one({
                    'user_id': student_id,
                    'therapist_id': therapist_id,
                    'type': 'virtual'
                }, sort=[('datetime', -1)])
                
                # Get next upcoming VIRTUAL appointment
                next_appointment = mongo.db.appointments.find_one({
                    'user_id': student_id,
                    'therapist_id': therapist_id,
                    'datetime': {'$gte': datetime.now()},
                    'status': 'confirmed',
                    'type': 'virtual'
                }, sort=[('datetime', 1)])
                
                # Count total virtual sessions
                total_sessions = mongo.db.appointments.count_documents({
                    'user_id': student_id,
                    'therapist_id': therapist_id,
                    'status': 'completed',
                    'type': 'virtual'
                })
                
                # Get crisis level from intake
                intake = mongo.db.intake_assessments.find_one({'student_id': student_id})
                crisis_level = intake.get('crisis_level', 'normal') if intake else 'normal'
                
                # Get unread messages
                unread_messages = mongo.db.therapist_chats.count_documents({
                    'student_id': student_id,
                    'therapist_id': therapist_id,
                    'sender': 'student',
                    'read': False
                })
                
                students_data.append({
                    'student': student,
                    'assignment': assignment,
                    'latest_appointment': latest_appointment,
                    'next_appointment': next_appointment,
                    'total_sessions': total_sessions,
                    'crisis_level': crisis_level,
                    'unread_messages': unread_messages,
                    'assigned_at': assignment.get('created_at', datetime.now()),
                    'auto_assigned': assignment.get('auto_assigned', True)
                })
            except Exception as e:
                logger.error(f"Error processing student data: {e}")
                continue
        
        # Sort students by crisis level first, then by most recently assigned
        students_data.sort(key=lambda x: (
            0 if x['crisis_level'] == 'critical' else 1 if x['crisis_level'] == 'high' else 2,
            -x.get('assigned_at', datetime.now()).timestamp()
        ))
        
        return render_template('therapist/students.html',
                            therapist=therapist,
                            students_data=students_data,
                            settings=settings)
    
    except Exception as e:
        logger.error(f"Error in students route: {e}")
        flash('An error occurred while loading your students', 'error')
        return redirect(url_for('therapist.index'))

@therapist_bp.route('/virtual-sessions')
@therapist_required
def virtual_sessions():
    """Dedicated virtual sessions management page."""
    therapist_id = ObjectId(session['user'])
    
    # Get all virtual sessions
    sessions = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'type': 'virtual'
    }).sort('datetime', -1))
    
    # Add student details and format
    for appointment in sessions:  # Changed from 'session' to 'appointment'
        student = mongo.db.users.find_one({'_id': appointment['user_id']})
        if student:
            appointment['student_name'] = f"{student['first_name']} {student['last_name']}"
        
        # Format datetime
        if appointment.get('datetime'):
            appointment['formatted_time'] = appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
        
        # Ensure meeting info
        if not appointment.get('meeting_info'):
            appointment['meeting_info'] = {
                'meet_link': f"https://meet.google.com/session-{appointment['_id']}",
                'platform': 'Google Meet'
            }
    
    # Group by status - no more suggested sessions, all auto-confirmed
    confirmed_sessions = [s for s in sessions if s['status'] == 'confirmed']
    completed_sessions = [s for s in sessions if s['status'] == 'completed']
    cancelled_sessions = [s for s in sessions if s['status'] == 'cancelled']
    
    return render_template('therapist/virtual_sessions.html',
                         confirmed_sessions=confirmed_sessions,
                         completed_sessions=completed_sessions,
                         cancelled_sessions=cancelled_sessions)

@therapist_bp.route('/availability', methods=['GET', 'POST'])
@therapist_required
def availability():
    """Manage auto-scheduling availability - Fully Automated System."""
    therapist_id = ObjectId(session['user'])
    
    if request.method == 'POST':
        try:
            # Update availability settings
            availability_data = {
                'therapist_id': therapist_id,
                'auto_schedule_enabled': request.form.get('auto_schedule_enabled') == 'on',
                'max_daily_sessions': int(request.form.get('max_daily_sessions', 8)),
                'crisis_priority': request.form.get('crisis_priority') == 'on',
                'working_days': request.form.getlist('working_days[]'),
                'working_hours': {
                    'start': request.form.get('start_time', '09:00'),
                    'end': request.form.get('end_time', '17:00')
                },
                'buffer_time': int(request.form.get('buffer_time', 15)),  # minutes between sessions
                'auto_reschedule_enabled': request.form.get('auto_reschedule_enabled') == 'on',
                'suggest_alternative_enabled': request.form.get('suggest_alternative_enabled') == 'on',
                'updated_at': datetime.now()
            }
            
            mongo.db.therapist_availability.update_one(
                {'therapist_id': therapist_id},
                {'$set': availability_data},
                upsert=True
            )
            
            flash('Availability settings updated successfully', 'success')
            
        except Exception as e:
            logger.error(f"Error updating availability: {e}")
            flash('Error updating availability settings', 'error')
    
    # Get current availability
    availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id}) or {
        'auto_schedule_enabled': True,
        'max_daily_sessions': 8,
        'crisis_priority': True,
        'working_days': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
        'working_hours': {'start': '09:00', 'end': '17:00'},
        'buffer_time': 15,
        'auto_reschedule_enabled': True,
        'suggest_alternative_enabled': True
    }
    
    return render_template('therapist/availability.html', availability=availability)

@therapist_bp.route('/auto-reschedule-appointment/<appointment_id>', methods=['POST'])
@therapist_required
def auto_reschedule_appointment(appointment_id):
    """Auto-reschedule an appointment to the next available slot."""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            return jsonify({'error': 'Appointment not found'}), 404
        
        # Get therapist availability
        availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id})
        if not availability or not availability.get('auto_reschedule_enabled'):
            return jsonify({'error': 'Auto-reschedule not enabled'}), 400
        
        # Find next available slot
        next_slot = find_next_available_slot(therapist_id)
        if not next_slot:
            return jsonify({'error': 'No available slots found'}), 400
        
        # Update appointment
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {
                    'datetime': next_slot,
                    'formatted_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
                    'auto_rescheduled': True,
                    'rescheduled_at': datetime.now(),
                    'rescheduled_by': therapist_id,
                    'rescheduled_reason': 'Therapist unavailable - auto-rescheduled'
                }
            }
        )
        
        # Notify student
        mongo.db.notifications.insert_one({
            'user_id': appointment['user_id'],
            'type': 'appointment_auto_rescheduled',
            'message': f'Your virtual session has been automatically rescheduled to {next_slot.strftime("%A, %B %d at %I:%M %p")} due to therapist availability.',
            'related_id': ObjectId(appointment_id),
            'read': False,
            'created_at': datetime.now()
        })
        
        return jsonify({
            'success': True, 
            'message': 'Appointment auto-rescheduled successfully',
            'new_time': next_slot.strftime('%A, %B %d at %I:%M %p')
        })
        
    except Exception as e:
        logger.error(f"Error auto-rescheduling appointment: {e}")
        return jsonify({'error': 'Failed to auto-reschedule appointment'}), 500

@therapist_bp.route('/suggest-alternative-therapist/<appointment_id>', methods=['POST'])
@therapist_required
def suggest_alternative_therapist(appointment_id):
    """Suggest student to auto-schedule with alternative therapist."""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            return jsonify({'error': 'Appointment not found'}), 404
        
        # Get therapist availability settings
        availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id})
        if not availability or not availability.get('suggest_alternative_enabled'):
            return jsonify({'error': 'Alternative therapist suggestion not enabled'}), 400
        
        # Get student's intake data to find compatible therapists
        student_id = appointment['user_id']
        intake = mongo.db.intake_assessments.find_one({'student_id': student_id})
        
        # Find alternative therapists with similar specializations
        alternative_therapists = find_alternative_therapists(
            current_therapist_id=therapist_id,
            student_intake=intake,
            appointment_datetime=appointment['datetime']
        )
        
        if not alternative_therapists:
            return jsonify({'error': 'No alternative therapists available'}), 400
        
        # Cancel current appointment
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {
                    'status': 'cancelled',
                    'cancelled_at': datetime.now(),
                    'cancelled_by': therapist_id,
                    'cancellation_reason': 'Therapist unavailable - alternative suggested'
                }
            }
        )
        
        # Create alternative options for student
        alternative_options = []
        for alt_therapist in alternative_therapists[:3]:  # Top 3 alternatives
            # Find available slot for this therapist
            alt_slot = find_next_available_slot(alt_therapist['_id'])
            if alt_slot:
                alternative_options.append({
                    'therapist_id': str(alt_therapist['_id']),
                    'therapist_name': alt_therapist['name'],
                    'specializations': alt_therapist.get('specializations', []),
                    'available_time': alt_slot.strftime('%A, %B %d at %I:%M %p'),
                    'datetime': alt_slot.isoformat()
                })
        
        # Store alternative options
        mongo.db.alternative_therapist_options.insert_one({
            'student_id': student_id,
            'original_appointment_id': ObjectId(appointment_id),
            'original_therapist_id': therapist_id,
            'alternatives': alternative_options,
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24)
        })
        
        # Notify student with alternatives
        mongo.db.notifications.insert_one({
            'user_id': student_id,
            'type': 'alternative_therapist_suggested',
            'message': f'Your therapist is unavailable. We found {len(alternative_options)} alternative therapists for you to choose from.',
            'related_id': ObjectId(appointment_id),
            'read': False,
            'created_at': datetime.now()
        })
        
        return jsonify({
            'success': True,
            'message': f'Alternative therapist options sent to student',
            'alternatives_count': len(alternative_options)
        })
        
    except Exception as e:
        logger.error(f"Error suggesting alternative therapist: {e}")
        return jsonify({'error': 'Failed to suggest alternative therapist'}), 500

@therapist_bp.route('/reschedule-appointment/<appointment_id>', methods=['POST'])
@therapist_required
def reschedule_appointment(appointment_id):
    """Reschedule an appointment to a new virtual slot (manual)."""
    therapist_id = ObjectId(session['user'])
    
    try:
        new_datetime_str = request.form.get('new_datetime')
        if not new_datetime_str:
            return jsonify({'error': 'New datetime is required'}), 400
        
        new_datetime = datetime.fromisoformat(new_datetime_str)
        
        # Update appointment
        result = mongo.db.appointments.update_one(
            {
                '_id': ObjectId(appointment_id),
                'therapist_id': therapist_id
            },
            {
                '$set': {
                    'datetime': new_datetime,
                    'formatted_time': new_datetime.strftime('%A, %B %d at %I:%M %p'),
                    'rescheduled_at': datetime.now(),
                    'rescheduled_by': therapist_id
                }
            }
        )
        
        if result.modified_count > 0:
            # Notify student
            appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            mongo.db.notifications.insert_one({
                'user_id': appointment['user_id'],
                'type': 'appointment_rescheduled',
                'message': f'Your virtual session has been rescheduled to {new_datetime.strftime("%A, %B %d at %I:%M %p")}.',
                'related_id': ObjectId(appointment_id),
                'read': False,
                'created_at': datetime.now()
            })
            
            return jsonify({'success': True, 'message': 'Appointment rescheduled successfully'})
        else:
            return jsonify({'error': 'Appointment not found or could not be updated'}), 404
            
    except Exception as e:
        logger.error(f"Error rescheduling appointment: {e}")
        return jsonify({'error': 'Failed to reschedule appointment'}), 500

@therapist_bp.route('/join-session/<appointment_id>')
@therapist_required
def join_session(appointment_id):
    """Join a virtual therapy session."""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            flash('Session not found', 'error')
            return redirect(url_for('therapist.virtual_sessions'))
        
        # Get meeting info
        meeting_info = appointment.get('meeting_info', {})
        if not meeting_info or not meeting_info.get('meet_link'):
            flash('No meeting link available', 'error')
            return redirect(url_for('therapist.virtual_sessions'))
        
        # Update last accessed
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': {'therapist_last_joined': datetime.now()}}
        )
        
        # Redirect to Google Meet
        return redirect(meeting_info['meet_link'])
        
    except Exception as e:
        logger.error(f"Error joining session: {e}")
        flash('Unable to join session', 'error')
        return redirect(url_for('therapist.virtual_sessions'))

@therapist_bp.route('/student-details/<student_id>')
@therapist_required
def student_details(student_id):
    """View details for a specific student - VIRTUAL SESSIONS ONLY."""
    therapist_id = ObjectId(session['user'])
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        flash('Student not found or not assigned to you', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get student data
    student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get intake assessment with crisis level
    intake_data = mongo.db.intake_assessments.find_one({
        'student_id': ObjectId(student_id)
    })
    
    # Get VIRTUAL appointments only
    past_appointments = list(mongo.db.appointments.find({
        'user_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'status': 'completed',
        'type': 'virtual'
    }).sort('datetime', -1))
    
    upcoming_appointments = list(mongo.db.appointments.find({
        'user_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'datetime': {'$gte': datetime.now()},
        'status': 'confirmed',
        'type': 'virtual'
    }).sort('datetime', 1))
    
    # Ensure all appointments have meeting info
    for appt in upcoming_appointments:
        if not appt.get('meeting_info'):
            appt['meeting_info'] = {
                'meet_link': f"https://meet.google.com/session-{appt['_id']}",
                'platform': 'Google Meet'
            }
            mongo.db.appointments.update_one(
                {'_id': appt['_id']},
                {'$set': {'meeting_info': appt['meeting_info']}}
            )
    
    # Get session notes
    session_notes = {}
    for appt in past_appointments:
        note = mongo.db.session_notes.find_one({'appointment_id': appt['_id']})
        if note:
            session_notes[str(appt['_id'])] = note
    
    # Get shared resources
    shared_resources = list(mongo.db.shared_resources.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id
    }).sort('shared_at', -1))
    
    # Get recent messages
    recent_messages = list(mongo.db.therapist_chats.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id
    }).sort('timestamp', -1).limit(5))
    
    # Calculate stats
    stats = {
        'total_virtual_sessions': len(past_appointments),
        'cancelled_sessions': mongo.db.appointments.count_documents({
            'user_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'status': 'cancelled',
            'type': 'virtual'
        }),
        'crisis_level': intake_data.get('crisis_level', 'normal') if intake_data else 'normal',
        'auto_assigned': assignment.get('auto_assigned', True),
        'days_since_assignment': None,
        'days_since_last_session': None
    }
    
    # Calculate days since assignment and last session
    if assignment.get('created_at'):
        stats['days_since_assignment'] = (datetime.now() - assignment['created_at']).days
    
    if past_appointments:
        last_session = past_appointments[0]
        stats['days_since_last_session'] = (datetime.now() - last_session['datetime']).days

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/student_details.html',
                         therapist_id=therapist_id,
                         student=student,
                         intake_data=intake_data,
                         assignment=assignment,
                         past_appointments=past_appointments,
                         upcoming_appointments=upcoming_appointments,
                         session_notes=session_notes,
                         shared_resources=shared_resources,
                         recent_messages=recent_messages,
                         stats=stats,
                         settings=settings)

# API Routes for auto-scheduling
@therapist_bp.route('/api/auto-schedule-slots')
@therapist_required
def get_auto_schedule_slots():
    """Get available auto-schedule slots for the therapist."""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Get availability settings
        availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id})
        if not availability or not availability.get('auto_schedule_enabled'):
            return jsonify({'error': 'Auto-scheduling not enabled'}), 400
        
        # Generate available slots for next 2 weeks
        slots = []
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for day_offset in range(14):
            check_date = current_date + timedelta(days=day_offset)
            
            # Skip if not a working day
            day_name = check_date.strftime('%A').lower()
            if day_name not in availability.get('working_days', []):
                continue
            
            # Generate hourly slots within working hours
            start_hour = int(availability['working_hours']['start'].split(':')[0])
            end_hour = int(availability['working_hours']['end'].split(':')[0])
            
            for hour in range(start_hour, end_hour):
                slot_time = check_date.replace(hour=hour, minute=0)
                
                # Check if slot is available
                existing = mongo.db.appointments.find_one({
                    'therapist_id': therapist_id,
                    'datetime': slot_time,
                    'status': 'confirmed'
                })
                
                if not existing:
                    slots.append({
                        'datetime': slot_time.isoformat(),
                        'formatted': slot_time.strftime('%A, %B %d at %I:%M %p'),
                        'day': day_name.title(),
                        'time': slot_time.strftime('%I:%M %p')
                    })
        
        return jsonify({
            'available_slots': slots[:20],  # Limit to 20 slots
            'total_available': len(slots)
        })
        
    except Exception as e:
        logger.error(f"Error getting auto-schedule slots: {e}")
        return jsonify({'error': 'Failed to get available slots'}), 500

# Utility Functions
def find_next_available_slot(therapist_id):
    """Find the next available appointment slot for a therapist"""
    
    # Get existing appointments for this therapist
    existing_appointments = list(mongo.db.appointments.find({
        'therapist_id': ObjectId(therapist_id),
        'status': 'confirmed',
        'datetime': {'$gte': datetime.now()}
    }))
    
    # Extract busy times
    busy_times = [apt['datetime'] for apt in existing_appointments]
    
    # Get therapist availability
    availability = mongo.db.therapist_availability.find_one({'therapist_id': ObjectId(therapist_id)})
    if not availability:
        # Default business hours: 9 AM to 5 PM, Monday to Friday
        business_hours = [(9, 17)]
        working_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    else:
        start_hour = int(availability['working_hours']['start'].split(':')[0])
        end_hour = int(availability['working_hours']['end'].split(':')[0])
        business_hours = [(start_hour, end_hour)]
        working_days = availability.get('working_days', ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])
    
    # Start looking from tomorrow
    current_date = datetime.now() + timedelta(days=1)
    
    for day_offset in range(14):  # Look up to 2 weeks ahead
        check_date = current_date + timedelta(days=day_offset)
        
        # Skip if not a working day
        day_name = check_date.strftime('%A').lower()
        if day_name not in working_days:
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

def find_alternative_therapists(current_therapist_id, student_intake, appointment_datetime):
    """Find alternative therapists compatible with student's needs."""
    try:
        # Get student preferences from intake
        primary_concern = student_intake.get('primary_concern') if student_intake else None
        therapist_gender = student_intake.get('therapist_gender') if student_intake else 'no_preference'
        crisis_level = student_intake.get('crisis_level') if student_intake else 'normal'
        
        # Build query for compatible therapists
        query = {
            '_id': {'$ne': current_therapist_id},  # Exclude current therapist
            'status': 'active'
        }
        
        # Add gender preference if specified
        if therapist_gender and therapist_gender != 'no_preference':
            query['gender'] = therapist_gender
        
        # Find therapists with matching specializations
        therapists = list(mongo.db.therapists.find(query))
        
        # Filter by specialization match and availability
        compatible_therapists = []
        for therapist in therapists:
            # Check if they have matching specializations
            therapist_specs = therapist.get('specializations', [])
            if primary_concern and primary_concern in therapist_specs:
                # Check availability
                availability = mongo.db.therapist_availability.find_one({
                    'therapist_id': therapist['_id'],
                    'auto_schedule_enabled': True
                })
                
                if availability:
                    # Check if they have capacity
                    current_load = mongo.db.therapist_assignments.count_documents({
                        'therapist_id': therapist['_id'],
                        'status': 'active'
                    })
                    
                    max_students = availability.get('max_students', 20)
                    if current_load < max_students:
                        compatible_therapists.append(therapist)
        
        # Sort by compatibility score (number of matching specializations)
        def compatibility_score(therapist):
            specs = therapist.get('specializations', [])
            if not primary_concern:
                return len(specs)
            return len([s for s in specs if s == primary_concern]) + len(specs)
        
        compatible_therapists.sort(key=compatibility_score, reverse=True)
        return compatible_therapists
        
    except Exception as e:
        logger.error(f"Error finding alternative therapists: {e}")
        return []

# Keep existing routes for other functionality (chat, resources, profile, etc.)
@therapist_bp.route('/add-session-notes/<appointment_id>', methods=['GET', 'POST'])
@therapist_required
def add_session_notes(appointment_id):
    """Add notes for a completed session."""
    therapist_id = ObjectId(session['user'])
    
    # Find the appointment
    appointment = mongo.db.appointments.find_one({
        '_id': ObjectId(appointment_id),
        'therapist_id': therapist_id,
        'status': 'completed'
    })
    
    if not appointment:
        flash('Appointment not found or not completed', 'error')
        return redirect(url_for('therapist.virtual_sessions'))
    
    # Check if notes already exist
    existing_notes = mongo.db.session_notes.find_one({'appointment_id': ObjectId(appointment_id)})
    
    # Get student info
    student = mongo.db.users.find_one({'_id': appointment['user_id']})
    
    if request.method == 'POST':
        try:
            # Get form data
            summary = request.form.get('summary', '').strip()
            topics_discussed = request.form.getlist('topics_discussed[]')
            progress = request.form.get('progress', '').strip()
            action_items = request.form.getlist('action_items[]')
            recommendations = request.form.get('recommendations', '').strip()
            next_steps = request.form.get('next_steps', '').strip()
            
            # Validate form data
            if not summary:
                flash('Summary is required', 'error')
                return redirect(url_for('therapist.add_session_notes', appointment_id=appointment_id))
            
            # Prepare resources to share
            shared_resources = []
            resource_ids = request.form.getlist('shared_resources[]')
            
            if resource_ids:
                resources = list(mongo.db.resources.find({'_id': {'$in': [ObjectId(rid) for rid in resource_ids]}}))
                
                for resource in resources:
                    shared_resources.append({
                        'id': resource['_id'],
                        'title': resource['title'],
                        'type': resource['type'],
                        'description': resource['description'],
                        'url': resource['url']
                    })
                    
                    # Also record in shared_resources collection
                    mongo.db.shared_resources.insert_one({
                        'student_id': appointment['user_id'],
                        'therapist_id': therapist_id,
                        'resource_id': resource['_id'],
                        'title': resource['title'],
                        'type': resource['type'],
                        'description': resource['description'],
                        'url': resource['url'],
                        'shared_at': datetime.now(timezone.utc),
                        'appointment_id': ObjectId(appointment_id)
                    })
            
            # Create notes object
            notes_data = {
                'appointment_id': ObjectId(appointment_id),
                'student_id': appointment['user_id'],
                'therapist_id': therapist_id,
                'session_date': appointment['datetime'],
                'summary': summary,
                'topics_discussed': topics_discussed,
                'progress': progress,
                'action_items': action_items,
                'recommendations': recommendations,
                'next_steps': next_steps,
                'shared_resources': shared_resources,
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc)
            }
            
            if existing_notes:
                # Update existing notes
                mongo.db.session_notes.update_one(
                    {'_id': existing_notes['_id']},
                    {'$set': {
                        'summary': summary,
                        'topics_discussed': topics_discussed,
                        'progress': progress,
                        'action_items': action_items,
                        'recommendations': recommendations,
                        'next_steps': next_steps,
                        'shared_resources': shared_resources,
                        'updated_at': datetime.now(timezone.utc)
                    }}
                )
                flash('Session notes updated successfully', 'success')
            else:
                # Create new notes
                mongo.db.session_notes.insert_one(notes_data)
                
                # Add notification for student
                mongo.db.notifications.insert_one({
                    'user_id': appointment['user_id'],
                    'type': 'session_notes_added',
                    'message': f'Session notes are now available for your appointment on {appointment["datetime"].strftime("%A, %B %d")}.',
                    'related_id': ObjectId(appointment_id),
                    'read': False,
                    'created_at': datetime.now(timezone.utc)
                })
                
                flash('Session notes added successfully', 'success')
            
            return redirect(url_for('therapist.student_details', student_id=appointment['user_id']))
            
        except Exception as e:
            logger.error(f"Add session notes error: {e}")
            flash('An error occurred while saving the session notes', 'error')
            return redirect(url_for('therapist.add_session_notes', appointment_id=appointment_id))
    
    # Get available resources to share
    available_resources = list(mongo.db.resources.find({'status': 'active'}).sort('title', 1))

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/add_session_notes.html',
                         appointment=appointment,
                         student=student,
                         existing_notes=existing_notes,
                         available_resources=available_resources,
                         settings=settings)

@therapist_bp.route('/chat/<student_id>')
@therapist_required
def chat(student_id):
    """Chat with a student."""
    therapist_id = ObjectId(session['user'])
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        flash('Student not found or not assigned to you', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get student data
    student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get chat history
    chat_history = list(mongo.db.therapist_chats.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id
    }).sort('timestamp', 1))
    
    # Mark student messages as read
    mongo.db.therapist_chats.update_many(
        {
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'sender': 'student',
            'read': False
        },
        {'$set': {'read': True, 'read_at': datetime.now(timezone.utc)}}
    )
    
    # Get upcoming appointments
    upcoming_appointments = list(mongo.db.appointments.find({
        'user_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'datetime': {'$gte': datetime.now()},
        'status': 'confirmed'
    }).sort('datetime', 1))
    
    # Get available resources to share
    available_resources = list(mongo.db.resources.find({'status': 'active'}).sort('title', 1))
    
    # Get already shared resources
    shared_resources = list(mongo.db.shared_resources.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id
    }).sort('shared_at', -1).limit(5))

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/chat.html',
                         therapist_id=therapist_id,
                         student=student,
                         chat_history=chat_history,
                         upcoming_appointments=upcoming_appointments,
                         available_resources=available_resources,
                         shared_resources=shared_resources,
                         settings=settings)

@therapist_bp.route('/send-message/<student_id>', methods=['POST'])
@therapist_required
def send_message(student_id):
    """Send a message to a student."""
    therapist_id = ObjectId(session['user'])
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        return jsonify({'success': False, 'error': 'Student not assigned to you'})
    
    # Get message content
    message = request.form.get('message', '').strip()
    
    if not message:
        return jsonify({'success': False, 'error': 'Message cannot be empty'})
    
    try:
        # Create message
        new_message = {
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'sender': 'therapist',
            'message': message,
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        }
        
        result = mongo.db.therapist_chats.insert_one(new_message)
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(student_id),
            'type': 'new_message',
            'message': 'You have a new message from your therapist.',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Return formatted message for immediate display
        return jsonify({
            'success': True,
            'message': {
                'id': str(result.inserted_id),
                'content': message,
                'timestamp': datetime.now(timezone.utc).strftime('%I:%M %p | %b %d')
            }
        })
        
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return jsonify({'success': False, 'error': 'An error occurred while sending the message'})

@therapist_bp.route('/share-resource', methods=['POST'])
@therapist_required
def share_resource():
    """Share a resource with a student."""
    therapist_id = ObjectId(session['user'])
    
    # Get form data
    student_id = request.form.get('student_id')
    resource_id = request.form.get('resource_id')
    custom_message = request.form.get('message', '').strip()
    
    if not student_id or not resource_id:
        flash('Student ID and Resource ID are required', 'error')
        return redirect(url_for('therapist.students'))
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        flash('Student not assigned to you', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get resource
    resource = mongo.db.resources.find_one({'_id': ObjectId(resource_id)})
    
    if not resource:
        flash('Resource not found', 'error')
        return redirect(url_for('therapist.chat', student_id=student_id))
    
    try:
        # Share resource
        shared_resource = {
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'resource_id': ObjectId(resource_id),
            'title': resource['title'],
            'type': resource['type'],
            'description': resource['description'],
            'url': resource['url'],
            'shared_at': datetime.now(timezone.utc),
            'custom_message': custom_message
        }
        
        result = mongo.db.shared_resources.insert_one(shared_resource)
        
        # Add a message in chat about the shared resource
        chat_message = f"I've shared a resource with you: {resource['title']}"
        if custom_message:
            chat_message += f"\n\nNote: {custom_message}"
        
        mongo.db.therapist_chats.insert_one({
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'sender': 'therapist',
            'message': chat_message,
            'resource_id': ObjectId(resource_id),
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        })
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(student_id),
            'type': 'resource_shared',
            'message': f'Your therapist shared a resource with you: {resource["title"]}',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Resource shared successfully', 'success')
        
    except Exception as e:
        logger.error(f"Share resource error: {e}")
        flash('An error occurred while sharing the resource', 'error')
    
    return redirect(url_for('therapist.chat', student_id=student_id))

@therapist_bp.route('/profile', methods=['GET', 'POST'])
@therapist_required
def profile():
    """Therapist profile and settings."""
    try:
        therapist_id = ObjectId(session['user'])
        
        # Get therapist data
        therapist = find_therapist_by_id(therapist_id)
        
        if not therapist:
            flash('Therapist not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Convert therapist to dictionary if it's not already
        if not isinstance(therapist, dict):
            if hasattr(therapist, '__dict__'):
                therapist = vars(therapist)
            elif isinstance(therapist, str):
                therapist = {'name': therapist, '_id': therapist_id}
            else:
                therapist = {'_id': therapist_id}
        
        # Get user document for additional info
        user = mongo.db.users.find_one({'_id': therapist_id})
        
        # If not found with ObjectId, try with string ID
        if not user:
            string_id = str(therapist_id)
            user = mongo.db.users.find_one({'_id': string_id})
        
        # If still not found, check if there's a user_id field in therapist
        if not user and isinstance(therapist, dict) and therapist.get('user_id'):
            user_id = therapist['user_id']
            if isinstance(user_id, str):
                try:
                    user_id = ObjectId(user_id)
                except:
                    pass
            user = mongo.db.users.find_one({'_id': user_id})
        
        # Auto-create user document if it doesn't exist
        if not user:
            try:
                # Create a new user document based on therapist data
                new_user = {
                    '_id': therapist_id,
                    'first_name': therapist.get('first_name', 'Unknown'),
                    'last_name': therapist.get('last_name', 'User'),
                    'email': therapist.get('email', 'unknown@example.com'),
                    'password': therapist.get('password', ''),  # Copy password hash if available
                    'role': 'therapist',
                    'created_at': therapist.get('created_at', datetime.now()),
                    'login_count': therapist.get('login_count', 0),
                    'last_login': therapist.get('last_login', None)
                }
                
                # Insert the new user document
                result = mongo.db.users.insert_one(new_user)
                if result.inserted_id:
                    user = new_user
                    logger.info(f"Created new user account for therapist ID {therapist_id}")
                else:
                    raise Exception("Failed to insert new user document")
            except Exception as e:
                logger.error(f"Failed to create user account for therapist: {e}")
                # Continue with placeholder data as before
                user = {
                    '_id': therapist_id,
                    'first_name': therapist.get('first_name', 'Unknown'),
                    'last_name': therapist.get('last_name', 'User'),
                    'email': therapist.get('email', 'unknown@example.com'),
                    'created_at': datetime.now(),
                    'login_count': 0,
                    'last_login': 'Never'
                }
                logger.warning(f"User account not found for therapist ID {therapist_id}. Using placeholder data.")
        
        # Handle profile updates
        if request.method == 'POST':
            try:
                form_type = request.form.get('form_type')
                
                if form_type == 'profile':
                    # Update profile information
                    specialization = request.form.get('specialization', '').strip()
                    bio = request.form.get('bio', '').strip()
                    office_hours_desc = request.form.get('office_hours', '').strip()
                    
                    # Update therapist document
                    mongo.db.therapists.update_one(
                        {'_id': therapist_id},
                        {'$set': {
                            'specialization': specialization,
                            'bio': bio,
                            'office_hours': {
                                'description': office_hours_desc,
                                'days': [0, 1, 2, 3, 4],  # Default to weekdays
                                'slots': ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']  # Default slots
                            }
                        }}
                    )
                    
                    flash('Profile updated successfully', 'success')
                    
                elif form_type == 'password':
                    # Update password
                    current_password = request.form.get('current_password', '')
                    new_password = request.form.get('new_password', '')
                    confirm_password = request.form.get('confirm_password', '')
                    
                    # Validate passwords
                    from werkzeug.security import check_password_hash, generate_password_hash
                    
                    if not user.get('password'):
                        # If no password exists yet, allow setting a new one without checking current
                        if new_password != confirm_password:
                            flash('New passwords do not match', 'error')
                            return redirect(url_for('therapist.profile'))
                        
                        if len(new_password) < 8:
                            flash('New password must be at least 8 characters long', 'error')
                            return redirect(url_for('therapist.profile'))
                        
                        # Set password in both collections for consistency
                        password_hash = generate_password_hash(new_password)
                        mongo.db.users.update_one(
                            {'_id': user['_id']},
                            {'$set': {'password': password_hash}}
                        )
                        mongo.db.therapists.update_one(
                            {'_id': therapist_id},
                            {'$set': {'password': password_hash}}
                        )
                        
                        flash('Password set successfully', 'success')
                    else:
                        # Normal password update flow with current password check
                        if not check_password_hash(user['password'], current_password):
                            flash('Current password is incorrect', 'error')
                            return redirect(url_for('therapist.profile'))
                        
                        if new_password != confirm_password:
                            flash('New passwords do not match', 'error')
                            return redirect(url_for('therapist.profile'))
                        
                        if len(new_password) < 8:
                            flash('New password must be at least 8 characters long', 'error')
                            return redirect(url_for('therapist.profile'))
                        
                        # Update password in both collections for consistency
                        password_hash = generate_password_hash(new_password)
                        mongo.db.users.update_one(
                            {'_id': user['_id']},
                            {'$set': {'password': password_hash}}
                        )
                        mongo.db.therapists.update_one(
                            {'_id': therapist_id},
                            {'$set': {'password': password_hash}}
                        )
                        
                        flash('Password updated successfully', 'success')
                
            except Exception as e:
                logger.error(f"Profile update error: {e}")
                flash(f'An error occurred while updating your profile: {str(e)}', 'error')
        
        # Get account statistics
        stats = {}
        try:
            # Ensure we have a created_at value that's a datetime
            created_at = user.get('created_at') if isinstance(user, dict) else None
            if created_at and hasattr(created_at, 'strftime'):
                member_since = created_at.strftime('%B %d, %Y')
            else:
                member_since = 'N/A'
            
            # Ensure we have a user login count that's a number
            login_count = user.get('login_count') if isinstance(user, dict) else None
            if not isinstance(login_count, (int, float)):
                login_count = 0
            
            # Ensure we have a last login value that's a string
            last_login = user.get('last_login') if isinstance(user, dict) else None
            if not isinstance(last_login, str):
                if hasattr(last_login, 'strftime'):  # If it's a datetime
                    last_login = last_login.strftime('%B %d, %Y at %I:%M %p')
                else:
                    last_login = 'Never'
            
            stats = {
                'member_since': member_since,
                'total_sessions': mongo.db.appointments.count_documents({
                    'therapist_id': therapist_id,
                    'status': 'completed'
                }),
                'current_students': mongo.db.therapist_assignments.count_documents({
                    'therapist_id': therapist_id,
                    'status': 'active'
                }),
                'login_count': login_count,
                'last_login': last_login
            }
        except Exception as e:
            logger.error(f"Error generating profile statistics: {e}")
            stats = {
                'member_since': 'N/A',
                'total_sessions': 0,
                'current_students': 0,
                'login_count': 0,
                'last_login': 'Never'
            }
        
        settings = mongo.db.settings.find_one() or {}
        
        return render_template('therapist/profile.html',
                            therapist=therapist,
                            user=user,
                            stats=stats,
                            settings=settings)
                            
    except Exception as e:
        logger.error(f"Unexpected error in profile route: {str(e)}")
        flash(f"An unexpected error occurred: {str(e)}", 'error')
        return redirect(url_for('therapist.index'))

@therapist_bp.route('/resources')
@therapist_required
def resources():
    """View and manage resources."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get all system resources
    system_resources = list(mongo.db.resources.find({'status': 'active'}).sort('title', 1))
    
    # Get therapist's custom resources
    custom_resources = list(mongo.db.therapist_resources.find({
        'therapist_id': therapist_id
    }).sort('title', 1))
    
    # Get recently shared resources
    recently_shared = list(mongo.db.shared_resources.find({
        'therapist_id': therapist_id
    }).sort('shared_at', -1).limit(10))
    
    # Get student details for recently shared resources
    for shared in recently_shared:
        student = mongo.db.users.find_one({'_id': shared['student_id']})
        if student:
            shared['student_name'] = f"{student['first_name']} {student['last_name']}"

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/resources.html',
                         therapist=therapist,
                         system_resources=system_resources,
                         custom_resources=custom_resources,
                         recently_shared=recently_shared,
                         settings=settings)