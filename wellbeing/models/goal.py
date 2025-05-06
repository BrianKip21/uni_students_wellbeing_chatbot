from datetime import datetime, timezone
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def create_goal(user_id, goal_type, description, target, unit, frequency):
    """Create a new goal."""
    # Handle custom goal type
    if goal_type == 'custom':
        goal_type = description[:20]  # Use part of description as type
    
    # Create goal document
    goal = {
        'user_id': user_id,
        'type': goal_type[:50],  # Limit type length
        'description': description[:500],  # Limit description length
        'target': int(target) if target > 0 else 1,  # Ensure target is positive
        'progress': 0,
        'unit': unit[:20],  # Limit unit length
        'frequency': frequency,
        'created_at': datetime.now(timezone.utc),
        'last_updated': datetime.now(timezone.utc)
    }
    
    # Insert into database
    result = mongo.db.goals.insert_one(goal)
    return str(result.inserted_id)

def get_goals(user_id):
    """Get all goals for a user."""
    return list(mongo.db.goals.find({
        "user_id": user_id
    }).sort("created_at", -1))

def update_goal_progress(user_id, goal_id, increment):
    """Update progress for a goal."""
    try:
        # Find the goal
        goal = mongo.db.goals.find_one({
            '_id': ObjectId(goal_id),
            'user_id': user_id
        })
        
        if not goal:
            return False, "Goal not found"
        
        # Update progress
        current_progress = int(goal.get('progress', 0)) + increment
        
        # Ensure progress doesn't go below 0
        if current_progress < 0:
            current_progress = 0
        
        # Check if goal is completed
        target = int(goal.get('target', 0))
        goal_completed = current_progress >= target
        
        # Update in database
        mongo.db.goals.update_one(
            {'_id': ObjectId(goal_id)},
            {
                '$set': {
                    'progress': current_progress,
                    'last_updated': datetime.now(timezone.utc)
                }
            }
        )
        
        return True, {
            'new_progress': current_progress,
            'goal_completed': goal_completed
        }
    except Exception as e:
        current_app.logger.error(f"Error updating goal progress: {str(e)}")
        return False, str(e)

def delete_goal(user_id, goal_id):
    """Delete a goal."""
    result = mongo.db.goals.delete_one({
        '_id': ObjectId(goal_id),
        'user_id': user_id
    })
    
    return result.deleted_count > 0