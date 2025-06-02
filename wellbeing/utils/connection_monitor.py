# wellbeing/utils/connection_monitor.py
# Connection monitoring and analytics utilities

from datetime import datetime, timedelta, timezone
from wellbeing import mongo, logger
from typing import Dict, List, Optional
from bson.objectid import ObjectId
import json

class ConnectionMonitor:
    """Monitor and analyze student-therapist connections"""
    
    @staticmethod
    def log_connection_event(student_id: str, therapist_id: str, action: str, 
                           user_role: str, details: dict = None, request=None):
        """Log connection events for analysis"""
        try:
            log_entry = {
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'action': action,
                'user_role': user_role,
                'timestamp': datetime.now(timezone.utc),
                'details': details or {},
                'ip_address': request.remote_addr if request else 'unknown',
                'user_agent': request.headers.get('User-Agent', 'unknown') if request else 'unknown'
            }
            
            mongo.db.connection_logs.insert_one(log_entry)
            
        except Exception as e:
            logger.error(f"Failed to log connection event: {str(e)}")
    
    @staticmethod
    def get_connection_analytics(student_id: str = None, therapist_id: str = None, 
                               days: int = 7) -> Dict:
        """Get analytics for connections"""
        try:
            match_filter = {
                'timestamp': {'$gte': datetime.now() - timedelta(days=days)}
            }
            
            if student_id:
                match_filter['student_id'] = ObjectId(student_id)
            if therapist_id:
                match_filter['therapist_id'] = ObjectId(therapist_id)
            
            pipeline = [
                {'$match': match_filter},
                {'$group': {
                    '_id': '$action',
                    'count': {'$sum': 1},
                    'last_occurrence': {'$max': '$timestamp'}
                }},
                {'$sort': {'count': -1}}
            ]
            
            results = list(mongo.db.connection_logs.aggregate(pipeline))
            
            # Get total message count
            message_count = mongo.db.therapist_chats.count_documents({
                **({'student_id': ObjectId(student_id)} if student_id else {}),
                **({'therapist_id': ObjectId(therapist_id)} if therapist_id else {}),
                'timestamp': {'$gte': datetime.now() - timedelta(days=days)}
            })
            
            return {
                'period_days': days,
                'action_breakdown': results,
                'total_messages': message_count,
                'total_events': sum(r['count'] for r in results)
            }
            
        except Exception as e:
            logger.error(f"Failed to get connection analytics: {str(e)}")
            return {}
    
    @staticmethod
    def check_connection_health() -> List[Dict]:
        """Check health of all active connections"""
        try:
            # Get all active assignments
            assignments = list(mongo.db.therapist_assignments.find({'status': 'active'}))
            
            health_reports = []
            
            for assignment in assignments:
                student_id = assignment['student_id']
                therapist_id = assignment['therapist_id']
                
                # Check last interaction
                last_message = mongo.db.therapist_chats.find_one({
                    'student_id': student_id,
                    'therapist_id': therapist_id
                }, sort=[('timestamp', -1)])
                
                # Check upcoming appointments
                upcoming_appointments = mongo.db.appointments.count_documents({
                    'student_id': student_id,
                    'therapist_id': therapist_id,
                    'datetime': {'$gte': datetime.now()},
                    'status': 'confirmed'
                })
                
                days_since_last_message = None
                if last_message:
                    days_since_last_message = (datetime.now() - last_message['timestamp']).days
                
                # Determine health status
                health_status = 'healthy'
                alerts = []
                
                if days_since_last_message is None:
                    health_status = 'critical'
                    alerts.append('No messages exchanged')
                elif days_since_last_message > 14:
                    health_status = 'warning'
                    alerts.append(f'No communication for {days_since_last_message} days')
                
                if upcoming_appointments == 0:
                    if health_status == 'healthy':
                        health_status = 'warning'
                    alerts.append('No upcoming appointments scheduled')
                
                health_reports.append({
                    'student_id': str(student_id),
                    'therapist_id': str(therapist_id),
                    'health_status': health_status,
                    'days_since_last_message': days_since_last_message,
                    'upcoming_appointments': upcoming_appointments,
                    'alerts': alerts,
                    'assignment_date': assignment.get('created_at')
                })
            
            return health_reports
            
        except Exception as e:
            logger.error(f"Failed to check connection health: {str(e)}")
            return []
    
    @staticmethod
    def get_connection_metrics(student_id: str, therapist_id: str) -> Dict:
        """Get detailed metrics for a specific connection"""
        try:
            # Message metrics
            message_stats = ConnectionMonitor._get_message_metrics(student_id, therapist_id)
            
            # Appointment metrics
            appointment_stats = ConnectionMonitor._get_appointment_metrics(student_id, therapist_id)
            
            # Response time metrics
            response_stats = ConnectionMonitor._get_response_time_metrics(student_id, therapist_id)
            
            # Engagement metrics
            engagement_stats = ConnectionMonitor._get_engagement_metrics(student_id, therapist_id)
            
            return {
                'connection_id': f"{student_id}_{therapist_id}",
                'student_id': student_id,
                'therapist_id': therapist_id,
                'messages': message_stats,
                'appointments': appointment_stats,
                'response_times': response_stats,
                'engagement': engagement_stats,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting connection metrics: {str(e)}")
            return {}
    
    @staticmethod
    def _get_message_metrics(student_id: str, therapist_id: str) -> Dict:
        """Get message-related metrics"""
        try:
            base_query = {
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            }
            
            # Total messages
            total_messages = mongo.db.therapist_chats.count_documents(base_query)
            
            # Messages by sender
            student_messages = mongo.db.therapist_chats.count_documents({
                **base_query,
                'sender': 'student'
            })
            
            therapist_messages = mongo.db.therapist_chats.count_documents({
                **base_query,
                'sender': 'therapist'
            })
            
            # Recent activity (last 7 days)
            recent_query = {
                **base_query,
                'timestamp': {'$gte': datetime.now() - timedelta(days=7)}
            }
            recent_messages = mongo.db.therapist_chats.count_documents(recent_query)
            
            # Average messages per day (last 30 days)
            monthly_query = {
                **base_query,
                'timestamp': {'$gte': datetime.now() - timedelta(days=30)}
            }
            monthly_messages = mongo.db.therapist_chats.count_documents(monthly_query)
            avg_daily_messages = monthly_messages / 30
            
            return {
                'total_messages': total_messages,
                'student_messages': student_messages,
                'therapist_messages': therapist_messages,
                'recent_messages_7d': recent_messages,
                'avg_daily_messages_30d': round(avg_daily_messages, 2),
                'message_balance_ratio': round(student_messages / max(therapist_messages, 1), 2)
            }
            
        except Exception as e:
            logger.error(f"Error getting message metrics: {str(e)}")
            return {}
    
    @staticmethod
    def _get_appointment_metrics(student_id: str, therapist_id: str) -> Dict:
        """Get appointment-related metrics"""
        try:
            base_query = {
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            }
            
            # Total appointments
            total_appointments = mongo.db.appointments.count_documents(base_query)
            
            # Completed appointments
            completed = mongo.db.appointments.count_documents({
                **base_query,
                'status': 'completed'
            })
            
            # Cancelled appointments
            cancelled = mongo.db.appointments.count_documents({
                **base_query,
                'status': 'cancelled'
            })
            
            # Upcoming appointments
            upcoming = mongo.db.appointments.count_documents({
                **base_query,
                'datetime': {'$gte': datetime.now()},
                'status': 'confirmed'
            })
            
            # Auto-scheduled appointments
            auto_scheduled = mongo.db.appointments.count_documents({
                **base_query,
                'auto_scheduled': True
            })
            
            # Calculate completion rate
            completion_rate = (completed / max(total_appointments, 1)) * 100
            
            # Calculate cancellation rate
            cancellation_rate = (cancelled / max(total_appointments, 1)) * 100
            
            return {
                'total_appointments': total_appointments,
                'completed_appointments': completed,
                'cancelled_appointments': cancelled,
                'upcoming_appointments': upcoming,
                'auto_scheduled_appointments': auto_scheduled,
                'completion_rate': round(completion_rate, 1),
                'cancellation_rate': round(cancellation_rate, 1)
            }
            
        except Exception as e:
            logger.error(f"Error getting appointment metrics: {str(e)}")
            return {}
    
    @staticmethod
    def _get_response_time_metrics(student_id: str, therapist_id: str) -> Dict:
        """Get response time metrics"""
        try:
            # Get all messages ordered by timestamp
            messages = list(mongo.db.therapist_chats.find({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            }).sort('timestamp', 1))
            
            if len(messages) < 2:
                return {
                    'avg_therapist_response_minutes': 0,
                    'avg_student_response_minutes': 0,
                    'fastest_response_minutes': 0,
                    'slowest_response_minutes': 0
                }
            
            therapist_response_times = []
            student_response_times = []
            all_response_times = []
            
            for i in range(1, len(messages)):
                current_msg = messages[i]
                prev_msg = messages[i-1]
                
                # Skip if same sender (not a response)
                if current_msg['sender'] == prev_msg['sender']:
                    continue
                
                response_time = (current_msg['timestamp'] - prev_msg['timestamp']).total_seconds() / 60
                
                # Only consider responses within 7 days (ignore very delayed responses)
                if response_time <= 10080:  # 7 days in minutes
                    all_response_times.append(response_time)
                    
                    if current_msg['sender'] == 'therapist':
                        therapist_response_times.append(response_time)
                    else:
                        student_response_times.append(response_time)
            
            def safe_avg(times):
                return round(sum(times) / len(times), 1) if times else 0
            
            return {
                'avg_therapist_response_minutes': safe_avg(therapist_response_times),
                'avg_student_response_minutes': safe_avg(student_response_times),
                'fastest_response_minutes': round(min(all_response_times), 1) if all_response_times else 0,
                'slowest_response_minutes': round(max(all_response_times), 1) if all_response_times else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting response time metrics: {str(e)}")
            return {}
    
    @staticmethod
    def _get_engagement_metrics(student_id: str, therapist_id: str) -> Dict:
        """Get engagement metrics"""
        try:
            # Get assignment date
            assignment = mongo.db.therapist_assignments.find_one({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id),
                'status': 'active'
            })
            
            assignment_date = assignment.get('created_at') if assignment else datetime.now()
            days_connected = (datetime.now() - assignment_date).days
            
            # Shared resources
            shared_resources = mongo.db.shared_resources.count_documents({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            })
            
            # Active days (days with at least one message)
            pipeline = [
                {
                    '$match': {
                        'student_id': ObjectId(student_id),
                        'therapist_id': ObjectId(therapist_id)
                    }
                },
                {
                    '$group': {
                        '_id': {
                            'year': {'$year': '$timestamp'},
                            'month': {'$month': '$timestamp'},
                            'day': {'$dayOfMonth': '$timestamp'}
                        }
                    }
                },
                {
                    '$count': 'active_days'
                }
            ]
            
            result = list(mongo.db.therapist_chats.aggregate(pipeline))
            active_days = result[0]['active_days'] if result else 0
            
            # Engagement score (0-100)
            engagement_score = min(100, (
                (active_days / max(days_connected, 1)) * 40 +  # 40% weight for active days
                (min(shared_resources, 10) / 10) * 20 +        # 20% weight for resource sharing
                (min(mongo.db.appointments.count_documents({   # 40% weight for appointment attendance
                    'student_id': ObjectId(student_id),
                    'therapist_id': ObjectId(therapist_id),
                    'status': 'completed'
                }), 10) / 10) * 40
            ))
            
            return {
                'days_connected': days_connected,
                'active_communication_days': active_days,
                'shared_resources_count': shared_resources,
                'engagement_score': round(engagement_score, 1),
                'engagement_level': (
                    'high' if engagement_score >= 70 else
                    'medium' if engagement_score >= 40 else
                    'low'
                )
            }
            
        except Exception as e:
            logger.error(f"Error getting engagement metrics: {str(e)}")
            return {}
    
    @staticmethod
    def generate_connection_report(student_id: str, therapist_id: str) -> Dict:
        """Generate a comprehensive connection report"""
        try:
            # Get basic info
            student = mongo.db.users.find_one({'_id': ObjectId(student_id)})
            therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
            assignment = mongo.db.therapist_assignments.find_one({
                'student_id': ObjectId(student_id),
                'therapist_id': ObjectId(therapist_id)
            })
            
            # Get comprehensive metrics
            metrics = ConnectionMonitor.get_connection_metrics(student_id, therapist_id)
            
            # Get health status
            health_reports = ConnectionMonitor.check_connection_health()
            connection_health = next(
                (report for report in health_reports 
                 if report['student_id'] == student_id and report['therapist_id'] == therapist_id),
                None
            )
            
            # Generate recommendations
            recommendations = ConnectionMonitor._generate_recommendations(metrics, connection_health)
            
            report = {
                'report_id': f"connection_report_{student_id}_{therapist_id}_{datetime.now().strftime('%Y%m%d')}",
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'connection_info': {
                    'student': {
                        'id': student_id,
                        'name': f"{student.get('first_name', '')} {student.get('last_name', '')}".strip() if student else 'Unknown',
                        'email': student.get('email', '') if student else ''
                    },
                    'therapist': {
                        'id': therapist_id,
                        'name': therapist.get('name', 'Unknown') if therapist else 'Unknown',
                        'license_number': therapist.get('license_number', '') if therapist else '',
                        'specializations': therapist.get('specializations', []) if therapist else []
                    },
                    'assignment_date': assignment.get('created_at').isoformat() if assignment and assignment.get('created_at') else None,
                    'auto_assigned': assignment.get('auto_assigned', False) if assignment else False
                },
                'metrics': metrics,
                'health_status': connection_health,
                'recommendations': recommendations,
                'summary': {
                    'overall_health': connection_health.get('health_status', 'unknown') if connection_health else 'unknown',
                    'engagement_level': metrics.get('engagement', {}).get('engagement_level', 'unknown'),
                    'communication_frequency': 'high' if metrics.get('messages', {}).get('recent_messages_7d', 0) > 10 else 'low',
                    'appointment_attendance': 'good' if metrics.get('appointments', {}).get('completion_rate', 0) > 80 else 'needs_improvement'
                }
            }
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating connection report: {str(e)}")
            return {}
    
    @staticmethod
    def _generate_recommendations(metrics: Dict, health_status: Dict) -> List[Dict]:
        """Generate actionable recommendations based on metrics"""
        recommendations = []
        
        try:
            # Message-based recommendations
            messages = metrics.get('messages', {})
            if messages.get('recent_messages_7d', 0) < 3:
                recommendations.append({
                    'type': 'communication',
                    'priority': 'high',
                    'title': 'Increase Communication Frequency',
                    'description': 'Consider reaching out more frequently to maintain therapeutic momentum.',
                    'suggested_actions': [
                        'Send daily check-in messages',
                        'Share relevant resources',
                        'Schedule regular virtual coffee chats'
                    ]
                })
            
            # Appointment-based recommendations
            appointments = metrics.get('appointments', {})
            if appointments.get('cancellation_rate', 0) > 20:
                recommendations.append({
                    'type': 'appointments',
                    'priority': 'medium',
                    'title': 'Reduce Appointment Cancellations',
                    'description': 'High cancellation rate may indicate scheduling or engagement issues.',
                    'suggested_actions': [
                        'Review appointment timing preferences',
                        'Implement reminder system',
                        'Discuss barriers to attendance'
                    ]
                })
            
            # Engagement-based recommendations
            engagement = metrics.get('engagement', {})
            if engagement.get('engagement_score', 0) < 50:
                recommendations.append({
                    'type': 'engagement',
                    'priority': 'high',
                    'title': 'Improve Student Engagement',
                    'description': 'Low engagement score suggests need for more interactive approach.',
                    'suggested_actions': [
                        'Share more multimedia resources',
                        'Implement gamification elements',
                        'Schedule more frequent but shorter sessions'
                    ]
                })
            
            # Response time recommendations
            response_times = metrics.get('response_times', {})
            if response_times.get('avg_therapist_response_minutes', 0) > 1440:  # 24 hours
                recommendations.append({
                    'type': 'responsiveness',
                    'priority': 'medium',
                    'title': 'Improve Response Time',
                    'description': 'Faster responses can improve therapeutic relationship.',
                    'suggested_actions': [
                        'Set specific times for checking messages',
                        'Use auto-responders for acknowledgment',
                        'Prioritize urgent messages'
                    ]
                })
            
            # Health-based recommendations
            if health_status and health_status.get('health_status') == 'critical':
                recommendations.append({
                    'type': 'health',
                    'priority': 'critical',
                    'title': 'Address Connection Health Issues',
                    'description': 'Connection shows signs of deterioration requiring immediate attention.',
                    'suggested_actions': [
                        'Schedule emergency check-in session',
                        'Review treatment plan',
                        'Consider referral or additional support'
                    ]
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}")
            return []