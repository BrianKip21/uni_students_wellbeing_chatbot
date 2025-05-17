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

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/calendar.html',
                         therapist=therapist,
                         calendar_data=calendar_data,
                         selected_date=selected_date,
                         view=view,
                         start_date=start_date,
                         end_date=end_date,
                         settings=settings,
                         datetime=datetime,  # Pass datetime
                         timedelta=timedelta) 
                         

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

    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/appointments.html',
                         therapist=therapist,
                         appointments=appointments,
                         pending_requests=pending_requests,
                         reschedule_requests=reschedule_requests,
                         cancellation_requests=cancellation_requests,
                         students=students,
                         filter_status=filter_status,
                         settings=settings
                        )

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
    
    # Log the number of assignments found (for debugging)
    logger.info(f"Found {len(assignments)} active assignments for therapist ID {therapist_id}")
    
    # Get user settings
    settings = mongo.db.settings.find_one() or {}
    
    # Get student details for each assignment
    students_data = []
    for assignment in assignments:
        student_id = assignment.get('student_id')
        if not student_id:
            logger.warning(f"Assignment {assignment['_id']} has no student_id field")
            continue
            
        student = mongo.db.users.find_one({'_id': student_id})
        if not student:
            logger.warning(f"Student with ID {student_id} not found")
            continue
            
        # Get latest appointment
        latest_appointment = mongo.db.appointments.find_one({
            'student_id': student_id,
            'therapist_id': therapist_id
        }, sort=[('date', -1)])
        
        # Get next upcoming appointment
        next_appointment = mongo.db.appointments.find_one({
            'student_id': student_id,
            'therapist_id': therapist_id,
            'date': {'$gte': datetime.now()},
            'status': 'scheduled'
        }, sort=[('date', 1)])
        
        # Count total sessions
        total_sessions = mongo.db.appointments.count_documents({
            'student_id': student_id,
            'therapist_id': therapist_id,
            'status': 'completed'
        })
        
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
            'unread_messages': unread_messages,
            'assigned_at': assignment.get('created_at', datetime.now())
        })
    
    # Sort students by most recently assigned
    students_data.sort(key=lambda x: x.get('assigned_at', datetime.now()), reverse=True)
    
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

    settings = mongo.db.settings.find_one() or {}
    
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
                         stats=stats,
                         settings=settings)

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

@therapist_bp.route('/schedule-appointment-from-calendar', methods=['POST'])
@therapist_required
def schedule_appointment_from_calendar():
    """Schedule an appointment from the calendar view."""
    therapist_id = ObjectId(session['user'])
    
    # Get form data
    student_id = request.form.get('student_id')
    date_str = request.form.get('date')
    time_str = request.form.get('time')
    session_type = request.form.get('session_type', 'online')
    notes = request.form.get('notes', '')
    
    # Validate required fields
    if not student_id or not date_str or not time_str:
        flash('Student, date, and time are required', 'error')
        return redirect(url_for('therapist.calendar'))
    
    try:
        # Convert student_id to ObjectId
        student_id_obj = ObjectId(student_id)
        
        # Verify assignment
        assignment = mongo.db.therapist_assignments.find_one({
            'therapist_id': therapist_id,
            'student_id': student_id_obj,
            'status': 'active'
        })
        
        if not assignment:
            flash('Student not assigned to you', 'error')
            return redirect(url_for('therapist.calendar'))
        
        # Get student data
        student = mongo.db.users.find_one({'_id': student_id_obj})
        
        if not student:
            flash('Student not found', 'error')
            return redirect(url_for('therapist.calendar'))
        
        # Parse appointment date
        try:
            appointment_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('therapist.calendar'))
        
        # Check if slot is available
        existing = mongo.db.appointments.find_one({
            'therapist_id': therapist_id,
            'date': appointment_date,
            'time': time_str,
            'status': {'$in': ['scheduled', 'pending']}
        })
        
        if existing:
            flash('This time slot is already booked', 'error')
            return redirect(url_for('therapist.calendar'))
        
        # Create appointment
        new_appointment = {
            'student_id': student_id_obj,
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
            'user_id': student_id_obj,
            'type': 'appointment_scheduled',
            'message': f'Your therapist has scheduled an appointment for you on {appointment_date.strftime("%A, %B %d")} at {time_str}.',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Add a message in chat about the scheduled appointment
        mongo.db.therapist_chats.insert_one({
            'student_id': student_id_obj,
            'therapist_id': therapist_id,
            'sender': 'therapist',
            'message': f"I've scheduled an appointment for you on {appointment_date.strftime('%A, %B %d')} at {time_str}. " + 
                      (f"Notes: {notes}" if notes else ""),
            'appointment_id': result.inserted_id,
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        })
        
        flash('Appointment scheduled successfully', 'success')
        
    except Exception as e:
        logger.error(f"Schedule appointment from calendar error: {e}")
        flash('An error occurred while scheduling the appointment', 'error')
    
    # Return to the calendar view
    view = request.form.get('view', 'week')
    date = request.form.get('calendar_date', '')  # The current view date
    
    if date:
        return redirect(url_for('therapist.calendar', date=date, view=view))
    else:
        return redirect(url_for('therapist.calendar', view=view))
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
        
        # NEW: Auto-create user document if it doesn't exist
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
        # Ensure user is a dictionary
        elif not isinstance(user, dict):
            if isinstance(user, str):
                user = {
                    '_id': therapist_id,
                    'name': user,
                    'first_name': user,
                    'last_name': '',
                    'email': 'unknown@example.com',
                    'created_at': datetime.now(),
                    'login_count': 0,
                    'last_login': 'Never'
                }
            elif hasattr(user, '__dict__'):
                user = vars(user)
            else:
                user = {
                    '_id': therapist_id,
                    'first_name': 'Unknown',
                    'last_name': 'User',
                    'email': 'unknown@example.com',
                    'created_at': datetime.now(),
                    'login_count': 0,
                    'last_login': 'Never'
                }
        
        if request.method == 'POST':
            try:
                form_type = request.form.get('form_type')
                
                if form_type == 'profile':
                    # Update profile information
                    specialization = request.form.get('specialization', '').strip()
                    bio = request.form.get('bio', '').strip()
                    office_hours_desc = request.form.get('office_hours', '').strip()
                    
                    # Check if office_hours is a string or object in the database
                    existing_therapist = mongo.db.therapists.find_one({'_id': therapist_id})
                    update_dict = {
                        'specialization': specialization,
                        'bio': bio
                    }
                    
                    # Handle office_hours update safely
                    if existing_therapist and 'office_hours' in existing_therapist:
                        if isinstance(existing_therapist['office_hours'], dict):
                            # If it's already a dictionary, update the description field
                            update_dict['office_hours.description'] = office_hours_desc
                        else:
                            # If it's a string or other type, replace the entire field
                            update_dict['office_hours'] = {
                                'description': office_hours_desc,
                                'days': [0, 1, 2, 3, 4],  # Default to weekdays
                                'slots': ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']  # Default slots
                            }
                    else:
                        # If office_hours doesn't exist yet, create it as a complete object
                        update_dict['office_hours'] = {
                            'description': office_hours_desc,
                            'days': [0, 1, 2, 3, 4],
                            'slots': ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']
                        }
                    
                    # Update therapist document
                    mongo.db.therapists.update_one(
                        {'_id': therapist_id},
                        {'$set': update_dict}
                    )
                    
                    # NEW: Also update name fields in the user document if they've changed
                    user_update = {}
                    if 'first_name' in therapist and therapist['first_name'] != user.get('first_name'):
                        user_update['first_name'] = therapist['first_name']
                    if 'last_name' in therapist and therapist['last_name'] != user.get('last_name'):
                        user_update['last_name'] = therapist['last_name']
                    
                    if user_update:
                        mongo.db.users.update_one(
                            {'_id': user['_id']},
                            {'$set': user_update}
                        )
                    
                    flash('Profile updated successfully', 'success')
                    
                    # Refresh therapist data after update
                    therapist = find_therapist_by_id(therapist_id)
                    if not isinstance(therapist, dict):
                        if hasattr(therapist, '__dict__'):
                            therapist = vars(therapist)
                        elif isinstance(therapist, str):
                            therapist = {'name': therapist, '_id': therapist_id}
                        else:
                            therapist = {'_id': therapist_id}
                    
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
                    
                    # Check if office_hours is a string or object in the database
                    existing_therapist = mongo.db.therapists.find_one({'_id': therapist_id})
                    
                    # Prepare the update operation
                    update_operations = {'max_students': max_students}
                    
                    if existing_therapist and 'office_hours' in existing_therapist and not isinstance(existing_therapist['office_hours'], dict):
                        # If it's a string or other type, create a new dictionary with all fields
                        update_operations['office_hours'] = {
                            'description': str(existing_therapist['office_hours']) if existing_therapist['office_hours'] else '',
                            'days': working_days,
                            'slots': slots
                        }
                    else:
                        # If it's already a dictionary or doesn't exist, create or update with a full object
                        update_operations['office_hours'] = {
                            'description': existing_therapist.get('office_hours', {}).get('description', '') 
                                          if isinstance(existing_therapist.get('office_hours'), dict) else '',
                            'days': working_days,
                            'slots': slots
                        }
                    
                    # Update therapist document
                    mongo.db.therapists.update_one(
                        {'_id': therapist_id},
                        {'$set': update_operations}
                    )
                    
                    flash('Availability settings updated successfully', 'success')
                    
                    # Refresh therapist data after update
                    therapist = find_therapist_by_id(therapist_id)
                    if not isinstance(therapist, dict):
                        if hasattr(therapist, '__dict__'):
                            therapist = vars(therapist)
                        elif isinstance(therapist, str):
                            therapist = {'name': therapist, '_id': therapist_id}
                        else:
                            therapist = {'_id': therapist_id}
                    
                elif form_type == 'password':
                    # Update password
                    current_password = request.form.get('current_password', '')
                    new_password = request.form.get('new_password', '')
                    confirm_password = request.form.get('confirm_password', '')
                    
                    # Validate passwords
                    from werkzeug.security import check_password_hash, generate_password_hash
                    
                    # NEW: Handle the case where the user might not have a password yet
                    if not isinstance(user, dict) or 'password' not in user or not user['password']:
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
                    
                    # Refresh user data after update
                    user = mongo.db.users.find_one({'_id': user['_id']})
                    if not isinstance(user, dict):
                        if isinstance(user, str):
                            user = {'name': user, '_id': therapist_id}
                        elif hasattr(user, '__dict__'):
                            user = vars(user)
                        else:
                            user = {
                                '_id': therapist_id,
                                'first_name': 'Unknown',
                                'last_name': 'User',
                                'email': 'unknown@example.com',
                                'created_at': datetime.now(),
                                'login_count': 0,
                                'last_login': 'Never'
                            }
                    
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
                    
                    # Refresh therapist data after update
                    therapist = find_therapist_by_id(therapist_id)
                    if not isinstance(therapist, dict):
                        if hasattr(therapist, '__dict__'):
                            therapist = vars(therapist)
                        elif isinstance(therapist, str):
                            therapist = {'name': therapist, '_id': therapist_id}
                        else:
                            therapist = {'_id': therapist_id}
                
            except Exception as e:
                logger.error(f"Profile update error: {e}")
                flash(f'An error occurred while updating your profile: {str(e)}', 'error')
        
        # Get account statistics with safe fallbacks for all fields
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
        
        # Final type checking for template variables
        if not isinstance(therapist, dict):
            therapist = {'error': 'Invalid therapist data', '_id': therapist_id}
        
        if not isinstance(user, dict):
            user = {'error': 'Invalid user data', '_id': therapist_id}
        
        # Ensure each value in therapist is not a dictionary or object to prevent nested .get() calls
        for key, value in list(therapist.items()):
            if isinstance(value, dict) or (hasattr(value, '__dict__') and not isinstance(value, (str, int, float, bool, datetime))):
                # Keep office_hours as a dictionary but convert other nested objects to strings
                if key != 'office_hours':
                    therapist[key] = str(value)
        
        # Ensure each value in user is not a dictionary or object
        for key, value in list(user.items()):
            if isinstance(value, dict) or (hasattr(value, '__dict__') and not isinstance(value, (str, int, float, bool, datetime))):
                # Convert nested objects to strings to prevent template errors with .get()
                user[key] = str(value)

        settings = mongo.db.settings.find_one() or {}
        if not isinstance(settings, dict):
            settings = {}
            
        # Ensure we have default values for critical fields in therapist
        if 'first_name' not in therapist:
            therapist['first_name'] = user.get('first_name', 'Unknown')
        if 'last_name' not in therapist:
            therapist['last_name'] = user.get('last_name', 'User')
            
        # Final safety check - convert to standard Python dictionaries
        therapist = dict(therapist)
        user = dict(user)
        stats = dict(stats)
        settings = dict(settings)
        
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

@therapist_bp.route('/student_requests')
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
        '$or': [
            {'status': 'pending_therapist_approval', 'therapist_id': therapist_id},
            {'status': 'pending', 'therapist_id': therapist_id}
        ]
    }).sort('created_at', 1))
    
    # IMPORTANT: Also check for new assignments created by admin
    # that haven't been acknowledged by the therapist yet
    admin_assignments = list(mongo.db.therapist_assignments.find({
        'therapist_id': therapist_id,
        'status': 'active',
        'acknowledged': {'$exists': False}  # Therapist hasn't acknowledged yet
    }).sort('created_at', -1))
    
    # Combine these admin assignments into the pending_requests list
    for assignment in admin_assignments:
        # Convert admin assignment to request format
        request_data = {
            '_id': assignment['_id'],
            'student_id': assignment['student_id'],
            'therapist_id': therapist_id,
            'status': 'admin_assigned',  # Special status for admin assignments
            'created_at': assignment.get('created_at', datetime.now()),
            'assigned_by': assignment.get('assigned_by', 'Admin'),
            'source': 'admin_assignment'  # Flag to identify source
        }
        pending_requests.append(request_data)
    
    # Get student details for each request
    for request in pending_requests:
        student = mongo.db.users.find_one({'_id': request['student_id']})
        if student:
            request['student_name'] = f"{student['first_name']} {student['last_name']}"
            request['student_email'] = student['email']
    
    # Get settings
    settings = mongo.db.settings.find_one() or {}
    
    return render_template('therapist/student_requests.html',
                         therapist=therapist,
                         pending_requests=pending_requests,
                         settings=settings)

@therapist_bp.route('/acknowledge-assignment/<assignment_id>', methods=['POST'])
@therapist_required
def acknowledge_assignment(assignment_id):
    """Acknowledge an assignment made by an admin."""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Find the assignment
        assignment = mongo.db.therapist_assignments.find_one({
            '_id': ObjectId(assignment_id),
            'therapist_id': therapist_id,
            'status': 'active'
        })
        
        if not assignment:
            flash('Assignment not found', 'error')
            return redirect(url_for('therapist.student_requests'))
        
        # Mark the assignment as acknowledged
        mongo.db.therapist_assignments.update_one(
            {'_id': ObjectId(assignment_id)},
            {'$set': {
                'acknowledged': True,
                'acknowledged_at': datetime.now()
            }}
        )
        
        # Get student info
        student = mongo.db.users.find_one({'_id': assignment['student_id']})
        student_name = f"{student['first_name']} {student['last_name']}" if student else "Unknown Student"
        
        # Send welcome message to student
        if student:
            therapist = find_therapist_by_id(therapist_id)
            welcome_message = f"Hello {student['first_name']}, I'm Dr. {therapist['first_name']} {therapist['last_name']}. I'll be your therapist. Feel free to message me anytime or schedule an appointment when you're ready."
            
            mongo.db.therapist_chats.insert_one({
                'student_id': assignment['student_id'],
                'therapist_id': therapist_id,
                'sender': 'therapist',
                'message': welcome_message,
                'read': False,
                'timestamp': datetime.now()
            })
        
        flash(f"You are now assigned to {student_name}. A welcome message has been sent.", 'success')
        return redirect(url_for('therapist.students'))
        
    except Exception as e:
        logger.error(f"Acknowledge assignment error: {e}")
        flash('An error occurred while acknowledging the assignment', 'error')
        return redirect(url_for('therapist.student_requests'))

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
    settings = mongo.db.settings.find_one() or {}
    
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
                         top_students=top_students,
                         settings=settings)
@therapist_bp.route('/export-session-report/<format>')
@therapist_required
def export_session_report(format):
    """Export session report in CSV or PDF format."""
    therapist_id = ObjectId(session['user'])
    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    
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
        flash('Invalid date format', 'error')
        return redirect(url_for('therapist.reports'))
    
    # Get sessions data
    sessions = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'date': {'$gte': from_date, '$lte': to_date}
    }).sort('date', 1))
    
    # Get student details for each session
    for appt in sessions:
        student = mongo.db.users.find_one({'_id': appt['student_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        else:
            appt['student_name'] = "Unknown"
    
    if format.lower() == 'csv':
        # Create CSV data
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Date', 'Time', 'Student', 'Session Type', 'Status'])
        
        # Write data
        for appt in sessions:
            writer.writerow([
                appt['date'].strftime('%Y-%m-%d'),
                appt['time'],
                appt.get('student_name', 'Unknown'),
                appt.get('session_type', 'N/A'),
                appt.get('status', 'N/A')
            ])
        
        # Create response
        output.seek(0)
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename=sessions_report_{datetime.now().strftime("%Y%m%d")}.csv'
        return response
    
    elif format.lower() == 'pdf':
        # This would need a PDF generation library like ReportLab or WeasyPrint
        # For simplicity, we'll return a placeholder response
        flash('PDF export is not yet implemented', 'error')
        return redirect(url_for('therapist.reports'))
    
    else:
        flash('Invalid export format', 'error')
        return redirect(url_for('therapist.reports'))


@therapist_bp.route('/export-student-report/<format>')
@therapist_required
def export_student_report(format):
    """Export student report in CSV or PDF format."""
    therapist_id = ObjectId(session['user'])
    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    
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
        flash('Invalid date format', 'error')
        return redirect(url_for('therapist.reports'))
    
    # Get active student assignments
    assignments = list(mongo.db.therapist_assignments.find({
        'therapist_id': therapist_id,
        'status': 'active'
    }))
    
    # Get student details and session statistics
    students_data = []
    for assignment in assignments:
        student = mongo.db.users.find_one({'_id': assignment['student_id']})
        if student:
            # Count sessions in the date range
            total_sessions = mongo.db.appointments.count_documents({
                'therapist_id': therapist_id,
                'student_id': assignment['student_id'],
                'status': 'completed',
                'date': {'$gte': from_date, '$lte': to_date}
            })
            
            # Get latest appointment
            latest_appointment = mongo.db.appointments.find_one({
                'therapist_id': therapist_id,
                'student_id': assignment['student_id'],
                'status': 'completed'
            }, sort=[('date', -1)])
            
            # Get next appointment
            next_appointment = mongo.db.appointments.find_one({
                'therapist_id': therapist_id,
                'student_id': assignment['student_id'],
                'date': {'$gte': datetime.now()},
                'status': 'scheduled'
            }, sort=[('date', 1)])
            
            students_data.append({
                'id': str(student['_id']),
                'name': f"{student['first_name']} {student['last_name']}",
                'email': student['email'],
                'total_sessions': total_sessions,
                'last_session': latest_appointment['date'].strftime('%Y-%m-%d') if latest_appointment else 'None',
                'next_session': next_appointment['date'].strftime('%Y-%m-%d') if next_appointment else 'None'
            })
    
    if format.lower() == 'csv':
        # Create CSV data
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['ID', 'Name', 'Email', 'Total Sessions', 'Last Session', 'Next Session'])
        
        # Write data
        for student in students_data:
            writer.writerow([
                student['id'],
                student['name'],
                student['email'],
                student['total_sessions'],
                student['last_session'],
                student['next_session']
            ])
        
        # Create response
        output.seek(0)
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename=students_report_{datetime.now().strftime("%Y%m%d")}.csv'
        return response
    
    elif format.lower() == 'pdf':
        # This would need a PDF generation library like ReportLab or WeasyPrint
        # For simplicity, we'll return a placeholder response
        flash('PDF export is not yet implemented', 'error')
        return redirect(url_for('therapist.reports'))
    
    else:
        flash('Invalid export format', 'error')
        return redirect(url_for('therapist.reports'))


@therapist_bp.route('/export-summary-report/<format>')
@therapist_required
def export_summary_report(format):
    """Export summary report in CSV or PDF format."""
    therapist_id = ObjectId(session['user'])
    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    
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
        flash('Invalid date format', 'error')
        return redirect(url_for('therapist.reports'))
    
    # Get therapist data
    therapist = find_therapist_by_id(therapist_id)
    
    # Calculate statistics
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
    
    active_students = mongo.db.therapist_assignments.count_documents({
        'therapist_id': therapist_id,
        'status': 'active'
    })
    
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
                'id': str(student['_id']),
                'name': f"{student['first_name']} {student['last_name']}",
                'count': result['count']
            })
    
    # Get weekly session breakdown
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
    
    # Compile summary data
    summary_data = {
        'therapist_name': f"Dr. {therapist.get('first_name', '')} {therapist.get('last_name', '')}",
        'period': f"{from_date.strftime('%B %d, %Y')} - {to_date.strftime('%B %d, %Y')}",
        'total_sessions': total_sessions,
        'cancelled_sessions': cancelled_sessions,
        'scheduled_sessions': scheduled_sessions,
        'active_students': active_students,
        'top_students': top_students,
        'weekly_sessions': weekly_sessions
    }
    
    if format.lower() == 'csv':
        # Create CSV data
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header and summary info
        writer.writerow(['Summary Report'])
        writer.writerow(['Therapist', summary_data['therapist_name']])
        writer.writerow(['Period', summary_data['period']])
        writer.writerow([])
        writer.writerow(['Total Sessions', summary_data['total_sessions']])
        writer.writerow(['Cancelled Sessions', summary_data['cancelled_sessions']])
        writer.writerow(['Scheduled Sessions', summary_data['scheduled_sessions']])
        writer.writerow(['Active Students', summary_data['active_students']])
        writer.writerow([])
        
        # Write top students
        writer.writerow(['Top Students'])
        writer.writerow(['Name', 'Sessions'])
        for student in summary_data['top_students']:
            writer.writerow([student['name'], student['count']])
        writer.writerow([])
        
        # Write weekly sessions
        writer.writerow(['Weekly Sessions'])
        writer.writerow(['Week', 'Sessions'])
        for week in summary_data['weekly_sessions']:
            writer.writerow([week['week'], week['count']])
        
        # Create response
        output.seek(0)
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename=summary_report_{datetime.now().strftime("%Y%m%d")}.csv'
        return response
    
    elif format.lower() == 'pdf':
       
        flash('PDF export is not yet implemented', 'error')
        return redirect(url_for('therapist.reports'))
    
    else:
        flash('Invalid export format', 'error')
        return redirect(url_for('therapist.reports'))