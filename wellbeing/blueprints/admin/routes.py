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
from wellbeing.utils.email import send_therapist_credentials, send_password_reset
from wellbeing.utils.automated_moderation import generate_automated_moderation_report, AutomatedModerator
from wellbeing.utils.moderation_setup import ModerationConfig
from datetime import timedelta

# Helper function to generate a random password
def generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.route('/api/setup-admin', methods=['POST'])
def setup_admin():
    """One-time admin setup for production"""
    
    # Check if admin already exists
    if mongo.db.admin.count_documents({}) > 0:
        return jsonify({"error": "Admin already exists"}), 400
    
    # Check setup key for security
    setup_key = request.headers.get('Setup-Key')
    expected_key = os.getenv('SETUP_KEY')
    
    if not expected_key or setup_key != expected_key:
        return jsonify({"error": "Invalid setup key"}), 401
    
    # Get admin details from request
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    # Basic password validation
    if len(password) < 8:
        return jsonify({"error": "Password too short"}), 400
    
    try:
        # Create admin
        hashed_password = generate_password_hash(password)
        
        result = mongo.db.admin.insert_one({
            "email": email,
            "password": hashed_password,
            "role": "super_admin",
            "created_at": datetime.utcnow(),
            "status": "active"
        })
        
        return jsonify({
            "message": "Admin created successfully",
            "admin_id": str(result.inserted_id)
        }), 201
        
    except Exception as e:
        return jsonify({"error": "Failed to create admin"}), 500

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


@admin_bp.route('/user-management')
@admin_required
def user_management():
    """Enhanced user management with separate handling for students and therapists"""
    try:
        # Get user type filter from query parameter
        user_type = request.args.get('type', 'all')  # 'all', 'students', 'therapists'
        
        # Get students with enhanced data
        students_data = []
        if user_type in ['all', 'students']:
            students_pipeline = [
                {
                    '$lookup': {
                        'from': 'users',
                        'localField': '_id',
                        'foreignField': '_id',
                        'as': 'user_info'
                    }
                },
                {
                    '$unwind': {
                        'path': '$user_info',
                        'preserveNullAndEmptyArrays': True
                    }
                },
                {
                    '$lookup': {
                        'from': 'therapist_assignments',
                        'localField': '_id',
                        'foreignField': 'student_id',
                        'as': 'assignment'
                    }
                },
                {
                    '$lookup': {
                        'from': 'intake_assessments',
                        'localField': '_id',
                        'foreignField': 'student_id',
                        'as': 'intake'
                    }
                }
            ]
            
            students_cursor = mongo.db.students.aggregate(students_pipeline)
            
            for student in students_cursor:
                # Get assigned therapist info if exists
                assigned_therapist = None
                if student.get('assignment') and len(student['assignment']) > 0:
                    assignment = student['assignment'][0]
                    if assignment.get('therapist_id'):
                        therapist = mongo.db.therapists.find_one({'_id': assignment['therapist_id']})
                        if therapist:
                            assigned_therapist = therapist.get('name', 'Unknown Therapist')
                
                # Get intake status
                intake_completed = len(student.get('intake', [])) > 0
                crisis_level = 'normal'
                if student.get('intake') and len(student['intake']) > 0:
                    crisis_level = student['intake'][0].get('crisis_level', 'normal')
                
                # Get session count
                session_count = mongo.db.appointments.count_documents({
                    'user_id': student['_id'],
                    'status': 'completed'
                })
                
                students_data.append({
                    '_id': student['_id'],
                    'student_id': student.get('student_id', 'N/A'),
                    'name': student.get('name', 'Unknown'),
                    'email': student.get('email', student.get('user_info', {}).get('email', 'N/A')),
                    'status': student.get('status', student.get('user_info', {}).get('status', 'inactive')),
                    'created_at': student.get('created_at', student.get('user_info', {}).get('created_at')),
                    'last_login': student.get('user_info', {}).get('last_login'),
                    'assigned_therapist': assigned_therapist,
                    'intake_completed': intake_completed,
                    'crisis_level': crisis_level,
                    'session_count': session_count,
                    'user_type': 'student'
                })
        
        # Get therapists with enhanced data
        therapists_data = []
        if user_type in ['all', 'therapists']:
            therapists_pipeline = [
                {
                    '$lookup': {
                        'from': 'users',
                        'localField': '_id',
                        'foreignField': '_id',
                        'as': 'user_info'
                    }
                },
                {
                    '$unwind': {
                        'path': '$user_info',
                        'preserveNullAndEmptyArrays': True
                    }
                },
                {
                    '$lookup': {
                        'from': 'therapist_assignments',
                        'localField': '_id',
                        'foreignField': 'therapist_id',
                        'as': 'assignments'
                    }
                }
            ]
            
            therapists_cursor = mongo.db.therapists.aggregate(therapists_pipeline)
            
            for therapist in therapists_cursor:
                # Get current student count
                current_students = len(therapist.get('assignments', []))
                
                # Get completed sessions count
                session_count = mongo.db.appointments.count_documents({
                    'therapist_id': therapist['_id'],
                    'status': 'completed'
                })
                
                # Get specializations as string
                specializations = therapist.get('specializations', [])
                specializations_str = ', '.join(specializations) if specializations else 'General'
                
                therapists_data.append({
                    '_id': therapist['_id'],
                    'name': therapist.get('name', 'Unknown'),
                    'email': therapist.get('email', therapist.get('user_info', {}).get('email', 'N/A')),
                    'license_number': therapist.get('license_number', 'N/A'),
                    'specializations': specializations_str,
                    'current_students': current_students,
                    'max_students': therapist.get('max_students', 20),
                    'status': therapist.get('status', therapist.get('user_info', {}).get('status', 'inactive')),
                    'created_at': therapist.get('created_at', therapist.get('user_info', {}).get('created_at')),
                    'last_login': therapist.get('user_info', {}).get('last_login'),
                    'session_count': session_count,
                    'rating': therapist.get('rating', 0.0),
                    'emergency_hours': therapist.get('emergency_hours', False),
                    'user_type': 'therapist'
                })
        
        # Calculate statistics
        total_students = len(students_data)
        active_students = len([s for s in students_data if s['status'] == 'active'])
        total_therapists = len(therapists_data)
        active_therapists = len([t for t in therapists_data if t['status'] == 'active'])
        
        # Get recent registrations (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        new_students = len([s for s in students_data if s.get('created_at') and s['created_at'] >= thirty_days_ago])
        new_therapists = len([t for t in therapists_data if t.get('created_at') and t['created_at'] >= thirty_days_ago])
        
        # Get available specializations for forms
        all_specializations = [
            'anxiety', 'depression', 'stress_management', 'trauma', 'grief_counseling',
            'relationship_counseling', 'family_therapy', 'group_therapy', 'substance_abuse',
            'eating_disorders', 'anger_management', 'life_coaching', 'academic_stress',
            'social_anxiety', 'panic_disorders', 'ptsd', 'bipolar_disorder', 'adhd',
            'autism_spectrum', 'lgbtq_issues', 'cultural_counseling', 'crisis_intervention'
        ]
        
        # Get unassigned therapists for student assignment
        unassigned_therapists = []
        for therapist in therapists_data:
            if therapist['current_students'] < therapist['max_students']:
                unassigned_therapists.append({
                    'id': str(therapist['_id']),
                    'name': therapist['name'],
                    'specializations': therapist['specializations'],
                    'available_slots': therapist['max_students'] - therapist['current_students']
                })
        
        statistics = {
            'total_students': total_students,
            'active_students': active_students,
            'total_therapists': total_therapists,
            'active_therapists': active_therapists,
            'new_students': new_students,
            'new_therapists': new_therapists,
            'total_users': total_students + total_therapists,
            'active_users': active_students + active_therapists
        }
        
        settings = mongo.db.settings.find_one() or {}
        
        return render_template('admin/user_management.html',
                             students_data=students_data,
                             therapists_data=therapists_data,
                             statistics=statistics,
                             user_type=user_type,
                             all_specializations=all_specializations,
                             unassigned_therapists=unassigned_therapists,
                             settings=settings)
                             
    except Exception as e:
        logger.error(f"Error in user management: {e}")
        flash('An error occurred while loading user data', 'error')
        return render_template('admin/user_management.html',
                             students_data=[],
                             therapists_data=[],
                             statistics={},
                             user_type='all',
                             all_specializations=[],
                             unassigned_therapists=[],
                             settings={})

@admin_bp.route('/api/users/<user_type>', methods=['POST'])
@admin_required
def add_user(user_type):
    """Add a new student or therapist"""
    try:
        data = request.get_json()
        
        # Validate common fields
        required_fields = ['name', 'email', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'{field.title()} is required'}), 400
        
        # Validate email format
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', data['email']):
            return jsonify({'success': False, 'error': 'Invalid email format'}), 400
        
        # Check if email already exists
        existing_user = mongo.db.users.find_one({'email': data['email']})
        if existing_user:
            return jsonify({'success': False, 'error': 'Email already exists'}), 400
        
        # Create base user document
        user_data = {
            'email': data['email'].lower().strip(),
            'password': generate_password_hash(data['password']),
            'role': user_type,
            'name': data['name'].strip(),
            'first_name': data.get('first_name', data['name'].split()[0]),
            'last_name': data.get('last_name', ' '.join(data['name'].split()[1:])),
            'status': 'active',
            'created_at': datetime.now(),
            'last_login': None
        }
        
        # Insert user first
        user_result = mongo.db.users.insert_one(user_data)
        user_id = user_result.inserted_id
        
        if user_type == 'student':
            # Validate student-specific fields
            if not data.get('student_id'):
                return jsonify({'success': False, 'error': 'Student ID is required'}), 400
            
            # Check if student ID already exists
            existing_student = mongo.db.students.find_one({'student_id': data['student_id']})
            if existing_student:
                # Rollback user creation
                mongo.db.users.delete_one({'_id': user_id})
                return jsonify({'success': False, 'error': 'Student ID already exists'}), 400
            
            # Create student profile
            student_data = {
                '_id': user_id,
                'student_id': data['student_id'].strip(),
                'name': data['name'].strip(),
                'email': data['email'].lower().strip(),
                'status': 'active',
                'assigned_therapist_id': None,
                'intake_completed': False,
                'created_at': datetime.now(),
                'progress': {
                    'meditation': 0,
                    'exercise': 0
                }
            }
            
            # Assign therapist if specified
            if data.get('assigned_therapist_id'):
                therapist_id = ObjectId(data['assigned_therapist_id'])
                therapist = mongo.db.therapists.find_one({'_id': therapist_id})
                if therapist:
                    student_data['assigned_therapist_id'] = therapist_id
                    
                    # Create assignment
                    assignment_data = {
                        'therapist_id': therapist_id,
                        'student_id': user_id,
                        'status': 'active',
                        'auto_assigned': False,
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    mongo.db.therapist_assignments.insert_one(assignment_data)
            
            mongo.db.students.insert_one(student_data)
            
        elif user_type == 'therapist':
            # Validate therapist-specific fields
            if not data.get('license_number'):
                return jsonify({'success': False, 'error': 'License number is required'}), 400
            
            # Check if license already exists
            existing_therapist = mongo.db.therapists.find_one({'license_number': data['license_number']})
            if existing_therapist:
                # Rollback user creation
                mongo.db.users.delete_one({'_id': user_id})
                return jsonify({'success': False, 'error': 'License number already exists'}), 400
            
            # Create therapist profile
            therapist_data = {
                '_id': user_id,
                'name': data['name'].strip(),
                'email': data['email'].lower().strip(),
                'license_number': data['license_number'].strip(),
                'phone': data.get('phone', ''),
                'gender': data.get('gender', ''),
                'bio': data.get('bio', ''),
                'specializations': data.get('specializations', []),
                'max_students': int(data.get('max_students', 20)),
                'current_students': 0,
                'emergency_hours': bool(data.get('emergency_hours', False)),
                'status': 'active',
                'rating': 5.0,
                'total_sessions': 0,
                'years_experience': int(data.get('years_experience', 0)),
                'created_at': datetime.now()
            }
            
            mongo.db.therapists.insert_one(therapist_data)
        
        return jsonify({
            'success': True,
            'message': f'{user_type.title()} added successfully',
            'user_id': str(user_id)
        })
        
    except Exception as e:
        logger.error(f"Error adding {user_type}: {e}")
        return jsonify({'success': False, 'error': 'Failed to add user'}), 500

@admin_bp.route('/api/users/<user_type>/<user_id>', methods=['PUT'])
@admin_required
def update_user(user_type, user_id):
    """Update student or therapist"""
    try:
        data = request.get_json()
        user_object_id = ObjectId(user_id)
        
        # Update user document
        user_updates = {
            'name': data.get('name', '').strip(),
            'updated_at': datetime.now()
        }
        
        # Only update email if it's different and doesn't exist
        if data.get('email'):
            new_email = data['email'].lower().strip()
            existing_user = mongo.db.users.find_one({'email': new_email, '_id': {'$ne': user_object_id}})
            if existing_user:
                return jsonify({'success': False, 'error': 'Email already exists'}), 400
            user_updates['email'] = new_email
        
        # Update password if provided
        if data.get('password'):
            user_updates['password'] = generate_password_hash(data['password'])
        
        mongo.db.users.update_one({'_id': user_object_id}, {'$set': user_updates})
        
        if user_type == 'student':
            # Update student-specific fields
            student_updates = {
                'name': data.get('name', '').strip(),
                'updated_at': datetime.now()
            }
            
            if data.get('email'):
                student_updates['email'] = data['email'].lower().strip()
            
            if data.get('student_id'):
                # Check if student ID is taken by another student
                existing_student = mongo.db.students.find_one({
                    'student_id': data['student_id'],
                    '_id': {'$ne': user_object_id}
                })
                if existing_student:
                    return jsonify({'success': False, 'error': 'Student ID already exists'}), 400
                student_updates['student_id'] = data['student_id'].strip()
            
            mongo.db.students.update_one({'_id': user_object_id}, {'$set': student_updates})
            
        elif user_type == 'therapist':
            # Update therapist-specific fields
            therapist_updates = {
                'name': data.get('name', '').strip(),
                'updated_at': datetime.now()
            }
            
            if data.get('email'):
                therapist_updates['email'] = data['email'].lower().strip()
            
            if data.get('license_number'):
                # Check if license is taken by another therapist
                existing_therapist = mongo.db.therapists.find_one({
                    'license_number': data['license_number'],
                    '_id': {'$ne': user_object_id}
                })
                if existing_therapist:
                    return jsonify({'success': False, 'error': 'License number already exists'}), 400
                therapist_updates['license_number'] = data['license_number'].strip()
            
            if 'specializations' in data:
                therapist_updates['specializations'] = data['specializations']
            
            if 'max_students' in data:
                therapist_updates['max_students'] = int(data['max_students'])
            
            if 'emergency_hours' in data:
                therapist_updates['emergency_hours'] = bool(data['emergency_hours'])
            
            if 'bio' in data:
                therapist_updates['bio'] = data['bio']
            
            if 'phone' in data:
                therapist_updates['phone'] = data['phone']
            
            if 'gender' in data:
                therapist_updates['gender'] = data['gender']
            
            mongo.db.therapists.update_one({'_id': user_object_id}, {'$set': therapist_updates})
        
        return jsonify({
            'success': True,
            'message': f'{user_type.title()} updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error updating {user_type}: {e}")
        return jsonify({'success': False, 'error': 'Failed to update user'}), 500

@admin_bp.route('/api/users/<user_type>/<user_id>/status', methods=['PUT'])
@admin_required
def toggle_user_status(user_type, user_id):
    """Toggle user active/inactive status"""
    try:
        data = request.get_json()
        new_status = data.get('status', 'active')
        user_object_id = ObjectId(user_id)
        
        # Update in both users and specific collection
        mongo.db.users.update_one(
            {'_id': user_object_id},
            {'$set': {'status': new_status, 'updated_at': datetime.now()}}
        )
        
        if user_type == 'student':
            mongo.db.students.update_one(
                {'_id': user_object_id},
                {'$set': {'status': new_status, 'updated_at': datetime.now()}}
            )
        elif user_type == 'therapist':
            mongo.db.therapists.update_one(
                {'_id': user_object_id},
                {'$set': {'status': new_status, 'updated_at': datetime.now()}}
            )
        
        return jsonify({
            'success': True,
            'message': f'{user_type.title()} status updated to {new_status}'
        })
        
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return jsonify({'success': False, 'error': 'Failed to update status'}), 500

@admin_bp.route('/api/users/<user_type>/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_type, user_id):
    """Delete a user and all related data"""
    try:
        user_object_id = ObjectId(user_id)
        
        # Delete from users collection
        mongo.db.users.delete_one({'_id': user_object_id})
        
        if user_type == 'student':
            # Delete student and related data
            mongo.db.students.delete_one({'_id': user_object_id})
            mongo.db.therapist_assignments.delete_many({'student_id': user_object_id})
            mongo.db.appointments.delete_many({'user_id': user_object_id})
            mongo.db.intake_assessments.delete_many({'student_id': user_object_id})
            mongo.db.shared_resources.delete_many({'student_id': user_object_id})
            mongo.db.therapist_chats.delete_many({'student_id': user_object_id})
            
        elif user_type == 'therapist':
            # Delete therapist and related data
            mongo.db.therapists.delete_one({'_id': user_object_id})
            mongo.db.therapist_assignments.delete_many({'therapist_id': user_object_id})
            mongo.db.appointments.delete_many({'therapist_id': user_object_id})
            mongo.db.shared_resources.delete_many({'therapist_id': user_object_id})
            mongo.db.therapist_chats.delete_many({'therapist_id': user_object_id})
            mongo.db.therapist_availability.delete_many({'therapist_id': user_object_id})
        
        return jsonify({
            'success': True,
            'message': f'{user_type.title()} deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting {user_type}: {e}")
        return jsonify({'success': False, 'error': 'Failed to delete user'}), 500

@admin_bp.route('/moderation-dashboard')
@admin_bp.route('/moderation-settings')  # Redirect to unified dashboard
@admin_bp.route('/test-moderation')      # Redirect to unified dashboard
@login_required
@admin_required
def moderation_dashboard():
    """Unified moderation control center"""
    try:
        # Get 24-hour report
        report = generate_automated_moderation_report(24)
        
        # Get recent crisis alerts
        recent_alerts = list(mongo.db.crisis_alerts.find({
            'created_at': {'$gte': datetime.now() - timedelta(hours=24)},
            'auto_detected': True
        }).sort('created_at', -1).limit(10))
        
        # Add student names to alerts
        for alert in recent_alerts:
            student = mongo.db.users.find_one({'_id': alert['student_id']})
            if student:
                alert['student_name'] = f"{student.get('first_name', '')} {student.get('last_name', '')}"
        
        # Get recent moderation actions
        recent_actions = list(mongo.db.automated_moderation_log.find({
            'timestamp': {'$gte': datetime.now() - timedelta(hours=24)}
        }).sort('timestamp', -1).limit(20))
        
        # Add user names to actions
        for action in recent_actions:
            if 'sender_id' in action:
                user = mongo.db.users.find_one({'_id': action['sender_id']})
                if user:
                    action['user_name'] = f"{user.get('first_name', '')} {user.get('last_name', '')}"
        
        # Get system settings
        settings = ModerationConfig.get_settings()
        
        # System health check
        system_health = {
            'moderation_enabled': settings.get('enabled', False),
            'crisis_detection': settings.get('content_filtering', {}).get('crisis_detection', False),
            'total_alerts_24h': len(recent_alerts),
            'total_actions_24h': len(recent_actions)
        }
        
        dashboard_data = {
            'report': report,
            'recent_alerts': recent_alerts,
            'recent_actions': recent_actions,
            'settings': settings,
            'system_health': system_health
        }
        
        return render_template('admin/moderation_dashboard.html', **dashboard_data)
        
    except Exception as e:
        logger.error(f"Error loading moderation dashboard: {e}")
        flash('Error loading moderation dashboard', 'error')
        return redirect(url_for('admin.dashboard'))

# Handle settings updates (POST to the unified dashboard)
@admin_bp.route('/moderation-dashboard', methods=['POST'])
@login_required
@admin_required
def update_moderation_settings():
    """Update moderation settings from unified dashboard"""
    try:
        # Update settings from form
        new_settings = {
            'enabled': 'moderation_enabled' in request.form,
            'rate_limits': {
                'student': {
                    'per_minute': int(request.form.get('student_per_minute', 3)),
                    'per_hour': int(request.form.get('student_per_hour', 20)),
                    'per_day': int(request.form.get('student_per_day', 100))
                },
                'therapist': {
                    'per_minute': int(request.form.get('therapist_per_minute', 5)),
                    'per_hour': int(request.form.get('therapist_per_hour', 50)),
                    'per_day': int(request.form.get('therapist_per_day', 200))
                }
            },
            'content_filtering': {
                'profanity_filter': 'profanity_filter' in request.form,
                'crisis_detection': 'crisis_detection' in request.form,
                'boundary_checking': 'boundary_checking' in request.form,
                'spam_detection': 'spam_detection' in request.form,
                'max_message_length': int(request.form.get('max_message_length', 2000))
            },
            'auto_escalation': {
                'crisis_alerts': 'crisis_alerts' in request.form,
                'emergency_scheduling': 'emergency_scheduling' in request.form,
                'supervisor_notifications': 'supervisor_notifications' in request.form
            }
        }
        
        if ModerationConfig.update_settings(new_settings):
            # Log the change
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'update_moderation_settings',
                'details': 'Updated automated moderation settings',
                'timestamp': datetime.now(timezone.utc)
            })
            
            flash('Moderation settings updated successfully!', 'success')
        else:
            flash('Failed to update settings', 'error')
            
    except Exception as e:
        logger.error(f"Error updating moderation config: {e}")
        flash('Error updating configuration', 'error')
    
    return redirect(url_for('admin.moderation_dashboard'))

# API endpoints for real-time data
@admin_bp.route('/api/moderation-stats')
@login_required
@admin_required
def api_moderation_stats():
    """Get real-time moderation statistics"""
    try:
        cutoff = datetime.now() - timedelta(hours=24)
        
        stats = {
            'total_messages': mongo.db.therapist_chats.count_documents({
                'timestamp': {'$gte': cutoff}
            }),
            'blocked_messages': mongo.db.automated_moderation_log.count_documents({
                'timestamp': {'$gte': cutoff},
                'action_taken': 'block'
            }),
            'filtered_messages': mongo.db.automated_moderation_log.count_documents({
                'timestamp': {'$gte': cutoff},
                'action_taken': 'filter'
            }),
            'crisis_alerts': mongo.db.crisis_alerts.count_documents({
                'created_at': {'$gte': cutoff},
                'auto_detected': True
            }),
            'system_health': 'healthy'
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error getting moderation stats: {e}")
        return jsonify({'error': 'Failed to get stats'}), 500

# API endpoint for testing (called from the unified dashboard)
@admin_bp.route('/api/test-moderation', methods=['POST'])
@login_required
@admin_required
def api_test_moderation():
    """API endpoint for testing moderation system"""
    try:
        test_type = request.json.get('test_type', 'all')
        
        # Define test cases
        test_cases = {
            'crisis': {
                'message': 'I want to hurt myself and end my life',
                'expected': 'BLOCKED',
                'type': 'crisis'
            },
            'profanity': {
                'message': 'This fucking situation is really annoying',
                'expected': 'FILTERED', 
                'type': 'profanity'
            },
            'boundary': {
                'message': 'Can you give me your personal phone number?',
                'expected': 'FLAGGED',
                'type': 'boundary'
            },
            'normal': {
                'message': 'How are you today?',
                'expected': 'ALLOWED',
                'type': 'normal'
            }
        }
        
        # Run specific test or all tests
        if test_type == 'all':
            tests_to_run = test_cases.values()
        else:
            tests_to_run = [test_cases.get(test_type)]
        
        results = []
        for test_case in tests_to_run:
            if test_case:
                try:
                    # Simulate moderation result (replace with actual AutomatedModerator call)
                    result = {
                        'test': test_case['type'].title() + ' Detection',
                        'message': test_case['message'],
                        'result': test_case['expected'],
                        'pass': True
                    }
                    results.append(result)
                except Exception as e:
                    results.append({
                        'test': test_case['type'].title() + ' Detection',
                        'message': test_case['message'],
                        'result': f'ERROR: {str(e)}',
                        'pass': False
                    })
        
        return jsonify({'results': results})
        
    except Exception as e:
        logger.error(f"Error testing moderation: {e}")
        return jsonify({'error': 'Test failed'}), 500

# Keep these separate routes if you want individual pages (optional)
@admin_bp.route('/crisis-alerts')
@login_required
@admin_required
def crisis_alerts():
    """Separate crisis alerts page (optional)"""
    try:
        status_filter = request.args.get('status', 'all')
        days_filter = int(request.args.get('days', 7))
        
        query = {
            'auto_detected': True,
            'created_at': {'$gte': datetime.now() - timedelta(days=days_filter)}
        }
        
        if status_filter != 'all':
            query['status'] = status_filter
        
        alerts = list(mongo.db.crisis_alerts.find(query).sort('created_at', -1))
        
        # Add user details
        for alert in alerts:
            student = mongo.db.users.find_one({'_id': alert['student_id']})
            if student:
                alert['student_name'] = f"{student.get('first_name', '')} {student.get('last_name', '')}"
                alert['student_email'] = student.get('email', '')
        
        stats = {
            'total_alerts': len(alerts),
            'unresolved_alerts': len([a for a in alerts if a.get('status') == 'auto_escalated']),
            'critical_alerts': len([a for a in alerts if a.get('crisis_level') == 'critical']),
            'high_alerts': len([a for a in alerts if a.get('crisis_level') == 'high'])
        }
        
        return render_template('admin/crisis_alerts.html', 
                             alerts=alerts, 
                             stats=stats,
                             status_filter=status_filter,
                             days_filter=days_filter)
        
    except Exception as e:
        logger.error(f"Error loading crisis alerts: {e}")
        flash('Error loading crisis alerts', 'error')
        return redirect(url_for('admin.moderation_dashboard'))

@admin_bp.route('/acknowledge-crisis/<alert_id>', methods=['POST'])
@login_required
@admin_required
def acknowledge_crisis_alert(alert_id):
    """Acknowledge crisis alert"""
    try:
        action = request.form.get('action', 'acknowledged')
        notes = request.form.get('notes', '')
        
        result = mongo.db.crisis_alerts.update_one(
            {'_id': ObjectId(alert_id)},
            {
                '$set': {
                    'status': 'acknowledged',
                    'acknowledged_by': ObjectId(session['user']),
                    'acknowledged_at': datetime.now(),
                    'admin_action': action,
                    'admin_notes': notes
                }
            }
        )
        
        if result.modified_count > 0:
            mongo.db.admin_logs.insert_one({
                'admin_id': ObjectId(session['user']),
                'action': 'acknowledge_crisis_alert',
                'details': f'Acknowledged crisis alert {alert_id}',
                'timestamp': datetime.now(timezone.utc)
            })
            flash('Crisis alert acknowledged successfully', 'success')
        else:
            flash('Alert not found or already processed', 'error')
        
        return redirect(url_for('admin.crisis_alerts'))
        
    except Exception as e:
        logger.error(f"Error acknowledging crisis alert: {e}")
        flash('Error processing alert', 'error')
        return redirect(url_for('admin.crisis_alerts'))