"""
Chatbot service for processing user messages and generating responses.
"""
import uuid
from datetime import datetime, timezone
from flask import current_app
from wellbeing import bert_model
from wellbeing.models.chat import create_chat, get_previous_message

def process_message(user_id, user_input):
    """
    Process a user message and generate a response.
    
    Args:
        user_id (str): User ID
        user_input (str): User message
        
    Returns:
        dict: Response data including text, confidence, and chat ID
    """
    # Record start time to calculate response time
    start_time = datetime.now()
    
    # Default values in case of errors
    response = "I'm having trouble understanding. Could you rephrase your question?"
    confidence = 0.0
    model_used = "error-fallback"
    detected_intent = "unknown"
    
    try:
        # Check for crisis content first
        if bert_model and bert_model.is_loaded and bert_model.check_for_crisis(user_input):
            crisis_response = bert_model.get_crisis_response()
            response = crisis_response["response"]
            confidence = crisis_response["confidence"]
            model_used = "crisis_detection"
            detected_intent = "crisis"
            bert_response = {"topic": "crisis"}
        elif bert_model and bert_model.is_loaded:
            # Use DistilBERT model
            bert_response = bert_model.get_response(user_input)
            response = bert_response["response"]
            confidence = bert_response["confidence"]
            model_used = bert_response["model"]
            detected_intent = bert_response.get("topic", "general")
        
    except Exception as model_error:
        current_app.logger.error(f"Error using models: {str(model_error)}")
        # We keep the default values set above
        bert_response = {"topic": "error"}
    
    # Calculate response time
    response_time = (datetime.now() - start_time).total_seconds() * 1000  # in milliseconds

    # Get or create session ID
    session_id = str(uuid.uuid4())

    # Store the chat in the database
    chat_id = create_chat(
        user_id=user_id,
        message=user_input,
        response=response,
        confidence=confidence,
        model_used=model_used,
        topic=bert_response.get("topic", "unknown") if 'bert_response' in locals() else "unknown",
        session_id=session_id
    )
    
    # Return the response data
    return {
        "response": response, 
        "confidence": float(confidence), 
        "model": model_used,
        "chat_id": chat_id
    }