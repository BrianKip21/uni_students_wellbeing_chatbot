"""API endpoints for chat functionality"""
from flask import request, jsonify, session
from wellbeing.blueprints.api import api_bp
from wellbeing.utils.decorators import login_required, csrf_protected
from wellbeing.services.chatbot_service import process_message
from wellbeing.models.chat import save_feedback, archive_chats
from wellbeing import logger, bert_model

@api_bp.route('/chat', methods=['POST'])
def chat():
    """API endpoint for processing chat messages."""
    try:
        logger.info("Chat endpoint called")
        
        # Check if user is in session
        if 'user' not in session:
            logger.error("No user in session")
            return jsonify({"error": "Not logged in", "chat_id": None, "response": "Please log in to use the chat."}), 401
            
        user_id = session['user']
        logger.info(f"User ID from session: {user_id}")
        
        # Get message from request
        user_input = request.json.get("message", "").strip()
        logger.info(f"Received message: {user_input}")
        
        if not user_input:
            return jsonify({"error": "Message cannot be empty"}), 400
        
        # Check model status
        logger.info(f"BERT model exists: {bert_model is not None}")
        if bert_model:
            logger.info(f"BERT model loaded: {getattr(bert_model, 'is_loaded', False)}")
        
        # Process message
        response_data = process_message(user_id, user_input)
        logger.info(f"Response generated: {response_data}")
        
        return jsonify(response_data)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in chatbot route: {e}\n{error_details}")
        return jsonify({"error": f"An error occurred: {str(e)}", "chat_id": None, "response": "Sorry, there was an error processing your message."}), 500
    
@api_bp.route('/feedback', methods=['POST'])
@login_required
@csrf_protected
def collect_feedback():
    """API endpoint for collecting user feedback on chat responses."""
    try:
        user_id = session['user']
        chat_id = request.json.get("chat_id")
        rating = request.json.get("rating", 0)  # 1-5 rating
        was_helpful = request.json.get("helpful", False)
        feedback_text = request.json.get("feedback", "")
        
        # Store the feedback
        success = save_feedback(chat_id, user_id, rating, was_helpful, feedback_text)
        
        if success:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Failed to save feedback"}), 500
            
    except Exception as e:
        logger.error(f"Error collecting feedback: {e}")
        return jsonify({"error": "Failed to save feedback"}), 500

@api_bp.route('/reset_chat', methods=['POST'])
@login_required
@csrf_protected
def reset_chat():
    """API endpoint for resetting the chat history."""
    try:
        user_id = session['user']
        
        # Archive all chat messages for this user
        count = archive_chats(user_id)
        
        return jsonify({'success': True, 'count': count})
        
    except Exception as e:
        logger.error(f"Error resetting chat: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500