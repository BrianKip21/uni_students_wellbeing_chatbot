# wellbeing/connection/routes.py
# Real-time connection routes for student-therapist bridge

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timezone, timedelta
import json
import uuid
from functools import wraps
from typing import Dict, List, Optional, Tuple, Any

from wellbeing import mongo, logger
from wellbeing.utils.decorators import login_required
from . import connection_bp  # Import the blueprint from __init__.py

# Socket.IO for real-time updates (if available)
try:
    from wellbeing import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logger.warning("Socket.IO not available - real-time features disabled")

# ===== SHARED UTILITIES =====

def get_user_role(user_id: str) -> str:
    """Get user role from either students or therapists collection"""
    try:
        # Check if user is a student
        student = mongo.db.users.find_one({'_id': ObjectId(user_id), 'role': 'student'})
        if student:
            return 'student'
        
        # Check if user is a therapist
        therapist = mongo.db.therapists.find_one({'_id': ObjectId(user_id)})
        if therapist:
            return 'therapist'
        
        # Check users collection for therapist role
        user = mongo.db.users.find_one({'_id': ObjectId(user_id), 'role': 'therapist'})
        if user:
            return 'therapist'
        
        return 'unknown'
    except Exception as e:
        logger.error(f"Error getting user role: {str(e)}")
        return 'unknown'

def validate_connection_access(student_id: str, therapist_id: str) -> bool:
    """Validate that student and therapist are connected"""
    try:
        # Check active assignment
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'status': 'active'
        })
        
        if assignment:
            return True
        
        # Check user assignment
        student = mongo.db.users.find_one({
            '_id': ObjectId(student_id),
            'assigned_therapist_id': ObjectId(therapist_id)
        })
        
        return bool(student)
    except Exception as e:
        logger.error(f"Error validating connection: {str(e)}")
        return False

def emit_real_time_update(room: str, event: str, data: dict):
    """Emit real-time update if Socket.IO is available"""
    if SOCKETIO_AVAILABLE:
        try:
            socketio.emit(event, data, room=room)
        except Exception as e:
            logger.error(f"Socket.IO emit error: {str(e)}")

# ===== CONNECTION VALIDATION DECORATORS =====

def require_valid_connection(f):
    """Decorator to ensure valid student-therapist connection"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        
        user_id = session['user']
        user_role = get_user_role(user_id)
        
        # Get connection parameters
        student_id = request.json.get('student_id') if request.is_json else request.form.get('student_id')
        therapist_id = request.json.get('therapist_id') if request.is_json else request.form.get('therapist_id')
        
        # Auto-fill based on user role
        if user_role == 'student':
            student_id = user_id
            if not therapist_id:
                student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                therapist_id = str(student.get('assigned_therapist_id')) if student and student.get('assigned_therapist_id') else None
        elif user_role == 'therapist':
            therapist_id = user_id
            if not student_id:
                return jsonify({'error': 'Student ID required for therapist actions'}), 400
        
        if not student_id or not therapist_id:
            return jsonify({'error': 'Both student and therapist IDs required'}), 400
        
        # Validate connection
        if not validate_connection_access(student_id, therapist_id):
            return jsonify({'error': 'Invalid connection between student and therapist'}), 403
        
        # Add to kwargs for use in route
        kwargs['student_id'] = student_id
        kwargs['therapist_id'] = therapist_id
        kwargs['user_role'] = user_role
        
        return f(*args, **kwargs)
    return decorated_function

# ===== REAL-TIME MESSAGING SYSTEM =====

@connection_bp.route('/send-message', methods=['POST'])
@login_required
@require_valid_connection
def send_message(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Unified messaging system for student-therapist communication"""
    try:
        data = request.get_json()
        message_content = data.get('message', '').strip()
        message_type = data.get('type', 'text')  # text, resource, appointment_update
        
        if not message_content:
            return jsonify({'error': 'Message content required'}), 400
        
        # Create message document
        message_data = {
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'sender': user_role,
            'message': message_content,
            'message_type': message_type,
            'read': False,
            'timestamp': datetime.now(timezone.utc),
            'metadata': data.get('metadata', {})
        }
        
        # Add type-specific data
        if message_type == 'resource':
            resource_id = data.get('resource_id')
            if resource_id:
                resource = mongo.db.resources.find_one({'_id': ObjectId(resource_id)})
                if resource:
                    message_data['resource_data'] = {
                        'resource_id': ObjectId(resource_id),
                        'title': resource['title'],
                        'type': resource['type'],
                        'url': resource['url']
                    }
        
        # Insert message
        result = mongo.db.therapist_chats.insert_one(message_data)
        message_id = result.inserted_id
        
        # Create notification for recipient
        recipient_id = therapist_id if user_role == 'student' else student_id
        notification_data = {
            'user_id': ObjectId(recipient_id),
            'type': 'new_message',
            'message': f'New message from your {"student" if user_role == "therapist" else "therapist"}',
            'related_id': message_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        }
        mongo.db.notifications.insert_one(notification_data)
        
        # Real-time update
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        emit_real_time_update(room_id, 'new_message', {
            'message_id': str(message_id),
            'sender': user_role,
            'content': message_content,
            'type': message_type,
            'timestamp': message_data['timestamp'].isoformat()
        })
        
        return jsonify({
            'success': True,
            'message_id': str(message_id),
            'timestamp': message_data['timestamp'].isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return jsonify({'error': 'Failed to send message'}), 500

@connection_bp.route('/get-messages', methods=['GET'])
@login_required
@require_valid_connection
def get_messages(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Get conversation history between student and therapist"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # Get messages
        messages = list(mongo.db.therapist_chats.find({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        }).sort('timestamp', -1).skip(offset).limit(limit))
        
        # Mark messages as read for current user
        if user_role == 'student':
            mongo.db.therapist_chats.update_many(
                {
                    'student_id': ObjectId(student_id),
                    'therapist_id': ObjectId(therapist_id),
                    'sender': 'therapist',
                    'read': False
                },
                {'$set': {'read': True, 'read_at': datetime.now(timezone.utc)}}
            )
        else:  # therapist
            mongo.db.therapist_chats.update_many(
                {
                    'student_id': ObjectId(student_id),
                    'therapist_id': ObjectId(therapist_id),
                    'sender': 'student',
                    'read': False
                },
                {'$set': {'read': True, 'read_at': datetime.now(timezone.utc)}}
            )
        
        # Format messages
        formatted_messages = []
        for msg in reversed(messages):  # Reverse to get chronological order
            formatted_msg = {
                'id': str(msg['_id']),
                'sender': msg['sender'],
                'content': msg['message'],
                'type': msg.get('message_type', 'text'),
                'timestamp': msg['timestamp'].isoformat(),
                'read': msg.get('read', False),
                'formatted_time': msg['timestamp'].strftime('%I:%M %p | %b %d')
            }
            
            # Add resource data if present
            if msg.get('resource_data'):
                formatted_msg['resource'] = {
                    'id': str(msg['resource_data']['resource_id']),
                    'title': msg['resource_data']['title'],
                    'type': msg['resource_data']['type'],
                    'url': msg['resource_data']['url']
                }
            
            formatted_messages.append(formatted_msg)
        
        return jsonify({
            'messages': formatted_messages,
            'total_count': mongo.db.therapist_chats.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            }),
            'has_more': len(messages) == limit
        })
        
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}")
        return jsonify({'error': 'Failed to get messages'}), 500

# ===== APPOINTMENT COORDINATION =====

@connection_bp.route('/sync-appointment', methods=['POST'])
@login_required
@require_valid_connection
def sync_appointment(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Sync appointment status between student and therapist views"""
    try:
        data = request.get_json()
        appointment_id = data.get('appointment_id')
        action = data.get('action')  # confirm, reschedule, cancel, complete
        
        if not appointment_id or not action:
            return jsonify({'error': 'Appointment ID and action required'}), 400
        
        # Get appointment
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        })
        
        if not appointment:
            return jsonify({'error': 'Appointment not found'}), 404
        
        # Process action
        update_data = {'last_modified': datetime.now(timezone.utc)}
        notification_message = ""
        
        if action == 'confirm':
            if user_role != 'therapist':
                return jsonify({'error': 'Only therapists can confirm appointments'}), 403
            
            update_data['status'] = 'confirmed'
            update_data['confirmed_at'] = datetime.now(timezone.utc)
            update_data['confirmed_by'] = ObjectId(therapist_id)
            notification_message = "Your appointment has been confirmed by your therapist"
            
        elif action == 'reschedule':
            new_datetime = data.get('new_datetime')
            if not new_datetime:
                return jsonify({'error': 'New datetime required for reschedule'}), 400
            
            new_dt = datetime.fromisoformat(new_datetime.replace('Z', '+00:00'))
            update_data.update({
                'datetime': new_dt,
                'formatted_time': new_dt.strftime('%A, %B %d at %I:%M %p'),
                'rescheduled_at': datetime.now(timezone.utc),
                'rescheduled_by': ObjectId(session['user'])
            })
            notification_message = f"Your appointment has been rescheduled to {update_data['formatted_time']}"
            
        elif action == 'cancel':
            reason = data.get('reason', 'Cancelled')
            update_data.update({
                'status': 'cancelled',
                'cancelled_at': datetime.now(timezone.utc),
                'cancelled_by': ObjectId(session['user']),
                'cancellation_reason': reason
            })
            notification_message = f"Your appointment has been cancelled: {reason}"
            
        elif action == 'complete':
            if user_role != 'therapist':
                return jsonify({'error': 'Only therapists can mark appointments as complete'}), 403
            
            update_data.update({
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc),
                'completed_by': ObjectId(therapist_id)
            })
            notification_message = "Your session has been marked as complete"
            
        else:
            return jsonify({'error': 'Invalid action'}), 400
        
        # Update appointment
        result = mongo.db.appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': update_data}
        )
        
        if result.modified_count == 0:
            return jsonify({'error': 'Failed to update appointment'}), 500
        
        # Create notification for other party
        recipient_id = student_id if user_role == 'therapist' else therapist_id
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(recipient_id),
            'type': f'appointment_{action}',
            'message': notification_message,
            'related_id': ObjectId(appointment_id),
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Real-time update
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        emit_real_time_update(room_id, 'appointment_updated', {
            'appointment_id': appointment_id,
            'action': action,
            'updated_by': user_role,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        return jsonify({
            'success': True,
            'appointment_id': appointment_id,
            'action': action,
            'updated_data': update_data
        })
        
    except Exception as e:
        logger.error(f"Error syncing appointment: {str(e)}")
        return jsonify({'error': 'Failed to sync appointment'}), 500

@connection_bp.route('/get-shared-appointments', methods=['GET'])
@login_required
@require_valid_connection
def get_shared_appointments(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Get all appointments between student and therapist"""
    try:
        status_filter = request.args.get('status')  # confirmed, completed, cancelled, all
        limit = int(request.args.get('limit', 10))
        
        # Build query
        query = {
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        }
        
        if status_filter and status_filter != 'all':
            if status_filter == 'upcoming':
                query.update({
                    'datetime': {'$gte': datetime.now()},
                    'status': 'confirmed'
                })
            else:
                query['status'] = status_filter
        
        # Get appointments
        appointments = list(mongo.db.appointments.find(query)
                          .sort('datetime', -1)
                          .limit(limit))
        
        # Format appointments
        formatted_appointments = []
        for apt in appointments:
            formatted_apt = {
                'id': str(apt['_id']),
                'datetime': apt.get('datetime').isoformat() if apt.get('datetime') else None,
                'formatted_time': apt.get('formatted_time', 'Time TBD'),
                'status': apt.get('status', 'pending'),
                'type': apt.get('type', 'virtual'),
                'crisis_level': apt.get('crisis_level', 'normal'),
                'auto_scheduled': apt.get('auto_scheduled', False),
                'meeting_info': apt.get('meeting_info', {}),
                'zoom_integrated': bool(apt.get('zoom_meeting_id')),
                'created_at': apt.get('created_at').isoformat() if apt.get('created_at') else None
            }
            
            # Add timing info
            if apt.get('datetime'):
                now = datetime.now()
                time_diff = (apt['datetime'] - now).total_seconds() / 60
                formatted_apt['time_until'] = int(time_diff) if time_diff > 0 else None
                formatted_apt['can_join'] = -15 <= time_diff <= 90  # 15 min before to 90 min after
            
            formatted_appointments.append(formatted_apt)
        
        return jsonify({
            'appointments': formatted_appointments,
            'total_count': mongo.db.appointments.count_documents(query)
        })
        
    except Exception as e:
        logger.error(f"Error getting shared appointments: {str(e)}")
        return jsonify({'error': 'Failed to get appointments'}), 500

# ===== RESOURCE SHARING =====

@connection_bp.route('/share-resource', methods=['POST'])
@login_required
@require_valid_connection
def share_resource(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Share a resource between student and therapist"""
    try:
        if user_role != 'therapist':
            return jsonify({'error': 'Only therapists can share resources'}), 403
        
        data = request.get_json()
        resource_id = data.get('resource_id')
        custom_message = data.get('message', '').strip()
        
        if not resource_id:
            return jsonify({'error': 'Resource ID required'}), 400
        
        # Get resource
        resource = mongo.db.resources.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify({'error': 'Resource not found'}), 404
        
        # Create shared resource record
        shared_resource = {
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'resource_id': ObjectId(resource_id),
            'title': resource['title'],
            'type': resource['type'],
            'description': resource['description'],
            'url': resource['url'],
            'custom_message': custom_message,
            'shared_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.shared_resources.insert_one(shared_resource)
        
        # Send message about shared resource
        message_data = {
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'sender': 'therapist',
            'message': f"I've shared a resource with you: {resource['title']}",
            'message_type': 'resource',
            'resource_data': {
                'resource_id': ObjectId(resource_id),
                'title': resource['title'],
                'type': resource['type'],
                'url': resource['url']
            },
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        }
        
        if custom_message:
            message_data['message'] += f"\n\nNote: {custom_message}"
        
        mongo.db.therapist_chats.insert_one(message_data)
        
        # Create notification
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(student_id),
            'type': 'resource_shared',
            'message': f'Your therapist shared a resource: {resource["title"]}',
            'related_id': result.inserted_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Real-time update
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        emit_real_time_update(room_id, 'resource_shared', {
            'resource_id': resource_id,
            'title': resource['title'],
            'shared_by': 'therapist',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        return jsonify({
            'success': True,
            'shared_resource_id': str(result.inserted_id),
            'resource': {
                'id': resource_id,
                'title': resource['title'],
                'type': resource['type'],
                'url': resource['url']
            }
        })
        
    except Exception as e:
        logger.error(f"Error sharing resource: {str(e)}")
        return jsonify({'error': 'Failed to share resource'}), 500

@connection_bp.route('/get-shared-resources', methods=['GET'])
@login_required
@require_valid_connection
def get_shared_resources(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Get resources shared between student and therapist"""
    try:
        limit = int(request.args.get('limit', 20))
        
        # Get shared resources
        shared_resources = list(mongo.db.shared_resources.find({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        }).sort('shared_at', -1).limit(limit))
        
        # Format resources
        formatted_resources = []
        for res in shared_resources:
            formatted_res = {
                'id': str(res['_id']),
                'resource_id': str(res['resource_id']),
                'title': res['title'],
                'type': res['type'],
                'description': res['description'],
                'url': res['url'],
                'custom_message': res.get('custom_message', ''),
                'shared_at': res['shared_at'].isoformat(),
                'formatted_date': res['shared_at'].strftime('%B %d, %Y at %I:%M %p')
            }
            formatted_resources.append(formatted_res)
        
        return jsonify({
            'shared_resources': formatted_resources,
            'total_count': mongo.db.shared_resources.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            })
        })
        
    except Exception as e:
        logger.error(f"Error getting shared resources: {str(e)}")
        return jsonify({'error': 'Failed to get shared resources'}), 500

# ===== NOTIFICATIONS AND STATUS =====

@connection_bp.route('/get-notifications', methods=['GET'])
@login_required
def get_notifications():
    """Get notifications for current user"""
    try:
        user_id = session['user']
        limit = int(request.args.get('limit', 10))
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        
        # Build query
        query = {'user_id': ObjectId(user_id)}
        if unread_only:
            query['read'] = False
        
        # Get notifications
        notifications = list(mongo.db.notifications.find(query)
                           .sort('created_at', -1)
                           .limit(limit))
        
        # Format notifications
        formatted_notifications = []
        for notif in notifications:
            formatted_notif = {
                'id': str(notif['_id']),
                'type': notif['type'],
                'message': notif['message'],
                'read': notif.get('read', False),
                'created_at': notif['created_at'].isoformat(),
                'formatted_time': notif['created_at'].strftime('%I:%M %p | %b %d'),
                'related_id': str(notif['related_id']) if notif.get('related_id') else None
            }
            formatted_notifications.append(formatted_notif)
        
        # Get unread count
        unread_count = mongo.db.notifications.count_documents({
            'user_id': ObjectId(user_id),
            'read': False
        })
        
        return jsonify({
            'notifications': formatted_notifications,
            'unread_count': unread_count,
            'total_count': mongo.db.notifications.count_documents({'user_id': ObjectId(user_id)})
        })
        
    except Exception as e:
        logger.error(f"Error getting notifications: {str(e)}")
        return jsonify({'error': 'Failed to get notifications'}), 500

@connection_bp.route('/mark-notification-read/<notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    try:
        user_id = session['user']
        
        result = mongo.db.notifications.update_one(
            {
                '_id': ObjectId(notification_id),
                'user_id': ObjectId(user_id)
            },
            {
                '$set': {
                    'read': True,
                    'read_at': datetime.now(timezone.utc)
                }
            }
        )
        
        if result.modified_count == 0:
            return jsonify({'error': 'Notification not found or already read'}), 404
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        return jsonify({'error': 'Failed to mark notification as read'}), 500

@connection_bp.route('/get-connection-status', methods=['GET'])
@login_required
@require_valid_connection
def get_connection_status(student_id=None, therapist_id=None, user_role=None, **kwargs):
    """Get real-time status of student-therapist connection"""
    try:
        # Get student data
        student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
        
        # Get therapist data
        therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
        
        # Get assignment data
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'status': 'active'
        })
        
        # Get latest appointment
        latest_appointment = mongo.db.appointments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        }, sort=[('datetime', -1)])
        
        # Get next appointment
        next_appointment = mongo.db.appointments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed'
        }, sort=[('datetime', 1)])
        
        # Get unread message counts
        unread_from_student = mongo.db.therapist_chats.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'sender': 'student',
            'read': False
        })
        
        unread_from_therapist = mongo.db.therapist_chats.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'sender': 'therapist',
            'read': False
        })
        
        # Calculate stats
        total_sessions = mongo.db.appointments.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'status': 'completed'
        })
        
        status_data = {
            'connection_active': bool(assignment),
            'student': {
                'id': str(student['_id']),
                'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                'email': student.get('email', ''),
                'last_login': student.get('last_login').isoformat() if student.get('last_login') else None
            } if student else None,
            'therapist': {
                'id': str(therapist['_id']),
                'name': therapist.get('name', ''),
                'license_number': therapist.get('license_number', ''),
                'email': therapist.get('email', ''),
                'specializations': therapist.get('specializations', [])
            } if therapist else None,
            'assignment': {
                'created_at': assignment.get('created_at').isoformat() if assignment and assignment.get('created_at') else None,
                'auto_assigned': assignment.get('auto_assigned', False) if assignment else False
            } if assignment else None,
            'latest_appointment': {
                'id': str(latest_appointment['_id']),
                'datetime': latest_appointment.get('datetime').isoformat() if latest_appointment.get('datetime') else None,
                'status': latest_appointment.get('status', 'unknown'),
                'type': latest_appointment.get('type', 'virtual')
            } if latest_appointment else None,
            'next_appointment': {
                'id': str(next_appointment['_id']),
                'datetime': next_appointment.get('datetime').isoformat() if next_appointment.get('datetime') else None,
                'formatted_time': next_appointment.get('formatted_time', 'Time TBD'),
                'can_join': False
            } if next_appointment else None,
            'messaging': {
                'unread_from_student': unread_from_student,
                'unread_from_therapist': unread_from_therapist,
                'total_messages': mongo.db.therapist_chats.count_documents({
                    'student_id': ObjectId(student_id),
                    'therapist_id': ObjectId(therapist_id)
                })
            },
            'statistics': {
                'total_sessions': total_sessions,
                'days_connected': (datetime.now() - assignment['created_at']).days if assignment and assignment.get('created_at') else 0,
                'shared_resources': mongo.db.shared_resources.count_documents({
                    'student_id': ObjectId(student_id),
                    'therapist_id': ObjectId(therapist_id)
                })
            }
        }
        
        # Check if next appointment can be joined
        if next_appointment and next_appointment.get('datetime'):
            time_diff = (next_appointment['datetime'] - datetime.now()).total_seconds() / 60
            status_data['next_appointment']['can_join'] = -15 <= time_diff <= 90
            status_data['next_appointment']['time_until'] = int(time_diff) if time_diff > 0 else None
        
        return jsonify(status_data)
        
    except Exception as e:
        logger.error(f"Error getting connection status: {str(e)}")
        return jsonify({'error': 'Failed to get connection status'}), 500

# ===== CROSS-NAVIGATION HELPERS =====

@connection_bp.route('/get-navigation-links', methods=['GET'])
@login_required
def get_navigation_links():
    """Get navigation links based on user role and connections"""
    try:
        user_id = session['user']
        user_role = get_user_role(user_id)
        
        links = {
            'user_role': user_role,
            'dashboard_url': None,
            'connections': [],
            'quick_actions': []
        }
        
        if user_role == 'student':
            links['dashboard_url'] = url_for('dashboard.index')
            
            # Get assigned therapist
            student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if student and student.get('assigned_therapist_id'):
                therapist = mongo.db.therapists.find_one({'_id': student['assigned_therapist_id']})
                if therapist:
                    links['connections'].append({
                        'type': 'therapist',
                        'id': str(therapist['_id']),
                        'name': therapist.get('name', 'Your Therapist'),
                        'license_number': therapist.get('license_number', ''),
                        'url': url_for('dashboard.therapist_info')
                    })
            
            links['quick_actions'] = [
                {'label': 'Book Appointment', 'url': url_for('dashboard.book_appointment')},
                {'label': 'View Messages', 'url': '#'},  # Will use JavaScript to open chat
                {'label': 'Join Session', 'url': '#'}  # Will check for active session
            ]
            
        elif user_role == 'therapist':
            links['dashboard_url'] = url_for('therapist.index')
            
            # Get assigned students
            assignments = list(mongo.db.therapist_assignments.find({
                'therapist_id': ObjectId(user_id),
                'status': 'active'
            }).limit(10))
            
            for assignment in assignments:
                student = mongo.db.users.find_one({'_id': assignment['student_id']})
                if student:
                    links['connections'].append({
                        'type': 'student',
                        'id': str(student['_id']),
                        'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip(),
                        'email': student.get('email', ''),
                        'url': url_for('therapist.student_details', student_id=str(student['_id']))
                    })
            
            links['quick_actions'] = [
                {'label': 'View Students', 'url': url_for('therapist.students')},
                {'label': 'Virtual Sessions', 'url': url_for('therapist.virtual_sessions')},
                {'label': 'Availability', 'url': url_for('therapist.availability')}
            ]
        
        return jsonify(links)
        
    except Exception as e:
        logger.error(f"Error getting navigation links: {str(e)}")
        return jsonify({'error': 'Failed to get navigation links'}), 500

# ===== UTILITY ENDPOINTS =====

@connection_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for connection system"""
    try:
        # Test database connection
        mongo.db.users.find_one({}, {'_id': 1})
        
        status = {
            'status': 'healthy',
            'database': 'connected',
            'socketio': 'available' if SOCKETIO_AVAILABLE else 'unavailable',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500

@connection_bp.route('/connection-stats', methods=['GET'])
@login_required
def get_connection_stats():
    """Get overall connection statistics"""
    try:
        user_id = session['user']
        user_role = get_user_role(user_id)
        
        if user_role == 'student':
            student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not student or not student.get('assigned_therapist_id'):
                return jsonify({'error': 'No therapist assigned'}), 404
            
            therapist_id = str(student['assigned_therapist_id'])
            student_id = user_id
            
        elif user_role == 'therapist':
            therapist_id = user_id
            # Get stats for all students
            return jsonify({
                'role': 'therapist',
                'total_students': mongo.db.therapist_assignments.count_documents({
                    'therapist_id': ObjectId(therapist_id),
                    'status': 'active'
                }),
                'total_sessions': mongo.db.appointments.count_documents({
                    'therapist_id': ObjectId(therapist_id),
                    'status': 'completed'
                }),
                'pending_messages': mongo.db.therapist_chats.count_documents({
                    'therapist_id': ObjectId(therapist_id),
                    'sender': 'student',
                    'read': False
                })
            })
        else:
            return jsonify({'error': 'Unknown user role'}), 400
        
        # Student-specific stats
        stats = {
            'role': 'student',
            'connection_active': validate_connection_access(student_id, therapist_id),
            'total_sessions': mongo.db.appointments.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'status': 'completed'
            }),
            'pending_messages': mongo.db.therapist_chats.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'sender': 'therapist',
                'read': False
            }),
            'shared_resources': mongo.db.shared_resources.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            }),
            'next_appointment': None
        }
        
        # Get next appointment
        next_apt = mongo.db.appointments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed'
        }, sort=[('datetime', 1)])
        
        if next_apt:
            stats['next_appointment'] = {
                'id': str(next_apt['_id']),
                'datetime': next_apt['datetime'].isoformat(),
                'formatted_time': next_apt.get('formatted_time', 'Time TBD')
            }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error getting connection stats: {str(e)}")
        return jsonify({'error': 'Failed to get connection stats'}), 500