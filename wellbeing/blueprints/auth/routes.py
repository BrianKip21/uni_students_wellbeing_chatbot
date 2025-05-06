from datetime import datetime, timezone
import secrets
from flask import render_template, request, redirect, url_for, session, flash, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from wellbeing.blueprints.auth import auth_bp
from wellbeing.models.user import (
    find_user_by_email, create_user, update_user_login, find_user_by_student_id, find_user_by_id
)
from wellbeing import mongo, logger
from wellbeing.utils.validators import validate_email, validate_password

@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    try:
        # Ensure JSON content type for POST requests
        if request.method == 'POST':
            if not request.is_json:
                return jsonify({'error': 'Content-Type must be application/json'}), 415

            data = request.get_json()
            email = data.get('email', '').strip()
            password = data.get('password', '')
            role = data.get('role', '').lower()

            # Validate input
            if not email or not password or not role:
                return jsonify({'error': 'All fields are required'}), 400

            # Select appropriate user collection based on role
            if role == 'admin':
                user_collection = mongo.db.admin
            elif role == 'therapist':
                user_collection = mongo.db.therapists
            else:
                user_collection = mongo.db.users
            
            # Find user
            user = user_collection.find_one({'email': email})
            
            if not user:
                return jsonify({'error': 'Invalid email or password'}), 401

            # Verify password
            if not check_password_hash(user['password'], password):
                return jsonify({'error': 'Invalid email or password'}), 401

            # Verify role
            if user.get('role', '').lower() != role:
                return jsonify({'error': 'Incorrect role selection'}), 401
                
            # Check if user account is active
            if user.get('status', 'Active') != 'Active':
                return jsonify({'error': 'Your account has been disabled. Please contact an admin.'}), 403

            # Create session
            session['user'] = str(user['_id'])
            session['role'] = role
            session['email'] = email
            session['logged_in'] = True
            session['last_activity'] = datetime.now(timezone.utc).isoformat()
            
            # Update last login time
            update_user_login(user['_id'])

            return jsonify({
                'message': 'Login successful', 
                'role': role
            }), 200

        # GET request - render login page
        return render_template('login.html')

    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    try:
        if request.method == 'POST':
            # Try getting JSON data first, otherwise get form data
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
            
            # Extract and sanitize input fields
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            email = data.get('email', '').strip()
            student_id = data.get('student_id', '').strip()
            password = data.get('password', '')
            confirm_password = data.get('confirm_password', '')
            
            # Validation checks
            errors = []
            
            if not first_name or not first_name.isalpha():
                errors.append('First name must contain only letters.')
            if not last_name or not last_name.isalpha():
                errors.append('Last name must contain only letters.')
            if not email or len(email) < 12:
                errors.append('Email must be at least 12 characters.')
            if not validate_email(email):
                errors.append('Invalid email format.')
            if not student_id or not student_id.isdigit():
                errors.append('Student ID must contain only numbers.')
            if not validate_password(password):
                errors.append('Password must be at least 8 characters with letters and numbers.')
            if password != confirm_password:
                errors.append('Passwords do not match.')
            
            if errors:
                return jsonify({'errors': errors}), 400
            
            # Check if student ID or email already exists
            if mongo.db.users.find_one({'student_id': student_id}):
                return jsonify({'error': 'Student ID already exists'}), 409
            if find_user_by_email(email):
                return jsonify({'error': 'Email already exists'}), 409
            
            # Create new user
            create_user(first_name, last_name, email, student_id, password)
            
            # Redirect to login page after successful registration
            return redirect(url_for('auth.login'))
        
        # GET request - Render registration page
        return render_template('register.html')
    
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/csrf-token', methods=['GET'])
def get_csrf_token():
    # Generate a new token
    csrf_token = secrets.token_hex(16)
    
    # Create a response and set a cookie
    response = make_response(jsonify({'status': 'success'}))
    response.set_cookie('csrf_token', csrf_token, httponly=False, samesite='Strict')
    
    return response

@auth_bp.before_app_request
def make_session_permanent():
    try:
        session.permanent = True
        
        # Skip session management for static files and login/register routes
        if request.endpoint in ['static', 'auth.login', 'auth.register']:
            return

        # Check session expiration
        if 'last_activity' in session:
            last_activity = session.get('last_activity')
            if isinstance(last_activity, str):
                last_activity = datetime.fromisoformat(last_activity)
            
            from flask import current_app
            if datetime.now(timezone.utc) - last_activity > current_app.config['PERMANENT_SESSION_LIFETIME']:
                session.clear()
                flash('Your session has expired. Please log in again.', 'warning')
                return redirect(url_for('auth.login'))

        # Update last activity time
        session['last_activity'] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.error(f"Session management error: {e}")
        session.clear()
        return redirect(url_for('auth.login'))