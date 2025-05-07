"""
Admin routes for dashboard, user management, and system features
"""
from datetime import datetime, timezone
from bson.objectid import ObjectId
import secrets
import string
from werkzeug.security import generate_password_hash
import pandas as pd
from flask import render_template, redirect, url_for, request, jsonify, flash, make_response, session
from wellbeing.blueprints.admin import admin_bp
from wellbeing.utils.decorators import login_required, admin_required, csrf_protected
from wellbeing import mongo, logger
from wellbeing.utils.file_handlers import handle_video_upload
from wellbeing.models.user import find_user_by_id, get_all_users
from wellbeing.models.resource import create_resource, update_resource, delete_resource
from wellbeing.services.feedback_service import export_training_data, analyze_feedback_data


# Helper function to generate a random password
def generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Admin dashboard with system overview."""
    # Fetch data from MongoDB for the dashboard
    total_users = mongo.db.users.count_documents({})
    total_chats = mongo.db.chats.count_documents({})
    
    # Calculate active users today based on the chats collection
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Count unique users who chatted today
    try:
        unique_users_today = len(mongo.db.chats.distinct('user_id', {
            'timestamp': {'$gte': today}
        }))
        active_today = unique_users_today
    except Exception as e:
        logger.error(f"Error calculating active users: {e}")
        active_today = 0
    
    # Get recent activity from the chats collection
    recent_activity = []
    
    try:
        recent_activity_cursor = mongo.db.chats.find().sort('timestamp', -1).limit(10)
        
        for msg in recent_activity_cursor:
            try:
                # Get user information
                user_id = msg.get('user_id')
                user = None
                username = "Unknown"
                
                if user_id:
                    try:
                        # Try to find the user in the users collection
                        if isinstance(user_id, ObjectId):
                            user = mongo.db.users.find_one({'_id': user_id})
                        elif isinstance(user_id, str) and ObjectId.is_valid(user_id):
                            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                    except Exception as e:
                        pass
                
                # Extract username from user document
                if user:
                    if 'first_name' in user and 'last_name' in user:
                        username = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    elif 'email' in user:
                        username = user.get('email', 'Unknown')
                
                # Process confidence
                confidence = 0
                if 'confidence' in msg:
                    raw_value = msg['confidence']
                    
                    try:
                        confidence_float = float(raw_value)
                        # If it's a decimal (0-1), convert to percentage
                        if confidence_float <= 1.0:
                            confidence = confidence_float * 100
                        else:
                            confidence = confidence_float
                    except Exception as e:
                        pass
                
                # Add activity to the list
                timestamp_str = "Unknown"
                try:
                    if msg.get('timestamp'):
                        if hasattr(msg['timestamp'], 'strftime'):
                            timestamp_str = msg['timestamp'].strftime('%Y-%m-%d %H:%M')
                        else:
                            timestamp_str = str(msg['timestamp'])
                except:
                    pass
                    
                recent_activity.append({
                    'user': username,
                    'message': msg.get('message', ''),
                    'response': msg.get('response', ''),
                    'timestamp': timestamp_str,
                    'confidence': float(confidence)
                })
                
            except Exception as e:
                logger.error(f"Error processing activity message: {e}")
    except Exception as e:
        logger.error(f"Error fetching chat data: {e}")
    
    return render_template('admin_dashboard.html', 
                         total_users=total_users,
                         total_chats=total_chats,
                         active_today=active_today,
                         recent_activity=recent_activity)

@admin_bp.route('/dashboard/data')
@login_required
@admin_required
def dashboard_data():
    """API endpoint to get fresh dashboard data (for AJAX refresh)."""
    # Fetch updated data from MongoDB
    total_users = mongo.db.users.count_documents({})
    total_chats = mongo.db.chats.count_documents({})
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        unique_users_today = len(mongo.db.chats.distinct('user_id', {
            'timestamp': {'$gte': today}
        }))
        active_today = unique_users_today
    except Exception as e:
        active_today = 0
    
    recent_activity = []
    try:
        recent_activity_cursor = mongo.db.chats.find().sort('timestamp', -1).limit(10)
        
        for msg in recent_activity_cursor:
            try:
                # Get user information
                user_id = msg.get('user_id')
                user = find_user_by_id(user_id)
                username = "Unknown"
                
                # Extract username from user document
                if user:
                    if 'first_name' in user and 'last_name' in user:
                        username = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    elif 'email' in user:
                        username = user.get('email', 'Unknown')
                
                # Process confidence
                confidence = 0
                if 'confidence' in msg:
                    try:
                        confidence_float = float(msg['confidence'])
                        confidence = confidence_float * 100 if confidence_float <= 1.0 else confidence_float
                    except:
                        pass
                
                # Format timestamp for display
                timestamp_str = "Unknown"
                try:
                    if msg.get('timestamp'):
                        if hasattr(msg['timestamp'], 'strftime'):
                            timestamp_str = msg['timestamp'].strftime('%Y-%m-%d %H:%M')
                        else:
                            timestamp_str = str(msg['timestamp'])
                except:
                    pass
                
                recent_activity.append({
                    'user': username,
                    'message': msg.get('message', ''),
                    'response': msg.get('response', ''),
                    'timestamp': timestamp_str,
                    'confidence': float(confidence)
                })
            except Exception as e:
                logger.error(f"Error processing activity: {e}")
    except Exception as e:
        logger.error(f"Error fetching activity data: {e}")
    
    return jsonify({
        'total_users': total_users,
        'total_chats': total_chats,
        'active_today': active_today,
        'recent_activity': recent_activity
    })

@admin_bp.route('/resources', methods=['GET', 'POST'])
@login_required
@admin_required
def resources():
    """Resource management page."""
    # Handle resource creation if POST
    if request.method == 'POST':
        data = request.form
        
        # Create new resource
        file_path = None
        
        # Handle file upload for video resources
        if data.get('type') == 'video' and 'video_file' in request.files:
            video_file = request.files['video_file']
            if video_file and video_file.filename:
                file_path = handle_video_upload(video_file)
        
        create_resource(
            title=data.get('title'),
            description=data.get('description'),
            resource_type=data.get('type'),
            content=data.get('content'),
            created_by=session.get('user'),
            file_path=file_path
        )
        
        flash('Resource added successfully!', 'success')
        return redirect(url_for('admin.resources'))
    
    # GET request - show resources
    resources = list(mongo.db.resources.find())
    return render_template('admin_resources.html', resources=resources)

@admin_bp.route('/resources/<resource_id>', methods=['PUT'])
@login_required
@admin_required
@csrf_protected
def update_resource_route(resource_id):
    """Update a resource."""
    data = request.form
    
    # Handle file upload for video resources
    file_path = None
    if data.get('type') == 'video' and 'video_file' in request.files:
        video_file = request.files['video_file']
        if video_file and video_file.filename:
            file_path = handle_video_upload(video_file)
    
    # Update the resource
    update_resource(
        resource_id=resource_id,
        title=data.get('title'),
        description=data.get('description'),
        resource_type=data.get('type'),
        content=data.get('content'),
        file_path=file_path
    )
    
    flash('Resource updated successfully!', 'success')
    return redirect(url_for('admin.resources'))

@admin_bp.route('/resources/<resource_id>', methods=['DELETE'])
@login_required
@admin_required
@csrf_protected
def delete_resource_route(resource_id):
    """Delete a resource."""
    # Delete the resource and its file if applicable
    success = delete_resource(resource_id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to delete resource'}), 500


@admin_bp.route('/chat-logs')
@login_required
@admin_required
def chat_logs():
    """Chat logs page with filtering and pagination."""
    # Get query parameters for filtering
    search_query = request.args.get('search', '')
    date_filter = request.args.get('date', '')
    topic_filter = request.args.get('topic', '')
    
    # Get current page from query params (default to page 1)
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except:
        page = 1
    
    # Items per page
    per_page = 10
    
    # Build query filter
    query_filter = {}
    
    # Add search filter if provided
    if search_query:
        # Try to match against message content or user_id
        query_filter['$or'] = [
            {'message': {'$regex': search_query, '$options': 'i'}},
            {'user_id': {'$regex': search_query, '$options': 'i'}}
        ]
    
    # Add date filter if provided
    if date_filter:
        try:
            # Convert string date to datetime object for the filter
            from datetime import datetime, timedelta
            
            # Parse the date string
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d')
            
            # Create date range for the entire day
            start_of_day = filter_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            # Add date range filter
            query_filter['timestamp'] = {'$gte': start_of_day, '$lt': end_of_day}
        except Exception as e:
            logger.error(f"Error parsing date filter: {e}")
    
    # Add topic filter if provided
    if topic_filter:
        # Check if we're using a topic field directly or it's nested
        query_filter['$or'] = query_filter.get('$or', []) + [
            {'conversation_context.topic': topic_filter},
            {'topic': topic_filter}
        ]
    
    try:
        # Get total count for pagination
        total_items = mongo.db.chats.count_documents(query_filter)
        total_pages = (total_items + per_page - 1) // per_page
        
        # Ensure page is within valid range
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        # Calculate skip value for pagination
        skip = (page - 1) * per_page
        
        # Fetch chat logs with pagination
        chat_logs_cursor = mongo.db.chats.find(query_filter).sort('timestamp', -1).skip(skip).limit(per_page)
        
        # Process the chat logs to add additional information
        chat_logs = []
        for chat in chat_logs_cursor:
            # Convert ObjectId to string for serialization
            chat['_id'] = str(chat['_id'])
            
            # Try to get username if available
            if 'user_id' in chat:
                user_id = chat['user_id']
                user = find_user_by_id(user_id)
                
                # Extract username from user document
                if user:
                    # Try different fields where username might be stored
                    if 'username' in user and user['username']:
                        chat['username'] = user['username']
                    elif 'full_name' in user and user['full_name']:
                        chat['username'] = user['full_name']
                    elif 'first_name' in user and 'last_name' in user:
                        chat['username'] = f"{user['first_name']} {user['last_name']}".strip()
                    elif 'email' in user and user['email']:
                        chat['username'] = user['email']
            
            # Process confidence score
            if 'confidence' in chat:
                try:
                    confidence_value = float(chat['confidence'])
                    chat['confidence'] = confidence_value * 100 if confidence_value <= 1.0 else confidence_value
                except:
                    pass
            
            chat_logs.append(chat)
        
        # Get unique topics for the dropdown
        topics_cursor = mongo.db.chats.aggregate([
            {'$group': {'_id': '$conversation_context.topic'}},
            {'$match': {'_id': {'$ne': None}}},
            {'$sort': {'_id': 1}}
        ])
        
        topics = [doc['_id'] for doc in topics_cursor if doc['_id']]
        
        # If no topics found from the above query, try an alternative field
        if not topics:
            topics_cursor = mongo.db.chats.aggregate([
                {'$group': {'_id': '$topic'}},
                {'$match': {'_id': {'$ne': None}}},
                {'$sort': {'_id': 1}}
            ])
            topics = [doc['_id'] for doc in topics_cursor if doc['_id']]
        
        # If still no topics, provide default ones
        if not topics:
            topics = ['academic', 'health', 'technical', 'financial', 'other']
        
        return render_template('chat_logs.html', 
                              chat_logs=chat_logs,
                              topics=topics,
                              page=page,
                              total_pages=total_pages)
        
    except Exception as e:
        logger.error(f"Error in chat_logs route: {e}")
        
        # Return empty data with error message
        return render_template('chat_logs.html', 
                              chat_logs=[],
                              topics=[],
                              page=1,
                              total_pages=1,
                              error=str(e))

@admin_bp.route('/view-chat/<chat_id>')
@login_required
@admin_required
def view_chat(chat_id):
    """View details of a specific chat."""
    try:
        # Find the chat by ID
        chat = mongo.db.chats.find_one({'_id': ObjectId(chat_id)})
        
        if not chat:
            flash('Chat not found', 'error')
            return redirect(url_for('admin.chat_logs'))
        
        # Try to get username if available
        username = "Unknown"
        if 'user_id' in chat:
            user_id = chat['user_id']
            user = find_user_by_id(user_id)
            
            # Extract username from user document
            if user:
                # Try different fields where username might be stored
                if 'username' in user and user['username']:
                    username = user['username']
                elif 'full_name' in user and user['full_name']:
                    username = user['full_name']
                elif 'first_name' in user and 'last_name' in user:
                    username = f"{user['first_name']} {user['last_name']}".strip()
                elif 'email' in user and user['email']:
                    username = user['email']
        
        # Process confidence score
        if 'confidence' in chat:
            try:
                confidence_value = float(chat['confidence'])
                chat['confidence'] = confidence_value * 100 if confidence_value <= 1.0 else confidence_value
            except:
                pass
        
        # Get other chats from the same user (for context)
        user_id = chat.get('user_id')
        related_chats = []
        
        if user_id:
            related_chats_cursor = mongo.db.chats.find({
                'user_id': user_id,
                '_id': {'$ne': ObjectId(chat_id)}  # Exclude current chat
            }).sort('timestamp', -1).limit(5)
            
            related_chats = list(related_chats_cursor)
            
            # Convert ObjectId to string for each related chat
            for related in related_chats:
                related['_id'] = str(related['_id'])
        
        # Convert ObjectId to string for serialization
        chat['_id'] = str(chat['_id'])
        
        return render_template('view_chat.html', 
                            chat=chat,
                            username=username,
                            related_chats=related_chats)
    
    except Exception as e:
        logger.error(f"Error viewing chat: {e}")
        
        flash(f'Error viewing chat: {str(e)}', 'error')
        return redirect(url_for('admin.chat_logs'))

@admin_bp.route('/delete-chat/<chat_id>', methods=['POST'])
@login_required
@admin_required
@csrf_protected
def delete_chat(chat_id):
    """Delete a chat message."""
    try:
        # Convert chat_id to ObjectId
        chat_obj_id = ObjectId(chat_id)
        
        # Find the chat first to check if it exists
        chat = mongo.db.chats.find_one({'_id': chat_obj_id})
        
        if not chat:
            flash('Chat not found', 'error')
            return redirect(url_for('admin.chat_logs'))
        
        # Delete the chat
        mongo.db.chats.delete_one({'_id': chat_obj_id})
        
        # Add a log entry for this deletion
        mongo.db.admin_logs.insert_one({
            'action': 'delete_chat',
            'chat_id': str(chat_obj_id),
            'admin_id': session.get('user'),
            'timestamp': datetime.now(timezone.utc),
            'details': {
                'user_id': chat.get('user_id'),
                'message': chat.get('message', '')[:100]  # Store truncated message for reference
            }
        })
        
        flash('Chat deleted successfully', 'success')
        return redirect(url_for('admin.chat_logs'))
        
    except Exception as e:
        logger.error(f"Error deleting chat: {e}")
        
        flash(f'Error deleting chat: {str(e)}', 'error')
        return redirect(url_for('admin.chat_logs'))

@admin_bp.route('/feedback-dashboard')
@login_required
@admin_required
def feedback_dashboard():
    """Dashboard for viewing feedback statistics and recommendations."""
    try:
        # Get feedback statistics
        total_chats = mongo.db.chats.count_documents({})
        chats_with_feedback = mongo.db.chats.count_documents({"feedback": {"$exists": True}})
        positive_feedback = mongo.db.chats.count_documents({"feedback.was_helpful": True})
        negative_feedback = mongo.db.chats.count_documents({"feedback.was_helpful": False})
        
        # Calculate average ratings
        pipeline = [
            {"$match": {"feedback.rating": {"$exists": True}}},
            {"$group": {"_id": None, "avg_rating": {"$avg": "$feedback.rating"}}}
        ]
        avg_rating_result = list(mongo.db.chats.aggregate(pipeline))
        avg_rating = avg_rating_result[0]['avg_rating'] if avg_rating_result else 0
        
        # Get latest recommendations
        latest_recommendation = mongo.db.improvement_recommendations.find_one(
            sort=[("timestamp", -1)]
        )
        
        # Get topics with low ratings
        pipeline = [
            {"$match": {"feedback.rating": {"$lt": 3}}},
            {"$group": {
                "_id": "$conversation_context.topic", 
                "count": {"$sum": 1},
                "avg_rating": {"$avg": "$feedback.rating"}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        problematic_topics = list(mongo.db.chats.aggregate(pipeline))
        
        # Render the dashboard template with data
        return render_template(
            'feedback_dashboard.html',
            stats={
                "total_chats": total_chats,
                "chats_with_feedback": chats_with_feedback,
                "feedback_rate": (chats_with_feedback / total_chats * 100) if total_chats > 0 else 0,
                "positive_feedback": positive_feedback,
                "negative_feedback": negative_feedback,
                "positive_rate": (positive_feedback / chats_with_feedback * 100) if chats_with_feedback > 0 else 0,
                "avg_rating": round(avg_rating, 2)
            },
            recommendations=latest_recommendation['recommendations'] if latest_recommendation and 'recommendations' in latest_recommendation else [],
            problematic_topics=problematic_topics
        )
        
    except Exception as e:
        logger.error(f"Error rendering feedback dashboard: {e}")
        flash('Error loading dashboard data', 'error')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/export-training-data')
@login_required
@admin_required
def export_training_data_route():
    """Exports high-quality training examples based on positive feedback."""
    try:
        # Get quality filter parameters from query string
        min_rating = int(request.args.get('min_rating', 4))
        helpful_only = request.args.get('helpful_only', 'true').lower() == 'true'
        
        # Get the training data
        training_df = export_training_data(min_rating, helpful_only)
        
        if training_df is not None and not training_df.empty:
            # Convert to CSV
            csv_data = training_df.to_csv(index=False)
            
            # Prepare CSV download response
            response = make_response(csv_data)
            response.headers["Content-Disposition"] = "attachment; filename=positive_training_data.csv"
            response.headers["Content-Type"] = "text/csv"
            return response
        else:
            flash('No matching positive feedback data available', 'warning')
            return redirect(url_for('admin.feedback_dashboard'))
            
    except Exception as e:
        logger.error(f"Error exporting training data: {e}")
        flash('Error exporting training data', 'error')
        return redirect(url_for('admin.feedback_dashboard'))
    
@admin_bp.route('/therapists', methods=['GET', 'POST'])
@admin_required
def therapist_management():
    """View and manage therapists"""
    try:
        # Get all therapists sorted by last name
        therapists = list(mongo.db.therapists.find().sort('last_name', 1))
        
        # Get student counts for each therapist
        for therapist in therapists:
            # Ensure proper ObjectId handling for MongoDB queries
            therapist_id = therapist['_id']
            student_count = mongo.db.appointments.count_documents({
                'therapist_id': therapist_id,
                'status': 'active'
            })
            therapist['student_count'] = student_count
            
        return render_template(
            'admin/therapists.html',  # Original template name
            therapists=therapists
        )
    except Exception as e:
        logger.error(f"Manage therapists error: {e}")
        flash('An error occurred while loading therapist data', 'error')
        return redirect(url_for('admin.therapist_management'))  # Changed redirect URL

@admin_bp.route('/therapists/create', methods=['GET', 'POST'])
@admin_required
def create_therapist():
    """Create a new therapist account"""
    try:
        if request.method == 'POST':
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            specialization = request.form.get('specialization', '').strip()
            office_hours = request.form.get('office_hours', '').strip()
            
            # Validate input
            if not first_name or not last_name or not email:
                flash('First name, last name, and email are required', 'error')
                return redirect(url_for('admin.create_therapist'))
            
            # Check if email already exists
            if mongo.db.therapists.find_one({'email': email}):
                flash('A therapist with this email already exists', 'error')
                return redirect(url_for('admin.create_therapist'))
            
            # Generate a random password
            temp_password = generate_random_password()
            hashed_password = generate_password_hash(temp_password)
            
            # Create therapist document
            new_therapist = {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'specialization': specialization,
                'office_hours': office_hours,
                'role': 'therapist',
                'password': hashed_password,
                'status': 'Active',
                'created_at': datetime.now(),
                'last_login': None,
                'bio': '',
                'credentials': ''
            }
            
            # Insert therapist
            result = mongo.db.therapists.insert_one(new_therapist)
            
            if result.inserted_id:
                # Display password to admin (safer than sending email in development)
                flash(f'Therapist account created successfully. Temporary password: {temp_password}', 'success')
                return redirect(url_for('admin.therapist_management'))
            else:
                flash('Failed to create therapist account', 'error')
                return redirect(url_for('admin.create_therapist'))
        
        return render_template('admin/create_therapist.html')
        
    except Exception as e:
        logger.error(f"Create therapist error: {e}")
        flash('An error occurred while creating the therapist account', 'error')
        return redirect(url_for('admin.therapist_management'))

@admin_bp.route('/therapists/<therapist_id>/reset-password', methods=['POST'])
@admin_required
def reset_therapist_password(therapist_id):
    """Reset a therapist's password"""
    try:
        # Get therapist data
        therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
        
        if not therapist:
            flash('Therapist not found', 'error')
            return redirect(url_for('admin.therapist_management'))
        
        # Generate a new random password
        new_password = generate_random_password()
        hashed_password = generate_password_hash(new_password)
        
        # Update therapist password
        result = mongo.db.therapists.update_one(
            {'_id': ObjectId(therapist_id)},
            {'$set': {'password': hashed_password}}
        )
        
        if result.modified_count:
            # Display password to admin (safer than sending email in development)
            flash(f'Password reset successfully. New password: {new_password}', 'success')
        else:
            flash('Failed to reset therapist password', 'error')
            
        return redirect(url_for('admin.therapist_management'))
        
    except Exception as e:
        logger.error(f"Reset therapist password error: {e}")
        flash('An error occurred while resetting the therapist password', 'error')
        return redirect(url_for('admin.therapist_management'))

@admin_bp.route('/therapists/<therapist_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_therapist_status(therapist_id):
    """Activate or deactivate a therapist account"""
    try:
        # Get therapist data
        therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
        
        if not therapist:
            flash('Therapist not found', 'error')
            return redirect(url_for('admin.therapist_management'))
        
        # Toggle status
        new_status = 'Inactive' if therapist.get('status') == 'Active' else 'Active'
        
        # Update therapist status
        result = mongo.db.therapists.update_one(
            {'_id': ObjectId(therapist_id)},
            {'$set': {'status': new_status}}
        )
        
        if result.modified_count:
            action = 'deactivated' if new_status == 'Inactive' else 'activated'
            flash(f'Therapist account {action} successfully', 'success')
        else:
            flash('Failed to update therapist status', 'error')
            
        return redirect(url_for('admin.therapist_management'))
        
    except Exception as e:
        logger.error(f"Toggle therapist status error: {e}")
        flash('An error occurred while updating the therapist status', 'error')
        return redirect(url_for('admin.therapist_management'))

@admin_bp.route('/add-therapist', methods=['GET', 'POST'])
@admin_required
def add_therapist():
    """Add a new therapist."""
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            specialization = request.form.get('specialization', '').strip()
            office_hours = request.form.get('office_hours', '').strip()
            password = request.form.get('password', '')
            
            # Validate form data
            if not first_name or not last_name or not email or not specialization or not password:
                flash('All fields are required', 'error')
                return redirect(url_for('admin.add_therapist'))
            
            # Check if email is already in use
            existing_user = mongo.db.users.find_one({'email': email})
            if existing_user:
                flash('Email is already in use', 'error')
                return redirect(url_for('admin.add_therapist'))
            
            # Create therapist user
            from werkzeug.security import generate_password_hash
            
            # Insert into users collection
            new_user = {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'role': 'therapist',
                'password': generate_password_hash(password),
                'created_at': datetime.now(timezone.utc),
                'last_login': None,
                'login_count': 0,
                'status': 'active'
            }
            
            user_result = mongo.db.users.insert_one(new_user)
            
            # Insert into therapists collection
            new_therapist = {
                '_id': user_result.inserted_id,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'specialization': specialization,
                'office_hours': {
                    'description': office_hours,
                    'days': [0, 1, 2, 3, 4],  # Monday-Friday
                    'slots': ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']
                },
                'max_students': 20,
                'current_students': 0,
                'status': 'Active',
                'created_at': datetime.now(timezone.utc)
            }
            
            therapist_result = mongo.db.therapists.insert_one(new_therapist)
            
            # Log activity
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'add_therapist',
                'details': f'Added therapist: {first_name} {last_name}',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Therapist added successfully', 'success')
            return redirect(url_for('admin.therapists'))
            
        except Exception as e:
            logger.error(f"Add therapist error: {e}")
            flash('An error occurred while adding the therapist', 'error')
            return redirect(url_for('admin.add_therapist'))
    
    return render_template('admin/add_therapist.html')

@admin_bp.route('/edit-therapist/<therapist_id>', methods=['GET', 'POST'])
@admin_required
def edit_therapist(therapist_id):
    """Edit therapist details."""
    therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
    
    if not therapist:
        flash('Therapist not found', 'error')
        return redirect(url_for('admin.therapists'))
    
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            specialization = request.form.get('specialization', '').strip()
            office_hours = request.form.get('office_hours', '').strip()
            max_students = int(request.form.get('max_students', 20))
            status = request.form.get('status', 'Active')
            
            # Validate form data
            if not first_name or not last_name or not email or not specialization:
                flash('All fields are required', 'error')
                return redirect(url_for('admin.edit_therapist', therapist_id=therapist_id))
            
            # Check if email is already in use by another user
            existing_user = mongo.db.users.find_one({'email': email, '_id': {'$ne': ObjectId(therapist_id)}})
            if existing_user:
                flash('Email is already in use by another user', 'error')
                return redirect(url_for('admin.edit_therapist', therapist_id=therapist_id))
            
            # Update therapist document
            mongo.db.therapists.update_one(
                {'_id': ObjectId(therapist_id)},
                {'$set': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'specialization': specialization,
                    'office_hours': {
                        'description': office_hours,
                        'days': [0, 1, 2, 3, 4],  # Monday-Friday
                        'slots': ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']
                    },
                    'max_students': max_students,
                    'status': status
                }}
            )
            
            # Update user document
            mongo.db.users.update_one(
                {'_id': ObjectId(therapist_id)},
                {'$set': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'status': 'active' if status == 'Active' else 'inactive'
                }}
            )
            
            # Log activity
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'edit_therapist',
                'details': f'Updated therapist: {first_name} {last_name}',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Therapist updated successfully', 'success')
            return redirect(url_for('admin.therapists'))
            
        except Exception as e:
            logger.error(f"Edit therapist error: {e}")
            flash('An error occurred while updating the therapist', 'error')
            return redirect(url_for('admin.edit_therapist', therapist_id=therapist_id))
    
    return render_template('admin/edit_therapist.html', therapist=therapist)

@admin_bp.route('/deactivate-therapist/<therapist_id>', methods=['POST'])
@admin_required
def deactivate_therapist(therapist_id):
    """Deactivate a therapist."""
    therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
    
    if not therapist:
        flash('Therapist not found', 'error')
        return redirect(url_for('admin.therapists'))
    
    try:
        # Update therapist status
        mongo.db.therapists.update_one(
            {'_id': ObjectId(therapist_id)},
            {'$set': {'status': 'Inactive'}}
        )
        
        # Update user status
        mongo.db.users.update_one(
            {'_id': ObjectId(therapist_id)},
            {'$set': {'status': 'inactive'}}
        )
        
        # Log activity
        mongo.db.admin_logs.insert_one({
            'admin_id': ObjectId(session['user']),
            'action': 'deactivate_therapist',
            'details': f'Deactivated therapist: {therapist["first_name"]} {therapist["last_name"]}',
            'timestamp': datetime.now(timezone.utc)
        })
        
        flash('Therapist deactivated successfully', 'success')
        
    except Exception as e:
        logger.error(f"Deactivate therapist error: {e}")
        flash('An error occurred while deactivating the therapist', 'error')
    
    return redirect(url_for('admin.therapists'))

@admin_bp.route('/students')
@admin_required
def students():
    """Manage students."""
    # Get all students
    students = list(mongo.db.users.find({'role': 'student'}).sort('last_name', 1))
    
    return render_template('admin/students.html', students=students)

@admin_bp.route('/student-details/<student_id>')
@admin_required
def student_details(student_id):
    """View student details."""
    student = mongo.db.users.find_one({'_id': ObjectId(student_id), 'role': 'student'})
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('admin.students'))
    
    # Get therapist assignment
    assignment = mongo.db.therapist_assignments.find_one({'student_id': ObjectId(student_id), 'status': 'active'})
    
    therapist = None
    if assignment:
        therapist = mongo.db.therapists.find_one({'_id': assignment['therapist_id']})
    
    # Get recent appointments
    appointments = list(mongo.db.appointments.find({'student_id': ObjectId(student_id)}).sort('date', -1).limit(10))
    
    # Get mood data
    moods = list(mongo.db.moods.find({'user_id': str(student_id)}).sort('timestamp', -1).limit(10))
    
    return render_template('admin/student_details.html', 
                         student=student, 
                         therapist=therapist, 
                         appointments=appointments,
                         moods=moods)

@admin_bp.route('/therapist-requests')
@admin_required
def therapist_requests():
    """Manage pending therapist requests."""
    # Get all pending requests
    pending_requests = list(mongo.db.therapist_requests.find({'status': 'pending'}).sort('created_at', 1))
    
    # Get student details for each request
    for request in pending_requests:
        student = mongo.db.users.find_one({'_id': request['student_id']})
        if student:
            request['student_name'] = f"{student['first_name']} {student['last_name']}"
            request['student_email'] = student['email']
    
    return render_template('admin/therapist_requests.html', requests=pending_requests)

@admin_bp.route('/assign-therapist/<request_id>', methods=['GET', 'POST'])
@admin_required
def assign_therapist(request_id):
    """Assign a therapist to a student request."""
    request_data = mongo.db.therapist_requests.find_one({'_id': ObjectId(request_id)})
    
    if not request_data:
        flash('Request not found', 'error')
        return redirect(url_for('admin.therapist_requests'))
    
    if request_data['status'] != 'pending':
        flash('This request has already been processed', 'warning')
        return redirect(url_for('admin.therapist_requests'))
    
    student = mongo.db.users.find_one({'_id': request_data['student_id']})
    
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('admin.therapist_requests'))
    
    if request.method == 'POST':
        try:
            therapist_id = request.form.get('therapist_id')
            
            if not therapist_id:
                flash('Please select a therapist', 'error')
                return redirect(url_for('admin.assign_therapist', request_id=request_id))
            
            therapist = mongo.db.therapists.find_one({'_id': ObjectId(therapist_id)})
            
            if not therapist:
                flash('Selected therapist not found', 'error')
                return redirect(url_for('admin.assign_therapist', request_id=request_id))
            
            # Check therapist capacity
            if therapist['current_students'] >= therapist['max_students']:
                flash('Selected therapist has reached maximum student capacity', 'error')
                return redirect(url_for('admin.assign_therapist', request_id=request_id))
            
            # Create assignment
            assignment = {
                'student_id': student['_id'],
                'therapist_id': therapist['_id'],
                'status': 'active',
                'created_at': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc),
                'notes': 'Assigned by admin based on student request'
            }
            
            assignment_result = mongo.db.therapist_assignments.insert_one(assignment)
            
            # Update therapist's current student count
            mongo.db.therapists.update_one(
                {'_id': therapist['_id']},
                {'$inc': {'current_students': 1}}
            )
            
            # Update request status
            mongo.db.therapist_requests.update_one(
                {'_id': ObjectId(request_id)},
                {'$set': {
                    'status': 'approved',
                    'therapist_id': therapist['_id'],
                    'updated_at': datetime.now(timezone.utc),
                    'processed_by': ObjectId(session['user'])
                }}
            )
            
            # Log activity
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'assign_therapist',
                'details': f'Assigned therapist {therapist["first_name"]} {therapist["last_name"]} to student {student["first_name"]} {student["last_name"]}',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Therapist assigned successfully', 'success')
            return redirect(url_for('admin.therapist_requests'))
            
        except Exception as e:
            logger.error(f"Assign therapist error: {e}")
            flash('An error occurred while assigning the therapist', 'error')
            return redirect(url_for('admin.assign_therapist', request_id=request_id))
    
    # Get available therapists (with capacity)
    available_therapists = list(mongo.db.therapists.find(
        {'status': 'Active', 'current_students': {'$lt': '$max_students'}}
    ).sort('current_students', 1))
    
    return render_template('admin/assign_therapist.html', 
                         request=request_data, 
                         student=student,
                         therapists=available_therapists)

@admin_bp.route('/reject-request/<request_id>', methods=['POST'])
@admin_required
def reject_request(request_id):
    """Reject a therapist request."""
    request_data = mongo.db.therapist_requests.find_one({'_id': ObjectId(request_id)})
    
    if not request_data:
        flash('Request not found', 'error')
        return redirect(url_for('admin.therapist_requests'))
    
    if request_data['status'] != 'pending':
        flash('This request has already been processed', 'warning')
        return redirect(url_for('admin.therapist_requests'))
    
    reason = request.form.get('reason', '')
    
    try:
        # Update request status
        mongo.db.therapist_requests.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': {
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now(timezone.utc),
                'processed_by': ObjectId(session['user'])
            }}
        )
        
        # Get student info for logging
        student = mongo.db.users.find_one({'_id': request_data['student_id']})
        student_name = f"{student['first_name']} {student['last_name']}" if student else "Unknown student"
        
        # Log activity
        mongo.db.admin_logs.insert_one({
            'admin_id': ObjectId(session['user']),
            'action': 'reject_request',
            'details': f'Rejected therapist request from {student_name}',
            'timestamp': datetime.now(timezone.utc)
        })
        
        flash('Request rejected successfully', 'success')
        
    except Exception as e:
        logger.error(f"Reject request error: {e}")
        flash('An error occurred while rejecting the request', 'error')
    
    return redirect(url_for('admin.therapist_requests'))

@admin_bp.route('/appointments')
@admin_required
def appointments():
    """View all appointments."""
    # Get filter parameters
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    status = request.args.get('status', '')
    
    # Build query
    query = {}
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query['date'] = {'$gte': from_date}
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            if 'date' in query:
                query['date']['$lte'] = to_date
            else:
                query['date'] = {'$lte': to_date}
        except ValueError:
            pass
    
    if status and status != 'all':
        query['status'] = status
    
    # Get appointments
    appointments = list(mongo.db.appointments.find(query).sort('date', -1).limit(100))
    
    # Get additional data for each appointment
    for appt in appointments:
        # Get student info
        student = mongo.db.users.find_one({'_id': appt['student_id']})
        if student:
            appt['student_name'] = f"{student['first_name']} {student['last_name']}"
        else:
            appt['student_name'] = "Unknown"
        
        # Get therapist info
        therapist = mongo.db.therapists.find_one({'_id': appt['therapist_id']})
        if therapist:
            appt['therapist_name'] = f"Dr. {therapist['first_name']} {therapist['last_name']}"
        else:
            appt['therapist_name'] = "Unknown"
    
    return render_template('admin/appointments.html', appointments=appointments)


@admin_bp.route('/reports')
@admin_required
def reports():
    """View system reports."""
    # Example report data
    reports = {
        'user_stats': {
            'total_users': mongo.db.users.count_documents({}),
            'active_students': mongo.db.users.count_documents({'role': 'student', 'status': 'active'}),
            'active_therapists': mongo.db.users.count_documents({'role': 'therapist', 'status': 'active'}),
            'new_users_this_month': mongo.db.users.count_documents({
                'created_at': {'$gte': datetime.now().replace(day=1, hour=0, minute=0, second=0)}
            })
        },
        'appointment_stats': {
            'total_appointments': mongo.db.appointments.count_documents({}),
            'completed_sessions': mongo.db.appointments.count_documents({'status': 'completed'}),
            'cancelled_sessions': mongo.db.appointments.count_documents({'status': 'cancelled'}),
            'pending_sessions': mongo.db.appointments.count_documents({'status': 'pending'}),
            'upcoming_sessions': mongo.db.appointments.count_documents({
                'date': {'$gte': datetime.now()},
                'status': 'scheduled'
            })
        },
        'therapist_load': []
    }
    
    # Get therapist load
    therapists = list(mongo.db.therapists.find({'status': 'Active'}).sort('current_students', -1))
    for therapist in therapists:
        reports['therapist_load'].append({
            'name': f"Dr. {therapist['first_name']} {therapist['last_name']}",
            'current_students': therapist['current_students'],
            'max_students': therapist['max_students'],
            'utilization': round((therapist['current_students'] / therapist['max_students']) * 100)
        })
    
    return render_template('admin/reports.html', reports=reports)

@admin_bp.route('/export-data', methods=['GET', 'POST'])
@admin_required
def export_data():
    """Export system data."""
    if request.method == 'POST':
        data_type = request.form.get('data_type', '')
        format_type = request.form.get('format', 'csv')
        
        if not data_type:
            flash('Please select a data type to export', 'error')
            return redirect(url_for('admin.export_data'))
        
        try:
            if data_type == 'students':
                data = list(mongo.db.users.find({'role': 'student'}, {'password': 0}))
                filename = f"students_export_{datetime.now().strftime('%Y%m%d')}"
            elif data_type == 'therapists':
                data = list(mongo.db.therapists.find())
                filename = f"therapists_export_{datetime.now().strftime('%Y%m%d')}"
            elif data_type == 'appointments':
                data = list(mongo.db.appointments.find())
                filename = f"appointments_export_{datetime.now().strftime('%Y%m%d')}"
            else:
                flash('Invalid data type selected', 'error')
                return redirect(url_for('admin.export_data'))
            
            if format_type == 'json':
                # Convert ObjectId to string for JSON serialization
                for item in data:
                    for key, value in item.items():
                        if isinstance(value, ObjectId):
                            item[key] = str(value)
                        elif isinstance(value, datetime):
                            item[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                
                # Create JSON file
                json_data = json.dumps(data, indent=4)
                
                return Response(
                    json_data,
                    mimetype="application/json",
                    headers={
                        "Content-disposition": f"attachment; filename={filename}.json"
                    }
                )
            else:  # CSV format
                # Create CSV file in memory
                memory_file = io.StringIO()
                
                if data:
                    # Get all unique keys from the data
                    all_keys = set()
                    for item in data:
                        all_keys.update(item.keys())
                    
                    # Create CSV writer
                    writer = csv.DictWriter(memory_file, fieldnames=sorted(all_keys))
                    writer.writeheader()
                    
                    # Write data to CSV
                    for item in data:
                        # Convert ObjectId and datetime to string
                        for key, value in item.items():
                            if isinstance(value, ObjectId):
                                item[key] = str(value)
                            elif isinstance(value, datetime):
                                item[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                        
                        writer.writerow(item)
                
                memory_file.seek(0)
                return Response(
                    memory_file.getvalue(),
                    mimetype="text/csv",
                    headers={
                        "Content-disposition": f"attachment; filename={filename}.csv"
                    }
                )
                
        except Exception as e:
            logger.error(f"Export data error: {e}")
            flash('An error occurred while exporting the data', 'error')
            return redirect(url_for('admin.export_data'))
    
    return render_template('admin/export_data.html')
@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    """System settings."""
    # Get current system settings
    system_settings = mongo.db.system_settings.find_one({'_id': 'main'})
    
    if not system_settings:
        # Initialize default settings if not found
        system_settings = {
            '_id': 'main',
            'max_sessions_per_student': 10,
            'default_session_duration': 50,
            'auto_assignment_enabled': True,
            'allow_self_cancellation': False,
            'minimum_cancellation_hours': 24,
            'default_resources_visible': True,
            'notification_settings': {
                'email_notifications': True,
                'admin_notifications': True
            },
            'session_types': ['online', 'in_person'],
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        mongo.db.system_settings.insert_one(system_settings)
    
    if request.method == 'POST':
        try:
            # Get form data
            max_sessions = int(request.form.get('max_sessions_per_student', 10))
            session_duration = int(request.form.get('default_session_duration', 50))
            auto_assignment = request.form.get('auto_assignment_enabled') == 'on'
            allow_cancellation = request.form.get('allow_self_cancellation') == 'on'
            cancellation_hours = int(request.form.get('minimum_cancellation_hours', 24))
            resources_visible = request.form.get('default_resources_visible') == 'on'
            email_notifications = request.form.get('email_notifications') == 'on'
            admin_notifications = request.form.get('admin_notifications') == 'on'
            
            # Update settings
            mongo.db.system_settings.update_one(
                {'_id': 'main'},
                {'$set': {
                    'max_sessions_per_student': max_sessions,
                    'default_session_duration': session_duration,
                    'auto_assignment_enabled': auto_assignment,
                    'allow_self_cancellation': allow_cancellation,
                    'minimum_cancellation_hours': cancellation_hours,
                    'default_resources_visible': resources_visible,
                    'notification_settings': {
                        'email_notifications': email_notifications,
                        'admin_notifications': admin_notifications
                    },
                    'updated_at': datetime.now(timezone.utc),
                    'updated_by': ObjectId(session['user'])
                }}
            )
            
            # Log activity
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'update_settings',
                'details': 'Updated system settings',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Settings updated successfully', 'success')
            return redirect(url_for('admin.settings'))
            
        except Exception as e:
            logger.error(f"Update settings error: {e}")
            flash('An error occurred while updating settings', 'error')
            return redirect(url_for('admin.settings'))
    
    return render_template('admin/settings.html', settings=system_settings)

@admin_bp.route('/add-admin', methods=['GET', 'POST'])
@admin_required
def add_admin():
    """Add a new admin user."""
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            
            # Validate form data
            if not first_name or not last_name or not email or not password:
                flash('All fields are required', 'error')
                return redirect(url_for('admin.add_admin'))
            
            # Check if email is already in use
            existing_user = mongo.db.users.find_one({'email': email})
            if existing_user:
                flash('Email is already in use', 'error')
                return redirect(url_for('admin.add_admin'))
            
            # Create admin user
            from werkzeug.security import generate_password_hash
            
            new_admin = {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'role': 'admin',
                'password': generate_password_hash(password),
                'created_at': datetime.now(timezone.utc),
                'last_login': None,
                'login_count': 0,
                'status': 'active',
                'created_by': ObjectId(session['user'])
            }
            
            mongo.db.users.insert_one(new_admin)
            
            # Log activity
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'add_admin',
                'details': f'Added admin user: {first_name} {last_name}',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Admin user added successfully', 'success')
            return redirect(url_for('admin.user_management'))
            
        except Exception as e:
            logger.error(f"Add admin error: {e}")
            flash('An error occurred while adding the admin user', 'error')
            return redirect(url_for('admin.add_admin'))
    
    return render_template('admin/add_admin.html')

@admin_bp.route('/logs')
@admin_required
def activity_logs():
    """View system activity logs."""
    # Get filter parameters
    action_type = request.args.get('action_type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Build query
    query = {}
    
    if action_type:
        query['action'] = action_type
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query['timestamp'] = {'$gte': from_date}
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            if 'timestamp' in query:
                query['timestamp']['$lte'] = to_date
            else:
                query['timestamp'] = {'$lte': to_date}
        except ValueError:
            pass
    
    # Get logs with pagination
    page = int(request.args.get('page', 1))
    per_page = 50
    
    logs = list(mongo.db.admin_logs.find(query).sort('timestamp', -1).skip((page - 1) * per_page).limit(per_page))
    
    # Get admin users for each log
    for log in logs:
        admin = mongo.db.users.find_one({'_id': log['admin_id']})
        if admin:
            log['admin_name'] = f"{admin['first_name']} {admin['last_name']}"
        else:
            log['admin_name'] = "Unknown"
    
    # Get total count for pagination
    total_logs = mongo.db.admin_logs.count_documents(query)
    total_pages = (total_logs + per_page - 1) // per_page
    
    # Get distinct action types for filter
    action_types = mongo.db.admin_logs.distinct('action')
    
    return render_template('admin/activity_logs.html', 
                         logs=logs, 
                         page=page, 
                         total_pages=total_pages,
                         action_types=action_types)

@admin_bp.route('/system-health')
@admin_required
def system_health():
    """View system health status."""
    # Get database stats
    db_stats = {
        'users': mongo.db.users.count_documents({}),
        'therapists': mongo.db.therapists.count_documents({}),
        'appointments': mongo.db.appointments.count_documents({}),
        'resources': mongo.db.resources.count_documents({}),
        'admin_logs': mongo.db.admin_logs.count_documents({})
    }
    
    # Get recent errors from logger
    # This would depend on your logging implementation
    recent_errors = []  # Placeholder
    
    # System uptime info
    import psutil
    from datetime import datetime
    
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    
    # System resource usage
    cpu_usage = psutil.cpu_percent()
    memory_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent
    
    return render_template('admin/system_health.html', 
                         db_stats=db_stats,
                         recent_errors=recent_errors,
                         uptime=uptime,
                         cpu_usage=cpu_usage,
                         memory_usage=memory_usage,
                         disk_usage=disk_usage)
@admin_bp.route('/model-config', methods=['GET', 'POST'])
@login_required
@admin_required
#@csrf_protected
def model_config():
    """Configure model settings like confidence thresholds and fallback behavior"""
    try:
        # Get current model settings
        model_settings = mongo.db.system_settings.find_one({'_id': 'model_config'})
        
        # If settings don't exist yet, create default values
        if not model_settings:
            model_settings = {
                "_id": "model_config",
                "bert_confidence_threshold": 0.7,
                "original_confidence_threshold": 0.5,
                "fallback_behavior": "highest_confidence",
                "default_model": "bert",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "updated_by": session.get('user', 'system')
            }
        
        # Handle form submission
        if request.method == 'POST':
            # Log the form data received for debugging
            logger.info(f"Form data received: {dict(request.form)}")
            
            # Get form data
            try:
                bert_threshold = float(request.form.get('bert_confidence_threshold', 0.7))
                original_threshold = float(request.form.get('original_confidence_threshold', 0.5))
            except ValueError as e:
                logger.error(f"Invalid input values: {e}")
                flash("Invalid threshold values. Please enter valid numbers.", "error")
                return redirect(url_for('admin.model_config'))
            
            # Create a copy of existing settings
            updated_settings = dict(model_settings)
            
            # Remove _id to avoid update issues
            if '_id' in updated_settings:
                del updated_settings['_id']
                
            # Update with new values
            updated_settings.update({
                "bert_confidence_threshold": bert_threshold,
                "original_confidence_threshold": original_threshold,
                "fallback_behavior": request.form.get('fallback_behavior', 'highest_confidence'),
                "default_model": request.form.get('default_model', 'bert'),
                "updated_at": datetime.now(timezone.utc),
                "updated_by": session.get('user', 'system')
            })
            
            # Log the settings we're about to save
            logger.info(f"Updating settings to: {updated_settings}")
            
            # Save to database
            try:
                result = mongo.db.system_settings.update_one(
                    {'_id': 'model_config'},
                    {'$set': updated_settings},
                    upsert=True
                )
                logger.info(f"MongoDB update result: {result.modified_count} documents modified")
                
                # Refresh settings from database
                model_settings = mongo.db.system_settings.find_one({'_id': 'model_config'})
                logger.info(f"Refreshed settings from DB: {model_settings}")
                
                flash("Model configuration updated successfully!", "success")
            except Exception as db_error:
                logger.error(f"Database error: {db_error}")
                flash(f"Error saving configuration: {str(db_error)}", "error")
                return render_template('model_config.html', settings=model_settings)
        
        # Render template with settings
        return render_template(
            'model_config.html',
            settings=model_settings
        )
        
    except Exception as e:
        logger.error(f"Error in model config: {e}")
        import traceback
        logger.error(traceback.format_exc())
        flash(f"Error managing model configuration: {str(e)}", "error")
        try:
          return render_template('model_config.html', settings=None)
        except:
        # If that fails too, then redirect to dashboard as last resort
            return redirect(url_for('admin.dashboard'))

@admin_bp.route('/users-management', endpoint='user_management')
@admin_bp.route('/users_management', endpoint='user_management_alt')
@login_required
@admin_required
def user_management():
    """User management page."""
    try:
        users = get_all_users()
        
        # Data preparation with safer type handling
        processed_users = []
        for user in users:
            try:
                user_data = {}
                # Safely convert ObjectId to string
                user_data['_id'] = str(user.get('_id', ''))
                
                # Set the name field that the template is expecting
                if 'first_name' in user and 'last_name' in user:
                    user_data['name'] = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                elif 'full_name' in user:
                    user_data['name'] = user['full_name']
                elif 'email' in user:
                    user_data['name'] = user['email']
                else:
                    user_data['name'] = "Unknown"
                
                # Ensure status is set
                user_data['status'] = user.get('status', 'Inactive')
                
                # Copy other fields
                for key, value in user.items():
                    if key not in ['_id', 'full_name']:  # Skip these as we've already processed them
                        user_data[key] = value
                
                # Safely format date if it exists and is a valid datetime
                if 'last_login' in user and user['last_login']:
                    try:
                        if hasattr(user['last_login'], 'strftime'):
                            user_data['last_login'] = user['last_login'].strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            user_data['last_login'] = str(user['last_login'])
                    except Exception as date_error:
                        logger.warning(f"Date formatting error: {date_error}")
                        user_data['last_login'] = "Invalid date format"
                
                processed_users.append(user_data)
            except Exception as user_error:
                logger.warning(f"Error processing user: {user_error}")
                continue
        
        return render_template('users_management.html', users=processed_users)
            
    except Exception as e:
        logger.error(f"Unhandled exception in user_management: {e}")
        return "An unexpected error occurred", 500