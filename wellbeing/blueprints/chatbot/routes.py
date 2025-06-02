"""
Chatbot routes - BERT only implementation.
This file contains all the chatbot-related routes.
"""
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
        recent_chats = get_recent_chats(user_id, limit=20)
        
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
    """Check if the BERT model is properly loaded."""
    try:
        # Get BERT model from app context
        bert_model = getattr(current_app, 'bert_model', None)
        
        # Check if model exists and is loaded
        model_exists = bert_model is not None
        model_loaded = False
        model_info = {}
        
        if bert_model:
            model_loaded = hasattr(bert_model, 'is_loaded') and bert_model.is_loaded
            
            # Get additional model info if available
            if hasattr(bert_model, 'get_model_info'):
                try:
                    model_info = bert_model.get_model_info()
                except:
                    model_info = {}
        
        status_data = {
            'bert_model_exists': model_exists,
            'bert_model_loaded': model_loaded,
            'model_type': 'BERT_ONLY',
            'status': 'healthy' if model_loaded else 'unhealthy',
            'model_info': model_info,
            'timestamp': str(current_app.config.get('app_start_time', 'unknown'))
        }
        
        logger.info(f"Model status check: {status_data}")
        return jsonify(status_data)
        
    except Exception as e:
        logger.error(f"Model status error: {e}")
        return jsonify({
            'bert_model_exists': False,
            'bert_model_loaded': False,
            'model_type': 'BERT_ONLY',
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
        
        # Check if BERT model is loaded
        bert_model = getattr(current_app, 'bert_model', None)
        
        if not bert_model:
            return jsonify({
                'error': 'BERT model not initialized',
                'status': 'model_not_found'
            }), 500
        
        if not hasattr(bert_model, 'is_loaded') or not bert_model.is_loaded:
            return jsonify({
                'error': 'BERT model not loaded properly',
                'status': 'model_not_loaded'
            }), 500
        
        # Test messages to try
        test_messages = [
            "I'm feeling stressed about work",
            "I can't sleep and feel anxious",
            "I'm having a hard time lately"
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
            'bert_model': False,
            'dependencies': False
        }
        
        # Check database connection
        try:
            from wellbeing.extensions import mongo
            mongo.db.command('ping')
            checks['database'] = True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
        
        # Check BERT model
        try:
            bert_model = getattr(current_app, 'bert_model', None)
            if bert_model and hasattr(bert_model, 'is_loaded'):
                checks['bert_model'] = bert_model.is_loaded
        except Exception as e:
            logger.error(f"BERT model health check failed: {e}")
        
        # Check key dependencies
        try:
            import torch
            import transformers
            checks['dependencies'] = True
        except ImportError as e:
            logger.error(f"Dependencies health check failed: {e}")
        
        overall_health = all(checks.values())
        
        return jsonify({
            'status': 'healthy' if overall_health else 'degraded',
            'checks': checks,
            'timestamp': str(current_app.config.get('app_start_time', 'unknown')),
            'service': 'chatbot'
        }), 200 if overall_health else 503
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'service': 'chatbot'
        }), 500


@chatbot_bp.route('/intents')
def get_available_intents():
    """Get list of available intents that the model can classify."""
    try:
        bert_model = getattr(current_app, 'bert_model', None)
        
        if not bert_model or not bert_model.is_loaded:
            # Return default intents if model not loaded
            default_intents = [
                'anxiety', 'depression', 'stress', 'sleep', 
                'general_support', 'crisis', 'coping', 'therapy'
            ]
            return jsonify({
                'intents': default_intents,
                'source': 'default',
                'model_loaded': False
            })
        
        # Get intents from trained model if available
        intents = []
        if hasattr(bert_model, 'intent_to_id'):
            intents = list(bert_model.intent_to_id.keys())
        elif hasattr(bert_model, 'get_model_info'):
            model_info = bert_model.get_model_info()
            intents = model_info.get('intents', [])
        
        return jsonify({
            'intents': intents,
            'source': 'trained_model',
            'model_loaded': True,
            'total_intents': len(intents)
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
        
        # Format response
        conversation_history = []
        for chat in chats:
            chat_item = {
                'id': str(chat.get('_id', '')),
                'message': chat.get('message', ''),
                'response': chat.get('response', ''),
                'timestamp': chat.get('timestamp', ''),
                'confidence': chat.get('confidence', 0),
                'model_used': chat.get('model_used', 'unknown'),
                'topic': chat.get('topic', 'general'),
                'feedback': chat.get('feedback')
            }
            conversation_history.append(chat_item)
        
        return jsonify({
            'status': 'success',
            'conversation_history': conversation_history,
            'total_messages': len(conversation_history),
            'user_id': str(user_id)
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
        
        # Add additional metrics
        response_data = {
            'status': 'success',
            'period_days': days,
            'user_id': str(user_id),
            'analytics': analytics,
            'insights': {
                'most_common_topic': max(analytics.get('topic_distribution', {}).items(), 
                                       key=lambda x: x[1], default=('general_support', 0))[0],
                'average_confidence': round(analytics.get('avg_confidence', 0), 2),
                'total_interactions': analytics.get('total_messages', 0)
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting chatbot analytics: {e}")
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
        bert_model = getattr(current_app, 'bert_model', None)
        
        debug_data = {
            'flask_debug': current_app.debug,
            'model_status': {
                'exists': bert_model is not None,
                'loaded': bert_model.is_loaded if bert_model else False,
                'type': type(bert_model).__name__ if bert_model else None
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
                'config': dict(current_app.config)
            }
        }
        
        return jsonify(debug_data)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'debug_failed': True
        }), 500