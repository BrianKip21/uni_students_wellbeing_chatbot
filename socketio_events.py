# wellbeing/socketio_events.py
# Real-time Socket.IO implementation for student-therapist connections

from flask import session, request
from flask_socketio import emit, join_room, leave_room, disconnect
from datetime import datetime, timezone
from bson.objectid import ObjectId
import json

from wellbeing import socketio, mongo, logger

# Import connection utilities
try:
    from wellbeing.connection.routes import validate_connection_access, get_user_role
except ImportError:
    logger.warning("Connection routes not available for Socket.IO events")
    
    def validate_connection_access(student_id, therapist_id):
        return False
    
    def get_user_role(user_id):
        return 'unknown'

# Store active connections
active_connections = {}
user_rooms = {}

# ===== CONNECTION MANAGEMENT =====

@socketio.on('connect')
def handle_connect(auth=None):
    """Handle client connection"""
    try:
        # Verify authentication
        if 'user' not in session:
            logger.warning(f"Unauthenticated Socket.IO connection attempt from {request.remote_addr}")
            disconnect()
            return False
        
        user_id = session['user']
        user_role = get_user_role(user_id)
        
        # Store connection info
        active_connections[request.sid] = {
            'user_id': user_id,
            'user_role': user_role,
            'connected_at': datetime.now(timezone.utc),
            'ip_address': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown')
        }
        
        logger.info(f"Socket.IO connection established: {user_role} {user_id} (SID: {request.sid})")
        
        # Send connection confirmation
        emit('connection_established', {
            'user_id': user_id,
            'user_role': user_role,
            'server_time': datetime.now(timezone.utc).isoformat(),
            'connection_id': request.sid
        })
        
        # Send initial status
        emit('status_update', get_user_status(user_id, user_role))
        
        return True
        
    except Exception as e:
        logger.error(f"Error in Socket.IO connect: {str(e)}")
        disconnect()
        return False

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    try:
        if request.sid in active_connections:
            connection_info = active_connections[request.sid]
            user_id = connection_info['user_id']
            user_role = connection_info['user_role']
            
            # Leave all rooms
            if request.sid in user_rooms:
                for room in user_rooms[request.sid]:
                    leave_room(room)
                del user_rooms[request.sid]
            
            # Remove from active connections
            del active_connections[request.sid]
            
            logger.info(f"Socket.IO disconnection: {user_role} {user_id} (SID: {request.sid})")
            
            # Notify other participants in shared rooms
            emit_user_status_update(user_id, 'offline')
            
    except Exception as e:
        logger.error(f"Error in Socket.IO disconnect: {str(e)}")

# ===== ROOM MANAGEMENT =====

@socketio.on('join_connection_room')
def handle_join_connection_room(data):
    """Join a room for student-therapist communication"""
    try:
        if request.sid not in active_connections:
            emit('error', {'message': 'Not authenticated'})
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        # Auto-fill based on user role
        if user_role == 'student':
            student_id = user_id
            if not therapist_id:
                student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                if student and student.get('assigned_therapist_id'):
                    therapist_id = str(student['assigned_therapist_id'])
        elif user_role == 'therapist':
            therapist_id = user_id
        
        if not student_id or not therapist_id:
            emit('error', {'message': 'Student ID and Therapist ID required'})
            return
        
        # Validate connection
        if not validate_connection_access(student_id, therapist_id):
            emit('error', {'message': 'Invalid connection'})
            return
        
        # Create room ID
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        
        # Join room
        join_room(room_id)
        
        # Track user rooms
        if request.sid not in user_rooms:
            user_rooms[request.sid] = set()
        user_rooms[request.sid].add(room_id)
        
        # Update connection info
        active_connections[request.sid].update({
            'current_room': room_id,
            'student_id': student_id,
            'therapist_id': therapist_id
        })
        
        logger.info(f"User {user_id} ({user_role}) joined room {room_id}")
        
        # Emit join confirmation
        emit('joined_connection_room', {
            'room_id': room_id,
            'student_id': student_id,
            'therapist_id': therapist_id,
            'user_role': user_role,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        # Notify other participants
        emit('user_joined', {
            'user_id': user_id,
            'user_role': user_role,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=room_id, include_self=False)
        
        # Send room status
        room_status = get_room_status(room_id, student_id, therapist_id)
        emit('room_status', room_status, room=room_id)
        
    except Exception as e:
        logger.error(f"Error joining connection room: {str(e)}")
        emit('error', {'message': 'Failed to join room'})

@socketio.on('leave_connection_room')
def handle_leave_connection_room(data):
    """Leave a connection room"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        
        # Leave room
        leave_room(room_id)
        
        # Remove from user rooms
        if request.sid in user_rooms and room_id in user_rooms[request.sid]:
            user_rooms[request.sid].remove(room_id)
        
        # Update connection info
        if 'current_room' in active_connections[request.sid]:
            del active_connections[request.sid]['current_room']
        
        logger.info(f"User {user_id} ({user_role}) left room {room_id}")
        
        # Notify other participants
        emit('user_left', {
            'user_id': user_id,
            'user_role': user_role,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=room_id)
        
        # Confirm leave
        emit('left_connection_room', {
            'room_id': room_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error leaving connection room: {str(e)}")

# ===== REAL-TIME MESSAGING =====

@socketio.on('send_real_time_message')
def handle_real_time_message(data):
    """Handle real-time message sending"""
    try:
        if request.sid not in active_connections:
            emit('error', {'message': 'Not authenticated'})
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        message_content = data.get('message', '').strip()
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        message_type = data.get('type', 'text')
        
        if not message_content or not student_id or not therapist_id:
            emit('error', {'message': 'Invalid message data'})
            return
        
        # Validate connection
        if not validate_connection_access(student_id, therapist_id):
            emit('error', {'message': 'Invalid connection'})
            return
        
        # Save message to database
        message_data = {
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'sender': user_role,
            'message': message_content,
            'message_type': message_type,
            'read': False,
            'timestamp': datetime.now(timezone.utc),
            'delivered_via': 'socket_io',
            'metadata': data.get('metadata', {})
        }
        
        result = mongo.db.therapist_chats.insert_one(message_data)
        message_id = result.inserted_id
        
        # Create notification for recipient
        recipient_id = therapist_id if user_role == 'student' else student_id
        mongo.db.notifications.insert_one({
            'user_id': ObjectId(recipient_id),
            'type': 'new_message',
            'message': f'New message from your {"student" if user_role == "therapist" else "therapist"}',
            'related_id': message_id,
            'read': False,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Prepare broadcast data
        broadcast_data = {
            'message_id': str(message_id),
            'sender': user_role,
            'sender_id': user_id,
            'content': message_content,
            'type': message_type,
            'timestamp': message_data['timestamp'].isoformat(),
            'formatted_time': message_data['timestamp'].strftime('%I:%M %p')
        }
        
        # Broadcast to room
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        emit('new_message', broadcast_data, room=room_id)
        
        # Send delivery confirmation to sender
        emit('message_delivered', {
            'message_id': str(message_id),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Real-time message sent: {user_role} {user_id} to room {room_id}")
        
    except Exception as e:
        logger.error(f"Error sending real-time message: {str(e)}")
        emit('error', {'message': 'Failed to send message'})

@socketio.on('mark_messages_read')
def handle_mark_messages_read(data):
    """Mark messages as read in real-time"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        if not validate_connection_access(student_id, therapist_id):
            return
        
        # Mark messages as read
        sender_role = 'therapist' if user_role == 'student' else 'student'
        
        result = mongo.db.therapist_chats.update_many(
            {
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'sender': sender_role,
                'read': False
            },
            {
                '$set': {
                    'read': True,
                    'read_at': datetime.now(timezone.utc)
                }
            }
        )
        
        if result.modified_count > 0:
            # Notify room of read status
            room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
            emit('messages_read', {
                'reader_role': user_role,
                'count': result.modified_count,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, room=room_id, include_self=False)
            
            logger.info(f"Marked {result.modified_count} messages as read by {user_role} {user_id}")
        
    except Exception as e:
        logger.error(f"Error marking messages as read: {str(e)}")

# ===== APPOINTMENT UPDATES =====

@socketio.on('appointment_status_update')
def handle_appointment_status_update(data):
    """Handle real-time appointment status updates"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        appointment_id = data.get('appointment_id')
        status = data.get('status')
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        if not all([appointment_id, status, student_id, therapist_id]):
            emit('error', {'message': 'Invalid appointment update data'})
            return
        
        # Validate connection and appointment ownership
        if not validate_connection_access(student_id, therapist_id):
            return
        
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id)
        })
        
        if not appointment:
            emit('error', {'message': 'Appointment not found'})
            return
        
        # Broadcast update to room
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        
        update_data = {
            'appointment_id': appointment_id,
            'status': status,
            'updated_by': user_role,
            'updated_by_id': user_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'appointment_datetime': appointment.get('datetime').isoformat() if appointment.get('datetime') else None
        }
        
        emit('appointment_updated', update_data, room=room_id)
        
        logger.info(f"Appointment {appointment_id} status updated to {status} by {user_role} {user_id}")
        
    except Exception as e:
        logger.error(f"Error updating appointment status: {str(e)}")
        emit('error', {'message': 'Failed to update appointment'})

# ===== TYPING INDICATORS =====

@socketio.on('typing_start')
def handle_typing_start(data):
    """Handle typing indicator start"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_role = connection_info['user_role']
        
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        if not validate_connection_access(student_id, therapist_id):
            return
        
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        
        emit('user_typing', {
            'user_role': user_role,
            'typing': True,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=room_id, include_self=False)
        
    except Exception as e:
        logger.error(f"Error handling typing start: {str(e)}")

@socketio.on('typing_stop')
def handle_typing_stop(data):
    """Handle typing indicator stop"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_role = connection_info['user_role']
        
        student_id = data.get('student_id')
        therapist_id = data.get('therapist_id')
        
        if not validate_connection_access(student_id, therapist_id):
            return
        
        room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
        
        emit('user_typing', {
            'user_role': user_role,
            'typing': False,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=room_id, include_self=False)
        
    except Exception as e:
        logger.error(f"Error handling typing stop: {str(e)}")

# ===== STATUS UPDATES =====

@socketio.on('request_status_update')
def handle_status_update_request(data):
    """Handle request for status update"""
    try:
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        user_id = connection_info['user_id']
        user_role = connection_info['user_role']
        
        status = get_user_status(user_id, user_role)
        emit('status_update', status)
        
    except Exception as e:
        logger.error(f"Error handling status update request: {str(e)}")

# ===== UTILITY FUNCTIONS =====

def get_user_status(user_id: str, user_role: str) -> dict:
    """Get current status for a user"""
    try:
        status = {
            'user_id': user_id,
            'user_role': user_role,
            'online': True,
            'last_seen': datetime.now(timezone.utc).isoformat()
        }
        
        if user_role == 'student':
            # Get assigned therapist status
            student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if student and student.get('assigned_therapist_id'):
                therapist_online = any(
                    conn['user_id'] == str(student['assigned_therapist_id'])
                    for conn in active_connections.values()
                )
                status['therapist_online'] = therapist_online
            
            # Get unread message count
            status['unread_messages'] = mongo.db.therapist_chats.count_documents({
                'student_id': ObjectId(user_id),
                'sender': 'therapist',
                'read': False
            })
            
        elif user_role == 'therapist':
            # Get online students
            assignments = mongo.db.therapist_assignments.find({
                'therapist_id': ObjectId(user_id),
                'status': 'active'
            })
            
            online_students = []
            total_unread = 0
            
            for assignment in assignments:
                student_id = str(assignment['student_id'])
                student_online = any(
                    conn['user_id'] == student_id
                    for conn in active_connections.values()
                )
                
                if student_online:
                    online_students.append(student_id)
                
                # Count unread messages from this student
                unread = mongo.db.therapist_chats.count_documents({
                    'student_id': assignment['student_id'],
                    'therapist_id': ObjectId(user_id),
                    'sender': 'student',
                    'read': False
                })
                total_unread += unread
            
            status['online_students'] = online_students
            status['unread_messages'] = total_unread
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting user status: {str(e)}")
        return {'user_id': user_id, 'user_role': user_role, 'online': True, 'error': str(e)}

def get_room_status(room_id: str, student_id: str, therapist_id: str) -> dict:
    """Get status for a connection room"""
    try:
        # Count active users in room
        active_users = []
        for sid, conn in active_connections.items():
            if sid in user_rooms and room_id in user_rooms[sid]:
                active_users.append({
                    'user_id': conn['user_id'],
                    'user_role': conn['user_role'],
                    'connected_at': conn['connected_at'].isoformat()
                })
        
        # Get recent activity
        recent_messages = mongo.db.therapist_chats.count_documents({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'timestamp': {'$gte': datetime.now(timezone.utc) - timedelta(hours=1)}
        })
        
        # Get next appointment
        next_appointment = mongo.db.appointments.find_one({
            'student_id': ObjectId(student_id),
            'therapist_id': ObjectId(therapist_id),
            'datetime': {'$gte': datetime.now()},
            'status': 'confirmed'
        }, sort=[('datetime', 1)])
        
        return {
            'room_id': room_id,
            'active_users': active_users,
            'user_count': len(active_users),
            'recent_messages': recent_messages,
            'next_appointment': {
                'id': str(next_appointment['_id']),
                'datetime': next_appointment['datetime'].isoformat(),
                'formatted_time': next_appointment.get('formatted_time', 'Time TBD')
            } if next_appointment else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting room status: {str(e)}")
        return {'room_id': room_id, 'error': str(e)}

def emit_user_status_update(user_id: str, status: str):
    """Emit user status update to relevant rooms"""
    try:
        user_role = get_user_role(user_id)
        
        # Find rooms that should be notified
        notify_rooms = set()
        
        if user_role == 'student':
            # Notify therapist rooms
            student = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if student and student.get('assigned_therapist_id'):
                therapist_id = str(student['assigned_therapist_id'])
                room_id = f"connection_{min(user_id, therapist_id)}_{max(user_id, therapist_id)}"
                notify_rooms.add(room_id)
                
        elif user_role == 'therapist':
            # Notify student rooms
            assignments = mongo.db.therapist_assignments.find({
                'therapist_id': ObjectId(user_id),
                'status': 'active'
            })
            
            for assignment in assignments:
                student_id = str(assignment['student_id'])
                room_id = f"connection_{min(student_id, user_id)}_{max(student_id, user_id)}"
                notify_rooms.add(room_id)
        
        # Emit to all relevant rooms
        for room_id in notify_rooms:
            socketio.emit('user_status_changed', {
                'user_id': user_id,
                'user_role': user_role,
                'status': status,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, room=room_id)
            
    except Exception as e:
        logger.error(f"Error emitting user status update: {str(e)}")

# ===== ADMIN MONITORING =====

@socketio.on('admin_get_connections')
def handle_admin_get_connections():
    """Admin endpoint to get all active connections"""
    try:
        # In production, add admin role check
        if request.sid not in active_connections:
            return
        
        connection_info = active_connections[request.sid]
        # Add admin role check here
        
        connections_summary = []
        for sid, conn in active_connections.items():
            connections_summary.append({
                'session_id': sid,
                'user_id': conn['user_id'],
                'user_role': conn['user_role'],
                'connected_at': conn['connected_at'].isoformat(),
                'current_room': conn.get('current_room'),
                'ip_address': conn.get('ip_address'),
                'duration_minutes': (datetime.now(timezone.utc) - conn['connected_at']).total_seconds() / 60
            })
        
        emit('admin_connections_data', {
            'total_connections': len(active_connections),
            'connections': connections_summary,
            'room_count': len(set(
                conn.get('current_room') for conn in active_connections.values() 
                if conn.get('current_room')
            )),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting admin connections: {str(e)}")
        emit('error', {'message': 'Failed to get connections data'})

# ===== ERROR HANDLING =====

@socketio.on_error_default
def default_error_handler(e):
    """Handle Socket.IO errors"""
    logger.error(f"Socket.IO error: {str(e)}")
    if request.sid in active_connections:
        connection_info = active_connections[request.sid]
        logger.error(f"Error context: User {connection_info['user_id']} ({connection_info['user_role']})")
    
    emit('error', {'message': 'An unexpected error occurred'})

# Export utility functions for external use
__all__ = [
    'active_connections',
    'user_rooms', 
    'get_user_status',
    'get_room_status',
    'emit_user_status_update'
]