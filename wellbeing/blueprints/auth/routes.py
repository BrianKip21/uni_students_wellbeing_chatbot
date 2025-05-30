from datetime import datetime, timezone, timedelta
import secrets
import os
import re
import logging
from flask import render_template, request, redirect, url_for, session, flash, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from wellbeing.blueprints.auth import auth_bp
from wellbeing.models.user import (
    find_user_by_email, create_user, update_user_login, find_user_by_student_id, find_user_by_id
)
from wellbeing import mongo, logger
from wellbeing.utils.validators import validate_email, validate_password
from wellbeing_modules import LicenseValidator, TestDataGenerator
from wellbeing.utils.email import send_password_reset_email

@auth_bp.route('/')
def index():
    return redirect(url_for('auth.landing'))

# =============================================================================
# LOGIN ROUTE - ENHANCED WITH ROLE-BASED REDIRECTION
# =============================================================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Enhanced login with better error handling and role-based redirection"""
    
    if request.method == 'POST':
        try:
            # Handle both JSON and form data
            if request.is_json:
                data = request.get_json()
                email = data.get('email', '').strip().lower()
                password = data.get('password', '')
                role = data.get('role', '')
            else:
                email = request.form.get('email', '').strip().lower()
                password = request.form.get('password', '')
                role = request.form.get('role', '')
            
            # Validate required fields
            if not all([email, password, role]):
                error_msg = 'All fields are required'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('login.html')
            
            # Validate email format
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                error_msg = 'Invalid email format'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('login.html')
            
            # Find user by email and role
            user = mongo.db.users.find_one({'email': email, 'role': role})
            
            if not user:
                error_msg = f'No {role} account found with this email'
                if request.is_json:
                    return jsonify({'error': error_msg}), 401
                flash(error_msg, 'error')
                return render_template('login.html')
            
            # Verify password
            if not check_password_hash(user['password'], password):
                error_msg = 'Invalid password'
                if request.is_json:
                    return jsonify({'error': error_msg}), 401
                flash(error_msg, 'error')
                return render_template('login.html')
            
            # Check account status
            if user.get('status') == 'inactive':
                error_msg = 'Account is inactive. Please contact support.'
                if request.is_json:
                    return jsonify({'error': error_msg}), 403
                flash(error_msg, 'error')
                return render_template('login.html')
            
            # Set session
            session['logged_in'] = True  # For existing system compatibility
            session['user_id'] = str(user['_id'])  # Alternative key used in some places
            session['user'] = str(user['_id'])  # New system key
            session['email'] = user['email']
            session['role'] = user['role']
            session['name'] = user.get('name', user['email'].split('@')[0])
            
            # Update last login
            mongo.db.users.update_one(
                {'_id': user['_id']},
                {'$set': {'last_login': datetime.now()}}
            )
            
            # Role-based redirection
            if role == 'admin':
                redirect_url = '/admin/dashboard'
            elif role == 'therapist':
                redirect_url = '/therapist/dashboard'
            else:  # student
                redirect_url = '/dashboard'
            
            if request.is_json:
                return jsonify({
                    'success': True,
                    'role': role,
                    'redirect_url': redirect_url,
                    'message': f'Welcome back, {session["name"]}!'
                })
            
            flash(f'Welcome back, {session["name"]}!', 'success')
            return redirect(redirect_url)
            
        except Exception as e:
            logging.error(f"Login error: {str(e)}")
            error_msg = 'Login failed. Please try again.'
            if request.is_json:
                return jsonify({'error': error_msg}), 500
            flash(error_msg, 'error')
            return render_template('login.html')
    
    return render_template('login.html')
    
@auth_bp.route('/landing')
def landing():
    return render_template('landing.html')

# =============================================================================
# FORGOT PASSWORD ROUTES
# =============================================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Handle forgot password requests"""
    
    if request.method == 'POST':
        try:
            from flask import current_app
            
            # Handle both JSON and form data
            if request.is_json:
                data = request.get_json()
                email = data.get('email', '').strip().lower()
            else:
                email = request.form.get('email', '').strip().lower()
            
            # Validate email
            if not email:
                error_msg = 'Email address is required'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('forgot_password.html')
            
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                error_msg = 'Invalid email format'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('forgot_password.html')
            
            # Find user by email
            user = mongo.db.users.find_one({'email': email})
            
            if not user:
                # Don't reveal if email exists or not for security
                success_msg = 'If an account with this email exists, a reset link has been sent.'
                if request.is_json:
                    return jsonify({'success': True, 'message': success_msg})
                flash(success_msg, 'success')
                return render_template('forgot_password.html')
            
            # Generate reset token
            reset_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + current_app.config['PASSWORD_RESET_TOKEN_EXPIRY']
            
            # Store reset token in database
            mongo.db.password_resets.delete_many({'email': email})  # Remove any existing tokens
            mongo.db.password_resets.insert_one({
                'email': email,
                'token': reset_token,
                'expires_at': expires_at,
                'created_at': datetime.now(timezone.utc)
            })
            
            # Send reset email
            try:
                success = send_password_reset_email(email, reset_token, user.get('name', email.split('@')[0]))
                if success:
                    success_msg = 'Password reset email sent! Check your inbox.'
                    if request.is_json:
                        return jsonify({'success': True, 'message': success_msg})
                    flash(success_msg, 'success')
                else:
                    raise Exception("Failed to send email")
            except Exception as e:
                logger.error(f"Failed to send reset email to {email}: {str(e)}")
                error_msg = 'Failed to send reset email. Please try again later.'
                if request.is_json:
                    return jsonify({'error': error_msg}), 500
                flash(error_msg, 'error')
            
            return render_template('forgot_password.html')
            
        except Exception as e:
            logging.error(f"Forgot password error: {str(e)}")
            error_msg = 'An error occurred. Please try again.'
            if request.is_json:
                return jsonify({'error': error_msg}), 500
            flash(error_msg, 'error')
            return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token=None):
    """Handle password reset with token"""
    
    if request.method == 'GET':
        # Display reset password form
        if not token:
            flash('Invalid reset link', 'error')
            return redirect(url_for('auth.forgot_password'))
        
        # Validate token
        reset_request = mongo.db.password_resets.find_one({
            'token': token,
            'expires_at': {'$gt': datetime.now(timezone.utc)}
        })
        
        if not reset_request:
            flash('Invalid or expired reset link', 'error')
            return redirect(url_for('auth.forgot_password'))
        
        return render_template('reset_password.html', token=token)
    
    if request.method == 'POST':
        try:
            # Handle both JSON and form data
            if request.is_json:
                data = request.get_json()
                password = data.get('password', '')
                confirm_password = data.get('confirm_password', '')
                token = data.get('token', '')
            else:
                password = request.form.get('password', '')
                confirm_password = request.form.get('confirm_password', '')
                token = request.form.get('token', '')
            
            # Validate input
            if not all([password, confirm_password, token]):
                error_msg = 'All fields are required'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            if password != confirm_password:
                error_msg = 'Passwords do not match'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            # Validate password strength
            if len(password) < 8:
                error_msg = 'Password must be at least 8 characters long'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            if not re.search(r'[A-Z]', password):
                error_msg = 'Password must contain at least one uppercase letter'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            if not re.search(r'[a-z]', password):
                error_msg = 'Password must contain at least one lowercase letter'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            if not re.search(r'[0-9]', password):
                error_msg = 'Password must contain at least one number'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            # Validate token
            reset_request = mongo.db.password_resets.find_one({
                'token': token,
                'expires_at': {'$gt': datetime.now(timezone.utc)}
            })
            
            if not reset_request:
                error_msg = 'Invalid or expired reset link'
                if request.is_json:
                    return jsonify({'error': error_msg}), 400
                flash(error_msg, 'error')
                return redirect(url_for('auth.forgot_password'))
            
            # Update user password
            hashed_password = generate_password_hash(password)
            result = mongo.db.users.update_one(
                {'email': reset_request['email']},
                {'$set': {'password': hashed_password, 'updated_at': datetime.now(timezone.utc)}}
            )
            
            if result.modified_count == 0:
                error_msg = 'Failed to update password'
                if request.is_json:
                    return jsonify({'error': error_msg}), 500
                flash(error_msg, 'error')
                return render_template('reset_password.html', token=token)
            
            # Delete the reset token
            mongo.db.password_resets.delete_one({'_id': reset_request['_id']})
            
            success_msg = 'Password reset successfully! You can now log in with your new password.'
            if request.is_json:
                return jsonify({'success': True, 'message': success_msg})
            
            flash(success_msg, 'success')
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            logging.error(f"Reset password error: {str(e)}")
            error_msg = 'An error occurred. Please try again.'
            if request.is_json:
                return jsonify({'error': error_msg}), 500
            flash(error_msg, 'error')
            return render_template('reset_password.html', token=token)

# =============================================================================
# REGISTER ROUTE - ENHANCED WITH LICENSE VALIDATION
# =============================================================================

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Enhanced registration with automated license validation"""
    
    if request.method == 'POST':
        try:
            # Get form data
            role = request.form.get('role', '').strip()
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Validate basic fields
            validation_errors = []
            
            if not all([role, first_name, last_name, email, password, confirm_password]):
                validation_errors.append('All fields are required')
            
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                validation_errors.append('Invalid email format')
            
            if len(password) < 8:
                validation_errors.append('Password must be at least 8 characters')
            
            if password != confirm_password:
                validation_errors.append('Passwords do not match')
            
            if not re.match(r'^[A-Za-z]+$', first_name):
                validation_errors.append('First name must contain only letters')
            
            if not re.match(r'^[A-Za-z]+$', last_name):
                validation_errors.append('Last name must contain only letters')
            
            # Check if email already exists
            existing_user = mongo.db.users.find_one({'email': email})
            if existing_user:
                validation_errors.append('Email already registered')
            
            # Role-specific validation
            if role == 'student':
                student_id = request.form.get('student_id', '').strip()
                if not student_id:
                    validation_errors.append('Student ID is required')
                elif not re.match(r'^\d+$', student_id):
                    validation_errors.append('Student ID must contain only numbers')
                
                # Check if student ID already exists
                existing_student = mongo.db.students.find_one({'student_id': student_id})
                if existing_student:
                    validation_errors.append('Student ID already registered')
            
            elif role == 'therapist':
                license_number = request.form.get('license_number', '').strip()
                
                if not license_number:
                    # Generate license for development
                    license_number = LicenseValidator.generate_license('kenya_clinical')
                    flash(f'🔧 Development mode: Generated license {license_number}', 'info')
                
                # Validate license
                license_validation = LicenseValidator.validate_license(license_number)
                if not license_validation['valid']:
                    validation_errors.append(f'Invalid license: {license_validation["error"]}')
                
                # Check if license already exists
                existing_therapist = mongo.db.therapists.find_one({'license_number': license_number})
                if existing_therapist:
                    validation_errors.append('License number already registered')
                
                # Validate specializations
                specializations = request.form.getlist('specializations')
                if not specializations:
                    validation_errors.append('At least one specialization is required')
            
            # Return errors if any
            if validation_errors:
                for error in validation_errors:
                    flash(error, 'error')
                return render_template('register.html')
            
            # Create user account
            user_data = {
                'email': email,
                'password': generate_password_hash(password),
                'role': role,
                'name': f"{first_name} {last_name}",
                'first_name': first_name,
                'last_name': last_name,
                'status': 'active',
                'created_at': datetime.now(),
                'last_login': None
            }
            
            # Insert user
            user_result = mongo.db.users.insert_one(user_data)
            user_id = user_result.inserted_id
            
            # Role-specific profile creation
            if role == 'student':
                student_data = {
                    '_id': user_id,
                    'student_id': student_id,
                    'name': f"{first_name} {last_name}",
                    'email': email,
                    'status': 'active',
                    'assigned_therapist_id': None,
                    'intake_completed': False,
                    'created_at': datetime.now(),
                    'progress': {
                        'meditation': 0,
                        'exercise': 0
                    }
                }
                mongo.db.students.insert_one(student_data)
                
                flash(f'✅ Student account created successfully! Welcome {first_name}!', 'success')
                
            elif role == 'therapist':
                # Process therapist-specific data
                therapist_data = {
                    '_id': user_id,
                    'name': f"{first_name} {last_name}",
                    'email': email,
                    'license_number': license_number,
                    'license_validation': license_validation,
                    'phone': request.form.get('phone', ''),
                    'gender': request.form.get('gender', ''),
                    'bio': request.form.get('bio', ''),
                    'specializations': specializations,
                    'max_students': int(request.form.get('max_students', 20)),
                    'current_students': 0,
                    'emergency_hours': bool(request.form.get('emergency_hours')),
                    'status': 'active',
                    'rating': 5.0,  # Start with perfect rating
                    'total_sessions': 0,
                    'years_experience': 0,
                    'created_at': datetime.now()
                }
                
                # Process availability
                availability = {}
                days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                available_days = request.form.getlist('available_days')
                
                for day in available_days:
                    if day in days:
                        start_time = request.form.get(f'{day}_start')
                        end_time = request.form.get(f'{day}_end')
                        if start_time and end_time:
                            availability[day] = {
                                'start': start_time,
                                'end': end_time
                            }
                
                therapist_data['availability'] = availability
                
                # Insert therapist
                mongo.db.therapists.insert_one(therapist_data)
                
                flash(f'✅ Therapist account created successfully! License: {license_number}', 'success')
            
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            logging.error(f"Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

# =============================================================================
# LOGOUT ROUTE
# =============================================================================

@auth_bp.route('/logout')
def logout():
    """Enhanced logout with proper session cleanup"""
    
    try:
        # Get user info before clearing session
        user_name = session.get('name', 'User')
        
        # Clear session
        session.clear()
        
        flash(f'👋 Goodbye, {user_name}! You have been logged out successfully.', 'info')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logging.error(f"Logout error: {str(e)}")
        session.clear()  # Clear session anyway
        return redirect(url_for('auth.login'))
    
# =============================================================================
# API ROUTES FOR DEVELOPMENT
# =============================================================================

@auth_bp.route('/api/generate-license/<license_type>')
def api_generate_license(license_type):
    """API endpoint to generate license for development"""
    
    try:
        license_number = LicenseValidator.generate_license(license_type)
        validation = LicenseValidator.validate_license(license_number)
        
        return jsonify({
            'success': True,
            'license_number': license_number,
            'validation': validation,
            'message': f'Generated {license_type} license'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@auth_bp.route('/api/validate-license', methods=['POST'])
def api_validate_license():
    """API endpoint to validate license number"""
    
    try:
        data = request.get_json()
        license_number = data.get('license_number', '').strip()
        
        if not license_number:
            return jsonify({
                'success': False,
                'error': 'License number is required'
            }), 400
        
        validation = LicenseValidator.validate_license(license_number)
        
        return jsonify({
            'success': True,
            'validation': validation
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@auth_bp.route('/api/check-email', methods=['POST'])
def api_check_email():
    """API endpoint to check if email is available"""
    
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({
                'success': False,
                'error': 'Email is required'
            }), 400
        
        existing_user = mongo.db.users.find_one({'email': email})
        
        return jsonify({
            'success': True,
            'available': existing_user is None,
            'message': 'Email available' if existing_user is None else 'Email already registered'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@auth_bp.route('/dev/create-test-accounts')
def create_test_accounts():
    """Create test accounts for development"""
    
    try:
        # Create test student
        student_data = {
            'email': 'student@test.com',
            'password': generate_password_hash('password123'),
            'role': 'student',
            'name': 'Test Student',
            'first_name': 'Test',
            'last_name': 'Student',
            'status': 'active',
            'created_at': datetime.now()
        }
        
        student_result = mongo.db.users.insert_one(student_data)
        
        # Create student profile
        student_profile = {
            '_id': student_result.inserted_id,
            'student_id': '2024001',
            'name': 'Test Student',
            'email': 'student@test.com',
            'status': 'active',
            'assigned_therapist_id': None,
            'intake_completed': False,
            'created_at': datetime.now()
        }
        mongo.db.students.insert_one(student_profile)
        
        # Create test therapist
        therapist_license = LicenseValidator.generate_license('kenya_clinical')
        therapist_data = {
            'email': 'therapist@test.com',
            'password': generate_password_hash('password123'),
            'role': 'therapist',
            'name': 'Dr. Test Therapist',
            'first_name': 'Dr. Test',
            'last_name': 'Therapist',
            'status': 'active',
            'created_at': datetime.now()
        }
        
        therapist_result = mongo.db.users.insert_one(therapist_data)
        
        # Create therapist profile
        therapist_profile = {
            '_id': therapist_result.inserted_id,
            'name': 'Dr. Test Therapist',
            'email': 'therapist@test.com',
            'license_number': therapist_license,
            'specializations': ['anxiety', 'depression'],
            'max_students': 25,
            'current_students': 0,
            'emergency_hours': True,
            'status': 'active',
            'rating': 5.0,
            'availability': {
                'monday': {'start': '09:00', 'end': '17:00'},
                'wednesday': {'start': '10:00', 'end': '18:00'},
                'friday': {'start': '08:00', 'end': '16:00'}
            },
            'created_at': datetime.now()
        }
        mongo.db.therapists.insert_one(therapist_profile)
        
        return jsonify({
            'success': True,
            'message': 'Test accounts created',
            'accounts': {
                'student': 'student@test.com / password123',
                'therapist': 'therapist@test.com / password123',
                'therapist_license': therapist_license
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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
        if request.endpoint in ['static', 'auth.login', 'auth.register', 'auth.forgot_password', 'auth.reset_password']:
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