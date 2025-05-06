"""API endpoints for user management"""
from datetime import datetime
from bson import json_util, ObjectId
import json
from flask import request, jsonify, session
from wellbeing.blueprints.api import api_bp
from wellbeing.utils.decorators import login_required, admin_required, csrf_protected, verify_csrf_token
from wellbeing.models.user import (
    get_all_users, find_user_by_id, create_user, update_user_status, 
    update_user_password, find_user_by_email, find_user_by_student_id
)
from wellbeing import mongo, logger
from werkzeug.security import generate_password_hash, check_password_hash

def parse_json(data):
    """
    Parse MongoDB BSON to JSON-compatible format
    Handles ObjectId and datetime conversions
    """
    return json.loads(json_util.dumps(data))

@api_bp.route('/users', methods=['GET'])
@login_required
@admin_required
def get_users():
    """API endpoint to get all users (admin only)"""
    try:
        users = get_all_users()
        return jsonify(parse_json(users))
    except Exception as e:
        logger.error(f"Error in get_users API: {e}")
        return jsonify({'message': f'Error fetching users: {str(e)}'}), 500

@api_bp.route('/users/<user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    """API endpoint to get a specific user"""
    try:
        # Admins can view any user, regular users can only view themselves
        if session.get('role') != 'admin' and session.get('user') != user_id:
            return jsonify({'message': 'Unauthorized access'}), 403
            
        user = find_user_by_id(user_id)
        if user:
            # Remove sensitive fields
            if 'password' in user:
                del user['password']
            return jsonify(parse_json(user))
        return jsonify({'message': 'User not found'}), 404
    except Exception as e:
        logger.error(f"Error in get_user API: {e}")
        return jsonify({'message': f'Error fetching user: {str(e)}'}), 500

@api_bp.route('/users/search', methods=['GET'])
@login_required
@admin_required
def search_users():
    """API endpoint to search for users (admin only)"""
    try:
        query = request.args.get('q', '')
        
        # Create a case-insensitive search across multiple fields
        search_filter = {
            '$or': [
                {'full_name': {'$regex': query, '$options': 'i'}},
                {'email': {'$regex': query, '$options': 'i'}},
                {'student_id': {'$regex': query, '$options': 'i'}}
            ]
        }
        
        users = get_all_users(search_filter)
        
        # Remove sensitive fields
        for user in users:
            if 'password' in user:
                del user['password']
        
        return jsonify(parse_json(users))
    except Exception as e:
        logger.error(f"Error in search_users API: {e}")
        return jsonify({'message': f'Error searching users: {str(e)}'}), 500

@api_bp.route('/users', methods=['POST'])
@login_required
@admin_required
@csrf_protected
def add_user():
    """API endpoint to add a new user (admin only)"""
    try:
        data = request.json
        
        # Basic validation
        required_fields = ['first_name', 'last_name', 'email', 'student_id', 'password']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'message': f'{field} is required'}), 400
        
        # Check if user with the same email or student ID already exists
        if find_user_by_email(data['email']):
            return jsonify({'message': 'Email already exists'}), 409
        if find_user_by_student_id(data['student_id']):
            return jsonify({'message': 'Student ID already exists'}), 409
        
        # Create user
        user_id = create_user(
            data['first_name'],
            data['last_name'],
            data['email'],
            data['student_id'],
            data['password'],
            data.get('role', 'student')
        )
        
        # Get the created user
        user = find_user_by_id(user_id)
        if 'password' in user:
            del user['password']
            
        return jsonify(parse_json(user)), 201
    except Exception as e:
        logger.error(f"Error in add_user API: {e}")
        return jsonify({'message': f'Error adding user: {str(e)}'}), 500

@api_bp.route('/users/<user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    """API endpoint to delete a user (admin only)"""
    try:
        # Find the user to be deleted
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        # Delete the user
        result = mongo.db.users.delete_one({"_id": ObjectId(user_id)})
        
        if result.deleted_count == 1:
            # Log the deletion
            mongo.db.admin_logs.insert_one({
                "action": "delete_user",
                "user_id": user_id,
                "user_name": user.get("full_name", ""),
                "timestamp": datetime.now(),
                "admin_id": session.get("user")
            })
            
            return jsonify({"success": True, "message": "User deleted successfully"}), 200
        else:
            return jsonify({"success": False, "message": "Failed to delete user"}), 500
            
    except Exception as e:
        logger.error(f"Error in delete_user API: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/users/<user_id>/status', methods=['PUT'])
@login_required
@admin_required
@csrf_protected
def update_user_status_route(user_id):
    """API endpoint to update a user's status (admin only)"""
    try:
        data = request.json
        
        # Check if status is provided
        if 'status' not in data:
            return jsonify({'message': 'Status is required'}), 400
        
        new_status = data['status']
        if new_status not in ['Active', 'Inactive', 'Suspended']:
            return jsonify({'message': 'Invalid status value'}), 400
        
        # Update the user status
        success = update_user_status(user_id, new_status)
        
        if success:
            # Get the updated user
            user = find_user_by_id(user_id)
            if 'password' in user:
                del user['password']
                
            return jsonify(parse_json(user))
        else:
            return jsonify({'message': 'User not found or status update failed'}), 404
            
    except Exception as e:
        logger.error(f"Error in update_user_status API: {e}")
        return jsonify({'message': f'Error updating user status: {str(e)}'}), 500

@api_bp.route('/users/<user_id>/password', methods=['PUT'])
@login_required
@csrf_protected
def update_user_password_route(user_id):
    """API endpoint to update a user's password"""
    try:
        # Admins can update any user's password, regular users can only update their own
        if session.get('role') != 'admin' and session.get('user') != user_id:
            return jsonify({'message': 'Unauthorized access'}), 403
            
        data = request.json
        
        # Check if password is provided
        if 'password' not in data or not data['password']:
            return jsonify({'message': 'New password is required'}), 400
        
        # If it's not an admin, also require the current password
        if session.get('role') != 'admin':
            if 'current_password' not in data or not data['current_password']:
                return jsonify({'message': 'Current password is required'}), 400
                
            # Verify current password
            user = find_user_by_id(user_id)
            if not user:
                return jsonify({'message': 'User not found'}), 404
                
            if not check_password_hash(user.get('password', ''), data['current_password']):
                return jsonify({'message': 'Current password is incorrect'}), 401
        
        # Update the password
        success = update_user_password(user_id, data['password'])
        
        if success:
            return jsonify({'message': 'Password updated successfully'})
        else:
            return jsonify({'message': 'User not found or password update failed'}), 404
            
    except Exception as e:
        logger.error(f"Error in update_user_password API: {e}")
        return jsonify({'message': f'Error updating password: {str(e)}'}), 500

@api_bp.route('/users/<user_id>', methods=['PUT'])
@login_required
@admin_required
@csrf_protected
def update_user(user_id):
    """API endpoint to update a user (admin only)"""
    try:
        data = request.json
        
        # Find the user to update
        user = find_user_by_id(user_id)
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        # Prepare fields to update
        update_data = {}
        
        # Process allowed fields
        allowed_fields = [
            'first_name', 'last_name', 'email', 'student_id', 
            'role', 'status'
        ]
        
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        # Special handling for email and student_id to check uniqueness
        if 'email' in update_data and update_data['email'] != user.get('email'):
            if find_user_by_email(update_data['email']):
                return jsonify({'message': 'Email already exists'}), 409
                
        if 'student_id' in update_data and update_data['student_id'] != user.get('student_id'):
            if find_user_by_student_id(update_data['student_id']):
                return jsonify({'message': 'Student ID already exists'}), 409
        
        # Update full_name if first_name or last_name changed
        if 'first_name' in update_data or 'last_name' in update_data:
            first_name = update_data.get('first_name', user.get('first_name', ''))
            last_name = update_data.get('last_name', user.get('last_name', ''))
            update_data['full_name'] = f"{first_name} {last_name}"
        
        # Update the user in the database
        if update_data:
            # Add last update timestamp
            update_data['updated_at'] = datetime.now()
            
            result = mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': update_data}
            )
            
            if result.modified_count == 0 and result.matched_count == 0:
                return jsonify({'message': 'User not found'}), 404
                
            # Get the updated user
            updated_user = find_user_by_id(user_id)
            if 'password' in updated_user:
                del updated_user['password']
                
            return jsonify(parse_json(updated_user))
        else:
            # No fields to update
            return jsonify({'message': 'No valid fields to update'}), 400
            
    except Exception as e:
        logger.error(f"Error in update_user API: {e}")
        return jsonify({'message': f'Error updating user: {str(e)}'}), 500