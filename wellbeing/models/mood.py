from datetime import datetime, timezone, time, date, timedelta
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def track_mood(user_id, mood, context=None):
    """Track or update a user's mood for today."""
    # Get current time in UTC
    current_time = datetime.now(timezone.utc)
    
    # Calculate today's date range
    today_start = datetime.combine(current_time.date(), time.min).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(current_time.date(), time.max).replace(tzinfo=timezone.utc)
    
    # Check if user already tracked mood today
    existing_mood = mongo.db.moods.find_one({
        'user_id': user_id,
        'timestamp': {'$gte': today_start, '$lte': today_end}
    })
    
    # Prepare mood data
    mood_data = {
        'mood': mood,
        'context': context[:500] if context else '',
        'timestamp': current_time
    }
    
    if existing_mood:
        # Update existing mood
        mongo.db.moods.update_one(
            {'_id': existing_mood['_id']},
            {'$set': mood_data}
        )
        return "updated"
    else:
        # Create new mood entry
        mood_data['user_id'] = user_id
        mongo.db.moods.insert_one(mood_data)
        return "created"

def get_mood_history(user_id, limit=30):
    """Get mood history for a user."""
    moods = list(mongo.db.moods.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(limit))
    
    # Format moods for display
    formatted_moods = []
    for mood in moods:
        try:
            mood_data = {
                '_id': str(mood['_id']),
                'mood': mood['mood'],
                'date': mood.get('timestamp', datetime.now(timezone.utc)).strftime('%a, %b %d'),
                'timestamp': mood.get('timestamp', datetime.now(timezone.utc))
            }
            
            # Add context if available
            if 'context' in mood:
                mood_data['context'] = mood['context']
                
            formatted_moods.append(mood_data)
        except Exception as e:
            current_app.logger.error(f"Error processing mood entry: {str(e)}")
    
    return formatted_moods

def get_latest_mood(user_id):
    """Get the latest mood for a user."""
    return mongo.db.moods.find_one({"user_id": user_id}, sort=[("timestamp", -1)])

def get_mood_stats(user_id, days=30):
    """Get mood statistics for a user over a period of days."""
    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # Get moods within date range
    moods = list(mongo.db.moods.find({
        "user_id": user_id,
        "timestamp": {"$gte": start_date, "$lte": end_date}
    }).sort("timestamp", 1))
    
    # Count occurrences of each mood
    mood_counts = {}
    for mood in moods:
        mood_value = mood.get('mood')
        if mood_value not in mood_counts:
            mood_counts[mood_value] = 0
        mood_counts[mood_value] += 1
    
    return {
        "total_entries": len(moods),
        "mood_counts": mood_counts,
        "date_range": {
            "start": start_date,
            "end": end_date
        }
    }