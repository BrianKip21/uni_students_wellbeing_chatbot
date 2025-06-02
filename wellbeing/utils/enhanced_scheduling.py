# wellbeing/utils/enhanced_scheduling.py
# Enhanced Automated Scheduling with Real-time Updates

from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
from flask import session, request, jsonify, flash, Blueprint
import uuid

from wellbeing.extensions import mongo, logger, socketio
from wellbeing.utils.scheduling import (
    get_therapist_available_slots,
    auto_schedule_best_time,
    schedule_appointment_automatically
)
from wellbeing.utils.mental_health import (
    detect_crisis_level,
    assign_therapist_immediately
)

# Socket.IO for real-time updates (if available)
try:
    from wellbeing import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logger.warning("Socket.IO not available - enhanced scheduling will work without real-time features")

# ===== ENHANCED AUTO-SCHEDULING WITH REAL-TIME UPDATES =====

class EnhancedAppointmentManager:
    """
    Enhanced version of your AppointmentManager with real-time connection updates
    Preserves all existing automation while adding real-time coordination
    """
    
    @staticmethod
    def create_appointment_with_zoom_and_notifications(
        student_id: str, 
        therapist: dict, 
        appointment_slot: dict, 
        crisis_level: str = 'normal',
        scheduling_context: str = 'auto'  # 'auto', 'intake', 'crisis', 'manual'
    ):
        """
        Enhanced appointment creation with real-time notifications
        Builds on your existing AppointmentManager.create_appointment_with_zoom
        """
        
        # Use your existing appointment creation logic
        from wellbeing.blueprints.dashboard.routes import AppointmentManager
        
        appointment_id, appointment_doc, zoom_success = AppointmentManager.create_appointment_with_zoom(
            student_id, therapist, appointment_slot, crisis_level
        )
        
        if appointment_id:
            # Add real-time notifications via connection system
            EnhancedAppointmentManager._send_real_time_appointment_notifications(
                appointment_id, appointment_doc, student_id, therapist, 
                scheduling_context, zoom_success
            )
            
            # Log the automated scheduling event
            EnhancedAppointmentManager._log_auto_scheduling_event(
                student_id, therapist['_id'], appointment_id, scheduling_context, crisis_level
            )
        
        return appointment_id, appointment_doc, zoom_success
    
    @staticmethod
    def _send_real_time_appointment_notifications(
        appointment_id, appointment_doc, student_id, therapist, 
        scheduling_context, zoom_success
    ):
        """Send real-time notifications for automated scheduling"""
        try:
            # Create room ID for this student-therapist connection
            therapist_id = str(therapist['_id'])
            room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
            
            # Prepare notification data
            notification_data = {
                'appointment_id': str(appointment_id),
                'student_id': student_id,
                'therapist_id': therapist_id,
                'appointment_time': appointment_doc['formatted_time'],
                'crisis_level': appointment_doc.get('crisis_level', 'normal'),
                'zoom_integrated': zoom_success,
                'scheduling_context': scheduling_context,
                'meeting_link': appointment_doc.get('meeting_info', {}).get('meet_link'),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Send real-time updates via Socket.IO
            if SOCKETIO_AVAILABLE:
                # Notify student
                socketio.emit('appointment_auto_scheduled', {
                    **notification_data,
                    'message': f'Your {"priority " if scheduling_context == "crisis" else ""}appointment has been automatically scheduled',
                    'recipient': 'student'
                }, room=room_id)
                
                # Notify therapist
                socketio.emit('appointment_auto_scheduled', {
                    **notification_data,
                    'message': f'New {"priority " if scheduling_context == "crisis" else ""}appointment automatically scheduled',
                    'recipient': 'therapist'
                }, room=room_id)
            
            # Create database notifications
            notifications = [
                {
                    'user_id': ObjectId(student_id),
                    'type': 'appointment_auto_scheduled',
                    'message': f'Your {"priority " if scheduling_context == "crisis" else ""}session has been automatically scheduled for {appointment_doc["formatted_time"]}',
                    'related_id': appointment_id,
                    'read': False,
                    'created_at': datetime.now(timezone.utc),
                    'metadata': {
                        'scheduling_context': scheduling_context,
                        'zoom_integrated': zoom_success,
                        'crisis_level': appointment_doc.get('crisis_level', 'normal')
                    }
                },
                {
                    'user_id': therapist['_id'],
                    'type': 'appointment_auto_scheduled',
                    'message': f'New {"priority " if scheduling_context == "crisis" else ""}appointment automatically scheduled with student for {appointment_doc["formatted_time"]}',
                    'related_id': appointment_id,
                    'read': False,
                    'created_at': datetime.now(timezone.utc),
                    'metadata': {
                        'scheduling_context': scheduling_context,
                        'zoom_integrated': zoom_success,
                        'student_id': student_id
                    }
                }
            ]
            
            mongo.db.notifications.insert_many(notifications)
            
        except Exception as e:
            logger.error(f"Error sending real-time appointment notifications: {str(e)}")
    
    @staticmethod
    def _log_auto_scheduling_event(student_id, therapist_id, appointment_id, context, crisis_level):
        """Log automated scheduling event for analytics"""
        try:
            from wellbeing.utils.connection_monitor import ConnectionMonitor
            
            ConnectionMonitor.log_connection_event(
                student_id=student_id,
                therapist_id=str(therapist_id),
                action='appointment_auto_scheduled',
                user_role='system',
                details={
                    'appointment_id': str(appointment_id),
                    'scheduling_context': context,
                    'crisis_level': crisis_level,
                    'auto_scheduled': True
                }
            )
        except Exception as e:
            logger.error(f"Error logging auto scheduling event: {str(e)}")

# ===== ENHANCED CRISIS-LEVEL AUTO-SCHEDULING =====

class CrisisSchedulingManager:
    """
    Enhanced crisis-level scheduling with immediate real-time notifications
    Builds on your existing crisis detection and immediate scheduling
    """
    
    @staticmethod
    def handle_crisis_intake_with_immediate_scheduling(intake_data, user_id):
        """
        Enhanced crisis intake handling with real-time updates
        Builds on your existing _schedule_immediate_appointment logic
        """
        try:
            # Use your existing crisis detection
            crisis_result = detect_crisis_level(intake_data)
            crisis_level = crisis_result['level']
            
            if crisis_level in ['high', 'critical']:
                # Use your existing therapist assignment
                therapist = assign_therapist_immediately(intake_data)
                
                if therapist:
                    # Send immediate real-time alert to therapist
                    CrisisSchedulingManager._send_crisis_alert(user_id, therapist, crisis_level, intake_data)
                    
                    # Use enhanced scheduling with real-time updates
                    available_slots = get_therapist_available_slots(therapist, crisis_level=crisis_level)
                    
                    if available_slots:
                        # Schedule immediately with real-time notifications
                        appointment_id, appointment_doc, zoom_success = EnhancedAppointmentManager.create_appointment_with_zoom_and_notifications(
                            user_id, therapist, available_slots[0], crisis_level, 'crisis'
                        )
                        
                        if appointment_id:
                            # Additional crisis-specific notifications
                            CrisisSchedulingManager._send_crisis_scheduled_notifications(
                                appointment_id, appointment_doc, user_id, therapist, crisis_level
                            )
                            
                            return {
                                'success': True,
                                'appointment_id': appointment_id,
                                'therapist': therapist,
                                'crisis_level': crisis_level,
                                'immediate_scheduling': True
                            }
            
            # Fall back to your existing non-crisis scheduling
            return CrisisSchedulingManager._handle_normal_intake_scheduling(intake_data, user_id)
            
        except Exception as e:
            logger.error(f"Error in crisis intake scheduling: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _send_crisis_alert(student_id, therapist, crisis_level, intake_data):
        """Send immediate crisis alert to therapist"""
        try:
            therapist_id = str(therapist['_id'])
            
            # Real-time crisis alert via Socket.IO
            if SOCKETIO_AVAILABLE:
                socketio.emit('crisis_alert', {
                    'student_id': student_id,
                    'crisis_level': crisis_level,
                    'primary_concern': intake_data.get('primary_concern', 'Not specified'),
                    'description': intake_data.get('description', ''),
                    'emergency_contact': {
                        'name': intake_data.get('emergency_contact_name'),
                        'phone': intake_data.get('emergency_contact_phone')
                    },
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'requires_immediate_attention': True
                }, room=f"therapist_{therapist_id}")
            
            # High-priority database notification
            mongo.db.notifications.insert_one({
                'user_id': therapist['_id'],
                'type': 'crisis_alert',
                'message': f'URGENT: Crisis-level student requires immediate attention',
                'related_id': ObjectId(student_id),
                'read': False,
                'created_at': datetime.now(timezone.utc),
                'priority': 'high',
                'metadata': {
                    'crisis_level': crisis_level,
                    'primary_concern': intake_data.get('primary_concern'),
                    'student_id': student_id
                }
            })
            
        except Exception as e:
            logger.error(f"Error sending crisis alert: {str(e)}")
    
    @staticmethod
    def _send_crisis_scheduled_notifications(appointment_id, appointment_doc, student_id, therapist, crisis_level):
        """Send crisis-specific scheduling notifications"""
        try:
            # Priority email notifications could go here
            # SMS alerts for therapists could go here
            # Escalation to supervisors could go here
            
            logger.info(f"Crisis appointment {appointment_id} scheduled for student {student_id} with therapist {therapist['_id']}")
            
        except Exception as e:
            logger.error(f"Error sending crisis scheduled notifications: {str(e)}")
    
    @staticmethod
    def _handle_normal_intake_scheduling(intake_data, user_id):
        """Handle normal (non-crisis) intake scheduling with your existing logic"""
        # This would use your existing intake processing logic
        # but with enhanced real-time notifications
        try:
            therapist = assign_therapist_immediately(intake_data)
            
            if therapist:
                # Send non-crisis assignment notification
                if SOCKETIO_AVAILABLE:
                    socketio.emit('therapist_assigned', {
                        'student_id': user_id,
                        'therapist_id': str(therapist['_id']),
                        'therapist_name': therapist.get('name', 'Your Therapist'),
                        'message': 'You have been assigned a therapist',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, room=f"student_{user_id}")
                
                return {
                    'success': True,
                    'therapist': therapist,
                    'crisis_level': 'normal',
                    'immediate_scheduling': False
                }
            
            return {'success': False, 'error': 'No available therapist'}
            
        except Exception as e:
            logger.error(f"Error in normal intake scheduling: {str(e)}")
            return {'success': False, 'error': str(e)}

# ===== ENHANCED AUTO-RESCHEDULING =====

class EnhancedReschedulingManager:
    """
    Enhanced auto-rescheduling with real-time coordination
    Builds on your existing auto_reschedule_appointment functionality
    """
    
    @staticmethod
    def auto_reschedule_with_real_time_updates(appointment_id, therapist_id, reason="Therapist unavailable"):
        """
        Enhanced auto-rescheduling with real-time updates
        Builds on your existing auto_reschedule_appointment logic
        """
        try:
            # Get the appointment
            appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            if not appointment:
                return {'success': False, 'error': 'Appointment not found'}
            
            student_id = str(appointment['student_id'])
            
            # Use your existing slot finding logic
            from wellbeing.blueprints.therapist.routes import find_next_available_slot
            next_slot = find_next_available_slot(therapist_id)
            
            if not next_slot:
                # Try alternative therapist assignment
                return EnhancedReschedulingManager._suggest_alternative_therapist_with_real_time(
                    appointment_id, student_id, therapist_id, reason
                )
            
            # Update appointment with your existing logic
            result = mongo.db.appointments.update_one(
                {'_id': ObjectId(appointment_id)},
                {
                    '$set': {
                        'datetime': next_slot,
                        'formatted_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
                        'auto_rescheduled': True,
                        'rescheduled_at': datetime.now(),
                        'rescheduled_by': ObjectId(therapist_id),
                        'rescheduled_reason': reason,
                        'original_datetime': appointment['datetime']
                    }
                }
            )
            
            if result.modified_count > 0:
                # Send real-time updates
                EnhancedReschedulingManager._send_reschedule_notifications(
                    appointment_id, student_id, therapist_id, next_slot, reason, 'auto_rescheduled'
                )
                
                return {
                    'success': True,
                    'new_time': next_slot.strftime('%A, %B %d at %I:%M %p'),
                    'rescheduled_automatically': True
                }
            
            return {'success': False, 'error': 'Failed to update appointment'}
            
        except Exception as e:
            logger.error(f"Error in auto-rescheduling: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _suggest_alternative_therapist_with_real_time(appointment_id, student_id, original_therapist_id, reason):
        """Enhanced alternative therapist suggestion with real-time updates"""
        try:
            # Use your existing alternative therapist logic
            from wellbeing.blueprints.therapist.routes import find_alternative_therapists
            
            appointment = mongo.db.appointments.find_one({'_id': ObjectId(appointment_id)})
            intake = mongo.db.intake_assessments.find_one({'student_id': ObjectId(student_id)})
            
            alternative_therapists = find_alternative_therapists(
                current_therapist_id=ObjectId(original_therapist_id),
                student_intake=intake,
                appointment_datetime=appointment['datetime']
            )
            
            if alternative_therapists:
                # Create alternative options with real-time scheduling
                alternatives = []
                for alt_therapist in alternative_therapists[:3]:
                    alt_slots = get_therapist_available_slots(alt_therapist, crisis_level='normal')
                    if alt_slots:
                        alternatives.append({
                            'therapist_id': str(alt_therapist['_id']),
                            'therapist_name': alt_therapist['name'],
                            'license_number': alt_therapist.get('license_number', ''),
                            'available_time': alt_slots[0]['formatted'],
                            'available_datetime': alt_slots[0]['datetime'].isoformat(),
                            'specializations': alt_therapist.get('specializations', [])
                        })
                
                if alternatives:
                    # Store alternatives and send real-time notification
                    mongo.db.alternative_therapist_options.insert_one({
                        'student_id': ObjectId(student_id),
                        'original_appointment_id': ObjectId(appointment_id),
                        'original_therapist_id': ObjectId(original_therapist_id),
                        'alternatives': alternatives,
                        'reason': reason,
                        'created_at': datetime.now(),
                        'expires_at': datetime.now() + timedelta(hours=24)
                    })
                    
                    # Send real-time notification to student
                    room_id = f"connection_{min(student_id, original_therapist_id)}_{max(student_id, original_therapist_id)}"
                    
                    if SOCKETIO_AVAILABLE:
                        socketio.emit('alternative_therapists_available', {
                            'original_appointment_id': appointment_id,
                            'reason': reason,
                            'alternatives': alternatives,
                            'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
                            'message': f'Your therapist is unavailable. We found {len(alternatives)} alternative options.'
                        }, room=room_id)
                    
                    return {
                        'success': True,
                        'alternative_therapists_offered': len(alternatives),
                        'expires_in_hours': 24
                    }
            
            return {'success': False, 'error': 'No alternative therapists available'}
            
        except Exception as e:
            logger.error(f"Error suggesting alternative therapist: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _send_reschedule_notifications(appointment_id, student_id, therapist_id, new_datetime, reason, reschedule_type):
        """Send real-time reschedule notifications"""
        try:
            room_id = f"connection_{min(student_id, therapist_id)}_{max(student_id, therapist_id)}"
            formatted_time = new_datetime.strftime('%A, %B %d at %I:%M %p')
            
            notification_data = {
                'appointment_id': appointment_id,
                'new_datetime': new_datetime.isoformat(),
                'formatted_time': formatted_time,
                'reason': reason,
                'reschedule_type': reschedule_type,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Real-time notifications
            if SOCKETIO_AVAILABLE:
                socketio.emit('appointment_rescheduled', notification_data, room=room_id)
            
            # Database notifications
            notifications = [
                {
                    'user_id': ObjectId(student_id),
                    'type': 'appointment_rescheduled',
                    'message': f'Your appointment has been automatically rescheduled to {formatted_time}. Reason: {reason}',
                    'related_id': ObjectId(appointment_id),
                    'read': False,
                    'created_at': datetime.now(timezone.utc)
                },
                {
                    'user_id': ObjectId(therapist_id),
                    'type': 'appointment_rescheduled',
                    'message': f'Appointment automatically rescheduled to {formatted_time}',
                    'related_id': ObjectId(appointment_id),
                    'read': False,
                    'created_at': datetime.now(timezone.utc)
                }
            ]
            
            mongo.db.notifications.insert_many(notifications)
            
        except Exception as e:
            logger.error(f"Error sending reschedule notifications: {str(e)}")

# ===== INTEGRATION WITH EXISTING ROUTES =====

def enhance_existing_scheduling_routes():
    """
    Enhance your existing scheduling routes with real-time updates
    Call this during app initialization
    """
    
    try:
        # Monkey-patch your existing AppointmentManager to use enhanced version
        import wellbeing.blueprints.dashboard.routes as dashboard_module
        
        # Store original method
        original_create_method = dashboard_module.AppointmentManager.create_appointment_with_zoom
        
        # Enhanced wrapper
        def enhanced_create_appointment_with_zoom(student_id, therapist, appointment_slot, crisis_level='normal'):
            # Call original method
            result = original_create_method(student_id, therapist, appointment_slot, crisis_level)
            
            # Add real-time notifications if successful
            if result[0]:  # appointment_id exists
                try:
                    EnhancedAppointmentManager._send_real_time_appointment_notifications(
                        result[0], result[1], student_id, therapist, 'enhanced_auto', result[2]
                    )
                except Exception as e:
                    logger.error(f"Error adding real-time notifications: {str(e)}")
            
            return result
        
        # Replace the method
        dashboard_module.AppointmentManager.create_appointment_with_zoom = enhanced_create_appointment_with_zoom
        
        logger.info("Enhanced scheduling routes with real-time updates")
        
    except ImportError as e:
        logger.warning(f"Could not enhance existing scheduling routes: {str(e)}")
    except Exception as e:
        logger.error(f"Error enhancing scheduling routes: {str(e)}")

# ===== AUTO-SCHEDULING API ENDPOINTS =====

# Create a blueprint for enhanced scheduling endpoints
enhanced_scheduling_bp = Blueprint('enhanced_scheduling', __name__, url_prefix='/api/enhanced-scheduling')

@enhanced_scheduling_bp.route('/auto-schedule-crisis', methods=['POST'])
def auto_schedule_crisis():
    """API endpoint for crisis-level auto-scheduling"""
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        intake_data = data.get('intake_data', {})
        
        result = CrisisSchedulingManager.handle_crisis_intake_with_immediate_scheduling(
            intake_data, student_id
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Crisis auto-scheduling error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@enhanced_scheduling_bp.route('/auto-reschedule/<appointment_id>', methods=['POST'])
def auto_reschedule_enhanced(appointment_id):
    """Enhanced auto-rescheduling endpoint"""
    try:
        data = request.get_json()
        therapist_id = data.get('therapist_id') or session.get('user')
        reason = data.get('reason', 'Scheduling conflict')
        
        result = EnhancedReschedulingManager.auto_reschedule_with_real_time_updates(
            appointment_id, therapist_id, reason
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Enhanced auto-rescheduling error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@enhanced_scheduling_bp.route('/scheduling-status', methods=['GET'])
def get_scheduling_status():
    """Get current auto-scheduling system status"""
    try:
        # Count recent auto-scheduled appointments
        today = datetime.now().replace(hour=0, minute=0, second=0)
        
        stats = {
            'auto_scheduled_today': mongo.db.appointments.count_documents({
                'auto_scheduled': True,
                'created_at': {'$gte': today}
            }),
            'crisis_scheduled_today': mongo.db.appointments.count_documents({
                'crisis_level': {'$in': ['high', 'critical']},
                'created_at': {'$gte': today}
            }),
            'auto_rescheduled_today': mongo.db.appointments.count_documents({
                'auto_rescheduled': True,
                'rescheduled_at': {'$gte': today}
            }),
            'alternative_suggestions_today': mongo.db.alternative_therapist_options.count_documents({
                'created_at': {'$gte': today}
            }),
            'system_status': 'operational',
            'socketio_available': SOCKETIO_AVAILABLE,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error getting scheduling status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@enhanced_scheduling_bp.route('/test-crisis-alert', methods=['POST'])
def test_crisis_alert():
    """Test endpoint for crisis alert system (development only)"""
    try:
        data = request.get_json()
        therapist_id = data.get('therapist_id')
        
        if not therapist_id:
            return jsonify({'error': 'Therapist ID required'}), 400
        
        # Send test crisis alert
        if SOCKETIO_AVAILABLE:
            socketio.emit('crisis_alert', {
                'student_id': 'test_student',
                'crisis_level': 'high',
                'primary_concern': 'Test Alert',
                'description': 'This is a test crisis alert',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'requires_immediate_attention': True,
                'test': True
            }, room=f"therapist_{therapist_id}")
            
            return jsonify({'success': True, 'message': 'Test crisis alert sent'})
        else:
            return jsonify({'success': False, 'message': 'Socket.IO not available'})
        
    except Exception as e:
        logger.error(f"Error sending test crisis alert: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ===== UTILITY FUNCTIONS =====

def get_enhanced_scheduling_metrics():
    """Get metrics for enhanced scheduling system"""
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0)
        week_ago = today - timedelta(days=7)
        
        metrics = {
            'auto_scheduling': {
                'total_auto_scheduled': mongo.db.appointments.count_documents({'auto_scheduled': True}),
                'auto_scheduled_this_week': mongo.db.appointments.count_documents({
                    'auto_scheduled': True,
                    'created_at': {'$gte': week_ago}
                }),
                'success_rate': 0.0
            },
            'crisis_handling': {
                'total_crisis_appointments': mongo.db.appointments.count_documents({
                    'crisis_level': {'$in': ['high', 'critical']}
                }),
                'crisis_this_week': mongo.db.appointments.count_documents({
                    'crisis_level': {'$in': ['high', 'critical']},
                    'created_at': {'$gte': week_ago}
                }),
                'avg_crisis_response_time': 0.0
            },
            'rescheduling': {
                'total_auto_rescheduled': mongo.db.appointments.count_documents({'auto_rescheduled': True}),
                'auto_rescheduled_this_week': mongo.db.appointments.count_documents({
                    'auto_rescheduled': True,
                    'rescheduled_at': {'$gte': week_ago}
                })
            },
            'alternative_therapists': {
                'total_suggestions': mongo.db.alternative_therapist_options.count_documents({}),
                'suggestions_this_week': mongo.db.alternative_therapist_options.count_documents({
                    'created_at': {'$gte': week_ago}
                })
            },
            'system_health': {
                'socketio_available': SOCKETIO_AVAILABLE,
                'database_responsive': True,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
        }
        
        # Calculate success rate
        total_attempts = mongo.db.appointments.count_documents({'auto_scheduled': True})
        successful = mongo.db.appointments.count_documents({
            'auto_scheduled': True,
            'status': {'$in': ['confirmed', 'completed']}
        })
        
        if total_attempts > 0:
            metrics['auto_scheduling']['success_rate'] = round((successful / total_attempts) * 100, 1)
        
        return metrics
        
    except Exception as e:
        logger.error(f"Error getting enhanced scheduling metrics: {str(e)}")
        return {}

def cleanup_expired_alternative_suggestions():
    """Clean up expired alternative therapist suggestions"""
    try:
        result = mongo.db.alternative_therapist_options.delete_many({
            'expires_at': {'$lt': datetime.now()}
        })
        
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} expired alternative therapist suggestions")
        
        return result.deleted_count
        
    except Exception as e:
        logger.error(f"Error cleaning up alternative suggestions: {str(e)}")
        return 0

# Export the enhanced components
__all__ = [
    'EnhancedAppointmentManager',
    'CrisisSchedulingManager', 
    'EnhancedReschedulingManager',
    'enhance_existing_scheduling_routes',
    'enhanced_scheduling_bp',
    'get_enhanced_scheduling_metrics',
    'cleanup_expired_alternative_suggestions'
]