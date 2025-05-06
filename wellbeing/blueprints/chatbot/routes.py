from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, jsonify, request, flash
from wellbeing.blueprints.chatbot import chatbot_bp
from wellbeing.models.user import find_user_by_id
from wellbeing.utils.decorators import login_required, csrf_protected
from wellbeing.services.chatbot_service import process_message
from wellbeing.models.chat import save_feedback, get_recent_chats, archive_chats
from wellbeing import logger

@chatbot_bp.route('/chatbot')
@login_required
def chatbot_page():
    """Render the chatbot interface page."""
    user_id = session['user']
    
    # Get the user document to access settings
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get user settings
    settings = user.get('settings', {})
    
    # Get recent chat messages, excluding archived ones
    recent_chats = get_recent_chats(user_id)
    
    return render_template('chatbot.html', messages=recent_chats, user=user, settings=settings)

@chatbot_bp.route('/api/chat', methods=['POST'])
@login_required
@csrf_protected
def chat():
    """API endpoint for processing chat messages."""
    try:
        user_id = session['user']
        user_input = request.json.get("message", "").strip()
        
        if not user_input:
            return jsonify({"error": "Message cannot be empty"}), 400
        
        # Process the message and get response
        response_data = process_message(user_id, user_input)
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in chatbot route: {e}")
        return jsonify({"error": "An error occurred while processing your request."}), 500

@chatbot_bp.route('/api/feedback', methods=['POST'])
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

@chatbot_bp.route('/api/reset_chat', methods=['POST'])
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

@chatbot_bp.route('/test-chatbot')
def test_chatbot():
    """Test endpoint for the chatbot (for development use)."""
    try:
        # Check if logged in or bypass for testing
        if 'user' not in session:
            return jsonify({'error': 'Not logged in'}), 401
            
        test_message = "I'm feeling stressed"
        user_id = session['user']
        
        # Process the test message
        response = process_message(user_id, test_message)
        
        return jsonify({
            'status': 'success',
            'test_message': test_message,
            'response': response['response']
        })
    except Exception as e:
        logger.error(f"Test endpoint error: {e}")
        return jsonify({'error': str(e)}), 500