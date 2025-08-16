"""
Chatbot routes - Claude API implementation.
This file contains all the chatbot-related routes.
"""
import anthropic
from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, jsonify, request, flash, current_app
from wellbeing.models.user import find_user_by_id
from wellbeing.utils.decorators import login_required
from wellbeing.services.chatbot_service import process_message
from wellbeing.models.chat import get_recent_chats
from wellbeing import logger

# Import the blueprint from __init__.py
from . import chatbot_bp


@chatbot_bp.route('/chatbot')
@login_required
def chatbot_page():
    """Render the chatbot interface page."""
    try:
        user_id = session['user']
        
        # Get the user document to access settings
        user = find_user_by_id(user_id)
        
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        # Get user settings with defaults
        settings = user.get('settings', {})
        default_settings = {
            'theme_mode': 'light',
            'contrast': 'normal',
            'text_size': 'md',
            'language': 'en'
        }
        settings = {**default_settings, **settings}
        
        # Get recent chat messages, excluding archived ones
        recent_chats = []
        
        # Convert ObjectIds to strings for template rendering
        for chat in recent_chats:
            if '_id' in chat:
                chat['_id'] = str(chat['_id'])
            if 'user_id' in chat:
                chat['user_id'] = str(chat['user_id'])
        
        logger.info(f"Chatbot page loaded for user {user_id} with {len(recent_chats)} recent messages")
        
        return render_template('chatbot.html', 
                             messages=recent_chats, 
                             user=user, 
                             settings=settings)
                             
    except Exception as e:
        logger.error(f"Error loading chatbot page: {e}")
        flash('Error loading chatbot. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))


@chatbot_bp.route('/model-status')
def model_status():
    """Check if the Claude API is properly configured and accessible."""
    try:
        # Check if Claude API key is configured
        api_key = current_app.config.get('CLAUDE_API_KEY')
        api_key_configured = bool(api_key and api_key.strip() and api_key.startswith('sk-ant-'))
        
        # Test API connectivity
        api_accessible = False
        model_info = {}
        
        if api_key_configured:
            try:
                # Test with a simple API call
                client = anthropic.Anthropic(api_key=api_key)
                
                # Test with a minimal message to verify API access
                test_response = client.messages.create(
                    model=current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307'),
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hello"}]
                )
                api_accessible = True
                
                # Get model info from config
                configured_model = current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307')
                available_models = current_app.config.get('AVAILABLE_CLAUDE_MODELS', {})
                
                model_info = {
                    'configured_model': configured_model,
                    'available_models': list(available_models.keys()),
                    'model_details': available_models.get(configured_model, {}),
                    'max_tokens': current_app.config.get('CLAUDE_MAX_TOKENS', 1000),
                    'temperature': current_app.config.get('CLAUDE_TEMPERATURE', 0.7),
                    'budget_limit': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                    'daily_limit': current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
                }
                
            except anthropic.APIError as api_error:
                logger.error(f"Claude API test failed: {api_error}")
            except Exception as api_error:
                logger.error(f"Claude API test failed: {api_error}")
        
        status_data = {
            'api_key_configured': api_key_configured,
            'api_accessible': api_accessible,
            'model_type': 'CLAUDE_AI',
            'status': 'healthy' if (api_key_configured and api_accessible) else 'unhealthy',
            'model_info': model_info,
            'timestamp': str(current_app.config.get('app_start_time', 'unknown')),
            'cost_tracking': {
                'enabled': True,
                'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                'alert_threshold': current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
            }
        }
        
        logger.info(f"Model status check: {status_data}")
        return jsonify(status_data)
        
    except Exception as e:
        logger.error(f"Model status error: {e}")
        return jsonify({
            'api_key_configured': False,
            'api_accessible': False,
            'model_type': 'CLAUDE_AI',
            'status': 'error',
            'error': str(e),
            'model_info': {}
        }), 500


@chatbot_bp.route('/test-chatbot')
@login_required
def test_chatbot():
    """Test endpoint for the chatbot (for development use)."""
    try:
        user_id = session['user']
        
        # Check if Claude API is configured
        api_key = current_app.config.get('CLAUDE_API_KEY')
        if not api_key:
            return jsonify({
                'error': 'Claude API key not configured',
                'status': 'api_key_missing'
            }), 500
        
        if not api_key.startswith('sk-ant-'):
            return jsonify({
                'error': 'Invalid Claude API key format',
                'status': 'api_key_invalid'
            }), 500
        
        # Test messages to try
        test_messages = [
            "I'm feeling stressed about exams",
            "I can't sleep and feel anxious about my grades",
            "I'm having trouble adjusting to university life",
            "I feel overwhelmed with my coursework"
        ]
        
        # Use the first test message
        test_message = test_messages[0]
        
        # Process the test message
        logger.info(f"Testing chatbot with message: {test_message}")
        response_data = process_message(user_id, test_message)
        
        return jsonify({
            'status': 'success',
            'test_message': test_message,
            'response': response_data.get('response', 'No response generated'),
            'model_used': response_data.get('model', 'unknown'),
            'confidence': response_data.get('confidence', 0),
            'intent': response_data.get('detected_intent', 'unknown'),
            'chat_id': response_data.get('chat_id'),
            'response_time_ms': response_data.get('response_time_ms', 0),
            'tokens_used': response_data.get('tokens_used', 0),
            'estimated_cost': response_data.get('estimated_cost', 0.0),
            'available_test_messages': test_messages
        })
        
    except Exception as e:
        logger.error(f"Test endpoint error: {e}")
        return jsonify({
            'error': f'Test failed: {str(e)}',
            'status': 'test_failed',
            'details': {
                'user_id': session.get('user', 'unknown'),
                'error_type': type(e).__name__
            }
        }), 500


@chatbot_bp.route('/health')
def health_check():
    """Simple health check endpoint for the chatbot service."""
    try:
        # Basic health checks
        checks = {
            'database': False,
            'claude_api': False,
            'dependencies': False,
            'budget_status': False
        }
        
        # Check database connection
        try:
            from wellbeing.extensions import mongo
            mongo.db.command('ping')
            checks['database'] = True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
        
        # Check Claude API
        try:
            api_key = current_app.config.get('CLAUDE_API_KEY')
            if api_key and api_key.startswith('sk-ant-'):
                client = anthropic.Anthropic(api_key=api_key)
                # Quick API test with minimal tokens
                test_response = client.messages.create(
                    model=current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307'),
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Hi"}]
                )
                checks['claude_api'] = True
        except Exception as e:
            logger.error(f"Claude API health check failed: {e}")
        
        # Check key dependencies
        try:
            import anthropic
            import uuid
            checks['dependencies'] = True
        except ImportError as e:
            logger.error(f"Dependencies health check failed: {e}")
        
        # Check budget status
        try:
            monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
            daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
            if monthly_budget > 0 and daily_budget > 0:
                checks['budget_status'] = True
        except Exception as e:
            logger.error(f"Budget status check failed: {e}")
        
        overall_health = all(checks.values())
        
        return jsonify({
            'status': 'healthy' if overall_health else 'degraded',
            'checks': checks,
            'timestamp': str(current_app.config.get('app_start_time', 'unknown')),
            'service': 'chatbot_claude',
            'budget_info': {
                'monthly_limit': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                'daily_limit': current_app.config.get('DAILY_SPENDING_LIMIT', 0.50),
                'alert_threshold': current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
            }
        }), 200 if overall_health else 503
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'service': 'chatbot_claude'
        }), 500


@chatbot_bp.route('/intents')
def get_available_intents():
    """Get list of available intents that the chatbot can classify."""
    try:
        # Enhanced intents for university student mental health
        available_intents = [
            'anxiety', 'depression', 'stress', 'sleep', 
            'relationships', 'academic', 'work', 'coping', 
            'therapy', 'self_esteem', 'eating', 'substance',
            'trauma', 'general_support', 'crisis'
        ]
        
        # Add intent descriptions for better understanding
        intent_descriptions = {
            'anxiety': 'Worry, nervousness, panic attacks',
            'depression': 'Sadness, hopelessness, emptiness',
            'stress': 'Feeling overwhelmed, pressure, burnout',
            'sleep': 'Insomnia, fatigue, sleep problems',
            'relationships': 'Dating, family, friendships, social issues',
            'academic': 'Study stress, exams, grades, assignments',
            'work': 'Job stress, career concerns, workplace issues',
            'coping': 'Managing emotions, coping strategies',
            'therapy': 'Professional help, counseling',
            'self_esteem': 'Confidence, self-worth, body image',
            'eating': 'Food, weight, eating disorders',
            'substance': 'Alcohol, drugs, addiction concerns',
            'trauma': 'PTSD, abuse, traumatic experiences',
            'general_support': 'General emotional support',
            'crisis': 'Suicidal thoughts, self-harm, emergency'
        }
        
        return jsonify({
            'intents': available_intents,
            'intent_descriptions': intent_descriptions,
            'source': 'keyword_classification_enhanced',
            'api_configured': bool(current_app.config.get('CLAUDE_API_KEY')),
            'total_intents': len(available_intents),
            'classification_method': 'keyword_based_with_claude',
            'crisis_detection': current_app.config.get('CRISIS_DETECTION_ENABLED', True)
        })
        
    except Exception as e:
        logger.error(f"Error getting intents: {e}")
        return jsonify({
            'error': str(e),
            'intents': [],
            'source': 'error'
        }), 500


@chatbot_bp.route('/conversation-history')
@login_required
def get_conversation_history():
    """Get conversation history for the current user."""
    try:
        user_id = session['user']
        limit = request.args.get('limit', 50, type=int)
        include_archived = request.args.get('include_archived', False, type=bool)
        
        # Get chat history
        chats = get_recent_chats(user_id, limit=limit, include_archived=include_archived)
        
        # Format response with enhanced data
        conversation_history = []
        total_cost = 0.0
        total_tokens = 0
        
        for chat in chats:
            # Calculate cost if available
            estimated_cost = chat.get('estimated_cost', 0.0)
            tokens_used = chat.get('tokens_used', 0)
            
            chat_item = {
                'id': str(chat.get('_id', '')),
                'message': chat.get('message', ''),
                'response': chat.get('response', ''),
                'timestamp': chat.get('timestamp', ''),
                'confidence': chat.get('confidence', 0),
                'model_used': chat.get('model_used', 'unknown'),
                'topic': chat.get('topic', 'general'),
                'feedback': chat.get('feedback'),
                'tokens_used': tokens_used,
                'estimated_cost': estimated_cost
            }
            conversation_history.append(chat_item)
            total_cost += estimated_cost
            total_tokens += tokens_used
        
        return jsonify({
            'status': 'success',
            'conversation_history': conversation_history,
            'total_messages': len(conversation_history),
            'user_id': str(user_id),
            'usage_summary': {
                'total_tokens': total_tokens,
                'total_estimated_cost': round(total_cost, 6),
                'average_tokens_per_message': round(total_tokens / len(conversation_history), 1) if conversation_history else 0,
                'average_cost_per_message': round(total_cost / len(conversation_history), 6) if conversation_history else 0
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting conversation history: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@chatbot_bp.route('/clear-history', methods=['POST'])
@login_required
def clear_conversation_history():
    """Archive all conversations for the current user."""
    try:
        user_id = session['user']
        
        # Archive all chats for this user
        from wellbeing.models.chat import archive_chats
        archived_count = archive_chats(user_id)
        
        logger.info(f"Archived {archived_count} conversations for user {user_id}")
        
        return jsonify({
            'status': 'success',
            'message': f'Archived {archived_count} conversations',
            'archived_count': archived_count
        })
        
    except Exception as e:
        logger.error(f"Error clearing conversation history: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@chatbot_bp.route('/analytics')
@login_required
def get_chatbot_analytics():
    """Get analytics about the user's chatbot usage."""
    try:
        user_id = session['user']
        days = request.args.get('days', 30, type=int)
        
        # Get chat analytics
        from wellbeing.models.chat import get_chat_analytics
        analytics = get_chat_analytics(user_id, days=days)
        
        # Add additional metrics specific to Claude
        response_data = {
            'status': 'success',
            'period_days': days,
            'user_id': str(user_id),
            'analytics': analytics,
            'insights': {
                'most_common_topic': max(analytics.get('topic_distribution', {}).items(), 
                                       key=lambda x: x[1], default=('general_support', 0))[0],
                'average_confidence': round(analytics.get('avg_confidence', 0), 2),
                'total_interactions': analytics.get('total_messages', 0),
                'crisis_interventions': analytics.get('crisis_count', 0),
                'estimated_total_cost': round(analytics.get('total_cost', 0), 4),
                'total_tokens_used': analytics.get('total_tokens', 0)
            },
            'budget_tracking': {
                'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                'usage_percentage': min(100, (analytics.get('total_cost', 0) / current_app.config.get('MAX_MONTHLY_SPEND', 5.00)) * 100),
                'remaining_budget': max(0, current_app.config.get('MAX_MONTHLY_SPEND', 5.00) - analytics.get('total_cost', 0))
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting chatbot analytics: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


@chatbot_bp.route('/budget-status')
@login_required
def get_budget_status():
    """Get current budget usage and limits."""
    try:
        user_id = session['user']
        
        # Get budget info from config
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        alert_threshold = current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
        
        # Get usage analytics for current month
        from wellbeing.models.chat import get_chat_analytics
        monthly_analytics = get_chat_analytics(user_id, days=30)
        daily_analytics = get_chat_analytics(user_id, days=1)
        
        monthly_spent = monthly_analytics.get('total_cost', 0)
        daily_spent = daily_analytics.get('total_cost', 0)
        
        budget_status = {
            'monthly': {
                'budget': monthly_budget,
                'spent': round(monthly_spent, 4),
                'remaining': round(max(0, monthly_budget - monthly_spent), 4),
                'percentage_used': round((monthly_spent / monthly_budget) * 100, 1) if monthly_budget > 0 else 0,
                'alert_triggered': monthly_spent >= alert_threshold
            },
            'daily': {
                'budget': daily_budget,
                'spent': round(daily_spent, 4),
                'remaining': round(max(0, daily_budget - daily_spent), 4),
                'percentage_used': round((daily_spent / daily_budget) * 100, 1) if daily_budget > 0 else 0
            },
            'status': 'ok' if monthly_spent < alert_threshold else 'warning' if monthly_spent < monthly_budget else 'limit_reached'
        }
        
        return jsonify({
            'status': 'success',
            'budget_status': budget_status,
            'user_id': str(user_id)
        })
        
    except Exception as e:
        logger.error(f"Error getting budget status: {e}")
        return jsonify({
            'error': str(e),
            'status': 'failed'
        }), 500


# Error handlers specific to chatbot blueprint
@chatbot_bp.errorhandler(404)
def chatbot_not_found(error):
    """Handle 404 errors in chatbot routes."""
    return jsonify({
        'error': 'Chatbot endpoint not found',
        'status': 404
    }), 404


@chatbot_bp.errorhandler(500)
def chatbot_internal_error(error):
    """Handle 500 errors in chatbot routes."""
    logger.error(f"Chatbot internal error: {error}")
    return jsonify({
        'error': 'Internal chatbot error',
        'status': 500
    }), 500


# Route for development/debugging
@chatbot_bp.route('/debug')
def debug_info():
    """Get debug information about the chatbot system (development only)."""
    if not current_app.debug:
        return jsonify({'error': 'Debug mode not enabled'}), 403
    
    try:
        api_key = current_app.config.get('CLAUDE_API_KEY')
        
        debug_data = {
            'flask_debug': current_app.debug,
            'claude_status': {
                'api_key_configured': bool(api_key and api_key.strip()),
                'api_key_format_valid': bool(api_key and api_key.startswith('sk-ant-')),
                'api_key_length': len(api_key) if api_key else 0,
                'configured_model': current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307'),
                'max_tokens': current_app.config.get('CLAUDE_MAX_TOKENS', 1000),
                'temperature': current_app.config.get('CLAUDE_TEMPERATURE', 0.7),
                'available_models': list(current_app.config.get('AVAILABLE_CLAUDE_MODELS', {}).keys())
            },
            'budget_config': {
                'monthly_budget': current_app.config.get('MAX_MONTHLY_SPEND', 5.00),
                'daily_budget': current_app.config.get('DAILY_SPENDING_LIMIT', 0.50),
                'alert_threshold': current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
            },
            'crisis_detection': {
                'enabled': current_app.config.get('CRISIS_DETECTION_ENABLED', True),
                'keywords_count': len(current_app.config.get('CRISIS_KEYWORDS', []))
            },
            'session_info': {
                'has_user': 'user' in session,
                'user_id': session.get('user', 'Not logged in')
            },
            'database_status': 'Connected',  # Simplified check
            'routes': [rule.rule for rule in current_app.url_map.iter_rules() 
                      if rule.rule.startswith('/chatbot')],
            'environment': {
                'python_path': current_app.instance_path,
                'config_keys': [key for key in current_app.config.keys() if 'CLAUDE' in key]
            }
        }
        
        return jsonify(debug_data)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'debug_failed': True
        }), 500