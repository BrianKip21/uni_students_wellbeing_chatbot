"""API endpoints for chat functionality using Claude API"""
from flask import request, jsonify, session, current_app
from wellbeing.blueprints.api import api_bp
from wellbeing.utils.decorators import login_required, csrf_protected
from wellbeing.services.chatbot_service import process_message
from wellbeing.models.chat import save_feedback, archive_chats
from wellbeing import logger

@api_bp.route('/chat', methods=['POST'])
def chat():
    """API endpoint for processing chat messages using Claude API."""
    try:
        logger.info("Chat endpoint called")
        
        # AUTHENTICATION CHECK
        if 'user' not in session:
            logger.error("No user in session")
            return jsonify({
                "error": "Not logged in", 
                "chat_id": None, 
                "response": "Please log in to use the chat.",
                "confidence": 0.0,
                "model": "error",
                "detected_intent": "authentication_error"
            }), 401
        
        user_id = session['user']
        logger.info(f"User ID from session: {user_id}")
        
        # Get message from request
        user_input = request.json.get("message", "").strip()
        logger.info(f"Received message: {user_input}")
        
        #MESSAGE VALIDATION
        if not user_input:
            logger.warning("Empty message received")
            return jsonify({
                "error": "Message cannot be empty",
                "chat_id": None,
                "response": "Please enter a message to continue our conversation.",
                "confidence": 0.0,
                "model": "validation_error",
                "detected_intent": "empty_message"
            }), 400
        
        # Check for message length (prevent very long messages)
        max_message_length = current_app.config.get('MAX_MESSAGE_LENGTH', 2000)
        if len(user_input) > max_message_length:
            logger.warning(f"Message too long: {len(user_input)} characters")
            return jsonify({
                "error": "Message too long",
                "chat_id": None,
                "response": f"Please keep your message under {max_message_length} characters for better processing.",
                "confidence": 0.0,
                "model": "validation_error",
                "detected_intent": "message_too_long"
            }), 400
        
        # Check Claude API configuration / API KEY VALIDATION
        api_key = current_app.config.get('CLAUDE_API_KEY')
        api_key_configured = bool(api_key and api_key.strip() and api_key.startswith('sk-ant-'))
        logger.info(f"Claude API key configured: {api_key_configured}")
        
        if not api_key_configured:
            logger.error("Claude API key not configured or invalid")
            return jsonify({
                "error": "AI service not available",
                "chat_id": None,
                "response": "I apologize, but the AI chat service is currently unavailable. Please contact support.",
                "confidence": 0.0,
                "model": "configuration_error",
                "detected_intent": "service_unavailable"
            }), 503
        
        # Check budget limits before processing
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        
        # Get current usage (simplified check - in production you'd check actual usage)
        from wellbeing.models.chat import get_chat_analytics
        daily_usage = get_chat_analytics(user_id, days=1).get('total_cost', 0)
        monthly_usage = get_chat_analytics(user_id, days=30).get('total_cost', 0)
        
        if monthly_usage >= monthly_budget:
            logger.warning(f"Monthly budget exceeded for user {user_id}: ${monthly_usage:.4f}")
            return jsonify({
                "error": "Budget limit reached",
                "chat_id": None,
                "response": f"You've reached your monthly chat budget of ${monthly_budget}. Please contact support or wait until next month.",
                "confidence": 0.0,
                "model": "budget_limit",
                "detected_intent": "budget_exceeded"
            }), 429
        
        if daily_usage >= daily_budget:
            logger.warning(f"Daily budget exceeded for user {user_id}: ${daily_usage:.4f}")
            return jsonify({
                "error": "Daily limit reached",
                "chat_id": None,
                "response": f"You've reached your daily chat limit of ${daily_budget}. Please try again tomorrow.",
                "confidence": 0.0,
                "model": "daily_limit",
                "detected_intent": "daily_limit_exceeded"
            }), 429
        
        # Process message using Claude service
        try:
            logger.info("Processing message with Claude service...")
            response_data = process_message(user_id, user_input)
            
            # Log the response details
            logger.info(f"Response generated successfully:")
            logger.info(f"  - Response length: {len(response_data.get('response', ''))}")
            logger.info(f"  - Model used: {response_data.get('model', 'unknown')}")
            logger.info(f"  - Confidence: {response_data.get('confidence', 0)}")
            logger.info(f"  - Intent: {response_data.get('detected_intent', 'unknown')}")
            logger.info(f"  - Chat ID: {response_data.get('chat_id', 'none')}")
            logger.info(f"  - Response time: {response_data.get('response_time_ms', 0)}ms")
            logger.info(f"  - Tokens used: {response_data.get('tokens_used', 0)}")
            logger.info(f"  - Estimated cost: ${response_data.get('estimated_cost', 0):.6f}")
            
            # Ensure all required fields are present
            formatted_response = {
                "response": response_data.get('response', 'I apologize, but I cannot generate a response right now.'),
                "confidence": float(response_data.get('confidence', 0.0)),
                "model": response_data.get('model', 'claude-haiku'),
                "chat_id": response_data.get('chat_id'),
                "detected_intent": response_data.get('detected_intent', 'general_support'),
                "response_time_ms": response_data.get('response_time_ms', 0),
                "tokens_used": response_data.get('tokens_used', 0),
                "estimated_cost": response_data.get('estimated_cost', 0.0)
            }
            
            # Check if this is a crisis response
            if response_data.get('detected_intent') == 'crisis' or response_data.get('model') == 'crisis_detection':
                logger.warning(f"Crisis message detected for user {user_id}")
                formatted_response['is_crisis'] = True
            
            # Add budget info to response
            remaining_monthly = max(0, monthly_budget - monthly_usage - response_data.get('estimated_cost', 0))
            remaining_daily = max(0, daily_budget - daily_usage - response_data.get('estimated_cost', 0))
            
            formatted_response['budget_info'] = {
                'remaining_monthly': round(remaining_monthly, 4),
                'remaining_daily': round(remaining_daily, 4),
                'usage_warning': remaining_monthly < (monthly_budget * 0.1)  # Warn at 90% usage
            }
            
            return jsonify(formatted_response)
            
        except Exception as service_error:
            logger.error(f"Claude service error: {service_error}")
            import traceback
            logger.error(f"Service error traceback: {traceback.format_exc()}")
            
            # Check for specific Claude errors
            error_response = {
                "error": "Service error",
                "chat_id": None,
                "response": "I apologize, but I'm experiencing technical difficulties right now. Please try again in a few moments, or contact support if the issue persists.",
                "confidence": 0.0,
                "model": "error-fallback",
                "detected_intent": "service_error"
            }
            
            # Customize error message based on error type
            error_str = str(service_error).lower()
            if 'rate limit' in error_str:
                error_response["response"] = "I'm currently receiving many messages. Please wait a moment and try again."
                error_response["model"] = "rate_limit_error"
            elif 'authentication' in error_str:
                error_response["response"] = "There's an authentication issue with the AI service. Please contact support."
                error_response["model"] = "auth_error"
            elif 'quota' in error_str or 'billing' in error_str:
                error_response["response"] = "The AI service is temporarily unavailable due to billing issues. Please contact support."
                error_response["model"] = "billing_error"
            
            return jsonify(error_response), 500
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Unexpected error in chat endpoint: {e}")
        logger.error(f"Full traceback: {error_details}")
        
        return jsonify({
            "error": f"Unexpected error: {str(e)}",
            "chat_id": None,
            "response": "I'm sorry, but something unexpected went wrong. Please refresh the page and try again, or contact support if the issue continues.",
            "confidence": 0.0,
            "model": "error",
            "detected_intent": "unexpected_error"
        }), 500


@api_bp.route('/reset_chat', methods=['POST'])
@login_required
@csrf_protected
def reset_chat():
    """API endpoint for resetting the chat history."""
    try:
        user_id = session['user']
        logger.info(f"Resetting chat history for user {user_id}")
        
        # Archive all chat messages for this user
        count = archive_chats(user_id)
        
        logger.info(f"Successfully archived {count} chat messages for user {user_id}")
        
        return jsonify({
            'success': True, 
            'count': count,
            'message': f'Successfully cleared {count} messages from your chat history. Your conversation data has been archived securely.'
        })
        
    except Exception as e:
        import traceback
        logger.error(f"Error resetting chat: {e}")
        logger.error(f"Reset chat traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False, 
            'error': str(e),
            'message': 'An error occurred while clearing your chat history. Please try again.'
        }), 500


@api_bp.route('/chat/status', methods=['GET'])
def chat_status():
    """API endpoint to check chat service status."""
    try:
        # Check Claude API configuration
        api_key = current_app.config.get('CLAUDE_API_KEY')
        api_key_configured = bool(api_key and api_key.strip() and api_key.startswith('sk-ant-'))
        model_configured = current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307')
        
        # Get budget info
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        
        status_data = {
            "service": "chat_claude",
            "status": "healthy" if api_key_configured else "degraded",
            "claude_configured": api_key_configured,
            "model": model_configured,
            "budget_limits": {
                "monthly_budget": monthly_budget,
                "daily_budget": daily_budget,
                "currency": "USD"
            },
            "features": {
                "crisis_detection": current_app.config.get('CRISIS_DETECTION_ENABLED', True),
                "topic_classification": True,
                "conversation_memory": True,
                "feedback_collection": True,
                "cost_tracking": True,
                "budget_monitoring": True
            },
            "available_models": list(current_app.config.get('AVAILABLE_CLAUDE_MODELS', {}).keys())
        }
        
        # If user is logged in, add user-specific info
        if 'user' in session:
            user_id = session['user']
            status_data["user_authenticated"] = True
            status_data["user_id"] = str(user_id)
            
            # Add user's current usage
            try:
                from wellbeing.models.chat import get_chat_analytics
                daily_usage = get_chat_analytics(user_id, days=1).get('total_cost', 0)
                monthly_usage = get_chat_analytics(user_id, days=30).get('total_cost', 0)
                
                status_data["user_usage"] = {
                    "daily_spent": round(daily_usage, 4),
                    "monthly_spent": round(monthly_usage, 4),
                    "daily_remaining": round(max(0, daily_budget - daily_usage), 4),
                    "monthly_remaining": round(max(0, monthly_budget - monthly_usage), 4),
                    "daily_percentage": round((daily_usage / daily_budget) * 100, 1) if daily_budget > 0 else 0,
                    "monthly_percentage": round((monthly_usage / monthly_budget) * 100, 1) if monthly_budget > 0 else 0
                }
            except Exception as analytics_error:
                logger.error(f"Error getting user analytics: {analytics_error}")
                status_data["user_usage"] = {"error": "Unable to fetch usage data"}
        else:
            status_data["user_authenticated"] = False
        
        return jsonify(status_data)
        
    except Exception as e:
        logger.error(f"Error checking chat status: {e}")
        return jsonify({
            "service": "chat_claude",
            "status": "error",
            "error": str(e)
        }), 500


@api_bp.route('/chat/health', methods=['GET'])
def chat_health():
    """Simple health check endpoint for the chat API."""
    try:
        # Basic health checks
        api_key = current_app.config.get('CLAUDE_API_KEY')
        checks = {
            "claude_api_configured": bool(api_key and api_key.strip() and api_key.startswith('sk-ant-')),
            "database_accessible": True,  # Simplified check
            "session_working": 'user' in session if session else False,
            "budget_configured": bool(current_app.config.get('MAX_MONTHLY_SPEND', 0) > 0),
            "crisis_detection_enabled": current_app.config.get('CRISIS_DETECTION_ENABLED', False)
        }
        
        overall_health = all(checks.values())
        
        # Add more detailed info for debugging
        health_data = {
            "status": "healthy" if overall_health else "degraded",
            "checks": checks,
            "service": "chat_api_claude",
            "config_info": {
                "model": current_app.config.get('CLAUDE_MODEL', 'unknown'),
                "max_tokens": current_app.config.get('CLAUDE_MAX_TOKENS', 0),
                "monthly_budget": current_app.config.get('MAX_MONTHLY_SPEND', 0),
                "daily_budget": current_app.config.get('DAILY_SPENDING_LIMIT', 0)
            }
        }
        
        return jsonify(health_data), 200 if overall_health else 503
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "service": "chat_api_claude"
        }), 500


@api_bp.route('/chat/budget', methods=['GET'])
@login_required
def get_budget_status():
    """API endpoint to get current user's budget status."""
    try:
        user_id = session['user']
        
        # Get budget configuration
        monthly_budget = current_app.config.get('MAX_MONTHLY_SPEND', 5.00)
        daily_budget = current_app.config.get('DAILY_SPENDING_LIMIT', 0.50)
        alert_threshold = current_app.config.get('USAGE_ALERT_THRESHOLD', 4.00)
        
        # Get current usage
        from wellbeing.models.chat import get_chat_analytics
        daily_analytics = get_chat_analytics(user_id, days=1)
        monthly_analytics = get_chat_analytics(user_id, days=30)
        
        daily_spent = daily_analytics.get('total_cost', 0)
        monthly_spent = monthly_analytics.get('total_cost', 0)
        
        budget_data = {
            "user_id": str(user_id),
            "monthly": {
                "budget": monthly_budget,
                "spent": round(monthly_spent, 4),
                "remaining": round(max(0, monthly_budget - monthly_spent), 4),
                "percentage": round((monthly_spent / monthly_budget) * 100, 1) if monthly_budget > 0 else 0,
                "alert_triggered": monthly_spent >= alert_threshold
            },
            "daily": {
                "budget": daily_budget,
                "spent": round(daily_spent, 4),
                "remaining": round(max(0, daily_budget - daily_spent), 4),
                "percentage": round((daily_spent / daily_budget) * 100, 1) if daily_budget > 0 else 0
            },
            "status": {
                "can_chat": monthly_spent < monthly_budget and daily_spent < daily_budget,
                "warning_level": "high" if monthly_spent >= alert_threshold else "medium" if monthly_spent >= (monthly_budget * 0.7) else "low"
            },
            "usage_stats": {
                "total_messages_today": daily_analytics.get('total_messages', 0),
                "total_messages_month": monthly_analytics.get('total_messages', 0),
                "total_tokens_today": daily_analytics.get('total_tokens', 0),
                "total_tokens_month": monthly_analytics.get('total_tokens', 0)
            }
        }
        
        return jsonify(budget_data)
        
    except Exception as e:
        logger.error(f"Error getting budget status: {e}")
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@api_bp.route('/chat/models', methods=['GET'])
def get_available_models():
    """API endpoint to get available Claude models and their pricing."""
    try:
        available_models = current_app.config.get('AVAILABLE_CLAUDE_MODELS', {})
        current_model = current_app.config.get('CLAUDE_MODEL', 'claude-3-haiku-20240307')
        
        models_data = {
            "current_model": current_model,
            "available_models": available_models,
            "total_models": len(available_models),
            "pricing_unit": "per million tokens",
            "currency": "USD"
        }
        
        return jsonify(models_data)
        
    except Exception as e:
        logger.error(f"Error getting available models: {e}")
        return jsonify({
            "error": str(e),
            "available_models": {}
        }), 500