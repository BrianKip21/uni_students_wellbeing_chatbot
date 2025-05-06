import re

def validate_email(email):
    """
    Validate email format.
    
    Args:
        email (str): Email address to validate
        
    Returns:
        bool: True if email is valid, False otherwise
    """
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def validate_password(password):
    """
    Validate password complexity.
    At least 8 characters, one uppercase, one lowercase, one number.
    
    Args:
        password (str): Password to validate
        
    Returns:
        bool: True if password meets requirements, False otherwise
    """
    # At least 8 characters, one uppercase, one lowercase, one number
    return (len(password) >= 8 and 
            any(c.isupper() for c in password) and 
            any(c.islower() for c in password) and 
            any(c.isdigit() for c in password))

def validate_student_id(student_id):
    """
    Validate student ID format (numeric only).
    
    Args:
        student_id (str): Student ID to validate
        
    Returns:
        bool: True if student ID is valid, False otherwise
    """
    return student_id.isdigit()

def validate_name(name):
    """
    Validate name (alphabetic characters only).
    
    Args:
        name (str): Name to validate
        
    Returns:
        bool: True if name is valid, False otherwise
    """
    return name.isalpha()