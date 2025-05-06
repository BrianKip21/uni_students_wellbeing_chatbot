"""Models package for database operations."""
from flask import current_app
from wellbeing import mongo

def create_indexes():
    """Create MongoDB indexes for better query performance."""
    # Users collection indexes
    mongo.db.users.create_index([
        ('name', 'text'),
        ('email', 'text'),
        ('student_id', 'text')
    ])
    mongo.db.users.create_index('email')
    mongo.db.users.create_index('student_id')

    # Resources collection indexes
    mongo.db.resources.create_index([
        ('title', 'text'),
        ('description', 'text')
    ])
    mongo.db.resources.create_index('type')
    
    # Chats collection indexes
    mongo.db.chats.create_index('user_id')
    mongo.db.chats.create_index('timestamp')
    mongo.db.chats.create_index([('conversation_context.topic', 1)])
    mongo.db.chats.create_index([('feedback.rating', 1)])
    
    # Moods collection indexes
    mongo.db.moods.create_index([('user_id', 1), ('timestamp', -1)])
    
    # Journals collection indexes
    mongo.db.journals.create_index([('user_id', 1), ('date', -1)])
    
    # Goals collection indexes
    mongo.db.goals.create_index([('user_id', 1), ('type', 1)])
    
    current_app.logger.info("MongoDB indexes created successfully")