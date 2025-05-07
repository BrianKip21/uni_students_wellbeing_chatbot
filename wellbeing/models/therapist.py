from datetime import datetime, timezone
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash
from flask import current_app
from wellbeing import mongo

def find_therapist_by_id(therapist_id):
    try:
        if isinstance(therapist_id, str) and ObjectId.is_valid(therapist_id):
            therapist_id = ObjectId(therapist_id)
        return mongo.db.therapists.find_one({"_id": therapist_id})
    except Exception as e:
        current_app.logger.error(f"Error finding therapist by ID: {str(e)}")
        return None

def create_therapist(first_name, last_name, email, password):
    new_therapist = {
        'first_name': first_name,
        'last_name': last_name,
        'full_name': f"{first_name} {last_name}",
        'email': email,
        'password': generate_password_hash(password),
        'role': 'therapist',
        'status': 'Active',
        'created_at': datetime.now(timezone.utc),
        'settings': {
            'text_size': 'md',
            'contrast': 'normal',
            'theme_mode': 'light',
            'widgets': ['appointments', 'messages', 'notes'],
            'default_view': 'dashboard'
        }
    }
    result = mongo.db.therapists.insert_one(new_therapist)
    return result.inserted_id

def update_therapist_settings(therapist_id, settings):
    mongo.db.therapists.update_one(
        {'_id': ObjectId(therapist_id)},
        {'$set': {'settings': settings}}
    )

def update_therapist_status(therapist_id, status):
    mongo.db.therapists.update_one(
        {'_id': ObjectId(therapist_id)},
        {'$set': {'status': status}}
    )

def get_all_therapists(query=None, skip=0, limit=0):
    if query is None:
        query = {}
    return list(mongo.db.therapists.find(query).skip(skip).limit(limit))
