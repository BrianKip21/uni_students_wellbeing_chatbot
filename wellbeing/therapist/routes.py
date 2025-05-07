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

@therapist_bp.route('/dashboard')
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
    
    return render_template('therapist/dashboard.html',
                         therapist=therapist,
                         today_appointments=today_appointments,
                         pending_appointment_requests=pending_appointment_requests,
                         pending_reschedules=pending_reschedules,
                         pending_cancellations=pending_cancellations,
                         unread_messages=unread_messages,
                         new_student_requests=new_student_requests,
                         stats=stats)

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