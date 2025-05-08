from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timedelta, timezone
import csv
import io
import json
from wellbeing.blueprints.therapist import therapist_bp
from wellbeing.utils.decorators import therapist_required
from wellbeing import mongo, logger
from wellbeing.models.therapist import find_therapist_by_id, update_therapist_settings

@therapist_bp.route('/dashboard', methods=['GET', 'POST'])
@therapist_required
def index():
    """Therapist dashboard with overview."""
    # Get therapist data
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get today's date
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get today's appointments
    today_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'date': {
            '$gte': today,
            '$lt': today + timedelta(days=1)
        },
        'status': 'scheduled'
    }).sort('time', 1))
    
    # Get student details for each appointment
    for appt in today_appointments:
        student = mongo.db.users.find_one({'_id': appt['student_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get pending requests (appointment requests, rescheduling, cancellations)
    pending_appointment_requests = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    for req in pending_appointment_requests:
        student = mongo.db.users.find_one({'_id': req['student_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    pending_reschedules = list(mongo.db.reschedule_requests.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    for req in pending_reschedules:
        student = mongo.db.users.find_one({'_id': req['student_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    pending_cancellations = list(mongo.db.cancellation_requests.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    for req in pending_cancellations:
        student = mongo.db.users.find_one({'_id': req['student_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get unread messages count
    unread_messages = mongo.db.therapist_chats.count_documents({
        'therapist_id': therapist_id,
        'sender': 'student',
        'read': False
    })
    
    # Get student assignment requests pending
    new_student_requests = list(mongo.db.therapist_requests.find({
        'status': 'pending_therapist_approval'  # Status when admin has pre-assigned a therapist, awaiting confirmation
    }).sort('created_at', 1))
    
    for req in new_student_requests:
        student = mongo.db.users.find_one({'_id': req['student_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get statistics
    stats = {
        'total_students': mongo.db.therapist_assignments.count_documents({
            'therapist_id': therapist_id,
            'status': 'active'
        }),
        'total_sessions': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'status': 'completed'
        }),
        'sessions_this_week': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'date': {
                '$gte': today - timedelta(days=today.weekday()),
                '$lt': today - timedelta(days=today.weekday()) + timedelta(days=7)
            },
            'status': 'scheduled'
        }),
        'pending_requests': len(pending_appointment_requests) + len(pending_reschedules) + len(pending_cancellations)
    }
    # Fetch settings
    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/dashboard.html',
                         therapist=therapist,
                         today_appointments=today_appointments,
                         pending_appointment_requests=pending_appointment_requests,
                         pending_reschedules=pending_reschedules,
                         pending_cancellations=pending_cancellations,
                         unread_messages=unread_messages,
                         new_student_requests=new_student_requests,
                         stats=stats,
                         settings=settings)

@therapist_bp.route('/calendar')
@therapist_required
def calendar():
    """View appointment calendar."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get date range parameters
    date_str = request.args.get('date', '')
    view = request.args.get('view', 'week')  # week, month
    
    try:
        if date_str:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            selected_date = datetime.now()
    except ValueError:
        selected_date = datetime.now()
    
    # Calculate date range based on view
    if view == 'month':
        # Start of month
        start_date = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # End of month
        if selected_date.month == 12:
            end_date = selected_date.replace(year=selected_date.year + 1, month=1, day=1)
        else:
            end_date = selected_date.replace(month=selected_date.month + 1, day=1)
    else:  # week view
        # Start of week (Monday)
        start_date = selected_date - timedelta(days=selected_date.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        # End of week (Sunday)
        end_date = start_date + timedelta(days=7)
    
    # Get appointments in the date range
    appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'date': {
            '$gte': start_date,
            '$lt': end_date
        }
    }).sort('date', 1).sort('time', 1))
    
    # Get student details for each appointment
    for appt in appointments:
        student = mongo.db.users.find_one({'_id': appt['student_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        else:
            appt['student_name'] = "Unknown"
    
    # Prepare calendar data
    calendar_data = []
    
    if view == 'month':
        # Generate all days in the month
        current_date = start_date
        while current_date < end_date:
            day_data = {
                'date': current_date,
                'appointments': []
            }
            
            # Add appointments for this day
            for appt in appointments:
                if appt['date'].date() == current_date.date():
                    day_data['appointments'].append(appt)
            
            calendar_data.append(day_data)
            current_date += timedelta(days=1)
    else:  # week view
        # Generate all days in the week
        current_date = start_date
        while current_date < end_date:
            day_data = {
                'date': current_date,
                'appointments': []
            }
            
            # Add appointments for this day
            for appt in appointments:
                if appt['date'].date() == current_date.date():
                    day_data['appointments'].append(appt)
            
            calendar_data.append(day_data)
            current_date += timedelta(days=1)
    
    return render_template('therapist/calendar.html',
                         therapist=therapist,
                         calendar_data=calendar_data,
                         selected_date=selected_date,
                         view=view,
                         start_date=start_date,
                         end_date=end_date)

@therapist_bp.route('/appointments')
@therapist_required
def appointments():
    """View all appointments."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get filter parameters
    filter_status = request.args.get('status', 'upcoming')  # upcoming, past, all
    
    # Build query
    query = {'therapist_id': therapist_id}
    
    if filter_status == 'upcoming':
        query['date'] = {'$gte': datetime.now()}
        query['status'] = 'scheduled'
    elif filter_status == 'past':
        query['$or'] = [
            {'date': {'$lt': datetime.now()}, 'status': 'completed'},
            {'status': 'cancelled'}
        ]
    # If 'all', no additional filter
    
    # Get all appointments based on filter
    appointments = list(mongo.db.appointments.find(query).sort('date', 1 if filter_status == 'upcoming' else -1))
    
    # Get pending appointment requests
    pending_requests = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    # Get reschedule requests
    reschedule_requests = list(mongo.db.reschedule_requests.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    # Get cancellation requests
    cancellation_requests = list(mongo.db.cancellation_requests.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', 1))
    
    # Get student details for each entry
    all_appointments = appointments + pending_requests + reschedule_requests + cancellation_requests
    student_ids = set(appt['student_id'] for appt in all_appointments)
    
    students = {}
    for student_id in student_ids:
        student = mongo.db.users.find_one({'_id': student_id})
        if student:
            students[str(student_id)] = {
                'name': f"{student['first_name']} {student['last_name']}",
                'email': student['email']
            }
    
    return render_template('therapist/appointments.html',
                         therapist=therapist,
                         appointments=appointments,
                         pending_requests=pending_requests,
                         reschedule_requests=reschedule_requests,
                         cancellation_requests=cancellation_requests,
                         students=students,
                         filter_status=filter_status)

@therapist_bp.route('/approve-appointment/<request_id>', methods=['POST'])
@therapist_required
def approve_appointment(request_id):
    """Approve a pending appointment request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the appointment request
    appointment = mongo.db.appointments.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not appointment:
        flash('Appointment request not found or cannot be approved', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Update appointment status
        mongo.db.appointments.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'scheduled',
                'updated_at': datetime.now(timezone.utc),
                'approved_by': therapist_id
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': appointment['student_id'],
            'type': 'appointment_approved',
            'message': f'Your appointment request for {appointment["date"].strftime("%A, %B %d")} at {appointment["time"]} has been approved.',
            'related_id': appointment['_id'],
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Appointment request approved successfully', 'success')
        
    except Exception as e:
        logger.error(f"Approve appointment error: {e}")
        flash('An error occurred while approving the appointment', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/reject-appointment/<request_id>', methods=['POST'])
@therapist_required
def reject_appointment(request_id):
    """Reject a pending appointment request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the appointment request
    appointment = mongo.db.appointments.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not appointment:
        flash('Appointment request not found or cannot be rejected', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Get reason for rejection
        reason = request.form.get('reason', '')
        
        # Update appointment status
        mongo.db.appointments.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now(timezone.utc),
                'rejected_by': therapist_id
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': appointment['student_id'],
            'type': 'appointment_rejected',
            'message': f'Your appointment request for {appointment["date"].strftime("%A, %B %d")} at {appointment["time"]} has been declined.',
            'related_id': appointment['_id'],
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Appointment request rejected successfully', 'success')
        
    except Exception as e:
        logger.error(f"Reject appointment error: {e}")
        flash('An error occurred while rejecting the appointment', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/approve-reschedule/<request_id>', methods=['POST'])
@therapist_required
def approve_reschedule(request_id):
    """Approve a reschedule request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the reschedule request
    reschedule = mongo.db.reschedule_requests.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not reschedule:
        flash('Reschedule request not found or cannot be approved', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Update the original appointment
        mongo.db.appointments.update_one(
            {'_id': reschedule['appointment_id']},
            {'$set': {
                'date': reschedule['requested_date'],
                'time': reschedule['requested_time'],
                'updated_at': datetime.now(timezone.utc),
                'reschedule_requested': False
            }}
        )
        
        # Update reschedule request status
        mongo.db.reschedule_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'approved',
                'updated_at': datetime.now(timezone.utc),
                'approved_by': therapist_id
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': reschedule['student_id'],
            'type': 'reschedule_approved',
            'message': f'Your reschedule request has been approved. Your appointment is now scheduled for {reschedule["requested_date"].strftime("%A, %B %d")} at {reschedule["requested_time"]}.',
            'related_id': reschedule['appointment_id'],
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Reschedule request approved successfully', 'success')
        
    except Exception as e:
        logger.error(f"Approve reschedule error: {e}")
        flash('An error occurred while approving the reschedule request', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/reject-reschedule/<request_id>', methods=['POST'])
@therapist_required
def reject_reschedule(request_id):
    """Reject a reschedule request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the reschedule request
    reschedule = mongo.db.reschedule_requests.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not reschedule:
        flash('Reschedule request not found or cannot be rejected', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Get reason for rejection
        reason = request.form.get('reason', '')
        
        # Update reschedule request status
        mongo.db.reschedule_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now(timezone.utc),
                'rejected_by': therapist_id
            }}
        )
        
        # Update the original appointment
        mongo.db.appointments.update_one(
            {'_id': reschedule['appointment_id']},
            {'$set': {
                'reschedule_requested': False,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': reschedule['student_id'],
            'type': 'reschedule_rejected',
            'message': f'Your reschedule request has been declined. Your original appointment time remains unchanged.',
            'related_id': reschedule['appointment_id'],
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Reschedule request rejected successfully', 'success')
        
    except Exception as e:
        logger.error(f"Reject reschedule error: {e}")
        flash('An error occurred while rejecting the reschedule request', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/approve-cancellation/<request_id>', methods=['POST'])
@therapist_required
def approve_cancellation(request_id):
    """Approve a cancellation request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the cancellation request
    cancellation = mongo.db.cancellation_requests.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not cancellation:
        flash('Cancellation request not found or cannot be approved', 'error')
        return redirect(url_for('therapist.appointments'))
    
@therapist_bp.route('/reject-cancellation/<request_id>', methods=['POST'])
@therapist_required
def reject_cancellation(request_id):
    """Reject a cancellation request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the cancellation request
    cancellation = mongo.db.cancellation_requests.find_one({
        '_id': ObjectId(request_id),
        'therapist_id': therapist_id,
        'status': 'pending'
    })
    
    if not cancellation:
        flash('Cancellation request not found or cannot be rejected', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Get reason for rejection
        reason = request.form.get('reason', '')
        
        # Update cancellation request status
        mongo.db.cancellation_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now(timezone.utc),
                'rejected_by': therapist_id
            }}
        )
        
        # Update the original appointment
        mongo.db.appointments.update_one(
            {'_id': cancellation['appointment_id']},
            {'$set': {
                'cancellation_requested': False,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': cancellation['student_id'],
            'type': 'cancellation_rejected',
            'message': f'Your cancellation request has been declined. Your appointment remains scheduled.',
            'related_id': cancellation['appointment_id'],
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Cancellation request rejected successfully', 'success')
        
    except Exception as e:
        logger.error(f"Reject cancellation error: {e}")
        flash('An error occurred while rejecting the cancellation request', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/complete-appointment/<appointment_id>', methods=['POST'])
@therapist_required
def complete_appointment(appointment_id):
    """Mark an appointment as completed."""
    therapist_id = ObjectId(session['user'])
    
    # Find the appointment
    appointment = mongo.db.appointments.find_one({
        '_id': ObjectId(appointment_id),
        'therapist_id': therapist_id,
        'status': 'scheduled'
    })
    
    if not appointment:
        flash('Appointment not found or cannot be completed', 'error')
        return redirect(url_for('therapist.appointments'))
    
    try:
        # Update appointment status
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': {
                'status': 'completed',
                'updated_at': datetime.now(timezone.utc),
                'completed_at': datetime.now(timezone.utc),
                'completed_by': therapist_id
            }}
        )
        
        flash('Appointment marked as completed. Please add session notes.', 'success')
        return redirect(url_for('therapist.add_session_notes', appointment_id=appointment_id))
        
    except Exception as e:
        logger.error(f"Complete appointment error: {e}")
        flash('An error occurred while completing the appointment', 'error')
    
    return redirect(url_for('therapist.appointments'))

@therapist_bp.route('/students')
@therapist_required
def students():
    """View assigned students."""
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
    settings = mongo.db.settings.find_one() or {}
    
    # Get student details for each assignment
    students_data = []
    for assignment in assignments:
        student = mongo.db.users.find_one({'_id': assignment['student_id']})
        if student:
            # Get latest appointment
            latest_appointment = mongo.db.appointments.find_one({
                'student_id': student['_id'],
                'therapist_id': therapist_id
            }, sort=[('date', -1)])
            
            # Get next upcoming appointment
            next_appointment = mongo.db.appointments.find_one({
                'student_id': student['_id'],
                'therapist_id': therapist_id,
                'date': {'$gte': datetime.now()},
                'status': 'scheduled'
            }, sort=[('date', 1)])
            
            # Count total sessions
            total_sessions = mongo.db.appointments.count_documents({
                'student_id': student['_id'],
                'therapist_id': therapist_id,
                'status': 'completed'
            })
            
            # Get unread messages
            unread_messages = mongo.db.therapist_chats.count_documents({
                'student_id': student['_id'],
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
                'unread_messages': unread_messages
            })
            

    
    return render_template('therapist/students.html',
                         therapist=therapist,
                         students_data=students_data,
                         settings=settings)

@therapist_bp.route('/student-details/<student_id>')
@therapist_required
def student_details(student_id):
    """View details for a specific student."""
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
    
    # Get assignment request details
    request_data = mongo.db.therapist_requests.find_one({
        'student_id': ObjectId(student_id),
        'status': 'approved'
    })
    
    # Get appointments
    past_appointments = list(mongo.db.appointments.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'status': 'completed'
    }).sort('date', -1))
    
    upcoming_appointments = list(mongo.db.appointments.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'date': {'$gte': datetime.now()},
        'status': 'scheduled'
    }).sort('date', 1))
    
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
        'total_sessions': len(past_appointments),
        'cancelled_sessions': mongo.db.appointments.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'status': 'cancelled'
        }),
        'rescheduled_sessions': mongo.db.reschedule_requests.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'status': 'approved'
        }),
        'days_since_first_session': None,
        'days_since_last_session': None
    }
    
    # Calculate days since first and last session
    if past_appointments:
        first_session = past_appointments[-1]  # Last in the reversed list
        last_session = past_appointments[0]    # First in the reversed list
        
        stats['days_since_first_session'] = (datetime.now() - first_session['date']).days
        stats['days_since_last_session'] = (datetime.now() - last_session['date']).days
    
    return render_template('therapist/student_details.html',
                         therapist_id=therapist_id,
                         student=student,
                         request_data=request_data,
                         assignment=assignment,
                         past_appointments=past_appointments,
                         upcoming_appointments=upcoming_appointments,
                         session_notes=session_notes,
                         shared_resources=shared_resources,
                         recent_messages=recent_messages,
                         stats=stats)

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
        return redirect(url_for('therapist.appointments'))
    
    # Check if notes already exist
    existing_notes = mongo.db.session_notes.find_one({'appointment_id': ObjectId(appointment_id)})
    
    # Get student info
    student = mongo.db.users.find_one({'_id': appointment['student_id']})
    
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
                        'student_id': appointment['student_id'],
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
                'student_id': appointment['student_id'],
                'therapist_id': therapist_id,
                'session_date': appointment['date'],
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
                    'user_id': appointment['student_id'],
                    'type': 'session_notes_added',
                    'message': f'Session notes are now available for your appointment on {appointment["date"].strftime("%A, %B %d")}.',
                    'related_id': ObjectId(appointment_id),
                    'read': False,
                    'created_at': datetime.now(timezone.utc)
                })
                
                flash('Session notes added successfully', 'success')
            
            return redirect(url_for('therapist.student_details', student_id=appointment['student_id']))
            
        except Exception as e:
            logger.error(f"Add session notes error: {e}")
            flash('An error occurred while saving the session notes', 'error')
            return redirect(url_for('therapist.add_session_notes', appointment_id=appointment_id))
    
    # Get available resources to share
    available_resources = list(mongo.db.resources.find({'status': 'active'}).sort('title', 1))
    
    return render_template('therapist/add_session_notes.html',
                         appointment=appointment,
                         student=student,
                         existing_notes=existing_notes,
                         available_resources=available_resources)

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
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id,
        'date': {'$gte': datetime.now()},
        'status': 'scheduled'
    }).sort('date', 1))
    
    # Get available resources to share
    available_resources = list(mongo.db.resources.find({'status': 'active'}).sort('title', 1))
    
    # Get already shared resources
    shared_resources = list(mongo.db.shared_resources.find({
        'student_id': ObjectId(student_id),
        'therapist_id': therapist_id
    }).sort('shared_at', -1).limit(5))
    
    return render_template('therapist/chat.html',
                         therapist_id=therapist_id,
                         student=student,
                         chat_history=chat_history,
                         upcoming_appointments=upcoming_appointments,
                         available_resources=available_resources,
                         shared_resources=shared_resources)

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

@therapist_bp.route('/schedule-appointment/<student_id>', methods=['GET', 'POST'])
@therapist_required
def schedule_appointment(student_id):
    """Schedule an appointment for a student."""
    therapist_id = ObjectId(session['user'])
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        flash('Student not assigned to you', 'error')
        return redirect(url_for('therapist.students'))
    
    # Get student data
    student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('therapist.students'))
    
    if request.method == 'POST':
        try:
            # Get form data
            date_str = request.form.get('date')
            time_str = request.form.get('time')
            session_type = request.form.get('session_type', 'online')
            notes = request.form.get('notes', '')
            
            # Validate date and time
            if not date_str or not time_str:
                flash('Date and time are required', 'error')
                return redirect(url_for('therapist.schedule_appointment', student_id=student_id))
            
            try:
                appointment_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format', 'error')
                return redirect(url_for('therapist.schedule_appointment', student_id=student_id))
            
            # Check if slot is available
            existing = mongo.db.appointments.find_one({
                'therapist_id': therapist_id,
                'date': appointment_date,
                'time': time_str,
                'status': {'$in': ['scheduled', 'pending']}
            })
            
            if existing:
                flash('This time slot is already booked', 'error')
                return redirect(url_for('therapist.schedule_appointment', student_id=student_id))
            
            # Create appointment
            new_appointment = {
                'student_id': ObjectId(student_id),
                'therapist_id': therapist_id,
                'date': appointment_date,
                'time': time_str,
                'session_type': session_type,
                'notes': notes,
                'status': 'scheduled',  # Directly scheduled, not pending
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc),
                'created_by': therapist_id
            }
            
            result = mongo.db.appointments.insert_one(new_appointment)
            
            # Add notification for student
            mongo.db.notifications.insert_one({
                'user_id': ObjectId(student_id),
                'type': 'appointment_scheduled',
                'message': f'Your therapist has scheduled an appointment for you on {appointment_date.strftime("%A, %B %d")} at {time_str}.',
                'related_id': result.inserted_id,
                'read': False,
                'created_at': datetime.now(timezone.utc)
            })
            
            # Add a message in chat about the scheduled appointment
            mongo.db.therapist_chats.insert_one({
                'student_id': ObjectId(student_id),
                'therapist_id': therapist_id,
                'sender': 'therapist',
                'message': f"I've scheduled an appointment for you on {appointment_date.strftime('%A, %B %d')} at {time_str}. " + 
                          (f"Notes: {notes}" if notes else ""),
                'appointment_id': result.inserted_id,
                'read': False,
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Appointment scheduled successfully', 'success')
            return redirect(url_for('therapist.student_details', student_id=student_id))
            
        except Exception as e:
            logger.error(f"Schedule appointment error: {e}")
            flash('An error occurred while scheduling the appointment', 'error')
            return redirect(url_for('therapist.schedule_appointment', student_id=student_id))
    
    # Get therapist's availability
    therapist = find_therapist_by_id(therapist_id)
    
    # Generate available time slots
    available_slots = []
    
    # Parse therapist's working days
    office_hours = therapist.get('office_hours', {})
    working_days = office_hours.get('days', [0, 1, 2, 3, 4])  # Default: Monday-Friday
    
    # Generate slots for the next 14 days
    for i in range(14):
        slot_date = datetime.now() + timedelta(days=i+1)
        
        # Skip non-working days
        if slot_date.weekday() not in working_days:
            continue
            
        # Add standard slots
        day_slots = office_hours.get('slots', ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00'])
        
        available_slots.append({
            'date': slot_date,
            'date_str': slot_date.strftime('%Y-%m-%d'),
            'day': slot_date.strftime('%A, %B %d'),
            'slots': day_slots
        })
    
    # Remove already booked slots
    booked_appointments = mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'date': {'$gte': datetime.now()},
        'status': {'$in': ['scheduled', 'pending']}
    })
    
    booked_slots = {}
    for appt in booked_appointments:
        date_str = appt['date'].strftime('%Y-%m-%d')
        if date_str not in booked_slots:
            booked_slots[date_str] = []
        booked_slots[date_str].append(appt['time'])
    
    # Filter out booked slots
    for day in available_slots:
        date_str = day['date_str']
        if date_str in booked_slots:
            day['slots'] = [slot for slot in day['slots'] if slot not in booked_slots[date_str]]
    
    return render_template('therapist/schedule_appointment.html',
                         therapist=therapist,
                         student=student,
                         available_slots=available_slots)

@therapist_bp.route('/profile', methods=['GET', 'POST'])
@therapist_required
def profile():
    """Therapist profile and settings."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
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
                        'office_hours.description': office_hours_desc
                    }}
                )
                
                flash('Profile updated successfully', 'success')
                
            elif form_type == 'availability':
                # Update availability settings
                available_days = request.form.getlist('available_days[]')
                max_students = int(request.form.get('max_students', 20))
                
                # Convert days from string to int
                working_days = [int(day) for day in available_days if day.isdigit()]
                
                # Get time slots
                slots = []
                for hour in range(8, 18):  # 8 AM to 5 PM
                    slot_key = f'slot_{hour}'
                    if request.form.get(slot_key) == 'on':
                        slots.append(f'{hour:02d}:00')
                
                # Update therapist document
                mongo.db.therapists.update_one(
                    {'_id': therapist_id},
                    {'$set': {
                        'office_hours.days': working_days,
                        'office_hours.slots': slots,
                        'max_students': max_students
                    }}
                )
                
                flash('Availability settings updated successfully', 'success')
                
            elif form_type == 'password':
                # Update password
                current_password = request.form.get('current_password', '')
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')
                
                # Validate passwords
                from werkzeug.security import check_password_hash, generate_password_hash
                
                user = mongo.db.users.find_one({'_id': therapist_id})
                
                if not user:
                    flash('User account not found', 'error')
                    return redirect(url_for('therapist.profile'))
                
                if not check_password_hash(user['password'], current_password):
                    flash('Current password is incorrect', 'error')
                    return redirect(url_for('therapist.profile'))
                
                if new_password != confirm_password:
                    flash('New passwords do not match', 'error')
                    return redirect(url_for('therapist.profile'))
                
                if len(new_password) < 8:
                    flash('New password must be at least 8 characters long', 'error')
                    return redirect(url_for('therapist.profile'))
                
                # Update password
                mongo.db.users.update_one(
                    {'_id': therapist_id},
                    {'$set': {'password': generate_password_hash(new_password)}}
                )
                
                flash('Password updated successfully', 'success')
                
            elif form_type == 'notifications':
                # Update notification preferences
                email_notifications = request.form.get('email_notifications') == 'on'
                sms_notifications = request.form.get('sms_notifications') == 'on'
                
                # Update user preferences
                update_therapist_settings(therapist_id, {
                    'notifications': {
                        'email': email_notifications,
                        'sms': sms_notifications
                    }
                })
                
                flash('Notification preferences updated successfully', 'success')
            
        except Exception as e:
            logger.error(f"Profile update error: {e}")
            flash('An error occurred while updating your profile', 'error')
    
    # Get user document for additional info
    user = mongo.db.users.find_one({'_id': therapist_id})
    
    # Get account statistics
    stats = {
        'member_since': user.get('created_at', datetime.now()).strftime('%B %d, %Y'),
        'total_sessions': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'status': 'completed'
        }),
        'current_students': mongo.db.therapist_assignments.count_documents({
            'therapist_id': therapist_id,
            'status': 'active'
        }),
        'login_count': user.get('login_count', 0),
        'last_login': user.get('last_login', 'Never')
    }
    
    return render_template('therapist/profile.html',
                         therapist=therapist,
                         user=user,
                         stats=stats)

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
    
    return render_template('therapist/resources.html',
                         therapist=therapist,
                         system_resources=system_resources,
                         custom_resources=custom_resources,
                         recently_shared=recently_shared)

@therapist_bp.route('/add-resource', methods=['GET', 'POST'])
@therapist_required
def add_resource():
    """Add a custom resource."""
    therapist_id = ObjectId(session['user'])
    
    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            resource_type = request.form.get('type', '').strip()
            url = request.form.get('url', '').strip()
            
            # Validate form data
            if not title or not description or not resource_type or not url:
                flash('All fields are required', 'error')
                return redirect(url_for('therapist.add_resource'))
            
            # Create resource
            new_resource = {
                'therapist_id': therapist_id,
                'title': title,
                'description': description,
                'type': resource_type,
                'url': url,
                'created_at': datetime.now(timezone.utc)
            }
            
            mongo.db.therapist_resources.insert_one(new_resource)
            
            flash('Resource added successfully', 'success')
            return redirect(url_for('therapist.resources'))
            
        except Exception as e:
            logger.error(f"Add resource error: {e}")
            flash('An error occurred while adding the resource', 'error')
            return redirect(url_for('therapist.add_resource'))
    
    return render_template('therapist/add_resource.html')

@therapist_bp.route('/edit-resource/<resource_id>', methods=['GET', 'POST'])
@therapist_required
def edit_resource(resource_id):
    """Edit a custom resource."""
    therapist_id = ObjectId(session['user'])
    
    # Find the resource
    resource = mongo.db.therapist_resources.find_one({
        '_id': ObjectId(resource_id),
        'therapist_id': therapist_id
    })
    
    if not resource:
        flash('Resource not found or not owned by you', 'error')
        return redirect(url_for('therapist.resources'))
    
    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            resource_type = request.form.get('type', '').strip()
            url = request.form.get('url', '').strip()
            
            # Validate form data
            if not title or not description or not resource_type or not url:
                flash('All fields are required', 'error')
                return redirect(url_for('therapist.edit_resource', resource_id=resource_id))
            
            # Update resource
            mongo.db.therapist_resources.update_one(
                {'_id': ObjectId(resource_id)},
                {'$set': {
                    'title': title,
                    'description': description,
                    'type': resource_type,
                    'url': url,
                    'updated_at': datetime.now(timezone.utc)
                }}
            )
            
            flash('Resource updated successfully', 'success')
            return redirect(url_for('therapist.resources'))
            
        except Exception as e:
            logger.error(f"Edit resource error: {e}")
            flash('An error occurred while updating the resource', 'error')
            return redirect(url_for('therapist.edit_resource', resource_id=resource_id))
    
    return render_template('therapist/edit_resource.html', resource=resource)

@therapist_bp.route('/delete-resource/<resource_id>', methods=['POST'])
@therapist_required
def delete_resource(resource_id):
    """Delete a custom resource."""
    therapist_id = ObjectId(session['user'])
    
    # Find the resource
    resource = mongo.db.therapist_resources.find_one({
        '_id': ObjectId(resource_id),
        'therapist_id': therapist_id
    })
    
    if not resource:
        flash('Resource not found or not owned by you', 'error')
        return redirect(url_for('therapist.resources'))
    
    try:
        # Delete resource
        mongo.db.therapist_resources.delete_one({
            '_id': ObjectId(resource_id),
            'therapist_id': therapist_id
        })
        
        flash('Resource deleted successfully', 'success')
        
    except Exception as e:
        logger.error(f"Delete resource error: {e}")
        flash('An error occurred while deleting the resource', 'error')
    
    return redirect(url_for('therapist.resources'))

@therapist_bp.route('/student-requests')
@therapist_required
def student_requests():
    """View pending student assignment requests."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get pending student assignment requests
    pending_requests = list(mongo.db.therapist_requests.find({
        'status': 'pending_therapist_approval',
        'therapist_id': therapist_id
    }).sort('created_at', 1))
    
    # Get student details for each request
    for request in pending_requests:
        student = mongo.db.users.find_one({'_id': request['student_id']})
        if student:
            request['student_name'] = f"{student['first_name']} {student['last_name']}"
            request['student_email'] = student['email']
    
    return render_template('therapist/student_requests.html',
                         therapist=therapist,
                         pending_requests=pending_requests)

@therapist_bp.route('/approve-student/<request_id>', methods=['POST'])
@therapist_required
def approve_student(request_id):
    """Approve a student assignment request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the request
    request_data = mongo.db.therapist_requests.find_one({
        '_id': ObjectId(request_id),
        'status': 'pending_therapist_approval',
        'therapist_id': therapist_id
    })
    
    if not request_data:
        flash('Request not found or cannot be approved', 'error')
        return redirect(url_for('therapist.student_requests'))
    
    try:
        # Check therapist capacity
        therapist = find_therapist_by_id(therapist_id)
        
        if therapist['current_students'] >= therapist['max_students']:
            flash('You have reached your maximum student capacity', 'error')
            return redirect(url_for('therapist.student_requests'))
        
        # Create therapist assignment
        assignment = {
            'student_id': request_data['student_id'],
            'therapist_id': therapist_id,
            'status': 'active',
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        assignment_result = mongo.db.therapist_assignments.insert_one(assignment)
        
        # Update therapist's current student count
        mongo.db.therapists.update_one(
            {'_id': therapist_id},
            {'$inc': {'current_students': 1}}
        )
        
        # Update request status
        mongo.db.therapist_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'approved',
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': request_data['student_id'],
            'type': 'therapist_assigned',
            'message': 'Your therapist request has been approved. You can now schedule appointments and chat with your therapist.',
            'related_id': assignment_result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Send welcome message
        student = mongo.db.users.find_one({'_id': request_data['student_id']})
        student_name = f"{student['first_name']}" if student else "there"
        
        mongo.db.therapist_chats.insert_one({
            'student_id': request_data['student_id'],
            'therapist_id': therapist_id,
            'sender': 'therapist',
            'message': f"Hello {student_name}, I'm Dr. {therapist['first_name']} {therapist['last_name']}. I'll be your therapist. Feel free to message me anytime or schedule an appointment when you're ready.",
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        })
        
        flash('Student request approved successfully', 'success')
        
    except Exception as e:
        logger.error(f"Approve student error: {e}")
        flash('An error occurred while approving the student request', 'error')
    
    return redirect(url_for('therapist.student_requests'))

@therapist_bp.route('/reject-student/<request_id>', methods=['POST'])
@therapist_required
def reject_student(request_id):
    """Reject a student assignment request."""
    therapist_id = ObjectId(session['user'])
    
    # Find the request
    request_data = mongo.db.therapist_requests.find_one({
        '_id': ObjectId(request_id),
        'status': 'pending_therapist_approval',
        'therapist_id': therapist_id
    })
    
    if not request_data:
        flash('Request not found or cannot be rejected', 'error')
        return redirect(url_for('therapist.student_requests'))
    
    try:
        # Get reason for rejection
        reason = request.form.get('reason', '')
        
        # Update request status
        mongo.db.therapist_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'rejected_by_therapist',
                'rejection_reason': reason,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        # Add notification for student
        mongo.db.notifications.insert_one({
            'user_id': request_data['student_id'],
            'type': 'therapist_request_rejected',
            'message': 'Your therapist request could not be fulfilled at this time. Please try again.',
            'related_id': ObjectId(request_id),
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        flash('Student request rejected successfully', 'success')
        
    except Exception as e:
        logger.error(f"Reject student error: {e}")
        flash('An error occurred while rejecting the student request', 'error')
    
    return redirect(url_for('therapist.student_requests'))

@therapist_bp.route('/reports')
@therapist_required
def reports():
    """View therapist reports."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get date range for reports
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    try:
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
        else:
            # Default to 30 days ago
            from_date = datetime.now() - timedelta(days=30)
            
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d')
        else:
            # Default to today
            to_date = datetime.now()
    except ValueError:
        from_date = datetime.now() - timedelta(days=30)
        to_date = datetime.now()
    
    # Session statistics
    total_sessions = mongo.db.appointments.count_documents({
        'therapist_id': therapist_id,
        'status': 'completed',
        'date': {'$gte': from_date, '$lte': to_date}
    })
    
    cancelled_sessions = mongo.db.appointments.count_documents({
        'therapist_id': therapist_id,
        'status': 'cancelled',
        'date': {'$gte': from_date, '$lte': to_date}
    })
    
    scheduled_sessions = mongo.db.appointments.count_documents({
        'therapist_id': therapist_id,
        'status': 'scheduled',
        'date': {'$gte': datetime.now()}
    })
    
    # Student statistics
    active_students = mongo.db.therapist_assignments.count_documents({
        'therapist_id': therapist_id,
        'status': 'active'
    })
    
    # Weekly session breakdown
    weekly_sessions = []
    current_date = from_date
    
    while current_date <= to_date:
        # Get start and end of week
        start_of_week = current_date - timedelta(days=current_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        # Count sessions in this week
        week_sessions = mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'status': 'completed',
            'date': {'$gte': start_of_week, '$lte': end_of_week}
        })
        
        if week_sessions > 0:
            weekly_sessions.append({
                'week': start_of_week.strftime('%b %d') + ' - ' + end_of_week.strftime('%b %d'),
                'count': week_sessions
            })
        
        # Move to next week
        current_date = end_of_week + timedelta(days=1)
    
    # Top students by session count
    pipeline = [
        {'$match': {
            'therapist_id': therapist_id,
            'status': 'completed',
            'date': {'$gte': from_date, '$lte': to_date}
        }},
        {'$group': {
            '_id': '$student_id',
            'count': {'$sum': 1}
        }},
        {'$sort': {'count': -1}},
        {'$limit': 5}
    ]
    
    top_students_result = list(mongo.db.appointments.aggregate(pipeline))
    
    # Get student names
    top_students = []
    for result in top_students_result:
        student = mongo.db.users.find_one({'_id': result['_id']})
        if student:
            top_students.append({
                'name': f"{student['first_name']} {student['last_name']}",
                'count': result['count']
            })
    
    return render_template('therapist/reports.html',
                         therapist=therapist,
                         from_date=from_date,
                         to_date=to_date,
                         stats={
                             'total_sessions': total_sessions,
                             'cancelled_sessions': cancelled_sessions,
                             'scheduled_sessions': scheduled_sessions,
                             'active_students': active_students
                         },
                         weekly_sessions=weekly_sessions,
                         top_students=top_students)