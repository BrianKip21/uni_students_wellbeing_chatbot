from datetime import datetime, timezone, timedelta
import uuid
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def create_chat(user_id, message, response, confidence, model_used, topic, session_id=None, **kwargs):
    """Create a new chat entry with cost tracking."""
    if session_id is None:
        session_id = str(uuid.uuid4())
        
    # Get previous message for context
    previous = get_previous_message(user_id)
    
    # Extract cost tracking data from kwargs (passed from chatbot_service.py)
    tokens_used = kwargs.get('tokens_used', 0)
    estimated_cost = kwargs.get('estimated_cost', 0.0)
    input_tokens = kwargs.get('input_tokens', 0)
    output_tokens = kwargs.get('output_tokens', 0)
    response_time_ms = kwargs.get('response_time_ms', 0)
    detected_intent = kwargs.get('detected_intent', topic)
    
    # Create chat document with cost tracking
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
            "response_time_ms": float(response_time_ms),
            "detected_intent": detected_intent
        },
        
        # Cost tracking fields (NEW - for budget dashboard)
        "tokens_used": int(tokens_used),
        "estimated_cost": float(estimated_cost),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_calculated_at": datetime.now(timezone.utc),
        
        # Archive status
        "archived": False
    }
    
    # Insert into MongoDB
    result = mongo.db.chats.insert_one(chat_data)
    
    # Log cost tracking info
    current_app.logger.info(f"Chat created with cost tracking: {result.inserted_id}")
    current_app.logger.info(f"  - Cost: ${estimated_cost:.6f}, Tokens: {tokens_used}")
    
    return str(result.inserted_id)

def get_previous_message(user_id):
    """Get the previous message and response for a user."""
    previous = mongo.db.chats.find_one(
        {"user_id": user_id, "archived": {"$ne": True}},
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
        {"user_id": user_id, "archived": {"$ne": True}},
        {"$set": {"archived": True, "archived_at": datetime.now(timezone.utc)}}
    )
    return result.modified_count

def get_chat_analytics(user_id, days=30):
    """
    Get chat analytics for a user over specified days.
    Returns usage statistics including costs and token counts.
    """
    try:
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Query chats in date range
        chats = list(mongo.db.chats.find({
            'user_id': user_id,  # Note: your user_id is already a string, not ObjectId
            'timestamp': {'$gte': start_date, '$lte': end_date},
            'archived': {'$ne': True}
        }))
        
        # Calculate analytics with improved cost handling
        total_messages = len(chats)
        total_cost = 0
        total_tokens = 0
        
        for chat in chats:
            # Get cost from estimated_cost field, or calculate from tokens if available
            cost = chat.get('estimated_cost', 0)
            if cost == 0 and 'tokens_used' in chat and chat['tokens_used'] > 0:
                # Estimate cost for old chats: roughly $0.000005 per token for Haiku
                cost = chat['tokens_used'] * 0.000005
            total_cost += cost
            
            # Get token count
            tokens = chat.get('tokens_used', 0)
            if tokens == 0:
                # Estimate tokens from message length for very old chats
                message_len = len(chat.get('message', ''))
                response_len = len(chat.get('response', ''))
                tokens = (message_len + response_len) // 4  # Rough estimate
            total_tokens += tokens
        
        # Count crisis messages
        crisis_count = len([
            chat for chat in chats 
            if chat.get('conversation_context', {}).get('topic') == 'crisis' 
            or chat.get('response_metadata', {}).get('detected_intent') == 'crisis'
        ])
        
        # Topic distribution
        topics = {}
        for chat in chats:
            # Get topic from either location (old vs new structure)
            topic = (chat.get('conversation_context', {}).get('topic') or 
                    chat.get('response_metadata', {}).get('detected_intent') or 
                    'general_support')
            topics[topic] = topics.get(topic, 0) + 1
        
        # Average confidence
        confidences = [chat.get('confidence', 0) for chat in chats if chat.get('confidence')]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            'total_messages': total_messages,
            'total_cost': round(total_cost, 6),
            'total_tokens': total_tokens,
            'crisis_count': crisis_count,
            'topic_distribution': topics,
            'avg_confidence': round(avg_confidence, 2),
            'avg_cost_per_message': round(total_cost / max(total_messages, 1), 6),
            'period_days': days
        }
        
    except Exception as e:
        current_app.logger.error(f"Error getting chat analytics: {e}")
        return {
            'total_messages': 0,
            'total_cost': 0.0,
            'total_tokens': 0,
            'crisis_count': 0,
            'topic_distribution': {},
            'avg_confidence': 0.0,
            'avg_cost_per_message': 0.0,
            'period_days': days
        }

def update_existing_chats_with_costs():
    """
    One-time migration function to add cost estimates to existing chats.
    Call this once to populate historical data for the budget dashboard.
    """
    try:
        # Find chats without cost data
        chats_without_costs = mongo.db.chats.find({
            'estimated_cost': {'$exists': False}
        })
        
        updated_count = 0
        for chat in chats_without_costs:
            # Estimate cost based on existing data
            tokens_used = chat.get('tokens_used', 0)
            
            if tokens_used == 0:
                # Estimate tokens from message + response length
                message_len = len(chat.get('message', ''))
                response_len = len(chat.get('response', ''))
                tokens_used = (message_len + response_len) // 4  # 4 chars per token estimate
                
                # Estimate input/output split
                input_tokens = message_len // 4
                output_tokens = response_len // 4
            else:
                # Use existing tokens, estimate input/output split
                input_tokens = tokens_used // 2
                output_tokens = tokens_used - input_tokens
            
            # Calculate cost using Claude Haiku pricing
            # $0.25/1M input tokens, $1.25/1M output tokens
            estimated_cost = (input_tokens * 0.00000025) + (output_tokens * 0.00000125)
            
            # Update the chat with cost data
            mongo.db.chats.update_one(
                {'_id': chat['_id']},
                {
                    '$set': {
                        'tokens_used': tokens_used,
                        'estimated_cost': estimated_cost,
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'cost_calculated_at': datetime.now(timezone.utc),
                        'cost_estimated': True,  # Flag to show this was estimated
                        'archived': False  # Set default archived status
                    }
                }
            )
            updated_count += 1
        
        current_app.logger.info(f"Updated {updated_count} existing chats with cost estimates")
        return updated_count
        
    except Exception as e:
        current_app.logger.error(f"Error updating existing chats with costs: {e}")
        return 0