from datetime import datetime, timezone
import uuid
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def create_chat(user_id, message, response, confidence, model_used, topic, session_id=None):
    """Create a new chat entry."""
    if session_id is None:
        session_id = str(uuid.uuid4())
        
    # Get previous message for context
    previous = get_previous_message(user_id)
    
    # Create chat document
    chat_data = {
        "user_id": user_id,
        "message": message,
        "response": response,
        "confidence": float(confidence),
        "model_used": model_used,
        "timestamp": datetime.now(timezone.utc),
        "session_id": session_id,
        "conversation_context": {
            "previous_message": previous,
            "topic": topic
        },
        "response_metadata": {
            "response_time_ms": 0,  # Will be calculated by the service
            "detected_intent": topic
        }
    }
    
    # Insert into MongoDB
    result = mongo.db.chats.insert_one(chat_data)
    return str(result.inserted_id)

def get_previous_message(user_id):
    """Get the previous message and response for a user."""
    previous = mongo.db.chats.find_one(
        {"user_id": user_id},
        sort=[("timestamp", -1)]
    )
    
    if previous:
        return {
            "message": previous.get("message", ""),
            "response": previous.get("response", "")
        }
    return {"message": "", "response": ""}

def get_recent_chats(user_id, limit=10, include_archived=False):
    """Get recent chats for a user."""
    query = {"user_id": user_id}
    if not include_archived:
        query["archived"] = {"$ne": True}
    
    chats = list(mongo.db.chats.find(query).sort("timestamp", -1).limit(limit))
    
    # Convert ObjectId to string for JSON serialization
    for chat in chats:
        chat['_id'] = str(chat['_id'])
    
    return chats

def get_chat_by_id(chat_id):
    """Get a chat by its ID."""
    try:
        chat = mongo.db.chats.find_one({"_id": ObjectId(chat_id)})
        if chat:
            chat['_id'] = str(chat['_id'])
        return chat
    except Exception as e:
        current_app.logger.error(f"Error finding chat by ID: {str(e)}")
        return None

def save_feedback(chat_id, user_id, rating, was_helpful, feedback_text):
    """Save feedback for a chat."""
    feedback_data = {
        "user_id": user_id,
        "chat_id": chat_id,
        "rating": rating,
        "was_helpful": was_helpful,
        "feedback_text": feedback_text,
        "timestamp": datetime.now(timezone.utc)
    }
    
    # Store in feedback collection
    mongo.db.feedback.insert_one(feedback_data)
    
    # Update the original chat document with this feedback
    mongo.db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"feedback": feedback_data}}
    )
    
    return True

def archive_chats(user_id):
    """Archive all chats for a user."""
    result = mongo.db.chats.update_many(
        {"user_id": user_id},
        {"$set": {"archived": True}}
    )
    return result.modified_count