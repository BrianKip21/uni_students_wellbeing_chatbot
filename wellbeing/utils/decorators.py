from functools import wraps
from flask import session, redirect, url_for, flash, request, abort, jsonify, current_app
import logging

def login_required(f):
    """
    Decorator to require login for a route.
    Redirects to login page if user is not logged in for regular routes.
    Returns JSON response for API routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Log for debugging
        logging.info(f"login_required check for {request.path}, method: {request.method}")
        logging.info(f"Session contains user: {('user' in session)}")
        
        if 'user' not in session:
            # Check if this is an API request
            if request.path.startswith('/api/'):
                logging.warning(f"Authentication failed for API route: {request.path}")
                return jsonify({
                    'success': False,
                    'message': 'Authentication required',
                    'code': 'auth_required'
                }), 401
            
            logging.info(f"Redirecting unauthenticated user to login from: {request.path}")
            return redirect(url_for('auth.login', next=request.url))
        
        logging.info(f"User authenticated for: {request.path}")
        return f(*args, **kwargs)
    
    return decorated_function


def admin_required(f):
    """
    Decorator to require admin role for a route.
    Returns 403 Forbidden if user is not an admin.
    Returns JSON response for API routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Log for debugging
        logging.info(f"admin_required check for {request.path}, method: {request.method}")
        logging.info(f"Session contains user: {('user' in session)}")
        logging.info(f"User role: {session.get('role')}")
        
        if 'user' not in session:
            # Check if this is an API request
            if request.path.startswith('/api/'):
                logging.warning(f"Authentication failed for API route: {request.path}")
                return jsonify({
                    'success': False,
                    'message': 'Authentication required',
                    'code': 'auth_required'
                }), 401
            
            logging.info(f"Redirecting unauthenticated user to login from: {request.path}")
            return redirect(url_for('auth.login', next=request.url))
            
        if session.get('role') != 'admin':
            # Check if this is an API request
            if request.path.startswith('/api/'):
                logging.warning(f"Admin access denied for API route: {request.path}")
                return jsonify({
                    'success': False,
                    'message': 'Admin access required',
                    'code': 'admin_required'
                }), 403
            
            logging.warning(f"Admin access denied for route: {request.path}")
            flash('You do not have permission to access this page.', 'error')
            return abort(403)
            
        logging.info(f"Admin access granted for: {request.path}")
        return f(*args, **kwargs)
    
    return decorated_function


def therapist_required(f):
    """
    Decorator to ensure the user is logged in as a therapist
    If not, redirects to login page
    Returns JSON response for API routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Log for debugging
        logging.info(f"therapist_required check for {request.path}, method: {request.method}")
        logging.info(f"Session logged_in: {session.get('logged_in')}")
        logging.info(f"User role: {session.get('role')}")
        
        if 'logged_in' not in session or not session.get('logged_in'):
            # Check if this is an API request
            if request.path.startswith('/api/'):
                logging.warning(f"Authentication failed for API route: {request.path}")
                return jsonify({
                    'success': False,
                    'message': 'Authentication required',
                    'code': 'auth_required'
                }), 401
                
            logging.info(f"Redirecting unauthenticated user to login from: {request.path}")
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
                 
        if session.get('role') != 'therapist':
            # Check if this is an API request
            if request.path.startswith('/api/'):
                logging.warning(f"Therapist access denied for API route: {request.path}")
                return jsonify({
                    'success': False,
                    'message': 'Therapist access required',
                    'code': 'therapist_required'
                }), 403
                
            logging.warning(f"Therapist access denied for route: {request.path}")
            flash('Access denied. This page is only for therapists.', 'error')
                         
            if session.get('role') == 'admin':
                return redirect(url_for('admin.dashboard'))
            elif session.get('role') == 'student':
                return redirect(url_for('dashboard.index'))
            else:
                return redirect(url_for('auth.login'))
        
        logging.info(f"Therapist access granted for: {request.path}")
        return f(*args, **kwargs)
    
    return decorated_function


def csrf_protected(f):
    """
    Decorator to enforce CSRF token validation on POST, PUT, DELETE requests.
    Returns JSON response for API routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Log for debugging
        logging.info(f"csrf_protected check for {request.path}, method: {request.method}")
        
        # Check CSRF for all methods that may modify data
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            token = request.headers.get('X-CSRF-Token')
            cookie_token = request.cookies.get('csrf_token')
            
            logging.info(f"CSRF header token present: {token is not None}")
            logging.info(f"CSRF cookie token present: {cookie_token is not None}")
            logging.info(f"CSRF tokens match: {token == cookie_token if token and cookie_token else False}")
            
            if not verify_csrf_token():
                # Check if this is an API request
                if request.path.startswith('/api/'):
                    logging.warning(f"CSRF validation failed for API route: {request.path}")
                    return jsonify({
                        'success': False,
                        'message': 'CSRF token missing or invalid',
                        'code': 'csrf_failed'
                    }), 403
                
                logging.warning(f"CSRF validation failed for route: {request.path}")
                abort(403, description="CSRF token missing or invalid.")
            
            logging.info(f"CSRF validation passed for: {request.path}")
        
        return f(*args, **kwargs)
    
    return decorated_function


def verify_csrf_token():
    """
    Verify the CSRF token from headers against the one in cookies.
    """
    token = request.headers.get('X-CSRF-Token')
    cookie_token = request.cookies.get('csrf_token')
    
    # Try to get token from form data as fallback
    if not token and request.form:
        token = request.form.get('csrf_token')
    
    # Try to get token from JSON data as fallback
    if not token and request.is_json:
        token = request.json.get('csrf_token')
         
    return token and cookie_token and token == cookie_token


def api_error_handler(f):
    """
    Decorator to catch exceptions in API routes and return JSON errors
    instead of HTML error pages.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logging.exception(f"API error in {request.path}: {str(e)}")
            
            # Get appropriate status code
            status_code = 500
            if hasattr(e, 'code'):
                status_code = e.code
            
            return jsonify({
                'success': False,
                'message': str(e),
                'code': 'server_error'
            }), status_code
    
    return decorated_function