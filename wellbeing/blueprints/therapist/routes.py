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
from wellbeing.utils.automated_moderation import send_auto_moderated_message, AutomatedModerator
from wellbeing.utils.scheduling import (
    create_enhanced_fallback_meeting_link,
    cancel_zoom_meeting_in_appointment,
    refresh_zoom_meeting_for_appointment
)

from wellbeing.utils.appointments import (
    is_zoom_integrated,
    can_schedule_appointment
)

# Add this NEW function to therapist.py
def get_therapist_students_with_fallback(therapist_id):
    """Get students for a therapist with fallback to users collection"""
    try:
        # Primary method: get from therapist_assignments
        assignments = list(mongo.db.therapist_assignments.find({
            'therapist_id': therapist_id,
            'status': 'active'
        }))
        
        logger.info(f"Found {len(assignments)} assignments for therapist {therapist_id}")
        
        # Fallback method: if no assignments found, check users collection
        if not assignments:
            logger.info(f"No assignments found, checking users collection for fallback")
            users_with_therapist = list(mongo.db.users.find({
                'assigned_therapist_id': therapist_id,
                'role': 'student'
            }))
            
            if users_with_therapist:
                logger.info(f"Found {len(users_with_therapist)} users assigned to therapist via users collection")
                # Create missing assignments
                for user in users_with_therapist:
                    assignment_data = {
                        'therapist_id': therapist_id,
                        'student_id': user['_id'],
                        'status': 'active',
                        'auto_assigned': True,
                        'created_at': user.get('assignment_date', datetime.now()),
                        'updated_at': datetime.now()
                    }
                    
                    # Check if assignment already exists before inserting
                    existing = mongo.db.therapist_assignments.find_one({
                        'therapist_id': therapist_id,
                        'student_id': user['_id']
                    })
                    
                    if not existing:
                        mongo.db.therapist_assignments.insert_one(assignment_data)
                        assignments.append(assignment_data)
                        logger.info(f"Created missing assignment for student {user['_id']}")
        
        return assignments
        
    except Exception as e:
        logger.error(f"Error getting therapist students: {str(e)}")
        return []
    
def _get_enhanced_session_controls_therapist(appointment):
    """Get enhanced session controls for therapist view with Zoom integration"""
    if not appointment.get('datetime'):
        return {
            'status': 'pending',
            'message': 'Time to be confirmed',
            'can_join': False,
            'button_class': 'btn-secondary',
            'icon': 'fas fa-clock',
            'zoom_status': 'pending'
        }
    
    now = datetime.now()
    session_time = appointment['datetime']
    time_diff = (session_time - now).total_seconds() / 60  # minutes
    
    status = appointment.get('status', 'confirmed')
    
    if status in ['cancelled', 'completed']:
        return {
            'status': status,
            'message': f'Session {status}',
            'can_join': False,
            'button_class': 'btn-secondary opacity-50',
            'icon': 'fas fa-check-circle' if status == 'completed' else 'fas fa-times-circle',
            'zoom_status': status
        }
    
    # Check Zoom integration status
    zoom_integrated = is_zoom_integrated(appointment.get('zoom_meeting_id'))
    meeting_info = appointment.get('meeting_info', {})
    has_meeting_link = bool(meeting_info.get('meet_link'))
    
    # 5-minute window logic
    join_window_start = 5  # 5 minutes before
    join_window_end = 5    # 5 minutes after start
    
    if time_diff > join_window_start:
        minutes_to_wait = int(time_diff - join_window_start)
        return {
            'status': 'waiting',
            'message': f'Available in {minutes_to_wait} minutes',
            'can_join': False,
            'button_class': 'btn-secondary',
            'icon': 'fas fa-clock',
            'countdown': True,
            'zoom_status': 'integrated' if zoom_integrated else 'fallback',
            'zoom_integrated': zoom_integrated,
            'meeting_available': has_meeting_link
        }
    elif -join_window_end <= time_diff <= join_window_start:
        return {
            'status': 'available',
            'message': 'Join Zoom Session',
            'can_join': True and has_meeting_link,
            'button_class': 'btn-success pulse' if has_meeting_link else 'btn-warning',
            'icon': 'fas fa-video',
            'urgent': time_diff <= 0,
            'zoom_status': 'integrated' if zoom_integrated else 'fallback',
            'zoom_integrated': zoom_integrated,
            'meeting_available': has_meeting_link
        }
    else:
        return {
            'status': 'expired',
            'message': 'Session window closed',
            'can_join': False,
            'button_class': 'btn-warning',
            'icon': 'fas fa-exclamation-triangle',
            'zoom_status': 'expired'
        }

def ensure_zoom_meeting_for_appointment(appointment):
    """Ensure appointment has Zoom meeting using your existing functions"""
    try:
        if not appointment.get('meeting_info') or not appointment['meeting_info'].get('meet_link'):
            # Try to refresh Zoom meeting if it exists
            if (appointment.get('zoom_meeting_id') and 
                not str(appointment.get('zoom_meeting_id', '')).startswith('fallback')):
                
                refresh_success = refresh_zoom_meeting_for_appointment(appointment['_id'])
                if refresh_success:
                    # Reload appointment to get updated meeting info
                    updated_appointment = mongo.db.appointments.find_one({'_id': appointment['_id']})
                    if updated_appointment and updated_appointment.get('meeting_info'):
                        appointment['meeting_info'] = updated_appointment['meeting_info']
                        return True
            
            # Create fallback meeting info using your existing function
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
            return True
            
    except Exception as e:
        logger.error(f"Error ensuring Zoom meeting: {str(e)}")
        return False
    
@therapist_bp.route('/dashboard', methods=['GET', 'POST'])
@therapist_required
def index():
    """Enhanced therapist dashboard with Zoom integration and session management"""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get today's date
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get today's appointments with enhanced Zoom controls
    today_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'datetime': {
            '$gte': today,
            '$lt': today + timedelta(days=1)
        },
        'status': 'confirmed',
        'type': 'virtual',
        'deleted': {'$ne': True}  # Exclude soft-deleted appointments
    }).sort('datetime', 1))
    
    # Add enhanced session controls with Zoom integration
    for appt in today_appointments:
        # Get student info (check both collections)
        student = mongo.db.users.find_one({'_id': appt['user_id']}) or mongo.db.students.find_one({'_id': appt['user_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        
        # Ensure Zoom meeting exists using your existing functions
        ensure_zoom_meeting_for_appointment(appt)
        
        # Add enhanced session controls with Zoom status
        appt['session_controls'] = _get_enhanced_session_controls_therapist(appt)
        
        # Add Zoom integration status
        appt['zoom_integrated'] = is_zoom_integrated(appt.get('zoom_meeting_id'))
        appt['zoom_status'] = _get_zoom_status(appt)
    
    # Get pending reschedule requests from students
    pending_reschedules = list(mongo.db.reschedule_requests.find({
        'therapist_id': therapist_id,
        'status': 'pending'
    }).sort('created_at', -1).limit(5))
    
    for req in pending_reschedules:
        student = mongo.db.users.find_one({'_id': req['student_id']}) or mongo.db.students.find_one({'_id': req['student_id']})
        if student:
            req['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get recent student cancellations (last 24 hours)
    recent_cancellations = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'status': 'cancelled',
        'cancelled_at': {'$gte': datetime.now() - timedelta(hours=24)}
    }).sort('cancelled_at', -1))
    
    for cancel in recent_cancellations:
        student = mongo.db.users.find_one({'_id': cancel['user_id']}) or mongo.db.students.find_one({'_id': cancel['user_id']})
        if student:
            cancel['student_name'] = f"{student['first_name']} {student['last_name']}"
    
    # Get crisis appointments with Zoom status
    crisis_appointments = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'crisis_level': {'$in': ['high', 'critical']},
        'status': 'confirmed',
        'datetime': {'$gte': datetime.now()},
        'deleted': {'$ne': True}
    }).sort('datetime', 1))
    
    for appt in crisis_appointments:
        student = mongo.db.users.find_one({'_id': appt['user_id']}) or mongo.db.students.find_one({'_id': appt['user_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        
        ensure_zoom_meeting_for_appointment(appt)
        appt['session_controls'] = _get_enhanced_session_controls_therapist(appt)
        appt['zoom_integrated'] = is_zoom_integrated(appt.get('zoom_meeting_id'))
    
    # Get unread messages count
    unread_messages = mongo.db.therapist_chats.count_documents({
        'therapist_id': therapist_id,
        'sender': 'student',
        'read': False
    })
    
    # Enhanced statistics with Zoom integration
    stats = {
        'total_students': mongo.db.therapist_assignments.count_documents({
            'therapist_id': therapist_id,
            'status': 'active'
        }),
        'virtual_sessions_today': len(today_appointments),
        'pending_reschedules': len(pending_reschedules),
        'recent_cancellations': len(recent_cancellations),
        'crisis_sessions': len(crisis_appointments),
        'auto_scheduled_today': mongo.db.appointments.count_documents({
            'therapist_id': therapist_id,
            'auto_scheduled': True,
            'created_at': {'$gte': today}
        }),
        'zoom_integrated_sessions': len([apt for apt in today_appointments if apt.get('zoom_integrated')])
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
                         pending_reschedules=pending_reschedules,
                         recent_cancellations=recent_cancellations,
                         crisis_appointments=crisis_appointments,
                         unread_messages=unread_messages,
                         stats=stats,
                         availability=availability,
                         settings=settings)

def _get_zoom_status(appointment):
    """Get Zoom integration status using your existing functions"""
    meeting_info = appointment.get('meeting_info', {})
    zoom_meeting_id = appointment.get('zoom_meeting_id')
    
    return {
        'integrated': is_zoom_integrated(zoom_meeting_id),
        'link_available': bool(meeting_info.get('meet_link')),
        'platform': meeting_info.get('platform', 'Unknown'),
        'meeting_id': zoom_meeting_id,
        'is_fallback': str(zoom_meeting_id).startswith('fallback') if zoom_meeting_id else True
    }

@therapist_bp.route('/api/respond-to-reschedule', methods=['POST'])
@therapist_required
def respond_to_reschedule():
    """Respond to student's auto-reschedule request with Zoom integration"""
    therapist_id = ObjectId(session['user'])
    
    try:
        data = request.get_json()
        request_id = data.get('request_id')
        response_type = data.get('response_type')  # 'provide_slots' or 'reject'
        suggested_slots = data.get('suggested_slots', [])
        therapist_message = data.get('message', '')
        
        if not request_id or not response_type:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Get reschedule request
        reschedule_request = mongo.db.reschedule_requests.find_one({
            '_id': ObjectId(request_id),
            'therapist_id': therapist_id,
            'status': 'pending'
        })
        
        if not reschedule_request:
            return jsonify({'success': False, 'error': 'Reschedule request not found'}), 404
        
        if response_type == 'provide_slots':
            # Convert suggested slots to proper format with Zoom meeting creation
            formatted_slots = []
            for slot_str in suggested_slots:
                try:
                    slot_datetime = datetime.fromisoformat(slot_str)
                    formatted_slots.append({
                        'datetime': slot_datetime,
                        'formatted': slot_datetime.strftime('%A, %B %d at %I:%M %p')
                    })
                except ValueError:
                    continue
            
            if not formatted_slots:
                return jsonify({'success': False, 'error': 'No valid time slots provided'}), 400
            
            # Update original appointment if student selects a slot later
            original_appointment = mongo.db.appointments.find_one({
                '_id': reschedule_request['original_appointment_id']
            })
            
            # Update request with therapist response
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'responded',
                        'therapist_response': therapist_message,
                        'suggested_times': formatted_slots,
                        'responded_at': datetime.now()
                    }
                }
            )
            
            # Notify student with Zoom-enabled options
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'reschedule_response',
                'title': 'New Time Options Available',
                'message': f"Your therapist provided {len(formatted_slots)} new Zoom session options. Choose your preferred time.",
                'reschedule_request_id': ObjectId(request_id),
                'created_at': datetime.now(),
                'read': False
            })
            
            return jsonify({
                'success': True,
                'message': f'Provided {len(formatted_slots)} time slots with Zoom integration'
            })
        
        elif response_type == 'reject':
            # Reject the reschedule request
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'rejected',
                        'therapist_response': therapist_message,
                        'responded_at': datetime.now()
                    }
                }
            )
            
            # Notify student
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'reschedule_rejected',
                'title': 'Reschedule Not Available',
                'message': f"Unable to reschedule at this time. {therapist_message}",
                'reschedule_request_id': ObjectId(request_id),
                'created_at': datetime.now(),
                'read': False
            })
            
            return jsonify({
                'success': True,
                'message': 'Reschedule request rejected'
            })
        
        return jsonify({'success': False, 'error': 'Invalid response type'}), 400
        
    except Exception as e:
        logger.error(f"Error responding to reschedule: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to respond'}), 500

@therapist_bp.route('/api/session-status/<appointment_id>')
@therapist_required
def get_session_status(appointment_id):
    """Get real-time session status with Zoom integration"""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            return jsonify({'error': 'Session not found'}), 404
        
        student = mongo.db.users.find_one({'_id': appointment['user_id']}) or mongo.db.students.find_one({'_id': appointment['user_id']})
        
        # Ensure Zoom meeting exists
        ensure_zoom_meeting_for_appointment(appointment)
        
        session_controls = _get_enhanced_session_controls_therapist(appointment)
        zoom_status = _get_zoom_status(appointment)
        
        return jsonify({
            'session_id': str(appointment['_id']),
            'student_name': f"{student['first_name']} {student['last_name']}" if student else 'Unknown Student',
            'datetime': appointment['datetime'].isoformat() if appointment.get('datetime') else None,
            'formatted_time': appointment.get('formatted_time', 'Time TBD'),
            'status': appointment.get('status', 'confirmed'),
            'session_controls': session_controls,
            'zoom_status': zoom_status,
            'meeting_link': appointment.get('meeting_info', {}).get('meet_link'),
            'student_joined': bool(appointment.get('last_joined')),
            'student_join_count': appointment.get('join_count', 0),
            'auto_scheduled': appointment.get('auto_scheduled', False),
            'zoom_meeting_id': appointment.get('zoom_meeting_id'),
            'host_link': appointment.get('meeting_info', {}).get('host_link')
        })
        
    except Exception as e:
        logger.error(f"Error getting session status: {str(e)}")
        return jsonify({'error': 'Failed to get session status'}), 500

@therapist_bp.route('/api/refresh-session-zoom/<appointment_id>', methods=['POST'])
@therapist_required
def refresh_session_zoom(appointment_id):
    """Refresh Zoom meeting for a session using your existing functions"""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            return jsonify({'error': 'Session not found'}), 404
        
        # Try to refresh Zoom meeting using your existing function
        refresh_success = refresh_zoom_meeting_for_appointment(ObjectId(appointment_id))
        
        if refresh_success:
            # Get updated appointment
            updated_appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            meeting_info = updated_appointment.get('meeting_info', {})
            
            return jsonify({
                'success': True,
                'message': 'Zoom meeting refreshed successfully',
                'meeting_link': meeting_info.get('meet_link'),
                'host_link': meeting_info.get('host_link'),
                'zoom_integrated': is_zoom_integrated(updated_appointment.get('zoom_meeting_id')),
                'platform': meeting_info.get('platform', 'Zoom')
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to refresh Zoom meeting. Using fallback link.',
                'zoom_integrated': False
            })
        
    except Exception as e:
        logger.error(f"Error refreshing Zoom meeting: {str(e)}")
        return jsonify({'error': 'Failed to refresh Zoom meeting'}), 500

@therapist_bp.route('/api/upcoming-sessions')
@therapist_required
def get_upcoming_sessions():
    """Get therapist's upcoming sessions with Zoom integration"""
    therapist_id = ObjectId(session['user'])
    
    try:
        upcoming_sessions = list(mongo.db.appointments.find({
            'therapist_id': therapist_id,
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed',
            'deleted': {'$ne': True}
        }).sort('datetime', 1).limit(10))
        
        sessions_data = []
        for session in upcoming_sessions:
            student = mongo.db.users.find_one({'_id': session['user_id']}) or mongo.db.students.find_one({'_id': session['user_id']})
            
            # Ensure Zoom meeting exists
            ensure_zoom_meeting_for_appointment(session)
            
            session_data = {
                'id': str(session['_id']),
                'student_name': f"{student['first_name']} {student['last_name']}" if student else 'Unknown Student',
                'student_id': str(session['user_id']),
                'datetime': session['datetime'].isoformat(),
                'formatted_time': session.get('formatted_time', 'Time TBD'),
                'crisis_level': session.get('crisis_level', 'normal'),
                'auto_scheduled': session.get('auto_scheduled', False),
                'session_controls': _get_enhanced_session_controls_therapist(session),
                'zoom_status': _get_zoom_status(session),
                'meeting_link': session.get('meeting_info', {}).get('meet_link'),
                'host_link': session.get('meeting_info', {}).get('host_link'),
                'zoom_integrated': is_zoom_integrated(session.get('zoom_meeting_id'))
            }
            sessions_data.append(session_data)
        
        return jsonify({
            'upcoming_sessions': sessions_data,
            'total_count': len(sessions_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting upcoming sessions: {str(e)}")
        return jsonify({'error': 'Failed to get sessions'}), 500

@therapist_bp.route('/api/cancel-session-therapist', methods=['POST'])
@therapist_required
def cancel_session_therapist():
    """Allow therapist to cancel session with Zoom meeting cancellation"""
    therapist_id = ObjectId(session['user'])
    
    try:
        data = request.get_json()
        appointment_id = data.get('appointment_id')
        cancellation_reason = data.get('reason', '').strip()
        
        if not appointment_id or not cancellation_reason:
            return jsonify({
                'success': False,
                'error': 'Appointment ID and reason are required'
            }), 400
        
        # Get appointment
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            return jsonify({'success': False, 'error': 'Appointment not found'}), 404
        
        # Cancel Zoom meeting using your existing function
        zoom_cancelled = False
        if appointment.get('zoom_meeting_id'):
            try:
                zoom_cancelled = cancel_zoom_meeting_in_appointment(ObjectId(appointment_id))
            except Exception as e:
                logger.warning(f"Failed to cancel Zoom meeting: {str(e)}")
        
        # Update appointment
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {
                    'status': 'cancelled',
                    'cancellation_reason': cancellation_reason,
                    'cancelled_at': datetime.now(),
                    'cancelled_by': 'therapist',
                    'zoom_cancelled': zoom_cancelled
                }
            }
        )
        
        # Notify student
        student = mongo.db.users.find_one({'_id': appointment['user_id']}) or mongo.db.students.find_one({'_id': appointment['user_id']})
        if student:
            mongo.db.student_notifications.insert_one({
                'user_id': student['_id'],
                'type': 'session_cancelled_by_therapist',
                'title': 'Zoom Session Cancelled',
                'message': f"Your Zoom session scheduled for {appointment.get('formatted_time', 'Unknown time')} has been cancelled. Reason: {cancellation_reason}",
                'appointment_id': ObjectId(appointment_id),
                'created_at': datetime.now(),
                'read': False
            })
        
        return jsonify({
            'success': True,
            'message': 'Session and Zoom meeting cancelled successfully',
            'zoom_cancelled': zoom_cancelled
        })
        
    except Exception as e:
        logger.error(f"Error cancelling session: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to cancel session'}), 500


@therapist_bp.route('/students')
@therapist_required
def students():
    """View assigned students with virtual session history - FIXED VERSION."""
    try:
        therapist_id = ObjectId(session['user'])
        therapist = find_therapist_by_id(therapist_id)
        
        if not therapist:
            flash('Therapist not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Use the fixed function to get students with fallback
        assignments = get_therapist_students_with_fallback(therapist_id)
        
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
                    'student_id': student_id,  # Use student_id consistently
                    'therapist_id': therapist_id,
                    'type': 'virtual'
                }, sort=[('datetime', -1)])
                
                # Get next upcoming VIRTUAL appointment
                next_appointment = mongo.db.appointments.find_one({
                    'student_id': student_id,  # Use student_id consistently
                    'therapist_id': therapist_id,
                    'datetime': {'$gte': datetime.now()},
                    'status': 'confirmed',
                    'type': 'virtual'
                }, sort=[('datetime', 1)])
                
                # Count total virtual sessions
                total_sessions = mongo.db.appointments.count_documents({
                    'student_id': student_id,  # Use student_id consistently
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
    """Enhanced virtual sessions with Zoom integration and session controls"""
    therapist_id = ObjectId(session['user'])
    
    # Get all virtual sessions (exclude soft-deleted)
    sessions = list(mongo.db.appointments.find({
        'therapist_id': therapist_id,
        'type': 'virtual',
        'deleted': {'$ne': True}
    }).sort('datetime', -1))
    
    # Add student details, Zoom status, and session controls
    for appointment in sessions:
        student = mongo.db.users.find_one({'_id': appointment['user_id']}) or mongo.db.students.find_one({'_id': appointment['user_id']})
        if student:
            appointment['student_name'] = f"{student['first_name']} {student['last_name']}"
        
        # Ensure Zoom meeting exists for upcoming sessions
        if appointment.get('status') == 'confirmed' and appointment.get('datetime') and appointment['datetime'] > datetime.now():
            ensure_zoom_meeting_for_appointment(appointment)
        
        # Add session controls and Zoom status
        appointment['session_controls'] = _get_enhanced_session_controls_therapist(appointment)
        appointment['zoom_integrated'] = is_zoom_integrated(appointment.get('zoom_meeting_id'))
        appointment['zoom_status'] = _get_zoom_status(appointment)
        
        # Format datetime
        if appointment.get('datetime'):
            appointment['formatted_time'] = appointment['datetime'].strftime('%A, %B %d at %I:%M %p')
    
    # Group by status with proper Zoom information
    upcoming_sessions = [s for s in sessions if s['status'] == 'confirmed' and s.get('datetime') and s['datetime'] > datetime.now()]
    completed_sessions = [s for s in sessions if s['status'] == 'completed']
    cancelled_sessions = [s for s in sessions if s['status'] == 'cancelled']
    
    # Get Zoom integration statistics
    zoom_stats = {
        'total_zoom_integrated': len([s for s in sessions if s.get('zoom_integrated')]),
        'upcoming_zoom_sessions': len([s for s in upcoming_sessions if s.get('zoom_integrated')]),
        'fallback_sessions': len([s for s in upcoming_sessions if not s.get('zoom_integrated')])
    }
    
    return render_template('therapist/virtual_sessions.html',
                         upcoming_sessions=upcoming_sessions,
                         completed_sessions=completed_sessions,
                         cancelled_sessions=cancelled_sessions,
                         total_sessions=len(sessions),
                         zoom_stats=zoom_stats)

# ADD notification handling for student actions with Zoom:
def handle_student_cancellation_notification(appointment_id, cancellation_reason):
    """Handle notification when student cancels Zoom session"""
    try:
        appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
        if not appointment:
            return False
        
        # Create therapist notification with Zoom info
        zoom_status = "Zoom meeting cancelled" if appointment.get('zoom_meeting_id') else "Meeting cancelled"
        
        mongo.db.therapist_notifications.insert_one({
            'therapist_id': appointment['therapist_id'],
            'type': 'student_cancelled_session',
            'title': 'Student Cancelled Zoom Session',
            'message': f"Student cancelled their Zoom session. Reason: {cancellation_reason}. {zoom_status}.",
            'appointment_id': appointment['_id'],
            'student_id': appointment['user_id'],
            'created_at': datetime.now(),
            'read': False,
            'zoom_info': {
                'meeting_cancelled': bool(appointment.get('zoom_meeting_id')),
                'zoom_integrated': is_zoom_integrated(appointment.get('zoom_meeting_id'))
            }
        })
        
        return True
        
    except Exception as e:
        logger.error(f"Error handling Zoom cancellation notification: {str(e)}")
        return False

# ADD process for handling expired appointments with Zoom cleanup:
def process_expired_appointments():
    """Background task to handle expired appointments and Zoom cleanup"""
    try:
        # Find appointments that ended more than 2 hours ago
        cutoff_time = datetime.now() - timedelta(hours=2)
        
        expired_appointments = mongo.db.appointments.find({
            'datetime': {'$lt': cutoff_time},
            'status': 'confirmed'
        })
        
        for appointment in expired_appointments:
            # Mark as completed
            mongo.db.appointments.update_one(
                {'_id': appointment['_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'auto_completed': True,
                        'completed_at': datetime.now()
                    }
                }
            )
            
            
    except Exception as e:
        logger.error(f"Error processing expired Zoom appointments: {str(e)}")

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
    """Enhanced join session with 5-minute window and Zoom integration"""
    therapist_id = ObjectId(session['user'])
    
    try:
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'therapist_id': therapist_id
        })
        
        if not appointment:
            flash('Session not found', 'error')
            return redirect(url_for('therapist.virtual_sessions'))
        
        # Check session timing with 5-minute window
        session_controls = _get_enhanced_session_controls_therapist(appointment)
        if not session_controls['can_join']:
            flash(f'Cannot join session: {session_controls["message"]}', 'warning')
            return redirect(url_for('therapist.virtual_sessions'))
        
        # Ensure Zoom meeting exists and get link
        ensure_zoom_meeting_for_appointment(appointment)
        
        meeting_info = appointment.get('meeting_info', {})
        meet_link = meeting_info.get('host_link') or meeting_info.get('meet_link')  # Prefer host link for therapist
        
        if not meet_link:
            # Try to refresh Zoom meeting
            refresh_success = refresh_zoom_meeting_for_appointment(ObjectId(appointment_id))
            if refresh_success:
                updated_appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
                meeting_info = updated_appointment.get('meeting_info', {})
                meet_link = meeting_info.get('host_link') or meeting_info.get('meet_link')
        
        if not meet_link:
            flash('No Zoom meeting link available. Please contact support.', 'error')
            return redirect(url_for('therapist.virtual_sessions'))
        
        # Update last accessed and log join
        mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {'therapist_last_joined': datetime.now()},
                '$inc': {'therapist_join_count': 1}
            }
        )
        
        logger.info(f"Therapist {therapist_id} joining Zoom session {appointment_id}")
        
        # Redirect to Zoom meeting
        return redirect(meet_link)
        
    except Exception as e:
        logger.error(f"Error joining Zoom session: {e}")
        flash('Unable to join Zoom session', 'error')
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
    """Send message with fully automated moderation"""
    therapist_id = ObjectId(session['user'])
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        return jsonify({'success': False, 'error': 'Student not assigned to you'})
    
    message = request.form.get('message', '').strip()
    
    if not message:
        return jsonify({'success': False, 'error': 'Message cannot be empty'})
    
    try:
        # Send through automated moderation
        result = send_auto_moderated_message(
            sender_id=str(therapist_id),
            recipient_id=student_id,
            message=message,
            sender_type='therapist'
        )
        
        if not result['success']:
            return jsonify({
                'success': False,
                'blocked': result.get('blocked', False),
                'error': result.get('reason', 'Message could not be sent'),
                'auto_response': result.get('auto_response')
            })
        
        # Message sent successfully
        response = {
            'success': True,
            'message': {
                'id': result['message_id'],
                'content': message,
                'timestamp': datetime.now().strftime('%I:%M %p | %b %d'),
                'was_filtered': result.get('filtered', False)
            }
        }
        
        # Add notifications for therapists
        if result.get('warnings'):
            response['warnings'] = result['warnings']
        
        if result.get('filtered'):
            response['content_filtered'] = True
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Therapist automated message send error: {e}")
        return jsonify({
            'success': False, 
            'error': 'An error occurred while sending the message'
        })
    
@therapist_bp.route('/api/crisis-alerts')
@therapist_required
def get_crisis_alerts():
    """Get automated crisis alerts for therapist"""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Get active crisis alerts for this therapist's students
        active_alerts = list(mongo.db.crisis_alerts.find({
            'therapist_id': therapist_id,
            'status': {'$in': ['auto_escalated', 'pending_review']},
            'created_at': {'$gte': datetime.now() - timedelta(days=7)}
        }).sort('created_at', -1))
        
        # Add student information
        for alert in active_alerts:
            student = mongo.db.users.find_one({'_id': alert['student_id']})
            if student:
                alert['student_name'] = f"{student['first_name']} {student['last_name']}"
                alert['student_email'] = student.get('email', '')
        
        return jsonify({
            'active_alerts': active_alerts,
            'total_count': len(active_alerts)
        })
        
    except Exception as e:
        logger.error(f"Error getting crisis alerts: {e}")
        return jsonify({'active_alerts': [], 'total_count': 0})

@therapist_bp.route('/api/acknowledge-crisis-alert/<alert_id>', methods=['POST'])
@therapist_required
def acknowledge_crisis_alert(alert_id):
    """Acknowledge and respond to automated crisis alert"""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Update alert status
        result = mongo.db.crisis_alerts.update_one(
            {
                '_id': ObjectId(alert_id),
                'therapist_id': therapist_id
            },
            {
                '$set': {
                    'status': 'acknowledged',
                    'acknowledged_by': therapist_id,
                    'acknowledged_at': datetime.now(),
                    'response_action': request.json.get('action', 'contacted_student')
                }
            }
        )
        
        if result.modified_count > 0:
            # Optionally notify student that alert was acknowledged
            alert = mongo.db.crisis_alerts.find_one({'_id': ObjectId(alert_id)})
            if alert:
                mongo.db.notifications.insert_one({
                    'user_id': alert['student_id'],
                    'type': 'crisis_response',
                    'message': 'Your therapist has been notified of your message and will respond shortly.',
                    'read': False,
                    'created_at': datetime.now()
                })
            
            return jsonify({'success': True, 'message': 'Crisis alert acknowledged'})
        else:
            return jsonify({'success': False, 'error': 'Alert not found or already processed'})
            
    except Exception as e:
        logger.error(f"Error acknowledging crisis alert: {e}")
        return jsonify({'success': False, 'error': 'Failed to acknowledge alert'})
    
# Bulk message operations with automated moderation
@therapist_bp.route('/api/bulk-message-status')
@therapist_required
def bulk_message_status():
    """Get moderation status for multiple recent messages"""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Get recent messages from this therapist's students
        recent_messages = list(mongo.db.therapist_chats.find({
            'therapist_id': therapist_id,
            'timestamp': {'$gte': datetime.now() - timedelta(hours=24)},
            'automated_moderation': True
        }).sort('timestamp', -1))
        
        # Group by moderation flags
        moderation_summary = {}
        for msg in recent_messages:
            flags = msg.get('moderation_flags', [])
            action = msg.get('moderation_action', 'allow')
            
            if flags:
                for flag in flags:
                    if flag not in moderation_summary:
                        moderation_summary[flag] = {'count': 0, 'action_types': {}}
                    
                    moderation_summary[flag]['count'] += 1
                    moderation_summary[flag]['action_types'][action] = \
                        moderation_summary[flag]['action_types'].get(action, 0) + 1
        
        return jsonify({
            'total_messages': len(recent_messages),
            'moderation_summary': moderation_summary,
            'period': '24_hours'
        })
        
    except Exception as e:
        logger.error(f"Error getting bulk message status: {e}")
        return jsonify({'error': 'Failed to get message status'})

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
            tags = request.form.get('tags', '').strip()
            
            # Validate required fields
            if not title or not description or not resource_type or not url:
                flash('All fields except tags are required', 'error')
                return redirect(url_for('therapist.resources'))
            
            # Validate URL format
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            # Process tags
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
            
            # Check for duplicate resource by title and therapist
            existing = mongo.db.therapist_resources.find_one({
                'therapist_id': therapist_id,
                'title': title
            })
            
            if existing:
                flash(f'A resource with the title "{title}" already exists in your library', 'error')
                return redirect(url_for('therapist.resources'))
            
            # Create resource
            custom_resource = {
                'therapist_id': therapist_id,
                'title': title,
                'description': description,
                'type': resource_type,
                'url': url,
                'tags': tag_list,
                'status': 'active',
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc)
            }
            
            result = mongo.db.therapist_resources.insert_one(custom_resource)
            
            # Log the creation
            logger.info(f"Therapist {therapist_id} created custom resource '{title}' with ID {result.inserted_id}")
            
            flash(f'Custom resource "{title}" created successfully', 'success')
            
        except Exception as e:
            logger.error(f"Error creating custom resource: {e}")
            flash('An error occurred while creating the resource', 'error')
    
    return redirect(url_for('therapist.resources'))


@therapist_bp.route('/edit-resource/<resource_id>', methods=['GET', 'POST'])
@therapist_required
def edit_resource(resource_id):
    """Edit a custom resource."""
    therapist_id = ObjectId(session['user'])
    
    # Verify resource ownership
    resource = mongo.db.therapist_resources.find_one({
        '_id': ObjectId(resource_id),
        'therapist_id': therapist_id
    })
    
    if not resource:
        flash('Resource not found or you do not have permission to edit it', 'error')
        return redirect(url_for('therapist.resources'))
    
    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            resource_type = request.form.get('type', '').strip()
            url = request.form.get('url', '').strip()
            tags = request.form.get('tags', '').strip()
            
            # Validate required fields
            if not title or not description or not resource_type or not url:
                flash('All fields except tags are required', 'error')
                return redirect(url_for('therapist.resources'))
            
            # Validate URL format
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            # Process tags
            tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
            
            # Check for duplicate title (excluding current resource)
            existing = mongo.db.therapist_resources.find_one({
                'therapist_id': therapist_id,
                'title': title,
                '_id': {'$ne': ObjectId(resource_id)}
            })
            
            if existing:
                flash(f'Another resource with the title "{title}" already exists in your library', 'error')
                return redirect(url_for('therapist.resources'))
            
            # Update resource
            update_data = {
                'title': title,
                'description': description,
                'type': resource_type,
                'url': url,
                'tags': tag_list,
                'updated_at': datetime.now(timezone.utc)
            }
            
            mongo.db.therapist_resources.update_one(
                {'_id': ObjectId(resource_id)},
                {'$set': update_data}
            )
            
            # Update any shared resource records to maintain consistency
            mongo.db.shared_resources.update_many(
                {'resource_id': ObjectId(resource_id)},
                {'$set': {
                    'title': title,
                    'type': resource_type,
                    'description': description,
                    'url': url
                }}
            )
            
            logger.info(f"Therapist {therapist_id} updated custom resource '{title}' (ID: {resource_id})")
            
            flash(f'Resource "{title}" updated successfully', 'success')
            
        except Exception as e:
            logger.error(f"Error updating custom resource: {e}")
            flash('An error occurred while updating the resource', 'error')
    
    return redirect(url_for('therapist.resources'))


@therapist_bp.route('/delete-resource/<resource_id>', methods=['POST'])
@therapist_required
def delete_resource(resource_id):
    """Delete a custom resource."""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Verify resource ownership
        resource = mongo.db.therapist_resources.find_one({
            '_id': ObjectId(resource_id),
            'therapist_id': therapist_id
        })
        
        if not resource:
            flash('Resource not found or you do not have permission to delete it', 'error')
            return redirect(url_for('therapist.resources'))
        
        resource_title = resource['title']
        
        # Check if resource has been shared
        shared_count = mongo.db.shared_resources.count_documents({
            'resource_id': ObjectId(resource_id)
        })
        
        if shared_count > 0:
            # Soft delete - mark as inactive instead of removing
            mongo.db.therapist_resources.update_one(
                {'_id': ObjectId(resource_id)},
                {'$set': {
                    'status': 'deleted',
                    'deleted_at': datetime.now(timezone.utc)
                }}
            )
            flash(f'Resource "{resource_title}" has been archived (it was previously shared with students)', 'success')
        else:
            # Hard delete if never shared
            mongo.db.therapist_resources.delete_one({'_id': ObjectId(resource_id)})
            flash(f'Resource "{resource_title}" deleted successfully', 'success')
        
        logger.info(f"Therapist {therapist_id} deleted custom resource '{resource_title}' (ID: {resource_id})")
        
    except Exception as e:
        logger.error(f"Error deleting custom resource: {e}")
        flash('An error occurred while deleting the resource', 'error')
    
    return redirect(url_for('therapist.resources'))


# First, let's debug what's in your database
# Add this temporary route to your therapist.py to see what's stored

@therapist_bp.route('/debug-resources')
@therapist_required  
def debug_resources():
    """Debug route to see what's in the resources collection."""
    
    # Get all resources from admin
    all_resources = list(mongo.db.resources.find())
    
    # Print to console for debugging
    print("=== DEBUG: Resources in database ===")
    for resource in all_resources:
        print(f"Resource: {resource}")
        print(f"Fields: {list(resource.keys())}")
        print("---")
    
    # Return as JSON to see in browser
    from bson import json_util
    import json
    
    return Response(
        json.dumps(all_resources, default=json_util.default, indent=2),
        mimetype='application/json'
    )

# ============================================================================
# Updated resources route to handle admin resource structure
# ============================================================================

@therapist_bp.route('/resources')
@therapist_required
def resources():
    """View and manage resources - Fixed for admin resource compatibility."""
    therapist_id = ObjectId(session['user'])
    therapist = find_therapist_by_id(therapist_id)
    
    if not therapist:
        flash('Therapist not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    try:
        # Get system resources (admin-created) - FIXED QUERY
        # Remove status filter since admin might not set it
        system_resources_raw = list(mongo.db.resources.find().sort('title', 1))
        
        # Transform admin resources to match template expectations
        system_resources = []
        for resource in system_resources_raw:
            try:
                # Map admin fields to template fields
                transformed_resource = {
                    '_id': resource['_id'],
                    'title': resource.get('title', 'Untitled'),
                    'description': resource.get('description', 'No description'),
                    'type': resource.get('resource_type', resource.get('type', 'article')),  # Admin uses 'resource_type'
                    'url': resource.get('file_path') or resource.get('url', '#'),  # Admin uses 'file_path'
                    'content': resource.get('content', ''),
                    'created_by': resource.get('created_by'),
                    'created_at': resource.get('created_at', datetime.now()),
                    'tags': resource.get('tags', [])
                }
                system_resources.append(transformed_resource)
            except Exception as e:
                logger.error(f"Error transforming resource {resource.get('_id')}: {e}")
                continue
        
        logger.info(f"Loaded {len(system_resources)} system resources for therapist {therapist_id}")
        
        # Get therapist's custom resources (unchanged)
        custom_resources = list(mongo.db.therapist_resources.find({
            'therapist_id': therapist_id,
            'status': {'$ne': 'deleted'}
        }).sort('title', 1))
        
        # Get recently shared resources with student names (unchanged)
        recently_shared = list(mongo.db.shared_resources.find({
            'therapist_id': therapist_id
        }).sort('shared_at', -1).limit(10))
        
        # Add student details for recently shared resources
        for shared in recently_shared:
            student = mongo.db.users.find_one({'_id': shared['student_id']})
            if student:
                shared['student_name'] = f"{student['first_name']} {student['last_name']}"
            else:
                shared['student_name'] = 'Unknown Student'
        
        # Get students data for sharing dropdown
        assignments = get_therapist_students_with_fallback(therapist_id)
        students_data = []
        
        for assignment in assignments:
            try:
                student_id = assignment.get('student_id')
                if not student_id:
                    continue
                    
                student = mongo.db.users.find_one({'_id': student_id})
                if not student:
                    continue
                
                # Get crisis level from intake assessment
                intake = mongo.db.intake_assessments.find_one({'student_id': student_id})
                crisis_level = intake.get('crisis_level', 'normal') if intake else 'normal'
                
                students_data.append({
                    'student': student,
                    'crisis_level': crisis_level,
                    'assignment': assignment
                })
                
            except Exception as e:
                logger.error(f"Error processing student data: {e}")
                continue
        
        # Sort students by crisis level
        students_data.sort(key=lambda x: (
            0 if x['crisis_level'] == 'critical' else 
            1 if x['crisis_level'] == 'high' else 2
        ))
        
        # Get resource sharing statistics
        sharing_stats = {
            'total_shared_this_week': mongo.db.shared_resources.count_documents({
                'therapist_id': therapist_id,
                'shared_at': {'$gte': datetime.now(timezone.utc) - timedelta(days=7)}
            }),
            'most_shared_resource': None,
            'students_with_shared_resources': len(set([s['student_id'] for s in recently_shared]))
        }
        
        # Find most shared resource
        pipeline = [
            {'$match': {'therapist_id': therapist_id}},
            {'$group': {'_id': '$resource_id', 'count': {'$sum': 1}, 'title': {'$first': '$title'}}},
            {'$sort': {'count': -1}},
            {'$limit': 1}
        ]
        
        most_shared = list(mongo.db.shared_resources.aggregate(pipeline))
        if most_shared:
            sharing_stats['most_shared_resource'] = {
                'title': most_shared[0]['title'],
                'count': most_shared[0]['count']
            }
        
        settings = mongo.db.settings.find_one() or {}
        
        return render_template('therapist/resources.html',
                             therapist=therapist,
                             system_resources=system_resources,  # Now properly formatted
                             custom_resources=custom_resources,
                             recently_shared=recently_shared,
                             students_data=students_data,
                             sharing_stats=sharing_stats,
                             settings=settings)
                             
    except Exception as e:
        logger.error(f"Error in resources route: {e}")
        flash('An error occurred while loading resources', 'error')
        return redirect(url_for('therapist.index'))



@therapist_bp.route('/share-resource', methods=['POST'])
@therapist_required
def share_resource():
    """Share a resource with a student - Fixed for admin resource compatibility."""
    therapist_id = ObjectId(session['user'])
    
    # Get form data
    student_id = request.form.get('student_id')
    resource_id = request.form.get('resource_id')
    custom_message = request.form.get('message', '').strip()
    
    if not student_id or not resource_id:
        flash('Student ID and Resource ID are required', 'error')
        return redirect(url_for('therapist.resources'))
    
    # Verify assignment
    assignment = mongo.db.therapist_assignments.find_one({
        'therapist_id': therapist_id,
        'student_id': ObjectId(student_id),
        'status': 'active'
    })
    
    if not assignment:
        flash('Student not assigned to you', 'error')
        return redirect(url_for('therapist.resources'))
    
    # Get resource - check ADMIN resources first, then custom
    resource = mongo.db.resources.find_one({'_id': ObjectId(resource_id)})
    
    if resource:
        # Transform admin resource for sharing
        resource_for_sharing = {
            'title': resource.get('title', 'Untitled'),
            'description': resource.get('description', 'No description'),
            'type': resource.get('resource_type', resource.get('type', 'article')),
            'url': resource.get('file_path') or resource.get('url', '#')
        }
    else:
        # Try custom resources if not found in admin resources
        resource = mongo.db.therapist_resources.find_one({
            '_id': ObjectId(resource_id),
            'therapist_id': therapist_id
        })
        
        if resource:
            resource_for_sharing = {
                'title': resource['title'],
                'description': resource['description'], 
                'type': resource['type'],
                'url': resource['url']
            }
        else:
            flash('Resource not found', 'error')
            return redirect(url_for('therapist.resources'))
    
    # Get student info for better flash messages
    student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
    student_name = f"{student['first_name']} {student['last_name']}" if student else 'Student'
    
    try:
        # Check if resource already shared recently (within last 24 hours)
        recent_share = mongo.db.shared_resources.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'resource_id': ObjectId(resource_id),
            'shared_at': {'$gte': datetime.now(timezone.utc) - timedelta(hours=24)}
        })
        
        if recent_share:
            flash(f'Resource "{resource_for_sharing["title"]}" was already shared with {student_name} in the last 24 hours', 'warning')
            return redirect(url_for('therapist.resources'))
        
        # Share resource using transformed data
        shared_resource = {
            'student_id': ObjectId(student_id),
            'therapist_id': therapist_id,
            'resource_id': ObjectId(resource_id),
            'title': resource_for_sharing['title'],
            'type': resource_for_sharing['type'],
            'description': resource_for_sharing['description'],
            'url': resource_for_sharing['url'],
            'shared_at': datetime.now(timezone.utc),
            'custom_message': custom_message
        }
        
        result = mongo.db.shared_resources.insert_one(shared_resource)
        
        # Add a message in chat about the shared resource
        chat_message = f"I've shared a resource with you: {resource_for_sharing['title']}"
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
            'message': f'Your therapist shared a resource with you: {resource_for_sharing["title"]}',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Log the sharing activity
        logger.info(f"Therapist {therapist_id} shared resource '{resource_for_sharing['title']}' with student {student_id}")
        
        flash(f'Resource "{resource_for_sharing["title"]}" shared successfully with {student_name}', 'success')
        
    except Exception as e:
        logger.error(f"Share resource error: {e}")
        flash('An error occurred while sharing the resource', 'error')
    
    return redirect(url_for('therapist.resources'))
    
@therapist_bp.route('/profile', methods=['GET', 'POST'])
@therapist_required
def profile():
    """Therapist profile and settings - CORRECTED WITHOUT LEGACY HANDLING."""
    try:
        therapist_id = ObjectId(session['user'])
        
        # Get therapist data from therapists collection
        therapist = mongo.db.therapists.find_one({'_id': therapist_id})
        
        # Get user data from users collection
        user = mongo.db.users.find_one({'_id': therapist_id})
        
        if not user or not therapist:
            flash('Account data not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Handle profile updates
        if request.method == 'POST':
            try:
                form_type = request.form.get('form_type')
                logger.info(f"Processing profile update: {form_type} for therapist {therapist_id}")
                
                if form_type == 'profile':
                    # Update basic profile information
                    phone = request.form.get('phone', '').strip()
                    gender = request.form.get('gender', '').strip()
                    bio = request.form.get('bio', '').strip()
                    years_experience = request.form.get('years_experience', '0')
                    
                    # Convert years_experience to int
                    try:
                        years_experience = int(years_experience) if years_experience else 0
                    except ValueError:
                        years_experience = 0
                    
                    # Update therapist document (matches auth registration fields)
                    update_data = {
                        'phone': phone,
                        'gender': gender, 
                        'bio': bio,
                        'years_experience': years_experience,
                        'updated_at': datetime.now()
                    }
                    
                    mongo.db.therapists.update_one(
                        {'_id': therapist_id},
                        {'$set': update_data}
                    )
                    
                    logger.info(f"Updated basic profile for therapist {therapist_id}")
                    flash('Profile updated successfully', 'success')
                
                elif form_type == 'professional':
                    # Update professional information (matches auth registration)
                    license_number = request.form.get('license_number', '').strip()
                    specializations = request.form.getlist('specializations[]')
                    max_students = request.form.get('max_students', '20')
                    emergency_hours = request.form.get('emergency_hours') == 'on'
                    available_days = request.form.getlist('available_days[]')
                    
                    # Validate license number
                    if not license_number:
                        flash('License number is required', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    # Check if license number is already used by another therapist
                    existing_license = mongo.db.therapists.find_one({
                        'license_number': license_number,
                        '_id': {'$ne': therapist_id}
                    })
                    
                    if existing_license:
                        flash('License number is already in use by another therapist', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    # Validate specializations
                    if not specializations:
                        flash('At least one specialization is required', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    # Convert max_students to int
                    try:
                        max_students = int(max_students) if max_students else 20
                    except ValueError:
                        max_students = 20
                    
                    # Process availability (matches auth registration format)
                    availability = {}
                    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                    
                    for day in days:
                        if day in available_days:
                            start_time = request.form.get(f'{day}_start', '09:00')
                            end_time = request.form.get(f'{day}_end', '17:00')
                            availability[day] = {
                                'start': start_time,
                                'end': end_time
                            }
                    
                    # Update therapist document (exact auth fields)
                    professional_update = {
                        'license_number': license_number,
                        'specializations': specializations,
                        'max_students': max_students,
                        'emergency_hours': emergency_hours,
                        'availability': availability,
                        'updated_at': datetime.now()
                    }
                    
                    mongo.db.therapists.update_one(
                        {'_id': therapist_id},
                        {'$set': professional_update}
                    )
                    
                    logger.info(f"Updated professional info for therapist {therapist_id}: license={license_number}, {len(specializations)} specializations")
                    flash('Professional information updated successfully', 'success')
                
                elif form_type == 'password':
                    # Update password
                    current_password = request.form.get('current_password', '')
                    new_password = request.form.get('new_password', '')
                    confirm_password = request.form.get('confirm_password', '')
                    
                    # Validate passwords
                    from werkzeug.security import check_password_hash, generate_password_hash
                    
                    if not user.get('password'):
                        flash('Password update error: No existing password found', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    # Check current password
                    if not check_password_hash(user['password'], current_password):
                        flash('Current password is incorrect', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    if new_password != confirm_password:
                        flash('New passwords do not match', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    if len(new_password) < 8:
                        flash('New password must be at least 8 characters long', 'error')
                        return redirect(url_for('therapist.profile'))
                    
                    # Update password in users collection
                    password_hash = generate_password_hash(new_password)
                    mongo.db.users.update_one(
                        {'_id': therapist_id},
                        {'$set': {'password': password_hash, 'updated_at': datetime.now()}}
                    )
                    
                    flash('Password updated successfully', 'success')
                
                else:
                    flash('Invalid form submission', 'error')
                    logger.warning(f"Unknown form_type received: {form_type}")
                
            except Exception as e:
                logger.error(f"Profile update error: {e}")
                flash(f'An error occurred while updating your profile: {str(e)}', 'error')
        
        # Refresh data after potential updates
        therapist = mongo.db.therapists.find_one({'_id': therapist_id})
        user = mongo.db.users.find_one({'_id': therapist_id})
        
        # Get account statistics
        stats = {}
        try:
            # Safe datetime handling
            created_at = user.get('created_at')
            if created_at and hasattr(created_at, 'strftime'):
                member_since = created_at.strftime('%B %d, %Y')
            else:
                member_since = 'N/A'
            
            # Safe integer handling
            login_count = user.get('login_count', 0)
            if not isinstance(login_count, (int, float)):
                login_count = 0
            
            # Safe last login handling
            last_login = user.get('last_login')
            if last_login and hasattr(last_login, 'strftime'):
                last_login_str = last_login.strftime('%B %d, %Y at %I:%M %p')
            else:
                last_login_str = 'Never'
            
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
                'last_login': last_login_str
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
@therapist_bp.route('/respond-reschedule/<request_id>')
@therapist_required
def respond_reschedule_page(request_id):
    """Page for therapist to respond to student's auto-reschedule request"""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Get the reschedule request
        reschedule_request = mongo.db.reschedule_requests.find_one({
            '_id': ObjectId(request_id),
            'therapist_id': therapist_id,
            'status': 'pending'
        })
        
        if not reschedule_request:
            flash('Reschedule request not found or already processed', 'error')
            return redirect(url_for('therapist.index'))
        
        # Get student information
        student = mongo.db.users.find_one({'_id': reschedule_request['student_id']}) or \
                  mongo.db.students.find_one({'_id': reschedule_request['student_id']})
        
        if not student:
            flash('Student not found', 'error')
            return redirect(url_for('therapist.index'))
        
        # Get original appointment details
        original_appointment = mongo.db.appointments.find_one({
            '_id': reschedule_request['original_appointment_id']
        })
        
        # Check if auto-rescheduling is available
        availability = mongo.db.therapist_availability.find_one({'therapist_id': therapist_id})
        auto_reschedule_enabled = availability and availability.get('auto_reschedule_enabled', True)
        
        # Find next available slot if auto-reschedule is enabled
        next_available_slot = None
        if auto_reschedule_enabled:
            next_available_slot = find_next_available_slot(therapist_id)
        
        return render_template('therapist/respond_reschedule.html',
                             reschedule_request=reschedule_request,
                             student=student,
                             original_appointment=original_appointment,
                             auto_reschedule_enabled=auto_reschedule_enabled,
                             next_available_slot=next_available_slot)
                             
    except Exception as e:
        logger.error(f"Error loading reschedule response page: {e}")
        flash('Error loading reschedule request', 'error')
        return redirect(url_for('therapist.index'))

@therapist_bp.route('/process-reschedule-response/<request_id>', methods=['POST'])
@therapist_required
def process_reschedule_response(request_id):
    """Process therapist's response to auto-reschedule request"""
    therapist_id = ObjectId(session['user'])
    
    try:
        # Get form data
        response_action = request.form.get('response_action')  # 'accept' or 'decline'
        therapist_message = request.form.get('therapist_message', '').strip()
        decline_reason = request.form.get('decline_reason', '').strip()
        
        if not response_action:
            flash('Please select an action', 'error')
            return redirect(url_for('therapist.respond_reschedule_page', request_id=request_id))
        
        # Get reschedule request
        reschedule_request = mongo.db.reschedule_requests.find_one({
            '_id': ObjectId(request_id),
            'therapist_id': therapist_id,
            'status': 'pending'
        })
        
        if not reschedule_request:
            flash('Reschedule request not found or already processed', 'error')
            return redirect(url_for('therapist.index'))
        
        # Get original appointment
        original_appointment = mongo.db.appointments.find_one({
            '_id': reschedule_request['original_appointment_id']
        })
        
        if not original_appointment:
            flash('Original appointment not found', 'error')
            return redirect(url_for('therapist.index'))
        
        if response_action == 'accept':
            # AUTO-RESCHEDULE: Find next available slot and update appointment
            next_slot = find_next_available_slot(therapist_id)
            
            if not next_slot:
                flash('No available slots found for auto-rescheduling', 'error')
                return redirect(url_for('therapist.respond_reschedule_page', request_id=request_id))
            
            # Update the original appointment with new time
            mongo.db.appointments.update_one(
                {'_id': original_appointment['_id']},
                {
                    '$set': {
                        'datetime': next_slot,
                        'formatted_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
                        'auto_rescheduled': True,
                        'rescheduled_at': datetime.now(),
                        'rescheduled_by': therapist_id,
                        'rescheduled_reason': f"Auto-rescheduled due to: {reschedule_request.get('missed_reason', 'scheduling conflict')}"
                    }
                }
            )
            
            # Update reschedule request as accepted
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'accepted',
                        'therapist_response': therapist_message,
                        'new_appointment_time': next_slot,
                        'responded_at': datetime.now()
                    }
                }
            )
            
            # Create new Zoom meeting for the rescheduled appointment
            updated_appointment = mongo.db.appointments.find_one({'_id': original_appointment['_id']})
            ensure_zoom_meeting_for_appointment(updated_appointment)
            
            # Notify student about successful auto-reschedule
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'auto_reschedule_accepted',
                'title': '✅ Session Auto-Rescheduled',
                'message': f"Great news! Your session has been automatically rescheduled to {next_slot.strftime('%A, %B %d at %I:%M %p')}. Your new Zoom meeting link is ready. {therapist_message}",
                'appointment_id': original_appointment['_id'],
                'created_at': datetime.now(),
                'read': False,
                'priority': 'high'
            })
            
            # Log successful auto-reschedule
            logger.info(f"Therapist {therapist_id} accepted auto-reschedule request {request_id}, new time: {next_slot}")
            
            flash(f'Auto-reschedule accepted! Session moved to {next_slot.strftime("%A, %B %d at %I:%M %p")} with new Zoom meeting', 'success')
            
        elif response_action == 'decline':
            # DECLINE: Reject the auto-reschedule request
            if not decline_reason:
                flash('Please provide a reason for declining', 'error')
                return redirect(url_for('therapist.respond_reschedule_page', request_id=request_id))
            
            # Update reschedule request as declined
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'declined',
                        'therapist_response': therapist_message,
                        'decline_reason': decline_reason,
                        'responded_at': datetime.now()
                    }
                }
            )
            
            # Keep original appointment as cancelled/missed
            mongo.db.appointments.update_one(
                {'_id': original_appointment['_id']},
                {
                    '$set': {
                        'status': 'cancelled',
                        'cancellation_reason': f"Reschedule declined: {decline_reason}",
                        'cancelled_by': therapist_id,
                        'cancelled_at': datetime.now()
                    }
                }
            )
            
            # Cancel Zoom meeting for original appointment
            if original_appointment.get('zoom_meeting_id'):
                try:
                    cancel_zoom_meeting_in_appointment(original_appointment['_id'])
                except Exception as e:
                    logger.warning(f"Failed to cancel Zoom meeting: {e}")
            
            # Notify student about declined reschedule
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'auto_reschedule_declined',
                'title': '❌ Reschedule Request Declined',
                'message': f"Your auto-reschedule request was declined. Reason: {decline_reason}. Please book a new appointment. {therapist_message}",
                'appointment_id': original_appointment['_id'],
                'created_at': datetime.now(),
                'read': False,
                'priority': 'high'
            })
            
            # Suggest booking new appointment
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'book_new_appointment',
                'title': '📅 Book New Appointment',
                'message': "Since your reschedule was declined, please book a new virtual session at your convenience.",
                'created_at': datetime.now(),
                'read': False,
                'priority': 'medium'
            })
            
            logger.info(f"Therapist {therapist_id} declined auto-reschedule request {request_id}, reason: {decline_reason}")
            
            flash(f'Reschedule request declined. Student has been notified.', 'info')
        
        return redirect(url_for('therapist.index'))
        
    except Exception as e:
        logger.error(f"Error processing reschedule response: {e}")
        flash('Error processing your response. Please try again.', 'error')
        return redirect(url_for('therapist.respond_reschedule_page', request_id=request_id))

@therapist_bp.route('/api/quick-reschedule-response', methods=['POST'])
@therapist_required
def quick_reschedule_response():
    """Quick API endpoint for accepting/declining reschedule from dashboard"""
    therapist_id = ObjectId(session['user'])
    
    try:
        data = request.get_json()
        request_id = data.get('request_id')
        action = data.get('action')  # 'quick_accept' or 'quick_decline'
        reason = data.get('reason', '')
        
        if not request_id or not action:
            return jsonify({'success': False, 'error': 'Missing required data'}), 400
        
        # Get reschedule request
        reschedule_request = mongo.db.reschedule_requests.find_one({
            '_id': ObjectId(request_id),
            'therapist_id': therapist_id,
            'status': 'pending'
        })
        
        if not reschedule_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        if action == 'quick_accept':
            # Quick accept - auto-reschedule immediately
            next_slot = find_next_available_slot(therapist_id)
            
            if not next_slot:
                return jsonify({'success': False, 'error': 'No available slots'}), 400
            
            # Update appointment
            original_appointment = mongo.db.appointments.find_one({
                '_id': reschedule_request['original_appointment_id']
            })
            
            mongo.db.appointments.update_one(
                {'_id': original_appointment['_id']},
                {
                    '$set': {
                        'datetime': next_slot,
                        'formatted_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
                        'auto_rescheduled': True,
                        'rescheduled_at': datetime.now(),
                        'rescheduled_by': therapist_id
                    }
                }
            )
            
            # Update request
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'accepted',
                        'new_appointment_time': next_slot,
                        'responded_at': datetime.now(),
                        'quick_response': True
                    }
                }
            )
            
            # Ensure Zoom meeting
            updated_appointment = mongo.db.appointments.find_one({'_id': original_appointment['_id']})
            ensure_zoom_meeting_for_appointment(updated_appointment)
            
            # Notify student
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'auto_reschedule_accepted',
                'title': '✅ Session Auto-Rescheduled',
                'message': f"Your session has been rescheduled to {next_slot.strftime('%A, %B %d at %I:%M %p')}",
                'appointment_id': original_appointment['_id'],
                'created_at': datetime.now(),
                'read': False
            })
            
            return jsonify({
                'success': True,
                'message': f'Auto-rescheduled to {next_slot.strftime("%A, %B %d at %I:%M %p")}',
                'new_time': next_slot.strftime('%A, %B %d at %I:%M %p')
            })
            
        elif action == 'quick_decline':
            # Quick decline with provided reason
            decline_reason = reason or 'Schedule unavailable'
            
            mongo.db.reschedule_requests.update_one(
                {'_id': ObjectId(request_id)},
                {
                    '$set': {
                        'status': 'declined',
                        'decline_reason': decline_reason,
                        'responded_at': datetime.now(),
                        'quick_response': True
                    }
                }
            )
            
            # Notify student
            mongo.db.student_notifications.insert_one({
                'user_id': reschedule_request['student_id'],
                'type': 'auto_reschedule_declined',
                'title': '❌ Reschedule Declined',
                'message': f'Your reschedule request was declined: {decline_reason}. Please book a new appointment.',
                'created_at': datetime.now(),
                'read': False
            })
            
            return jsonify({
                'success': True,
                'message': 'Reschedule request declined'
            })
        
        return jsonify({'success': False, 'error': 'Invalid action'}), 400
        
    except Exception as e:
        logger.error(f"Error in quick reschedule response: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500