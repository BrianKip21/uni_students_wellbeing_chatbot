
import datetime
from wellbeing import mongo, logger
from bson.objectid import ObjectId
from flask import request, session, redirect, url_for, flash, render_template, jsonify
from wellbeing.utils.decorators import login_required

def setup_automated_moderation():
    """One-time setup for automated moderation system"""
    
    try:
        # Create indexes for performance
        print("Creating database indexes...")
        
        # Message moderation indexes
        mongo.db.therapist_chats.create_index([
            ('automated_moderation', 1),
            ('timestamp', -1)
        ])
        
        mongo.db.therapist_chats.create_index([
            ('moderation_flags', 1),
            ('timestamp', -1)
        ])
        
        mongo.db.therapist_chats.create_index([
            ('message_hash', 1),
            ('timestamp', -1)
        ])
        
        # Crisis alert indexes
        mongo.db.crisis_alerts.create_index([
            ('status', 1),
            ('created_at', -1)
        ])
        
        mongo.db.crisis_alerts.create_index([
            ('therapist_id', 1),
            ('status', 1)
        ])
        
        # Moderation log indexes
        mongo.db.automated_moderation_log.create_index([
            ('sender_id', 1),
            ('timestamp', -1)
        ])
        
        mongo.db.automated_moderation_log.create_index([
            ('action_taken', 1),
            ('timestamp', -1)
        ])
        
        # Create default moderation settings
        default_settings = {
            'enabled': True,
            'rate_limits': {
                'student': {'per_minute': 3, 'per_hour': 20, 'per_day': 100},
                'therapist': {'per_minute': 5, 'per_hour': 50, 'per_day': 200}
            },
            'content_filtering': {
                'profanity_filter': True,
                'crisis_detection': True,
                'boundary_checking': True,
                'spam_detection': True,
                'max_message_length': 2000
            },
            'auto_escalation': {
                'crisis_alerts': True,
                'emergency_scheduling': True,
                'supervisor_notifications': True
            },
            'business_hours': {
                'start_hour': 8,
                'end_hour': 20,
                'working_days': [0, 1, 2, 3, 4]  # Monday-Friday
            },
            'created_at': datetime.datetime.now()
        }
        
        mongo.db.automated_moderation_settings.update_one(
            {},
            {'$setOnInsert': default_settings},
            upsert=True
        )
        
        print("✅ Automated moderation setup complete!")
        print("📊 Default settings created")
        print("🔍 Database indexes created")
        print("🚨 Crisis detection enabled")
        print("🛡️ Content filtering active")
        
        return True
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        logger.error(f"Moderation setup failed: {e}")
        return False

class ModerationConfig:
    """Dynamic configuration management for automated moderation"""
    
    @staticmethod
    def get_settings():
        """Get current moderation settings"""
        settings = mongo.db.automated_moderation_settings.find_one()
        if not settings:
            return ModerationConfig.get_default_settings()
        return settings
    
    @staticmethod
    def get_default_settings():
        """Default moderation settings"""
        return {
            'enabled': True,
            'rate_limits': {
                'student': {'per_minute': 3, 'per_hour': 20, 'per_day': 100},
                'therapist': {'per_minute': 5, 'per_hour': 50, 'per_day': 200}
            },
            'content_filtering': {
                'profanity_filter': True,
                'crisis_detection': True,
                'boundary_checking': True,
                'spam_detection': True,
                'max_message_length': 2000
            },
            'auto_escalation': {
                'crisis_alerts': True,
                'emergency_scheduling': True,
                'supervisor_notifications': True
            },
            'business_hours': {
                'start_hour': 8,
                'end_hour': 20,
                'working_days': [0, 1, 2, 3, 4]
            }
        }
    
    @staticmethod
    def update_settings(new_settings):
        """Update moderation settings"""
        new_settings['updated_at'] = datetime.datetime.now()
        
        result = mongo.db.automated_moderation_settings.update_one(
            {},
            {'$set': new_settings},
            upsert=True
        )
        
        return result.modified_count > 0 or result.upserted_id is not None

def test_automated_moderation():
    """Test automated moderation system"""
    try:
        from wellbeing.utils.automated_moderation import AutomatedModerator
        
        # Create valid test ObjectIds
        test_user_id = str(ObjectId())
        test_therapist_id = str(ObjectId())
        
        # Test basic moderation
        test_messages = [
            ("Hello, how are you?", "allow"),
            ("I want to kill myself", "escalate"),
            ("What's your phone number?", "filter"),
            ("HELP ME PLEASE!!!!!!", "allow"),  # Should be flagged but allowed
        ]
        
        for message, expected in test_messages:
            result = AutomatedModerator.moderate_message(
                message, 'student', test_user_id, test_therapist_id
            )
            
            if expected == "escalate" and result['escalation_level'] == 'none':
                return False
            elif expected == "filter" and result['action'] != 'filter':
                return False
            elif expected == "allow" and result['action'] not in ['allow', 'filter']:
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Automated moderation test failed: {e}")
        return False

def initialize_automated_moderation(app):
    """Initialize automated moderation system with your Flask app"""
    
    with app.app_context():
        # Setup database
        if setup_automated_moderation():
            print("✅ Automated moderation initialized successfully")
            
            # Test the system
            test_result = test_automated_moderation()
            if test_result:
                print("✅ Automated moderation test passed")
            else:
                print("⚠️ Automated moderation test failed - please check configuration")
        else:
            print("❌ Failed to initialize automated moderation")

# Background maintenance functions
def cleanup_old_moderation_data():
    """Clean up old moderation data"""
    try:
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=30)
        
        # Clean moderation logs
        deleted_logs = mongo.db.automated_moderation_log.delete_many({
            'timestamp': {'$lt': cutoff_date}
        })
        
        # Clean resolved crisis alerts
        resolved_cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
        deleted_alerts = mongo.db.crisis_alerts.delete_many({
            'status': 'resolved',
            'resolved_at': {'$lt': resolved_cutoff}
        })
        
        logger.info(f"Cleaned {deleted_logs.deleted_count} moderation logs, {deleted_alerts.deleted_count} crisis alerts")
        
    except Exception as e:
        logger.error(f"Error during moderation cleanup: {e}")

def generate_daily_moderation_report():
    """Generate and store daily moderation report"""
    try:
        from wellbeing.utils.automated_moderation import generate_automated_moderation_report
        
        report = generate_automated_moderation_report(24)
        if report:
            # Store report in database
            report['report_type'] = 'daily_automated'
            report['generated_at'] = datetime.datetime.now()
            
            mongo.db.moderation_reports.insert_one(report)
            
            # Send to supervisors if needed
            if report.get('crisis_alerts', 0) > 10:  # High crisis activity
                supervisors = mongo.db.users.find({'role': 'supervisor'})
                for supervisor in supervisors:
                    mongo.db.notifications.insert_one({
                        'user_id': supervisor['_id'],
                        'type': 'high_crisis_activity',
                        'message': f'High crisis activity detected: {report["crisis_alerts"]} alerts in 24h',
                        'read': False,
                        'created_at': datetime.datetime.now()
                    })
        
    except Exception as e:
        logger.error(f"Error generating daily moderation report: {e}")

def check_unresolved_crisis_alerts():
    """Check for crisis alerts that need attention"""
    try:
        # Find alerts older than 1 hour without response
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=1)
        
        unresolved_alerts = mongo.db.crisis_alerts.find({
            'status': 'auto_escalated',
            'created_at': {'$lt': cutoff_time}
        })
        
        for alert in unresolved_alerts:
            # Escalate to supervisor
            supervisors = mongo.db.users.find({'role': 'supervisor'})
            for supervisor in supervisors:
                mongo.db.notifications.insert_one({
                    'user_id': supervisor['_id'],
                    'type': 'unresolved_crisis_alert',
                    'message': f'Crisis alert has been unresolved for over 1 hour. Immediate intervention required.',
                    'priority': 'critical',
                    'related_id': alert['_id'],
                    'read': False,
                    'created_at': datetime.datetime.now()
                })
            
            # Update alert status
            mongo.db.crisis_alerts.update_one(
                {'_id': alert['_id']},
                {'$set': {'status': 'escalated_to_supervisor', 'escalated_at': datetime.datetime.now()}}
            )
        
    except Exception as e:
        logger.error(f"Error checking unresolved crisis alerts: {e}")

# Routes for configuration and monitoring
def add_moderation_routes(app):
    """Add moderation configuration routes to your app"""
    
    @app.route('/api/moderation-status')
    @login_required
    def get_moderation_status():
        """Get real-time moderation status for user"""
        from wellbeing.utils.automated_moderation import AutomatedModerator
        from datetime import timedelta
        
        user_id = str(session['user'])
        user_type = 'student' if session.get('role') == 'student' else 'therapist'
        
        try:
            # Check if user can send messages right now
            can_send = AutomatedModerator._check_rate_limits(user_id, user_type)
            
            # Get recent moderation actions for this user
            recent_actions = list(mongo.db.automated_moderation_log.find({
                'sender_id': ObjectId(user_id),
                'timestamp': {'$gte': datetime.datetime.now() - timedelta(hours=1)}
            }).sort('timestamp', -1).limit(5))
            
            # Count messages in last hour
            hour_ago = datetime.datetime.now() - timedelta(hours=1)
            recent_message_count = mongo.db.therapist_chats.count_documents({
                f'{user_type}_id': ObjectId(user_id),
                'timestamp': {'$gte': hour_ago}
            })
            
            # Check for any active crisis alerts
            active_crisis = mongo.db.crisis_alerts.find_one({
                'student_id': ObjectId(user_id) if user_type == 'student' else None,
                'therapist_id': ObjectId(user_id) if user_type == 'therapist' else None,
                'status': {'$in': ['auto_escalated', 'pending_review']},
                'created_at': {'$gte': datetime.datetime.now() - timedelta(hours=24)}
            })
            
            status = {
                'can_send_message': can_send,
                'rate_limit_status': 'ok' if can_send else 'limited',
                'messages_sent_last_hour': recent_message_count,
                'recent_flags': [action.get('flags', []) for action in recent_actions],
                'has_active_crisis_alert': bool(active_crisis),
                'business_hours': AutomatedModerator._is_business_hours(),
                'system_status': 'automated_moderation_active'
            }
            
            return jsonify(status)
            
        except Exception as e:
            logger.error(f"Error getting moderation status: {e}")
            return jsonify({
                'can_send_message': True,  # Fail open
                'rate_limit_status': 'unknown',
                'system_status': 'error'
            })
    
    @app.route('/api/moderation-health')
    @login_required  
    def moderation_health_check():
        """Health check for automated moderation system"""
        try:
            # Check if moderation is enabled
            settings = ModerationConfig.get_settings()
            
            # Check recent activity
            recent_activity = mongo.db.automated_moderation_log.count_documents({
                'timestamp': {'$gte': datetime.datetime.now() - datetime.timedelta(hours=1)}
            })
            
            # Check for errors
            error_count = mongo.db.automated_moderation_log.count_documents({
                'timestamp': {'$gte': datetime.datetime.now() - datetime.timedelta(hours=24)},
                'action_taken': 'error'
            })
            
            health_status = {
                'status': 'healthy' if error_count < 10 else 'degraded',
                'moderation_enabled': settings.get('enabled', False),
                'recent_activity': recent_activity,
                'error_count_24h': error_count,
                'last_check': datetime.datetime.now().isoformat()
            }
            
            return jsonify(health_status)
            
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': str(e),
                'last_check': datetime.datetime.now().isoformat()
            })