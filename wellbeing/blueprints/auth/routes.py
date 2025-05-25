from datetime import datetime, timezone
import secrets
import os
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
    return redirect(url_for('auth.landing'))

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
            if user.get('status', 'Active') != 'active':
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
    
@auth_bp.route('/landing')
def landing():
    return render_template('landing.html')

def create_enhanced_therapist(data, password):
    """Create a new therapist account with enhanced data structure matching your system"""
    try:
        hashed_password = generate_password_hash(password)
        
        # Process specializations
        specializations = []
        if isinstance(data.get('specializations'), list):
            specializations = data['specializations']
        else:
            # Handle form data where specializations come as multiple values
            specializations = request.form.getlist('specializations') if hasattr(request, 'form') else []
        
        # Process availability schedule
        availability = {}
        available_days = data.get('available_days', [])
        if not isinstance(available_days, list):
            available_days = request.form.getlist('available_days') if hasattr(request, 'form') else []
        
        for day in available_days:
            start_time = data.get(f'{day}_start')
            end_time = data.get(f'{day}_end')
            if start_time and end_time:
                availability[day] = [f"{start_time}-{end_time}"]
        
        # Build therapist data matching your enhanced structure
        therapist_data = {
            'name': f"Dr. {data['first_name']} {data['last_name']}",
            'first_name': data['first_name'],
            'last_name': data['last_name'],
            'email': data['email'].lower(),
            'license_number': data['license_number'],
            'specializations': specializations,
            'bio': data.get('bio', ''),
            'availability': availability,
            'max_students': int(data.get('max_students', 20)),
            'current_students': 0,  # Start with 0
            'rating': 0.0,  # Will be calculated based on reviews
            'total_sessions': 0,  # Start with 0
            'status': 'active',
            'gender': data.get('gender', ''),
            'phone': data.get('phone', ''),
            'emergency_hours': data.get('emergency_hours') == 'true',
            'password': hashed_password,
            'role': 'therapist',
            'is_verified': True,  # Auto-verify in development
            'is_mock_data': os.getenv('FLASK_ENV') == 'development',
            'speciality_focus': ', '.join(specializations[:2]) if specializations else '',
            'created_at': datetime.now(timezone.utc),
            'last_login': None
        }
        
        # Add crisis specialist flag if applicable
        if 'crisis_intervention' in specializations:
            therapist_data['crisis_specialist'] = True
        
        result = mongo.db.therapists.insert_one(therapist_data)
        logger.info(f"Enhanced therapist created successfully: {data['email']}")
        return result.inserted_id
        
    except Exception as e:
        logger.error(f"Error creating enhanced therapist: {e}")
        raise

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    try:
        if request.method == 'POST':
            # Try getting JSON data first, otherwise get form data
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
                # Handle multiple values (specializations, available_days)
                data['specializations'] = request.form.getlist('specializations')
                data['available_days'] = request.form.getlist('available_days')
            
            # Extract and sanitize input fields
            role = data.get('role', '').strip().lower()
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            email = data.get('email', '').strip()
            password = data.get('password', '')
            confirm_password = data.get('confirm_password', '')
            
            # Validation checks
            errors = []
            
            if not role or role not in ['student', 'therapist']:
                errors.append('Please select a valid role.')
            if not first_name or not first_name.isalpha():
                errors.append('First name must contain only letters.')
            if not last_name or not last_name.isalpha():
                errors.append('Last name must contain only letters.')
            if not email or len(email) < 12:
                errors.append('Email must be at least 12 characters.')
            if not validate_email(email):
                errors.append('Invalid email format.')
            if not validate_password(password):
                errors.append('Password must be at least 8 characters with letters and numbers.')
            if password != confirm_password:
                errors.append('Passwords do not match.')
            
            # Role-specific validation and processing
            if role == 'student':
                student_id = data.get('student_id', '').strip()
                
                if not student_id or not student_id.isdigit():
                    errors.append('Student ID must contain only numbers.')
                
                # Check if student ID or email already exists
                if not errors:
                    if mongo.db.users.find_one({'student_id': student_id}):
                        errors.append('Student ID already exists')
                    if find_user_by_email(email):
                        errors.append('Email already exists')
                
                if not errors:
                    # Create student account
                    create_user(first_name, last_name, email, student_id, password)
                    return redirect(url_for('auth.login'))
                    
            elif role == 'therapist':
                license_number = data.get('license_number', '').strip()
                specializations = data.get('specializations', [])
                
                if not license_number:
                    errors.append('License number is required for therapists.')
                if not specializations or len(specializations) == 0:
                    errors.append('At least one specialization is required.')
                
                # Check for existing therapist email or license
                if not errors:
                    if mongo.db.therapists.find_one({'email': email.lower()}):
                        errors.append('Email already exists')
                    if mongo.db.therapists.find_one({'license_number': license_number}):
                        errors.append('License number already exists')
                
                if not errors:
                    # Create enhanced therapist account
                    create_enhanced_therapist(data, password)
                    return redirect(url_for('auth.login'))
            
            if errors:
                if request.is_json:
                    return jsonify({'errors': errors}), 400
                else:
                    # For form submissions, flash errors and reload page
                    for error in errors:
                        flash(error, 'error')
                    return render_template('register.html')
        
        # GET request - Render registration page
        return render_template('register.html')
    
    except Exception as e:
        logger.error(f"Registration error: {e}")
        if request.is_json:
            return jsonify({'error': 'An unexpected error occurred'}), 500
        else:
            flash('An unexpected error occurred. Please try again.', 'error')
            return render_template('register.html')

@auth_bp.route('/register/bulk-therapists', methods=['POST'])
def bulk_register_therapists():
    """Development-only endpoint for bulk therapist registration"""
    try:
        # Only allow in development environment
        if os.getenv('FLASK_ENV') != 'development':
            return jsonify({'error': 'This endpoint is only available in development'}), 403
        
        # Enhanced mock therapist data for Kenya matching your system structure
        mock_therapists = [
            {
                "name": "Dr. Grace Wanjiku",
                "first_name": "Grace",
                "last_name": "Wanjiku",
                "email": "grace.wanjiku@university.edu",
                "license_number": "KPCA001234",
                "specializations": ["anxiety", "depression", "cognitive_behavioral"],
                "bio": "Specializing in anxiety and depression with 8+ years of experience. I use evidence-based CBT techniques to help students develop practical coping skills and build resilience.",
                "availability": {
                    "monday": ["09:00-12:00", "14:00-17:00"],
                    "tuesday": ["10:00-16:00"],
                    "wednesday": ["09:00-12:00", "13:00-18:00"],
                    "thursday": ["08:00-15:00"],
                    "friday": ["09:00-14:00"]
                },
                "max_students": 25,
                "gender": "female",
                "phone": "+254712345678",
                "emergency_hours": True,
                "speciality_focus": "Anxiety and academic stress"
            },
            {
                "name": "Dr. Michael Kiprotich",
                "first_name": "Michael",
                "last_name": "Kiprotich",
                "email": "michael.kiprotich@university.edu",
                "license_number": "KPCA005678",
                "specializations": ["academic_stress", "anxiety", "stress_management"],
                "bio": "Academic stress specialist helping students navigate university pressures. I focus on mindfulness-based stress reduction and practical time management strategies.",
                "availability": {
                    "monday": ["11:00-18:00"],
                    "wednesday": ["09:00-17:00"],
                    "thursday": ["10:00-16:00"],
                    "friday": ["08:00-15:00"],
                    "saturday": ["10:00-14:00"]
                },
                "max_students": 20,
                "gender": "male",
                "phone": "+254723456789",
                "emergency_hours": False,
                "speciality_focus": "Study habits and test anxiety"
            },
            {
                "name": "Dr. Sarah Mwangi",
                "first_name": "Sarah",
                "last_name": "Mwangi",
                "email": "sarah.mwangi@university.edu",
                "license_number": "KPCA009876",
                "specializations": ["trauma_therapy", "ptsd", "grief_counseling"],
                "bio": "Trauma-informed therapy specialist with expertise in PTSD and grief counseling. I provide a safe, supportive environment for healing using EMDR and other evidence-based approaches.",
                "availability": {
                    "tuesday": ["09:00-18:00"],
                    "thursday": ["08:00-17:00"],
                    "friday": ["10:00-19:00"],
                    "saturday": ["09:00-15:00"]
                },
                "max_students": 15,
                "gender": "female",
                "phone": "+254734567890",
                "emergency_hours": True,
                "speciality_focus": "Complex trauma and PTSD recovery"
            },
            {
                "name": "Dr. James Kamau",
                "first_name": "James",
                "last_name": "Kamau",
                "email": "james.kamau@university.edu",
                "license_number": "KPCA012345",
                "specializations": ["substance_abuse", "addiction_counseling", "group_therapy"],
                "bio": "Addiction counselor with 12+ years helping students overcome substance use challenges. I offer both individual and group therapy with a non-judgmental, recovery-focused approach.",
                "availability": {
                    "monday": ["13:00-19:00"],
                    "tuesday": ["12:00-18:00"],
                    "wednesday": ["14:00-20:00"],
                    "thursday": ["13:00-17:00"],
                    "sunday": ["15:00-19:00"]
                },
                "max_students": 22,
                "gender": "male",
                "phone": "+254701234567",
                "emergency_hours": True,
                "speciality_focus": "Substance abuse and behavioral addictions"
            },
            {
                "name": "Dr. Amanda Torres",
                "first_name": "Amanda",
                "last_name": "Torres",
                "email": "amanda.torres@university.edu",
                "license_number": "KPCA055555",
                "specializations": ["crisis_intervention", "suicide_prevention", "emergency_therapy"],
                "bio": "Crisis intervention specialist available for urgent mental health situations. Trained in suicide prevention, crisis de-escalation, and emergency psychological support with immediate response capabilities.",
                "availability": {
                    "monday": ["08:00-20:00"],
                    "tuesday": ["08:00-20:00"],
                    "wednesday": ["08:00-20:00"],
                    "thursday": ["08:00-20:00"],
                    "friday": ["08:00-20:00"],
                    "saturday": ["10:00-18:00"],
                    "sunday": ["12:00-18:00"]
                },
                "max_students": 30,
                "gender": "female",
                "phone": "+254700000911",
                "emergency_hours": True,
                "crisis_specialist": True,
                "speciality_focus": "Emergency intervention and crisis stabilization"
            }
        ]
        
        created_therapists = []
        for therapist_data in mock_therapists:
            try:
                # Check if therapist already exists
                existing = mongo.db.therapists.find_one({
                    '$or': [
                        {'email': therapist_data['email']},
                        {'license_number': therapist_data['license_number']}
                    ]
                })
                
                if existing:
                    logger.info(f"Therapist {therapist_data['email']} already exists, skipping...")
                    continue
                
                # Add common fields
                therapist_data.update({
                    'current_students': 0,
                    'rating': 4.5 + (len(created_therapists) * 0.1),  # Vary ratings
                    'total_sessions': 0,
                    'status': 'active',
                    'role': 'therapist',
                    'password': generate_password_hash('Password123'),  # Default dev password
                    'is_verified': True,
                    'is_mock_data': True,
                    'created_at': datetime.now(timezone.utc),
                    'last_login': None
                })
                
                result = mongo.db.therapists.insert_one(therapist_data)
                created_therapists.append({
                    'id': str(result.inserted_id),
                    'name': therapist_data['name'],
                    'email': therapist_data['email']
                })
                
            except Exception as e:
                logger.error(f"Error creating therapist {therapist_data['email']}: {e}")
                continue
        
        return jsonify({
            'message': f'Successfully created {len(created_therapists)} therapists',
            'therapists': created_therapists
        }), 201
        
    except Exception as e:
        logger.error(f"Bulk therapist registration error: {e}")
        return jsonify({'error': 'Failed to create bulk therapists'}), 500

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