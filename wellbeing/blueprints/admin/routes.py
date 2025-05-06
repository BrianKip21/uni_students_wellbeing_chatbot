"""
Admin routes for dashboard, user management, and system features
"""
from datetime import datetime, timezone
from bson.objectid import ObjectId
import pandas as pd
from flask import render_template, redirect, url_for, request, jsonify, flash, make_response, session
from wellbeing.blueprints.admin import admin_bp
from wellbeing.utils.decorators import login_required, admin_required, csrf_protected
from wellbeing import mongo, logger
from wellbeing.utils.file_handlers import handle_video_upload
from wellbeing.models.user import find_user_by_id, get_all_users
from wellbeing.models.resource import create_resource, update_resource, delete_resource
from wellbeing.services.feedback_service import export_training_data, analyze_feedback_data

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
                
                # Copy other fields
                for key, value in user.items():
                    if key != '_id':
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
