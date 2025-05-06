"""Database utility functions"""
from wellbeing import mongo, logger

def create_indexes():
    """Create database indexes for better query performance"""
    try:
        # User collection indexes
        mongo.db.users.create_index([("email", 1)], unique=True)
        mongo.db.users.create_index([("student_id", 1)], unique=True)
        mongo.db.users.create_index([("full_name", "text"), ("email", "text")])
        
        # Chat collection indexes
        mongo.db.chats.create_index([("user_id", 1)])
        mongo.db.chats.create_index([("timestamp", -1)])
        mongo.db.chats.create_index([("conversation_context.topic", 1)])
        
        # Feedback collection indexes
        mongo.db.feedback.create_index([("user_id", 1)])
        mongo.db.feedback.create_index([("chat_id", 1)], unique=True)
        
        # Resources collection indexes
        mongo.db.resources.create_index([("title", "text"), ("description", "text")])
        
        # Mood tracking indexes
        mongo.db.moods.create_index([("user_id", 1), ("timestamp", -1)])
        
        # Journal entries indexes
        mongo.db.journals.create_index([("user_id", 1), ("date", -1)])
        
        # Goals indexes
        mongo.db.goals.create_index([("user_id", 1)])
        
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")