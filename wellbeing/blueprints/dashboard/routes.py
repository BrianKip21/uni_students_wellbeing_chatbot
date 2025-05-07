from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timezone
import csv
import io
import json
from wellbeing.blueprints.dashboard import dashboard_bp
from wellbeing.utils.decorators import login_required
from wellbeing import mongo, logger
from wellbeing.models.user import find_user_by_id, update_user_settings

@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Dashboard index page with user's overview."""
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Check if we should redirect based on default view
    requested_view = request.args.get('view')
    if not requested_view and settings.get('default_view') != 'dashboard':
        default_view = settings.get('default_view')
        if default_view == 'calendar':
            return redirect(url_for('tracking.index'))
        elif default_view == 'list':
            return redirect(url_for('tracking.list_view'))
    
    # If progress field doesn't exist, initialize it
    if 'progress' not in user:
        user['progress'] = {
            'meditation': 0,
            'exercise': 0
        }
        
        # Save this default structure to the database
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'progress': user['progress']}}
        )
    
    # Fetch recent chats for the user
    recent_chats = list(mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1).limit(5))
    
    # Fetch recommended resources
    recommended_resources = list(mongo.db.resources.find().limit(2))
    
    # Get latest mood data
    latest_mood = mongo.db.moods.find_one({"user_id": str(user_id)}, sort=[("timestamp", -1)])
    
    # Check if student has a pending therapist request
    pending_request = mongo.db.therapist_requests.find_one({
        'student_id': user_id,
        'status': 'pending'
    })
    
    # Check if student has an assigned therapist
    assigned_therapist = mongo.db.therapist_assignments.find_one({
        'student_id': user_id,
        'status': 'active'
    })
    
    if assigned_therapist:
        therapist = mongo.db.therapists.find_one({'_id': assigned_therapist['therapist_id']})
        assigned_therapist['therapist_name'] = f"Dr. {therapist['first_name']} {therapist['last_name']}"
    else:
        assigned_therapist = None
    
    return render_template('dashboard.html',
                         user=user,
                         settings=settings,
                         recent_chats=recent_chats,
                         resources=recommended_resources,
                         latest_mood=latest_mood,
                         pending_request=pending_request,
                         assigned_therapist=assigned_therapist)

@dashboard_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Handle form submission (for profile updates)
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Basic validation
            errors = []
            
            # Names cannot be changed
            if first_name and first_name != user.get('first_name', ''):
                errors.append('First name cannot be changed.')
                
            if last_name and last_name != user.get('last_name', ''):
                errors.append('Last name cannot be changed.')
            
            # Email cannot be changed
            if email and email != user.get('email', ''):
                errors.append('Email cannot be changed.')
            
            # Password validation - always require current password verification
            if new_password or confirm_password:
                from werkzeug.security import check_password_hash, generate_password_hash
                
                # First check if current password was provided
                if not current_password:
                    errors.append('Current password is required to change your password.')
                else:
                    # Verify current password is correct before allowing password change
                    if not check_password_hash(user.get('password', ''), current_password):
                        errors.append('Current password is incorrect.')
                    else:
                        # Current password is correct, now validate the new password
                        if not new_password:
                            errors.append('New password is required.')
                        elif len(new_password) < 8:
                            errors.append('New password must be at least 8 characters.')
                        
                        if new_password != confirm_password:
                            errors.append('New passwords do not match.')
            
            # If there are validation errors, flash them and redirect
            if errors:
                for error in errors:
                    flash(error, 'error')
                return redirect(url_for('dashboard.profile'))
            
            # Prepare update data
            update_data = {}
            
            # Password change (only if current password is provided and verified)
            if current_password and new_password and check_password_hash(user.get('password', ''), current_password):
                update_data['password'] = generate_password_hash(new_password)
            
            # Update user data if there are changes
            if update_data:
                mongo.db.users.update_one(
                    {'_id': user_id},
                    {'$set': update_data}
                )
                flash('Password updated successfully!', 'success')
                
                # Refresh user data after update
                user = find_user_by_id(user_id)
            else:
                flash('No changes detected.', 'info')
                
        except Exception as e:
            logger.error(f"Profile update error: {e}")
            flash('An error occurred while updating your profile.', 'error')
    
    # Create options for statistics or additional info
    activity_stats = {
        'login_count': user.get('login_count', 0),
        'last_login': user.get('last_login', 'Never'),
        'registration_date': user.get('created_at', 'Unknown')
    }
    
    # Get user's recent activity (mood entries and other tracked actions)
    recent_activity = list(mongo.db.moods.find(
        {"user_id": str(user_id)}
    ).sort("timestamp", -1).limit(5))
    
    return render_template('profile.html', 
                          user=user, 
                          stats=activity_stats,
                          activity=recent_activity,
                          settings=settings)

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings page."""
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get or initialize user settings
    user_settings = user.get('settings', {})
    
    # Default settings if none exist
    if not user_settings:
        user_settings = {
            'text_size': 'md',
            'contrast': 'normal',
            'theme_mode': 'light',
            'widgets': ['mood_tracker', 'quick_actions', 'resources', 'progress'],
            'default_view': 'dashboard',
            'reminder_time': '09:00',
            'checkin_frequency': 'weekdays'
        }
        
        # Update user with default settings
        update_user_settings(user_id, user_settings)
    
    # Handle form submissions
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        try:
            if form_type == 'accessibility':
                # Update accessibility settings
                user_settings['text_size'] = request.form.get('text_size')
                user_settings['contrast'] = request.form.get('contrast')
                flash('Accessibility settings updated successfully!', 'success')
            
            elif form_type == 'theme':
                # Update theme settings
                user_settings['theme_mode'] = request.form.get('theme_mode')
                flash('Theme settings updated successfully!', 'success')
            
            elif form_type == 'dashboard':
                # Update dashboard settings
                widgets = request.form.getlist('widgets')
                if not widgets:
                    # Ensure at least one widget is selected
                    widgets = ['mood_tracker']
                
                user_settings['widgets'] = widgets
                user_settings['default_view'] = request.form.get('default_view')
                flash('Dashboard settings updated successfully!', 'success')
            
            elif form_type == 'reminders':
                # Update reminder settings
                user_settings['reminder_time'] = request.form.get('reminder_time')
                user_settings['checkin_frequency'] = request.form.get('checkin_frequency')
                flash('Reminder settings updated successfully!', 'success')
            
            # Save updated settings to database
            update_user_settings(user_id, user_settings)
            
        except Exception as e:
            logger.error(f"Settings update error: {e}")
            flash('An error occurred while updating settings.', 'error')
    
    return render_template('settings.html', user=user, settings=user_settings)

@dashboard_bp.route('/student_resources')
@login_required
def resources():
    """Student resources page."""
    # Get user from database
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get resources
    resources = list(mongo.db.resources.find())
    
    # Get user settings
    settings = user.get('settings', {})
    
    return render_template('student_resources.html', resources=resources, settings=settings, user=user)

@dashboard_bp.route('/download_data')
@login_required
def download_data():
    """Download user data in CSV format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Create CSV file in memory
        memory_file = io.StringIO()
        writer = csv.writer(memory_file)
        
        # Write user profile data
        writer.writerow(['Profile Information'])
        writer.writerow(['First Name', 'Last Name', 'Email', 'Student ID', 'Role', 'Created At'])
        writer.writerow([
            user.get('first_name', ''),
            user.get('last_name', ''),
            user.get('email', ''),
            user.get('student_id', ''),
            user.get('role', ''),
            user.get('created_at', datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write mood data
        writer.writerow(['Mood Tracking History'])
        writer.writerow(['Date', 'Mood', 'Notes'])
        
        moods = mongo.db.moods.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for mood in moods:
            writer.writerow([
                mood.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                mood.get('mood', ''),
                mood.get('context', '')
            ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write chat history
        writer.writerow(['Recent Conversations'])
        writer.writerow(['Date', 'Message'])
        
        chats = mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for chat in chats:
            writer.writerow([
                chat.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                chat.get('message', '')
            ])
        
        # Prepare response
        memory_file.seek(0)
        return Response(
            memory_file.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    
    except Exception as e:
        logger.error(f"Data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/download_data_json')
@login_required
def download_data_json():
    """Download user data in JSON format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Helper function to handle ObjectId and datetime serialization
        def json_serial(obj):
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # Create a copy of user data without password
        user_data = {k: v for k, v in user.items() if k != 'password'}
        
        # Get mood data
        moods = list(mongo.db.moods.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Get chat data
        chats = list(mongo.db.chats.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Combine all data
        export_data = {
            'profile': user_data,
            'moods': moods,
            'chats': chats
        }
        
        # Convert to JSON
        json_data = json.dumps(export_data, default=json_serial, indent=4)
        
        # Prepare response
        return Response(
            json_data,
            mimetype="application/json",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.json"}
        )
    
    except Exception as e:
        logger.error(f"JSON data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))
@dashboard_bp.route('/request-therapist')
@login_required
def request_therapist():
    """Request to be assigned to a therapist"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Check if student already has an assigned therapist
        existing_assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if existing_assignment:
            flash('You already have an assigned therapist', 'info')
            return redirect(url_for('dashboard.therapist_chat'))
        
        # Check if student already has a pending request
        existing_request = mongo.db.therapist_requests.find_one({
            'student_id': student_id,
            'status': 'pending'
        })
        
        if existing_request:
            flash('Your therapist request is still being processed', 'info')
            return redirect(url_for('dashboard.request_status'))
        
        # Add settings to template context
        return render_template(
            'request_therapist.html',
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Request therapist error: {e}")
        flash('An error occurred while loading therapist request page', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/submit-therapist-request', methods=['POST'])
@login_required
def submit_therapist_request():
    """Submit request for therapist assignment"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get form data
        issue_description = request.form.get('issue_description', '').strip()
        concerns = request.form.getlist('concerns')
        preferred_session_type = request.form.get('preferred_session_type', 'both')
        urgency_level = request.form.get('urgency_level', 'normal')
        
        # Validate input
        if not issue_description:
            flash('Please describe your issue or concern', 'error')
            return redirect(url_for('dashboard.request_therapist'))
        
        # Create therapist request
        request_data = {
            'student_id': student_id,
            'issue_description': issue_description,
            'concerns': concerns,
            'preferred_session_type': preferred_session_type,
            'urgency_level': urgency_level,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.therapist_requests.insert_one(request_data)
        
        if result.inserted_id:
            flash('Your therapist request has been submitted successfully. You will be notified when a therapist is assigned to you.', 'success')
            return redirect(url_for('dashboard.request_status'))
        else:
            flash('Failed to submit therapist request', 'error')
            return redirect(url_for('dashboard.request_therapist'))
        
    except Exception as e:
        logger.error(f"Submit therapist request error: {e}")
        flash('An error occurred while submitting your request', 'error')
        return redirect(url_for('dashboard.request_therapist'))

@dashboard_bp.route('/request-status')
@login_required
def request_status():
    """Check the status of a therapist request"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Get the request status
        request_data = mongo.db.therapist_requests.find_one({
            'student_id': student_id
        }, sort=[('created_at', -1)])
        
        # Check if there's an assignment
        assignment = None
        if request_data and request_data.get('status') == 'approved':
            assignment = mongo.db.therapist_assignments.find_one({
                'student_id': student_id,
                'status': 'active'
            })
            
            if assignment:
                therapist = mongo.db.therapists.find_one({'_id': assignment['therapist_id']})
                if therapist:
                    assignment['therapist_name'] = f"Dr. {therapist['first_name']} {therapist['last_name']}"
        
        return render_template(
            'request_status.html',
            request=request_data,
            assignment=assignment,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Request status error: {e}")
        flash('An error occurred while checking your request status', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/therapist-chat')
@login_required
def therapist_chat():
    """Chat with assigned therapist"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Check if student has an assigned therapist
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if not assignment:
            flash('You do not have an assigned therapist yet', 'info')
            return redirect(url_for('dashboard.request_therapist'))
        
        therapist_id = assignment['therapist_id']
        therapist = mongo.db.therapists.find_one({'_id': therapist_id})
        
        if not therapist:
            flash('There was an error finding your therapist', 'error')
            return redirect(url_for('dashboard.index'))
        
        # Get chat history
        chat_history = list(mongo.db.therapist_chats.find({
            'student_id': student_id,
            'therapist_id': therapist_id
        }).sort('timestamp', 1))
        
        # Get shared resources from therapist
        shared_resources = list(mongo.db.shared_resources.find({
            'student_id': student_id,
            'therapist_id': therapist_id
        }).sort('shared_at', -1))
        
        return render_template(
            'therapist_chat.html',
            therapist=therapist,
            chat_history=chat_history,
            assignment=assignment,
            shared_resources=shared_resources,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Therapist chat error: {e}")
        flash('An error occurred while loading the chat', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/send-therapist-message', methods=['POST'])
@login_required
def send_therapist_message():
    """Send message to therapist"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get form data
        message = request.form.get('message', '').strip()
        
        if not message:
            return jsonify({'success': False, 'error': 'Message cannot be empty'})
        
        # Check if student has an assigned therapist
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if not assignment:
            return jsonify({'success': False, 'error': 'No assigned therapist'})
        
        therapist_id = assignment['therapist_id']
        
        # Save message
        new_message = {
            'student_id': student_id,
            'therapist_id': therapist_id,
            'sender': 'student',
            'message': message,
            'read': False,
            'timestamp': datetime.now(timezone.utc)
        }
        
        result = mongo.db.therapist_chats.insert_one(new_message)
        
        if result.inserted_id:
            # Format message for immediate display
            formatted_message = {
                'id': str(result.inserted_id),
                'message': message,
                'sender': 'student',
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
            }
            return jsonify({'success': True, 'message': formatted_message})
        else:
            return jsonify({'success': False, 'error': 'Failed to send message'})
        
    except Exception as e:
        logger.error(f"Send therapist message error: {e}")
        return jsonify({'success': False, 'error': 'An error occurred'})

@dashboard_bp.route('/therapist-appointments')
@login_required
def therapist_appointments():
    """View and schedule therapist appointments"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Check if student has an assigned therapist
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if not assignment:
            flash('You do not have an assigned therapist yet', 'info')
            return redirect(url_for('dashboard.request_therapist'))
        
        therapist_id = assignment['therapist_id']
        therapist = mongo.db.therapists.find_one({'_id': therapist_id})
        
        if not therapist:
            flash('There was an error finding your therapist', 'error')
            return redirect(url_for('dashboard.index'))
        
        # Get upcoming appointments
        upcoming_appointments = list(mongo.db.appointments.find({
            'student_id': student_id,
            'therapist_id': therapist_id,
            'date': {'$gte': datetime.now()},
            'status': 'scheduled'
        }).sort('date', 1))
        
        # Get pending appointment requests
        pending_appointments = list(mongo.db.appointments.find({
            'student_id': student_id,
            'therapist_id': therapist_id,
            'status': 'pending'
        }).sort('date', 1))
        
        # Get past appointments
        past_appointments = list(mongo.db.appointments.find({
            'student_id': student_id,
            'therapist_id': therapist_id,
            '$or': [
                {'date': {'$lt': datetime.now()}, 'status': 'completed'},
                {'status': 'cancelled'}
            ]
        }).sort('date', -1).limit(5))
        
        # Get available time slots from therapist's schedule
        available_slots = []
        
        # Parse therapist's working days and hours
        office_hours = therapist.get('office_hours', {})
        working_days = office_hours.get('days', [0, 1, 2, 3, 4])  # Default: Monday-Friday
        
        # Generate slots for the next 14 days
        for i in range(14):
            slot_date = datetime.now() + timedelta(days=i+1)
            
            # Skip non-working days
            if slot_date.weekday() not in working_days:
                continue
                
            # Add standard slots based on therapist's hours
            day_slots = office_hours.get('slots', ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00'])
            
            available_slots.append({
                'date': slot_date,
                'date_str': slot_date.strftime('%Y-%m-%d'),
                'day': slot_date.strftime('%A, %B %d'),
                'slots': day_slots
            })
        
        # Remove already booked slots
        booked_appointments = mongo.db.appointments.find({
            'therapist_id': therapist_id,
            'date': {'$gte': datetime.now()},
            'status': {'$in': ['scheduled', 'pending']}
        })
        
        booked_slots = {}
        for appt in booked_appointments:
            date_str = appt['date'].strftime('%Y-%m-%d')
            if date_str not in booked_slots:
                booked_slots[date_str] = []
            booked_slots[date_str].append(appt['time'])
        
        # Filter out booked slots
        for day in available_slots:
            date_str = day['date_str']
            if date_str in booked_slots:
                day['slots'] = [slot for slot in day['slots'] if slot not in booked_slots[date_str]]
        
        # Get session notes for past appointments
        session_notes = {}
        for appt in past_appointments:
            note = mongo.db.session_notes.find_one({
                'appointment_id': appt['_id']
            })
            if note:
                session_notes[str(appt['_id'])] = note
        
        return render_template(
            'therapist_appointments.html',
            therapist=therapist,
            upcoming_appointments=upcoming_appointments,
            pending_appointments=pending_appointments,
            past_appointments=past_appointments,
            available_slots=available_slots,
            session_notes=session_notes,
            settings=settings,
            now=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Therapist appointments error: {e}")
        flash('An error occurred while loading appointment data', 'error')
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/schedule-appointment', methods=['POST'])
@login_required
def schedule_appointment():
    """Request a new appointment with therapist"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get form data
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        session_type = request.form.get('session_type', 'online')
        reason = request.form.get('reason', '')
        
        # Validate input
        if not date_str or not time_str:
            flash('Date and time are required', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Parse date
        try:
            appointment_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Check if student has an assigned therapist
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if not assignment:
            flash('You do not have an assigned therapist yet', 'error')
            return redirect(url_for('dashboard.request_therapist'))
        
        therapist_id = assignment['therapist_id']
        
        # Check if slot is available
        existing = mongo.db.appointments.find_one({
            'therapist_id': therapist_id,
            'date': appointment_date,
            'time': time_str,
            'status': {'$in': ['scheduled', 'pending']}
        })
        
        if existing:
            flash('This time slot is no longer available. Please select another time.', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Create new appointment request
        new_appointment = {
            'student_id': student_id,
            'therapist_id': therapist_id,
            'date': appointment_date,
            'time': time_str,
            'session_type': session_type,
            'reason': reason,
            'status': 'pending',  # Pending therapist approval
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.appointments.insert_one(new_appointment)
        
        if result.inserted_id:
            flash('Appointment request submitted successfully. Awaiting therapist approval.', 'success')
        else:
            flash('Failed to submit appointment request', 'error')
            
        return redirect(url_for('dashboard.therapist_appointments'))
        
    except Exception as e:
        logger.error(f"Schedule appointment error: {e}")
        flash('An error occurred while scheduling the appointment', 'error')
        return redirect(url_for('dashboard.therapist_appointments'))

@dashboard_bp.route('/request-reschedule/<appointment_id>', methods=['POST'])
@login_required
def request_reschedule(appointment_id):
    """Request to reschedule an appointment"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get form data
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        reason = request.form.get('reason', '')
        
        # Validate input
        if not date_str or not time_str:
            flash('Date and time are required', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Parse date
        try:
            new_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Find original appointment
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'student_id': student_id,
            'status': 'scheduled'
        })
        
        if not appointment:
            flash('Appointment not found or cannot be rescheduled', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Check if new slot is available
        existing = mongo.db.appointments.find_one({
            'therapist_id': appointment['therapist_id'],
            'date': new_date,
            'time': time_str,
            'status': {'$in': ['scheduled', 'pending']},
            '_id': {'$ne': ObjectId(appointment_id)}  # Exclude this appointment
        })
        
        if existing:
            flash('The requested time slot is not available', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Create reschedule request
        reschedule_request = {
            'appointment_id': ObjectId(appointment_id),
            'student_id': student_id,
            'therapist_id': appointment['therapist_id'],
            'original_date': appointment['date'],
            'original_time': appointment['time'],
            'requested_date': new_date,
            'requested_time': time_str,
            'reason': reason,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.reschedule_requests.insert_one(reschedule_request)
        
        if result.inserted_id:
            # Update appointment status to "reschedule pending"
            mongo.db.appointments.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$set': {
                    'reschedule_requested': True,
                    'updated_at': datetime.now(timezone.utc)
                }}
            )
            flash('Reschedule request submitted successfully. Awaiting therapist approval.', 'success')
        else:
            flash('Failed to submit reschedule request', 'error')
            
        return redirect(url_for('dashboard.therapist_appointments'))
        
    except Exception as e:
        logger.error(f"Request reschedule error: {e}")
        flash('An error occurred while requesting to reschedule', 'error')
        return redirect(url_for('dashboard.therapist_appointments'))

@dashboard_bp.route('/request-cancellation/<appointment_id>', methods=['POST'])
@login_required
def request_cancellation(appointment_id):
    """Request to cancel an appointment"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get form data
        reason = request.form.get('reason', '')
        
        # Find appointment
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'student_id': student_id,
            'status': 'scheduled'
        })
        
        if not appointment:
            flash('Appointment not found or cannot be cancelled', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Create cancellation request
        cancellation_request = {
            'appointment_id': ObjectId(appointment_id),
            'student_id': student_id,
            'therapist_id': appointment['therapist_id'],
            'appointment_date': appointment['date'],
            'appointment_time': appointment['time'],
            'reason': reason,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc)
        }
        
        result = mongo.db.cancellation_requests.insert_one(cancellation_request)
        
        if result.inserted_id:
            # Update appointment status to "cancellation pending"
            mongo.db.appointments.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$set': {
                    'cancellation_requested': True,
                    'updated_at': datetime.now(timezone.utc)
                }}
            )
            flash('Cancellation request submitted successfully. Awaiting therapist approval.', 'success')
        else:
            flash('Failed to submit cancellation request', 'error')
            
        return redirect(url_for('dashboard.therapist_appointments'))
        
    except Exception as e:
        logger.error(f"Request cancellation error: {e}")
        flash('An error occurred while requesting cancellation', 'error')
        return redirect(url_for('dashboard.therapist_appointments'))

@dashboard_bp.route('/session-notes/<appointment_id>')
@login_required
def view_session_notes(appointment_id):
    """View session notes for a specific appointment"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Find appointment
        appointment = mongo.db.appointments.find_one({
            '_id': ObjectId(appointment_id),
            'student_id': student_id,
            'status': 'completed'
        })
        
        if not appointment:
            flash('Appointment not found or notes are not available', 'error')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Get session notes
        notes = mongo.db.session_notes.find_one({
            'appointment_id': ObjectId(appointment_id)
        })
        
        if not notes:
            flash('No session notes are available for this appointment', 'info')
            return redirect(url_for('dashboard.therapist_appointments'))
        
        # Get therapist info
        therapist = mongo.db.therapists.find_one({'_id': appointment['therapist_id']})
        
        return render_template(
            'session_notes.html',
            notes=notes,
            appointment=appointment,
            therapist=therapist,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"View session notes error: {e}")
        flash('An error occurred while loading session notes', 'error')
        return redirect(url_for('dashboard.therapist_appointments'))

@dashboard_bp.route('/shared-resources')
@login_required
def shared_resources():
    """View resources shared by therapist"""
    try:
        student_id = ObjectId(session.get('user'))
        
        # Get user for settings
        user = find_user_by_id(student_id)
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
            
        # Get user settings
        settings = user.get('settings', {})
        
        # Check if student has an assigned therapist
        assignment = mongo.db.therapist_assignments.find_one({
            'student_id': student_id,
            'status': 'active'
        })
        
        if not assignment:
            flash('You do not have an assigned therapist yet', 'info')
            return redirect(url_for('dashboard.request_therapist'))
        
        therapist_id = assignment['therapist_id']
        therapist = mongo.db.therapists.find_one({'_id': therapist_id})
        
        # Get shared resources
        resources = list(mongo.db.shared_resources.find({
            'student_id': student_id,
            'therapist_id': therapist_id
        }).sort('shared_at', -1))
        
        return render_template(
            'shared_resources.html',
            resources=resources,
            therapist=therapist,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Shared resources error: {e}")
        flash('An error occurred while loading shared resources', 'error')
        return redirect(url_for('dashboard.index'))