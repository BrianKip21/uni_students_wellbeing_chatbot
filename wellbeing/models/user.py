from datetime import datetime, timezone
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from wellbeing import mongo

def find_user_by_id(user_id):
    """Find a user by ID."""
    try:
        if isinstance(user_id, str) and ObjectId.is_valid(user_id):
            user_id = ObjectId(user_id)
        return mongo.db.users.find_one({"_id": user_id})
    except Exception as e:
        current_app.logger.error(f"Error finding user by ID: {str(e)}")
        return None

def find_user_by_email(email):
    """Find a user by email."""
    return mongo.db.users.find_one({"email": email})

def find_user_by_student_id(student_id):
    """Find a user by student ID."""
    return mongo.db.users.find_one({"student_id": student_id})

def create_user(first_name, last_name, email, student_id, password, role='student'):
    """Create a new user."""
    new_user = {
        'first_name': first_name,
        'last_name': last_name,
        'full_name': f"{first_name} {last_name}",
        'email': email,
        'student_id': student_id,
        'password': generate_password_hash(password),
        'role': role,
        'created_at': datetime.now(timezone.utc),
        'last_login': None,
        'status': 'Active',
        'settings': {
            'text_size': 'md',
            'contrast': 'normal',
            'theme_mode': 'light',
            'widgets': ['mood_tracker', 'quick_actions', 'resources', 'progress'],
            'default_view': 'dashboard'
        }
    }
    
    result = mongo.db.users.insert_one(new_user)
    return result.inserted_id

def update_user_login(user_id):
    """Update user's last login time."""
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'last_login': datetime.now(timezone.utc)},
         '$inc': {'login_count': 1}}
    )

def update_user_password(user_id, new_password):
    """Update a user's password."""
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'password': generate_password_hash(new_password)}}
    )

def update_user_settings(user_id, settings):
    """Update a user's settings."""
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'settings': settings}}
    )

def update_user_status(user_id, status):
    """Update a user's status (Active/Inactive)."""
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'status': status}}
    )

def get_all_users(query=None, skip=0, limit=0):
    """Get all users with optional filtering and pagination."""
    if query is None:
        query = {}
    
    return list(mongo.db.users.find(query).skip(skip).limit(limit))