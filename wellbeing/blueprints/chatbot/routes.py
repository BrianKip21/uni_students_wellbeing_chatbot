from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, jsonify, request, flash
from wellbeing.blueprints.chatbot import chatbot_bp
from wellbeing.models.user import find_user_by_id
from wellbeing.utils.decorators import login_required
from wellbeing.services.chatbot_service import process_message
from wellbeing.models.chat import get_recent_chats
from wellbeing.ml.model_loader import original_model, original_model_loaded
from wellbeing import logger, bert_model

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

@chatbot_bp.route('/model-status')
def model_status():
    """Check if the models are properly loaded."""
    return jsonify({
        'bert_model_exists': bert_model is not None,
        'bert_model_loaded': bert_model is not None and hasattr(bert_model, 'is_loaded') and bert_model.is_loaded,
        'original_model_exists': original_model is not None,
        'original_model_loaded': original_model_loaded
    })

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