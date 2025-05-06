from datetime import datetime, timezone
from bson.objectid import ObjectId
from flask import current_app
from wellbeing import mongo

def get_all_resources(query=None, limit=0):
    """Get all resources with optional filtering."""
    if query is None:
        query = {}
    
    return list(mongo.db.resources.find(query).limit(limit))

def get_resource_by_id(resource_id):
    """Get a resource by its ID."""
    try:
        if isinstance(resource_id, str) and ObjectId.is_valid(resource_id):
            resource_id = ObjectId(resource_id)
        return mongo.db.resources.find_one({"_id": resource_id})
    except Exception as e:
        current_app.logger.error(f"Error finding resource by ID: {str(e)}")
        return None

def create_resource(title, description, resource_type, content, created_by, file_path=None):
    """Create a new resource."""
    new_resource = {
        'title': title,
        'description': description,
        'type': resource_type,
        'content': content,
        'created_at': datetime.now(timezone.utc),
        'created_by': created_by
    }
    
    if file_path:
        new_resource['file_path'] = file_path
    
    result = mongo.db.resources.insert_one(new_resource)
    return result.inserted_id

def update_resource(resource_id, title, description, resource_type, content, file_path=None):
    """Update an existing resource."""
    update_data = {
        'title': title,
        'description': description,
        'type': resource_type,
        'content': content,
        'updated_at': datetime.now(timezone.utc)
    }
    
    if file_path:
        update_data['file_path'] = file_path
    
    mongo.db.resources.update_one(
        {'_id': ObjectId(resource_id)},
        {'$set': update_data}
    )

def delete_resource(resource_id):
    """Delete a resource."""
    result = mongo.db.resources.delete_one({'_id': ObjectId(resource_id)})
    return result.deleted_count > 0