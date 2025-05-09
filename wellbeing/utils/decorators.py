from functools import wraps
from flask import session, redirect, url_for, flash, request, abort

def login_required(f):
    """
    Decorator to require login for a route.
    Redirects to login page if user is not logged in.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """
    Decorator to require admin role for a route.
    Returns 403 Forbidden if user is not an admin.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            flash('You do not have permission to access this page.', 'error')
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

def therapist_required(f):
    """
    Decorator to ensure the user is logged in as a therapist
    If not, redirects to login page
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('logged_in'):
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('auth.login'))
        
        if session.get('role') != 'therapist':
            flash('Access denied. This page is only for therapists.', 'error')
            
            if session.get('role') == 'admin':
                return redirect(url_for('admin.dashboard'))
            elif session.get('role') == 'student':
                return redirect(url_for('dashboard.index'))
            else:
                return redirect(url_for('auth.login'))
                
        return f(*args, **kwargs)
    return decorated_function

def csrf_protected(f):
    """
    Decorator to enforce CSRF token validation on POST requests.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'POST':
            if not verify_csrf_token():
                abort(403, description="CSRF token missing or invalid.")
        return f(*args, **kwargs)
    return decorated_function

def verify_csrf_token():
    token = request.headers.get('X-CSRF-Token')
    cookie_token = request.cookies.get('csrf_token')
    
    return token and cookie_token and token == cookie_token