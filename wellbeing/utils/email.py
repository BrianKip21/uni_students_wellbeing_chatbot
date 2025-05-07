import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from wellbeing import logger

def send_email(recipient_email, subject, body):
    """
    Send an email using SMTP configuration from app config
    
    Args:
        recipient_email (str): Email address of the recipient
        subject (str): Subject of the email
        body (str): Body text of the email (plain text)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        # Get email configuration from app config
        smtp_server = current_app.config.get('SMTP_SERVER')
        smtp_port = current_app.config.get('SMTP_PORT')
        smtp_username = current_app.config.get('SMTP_USERNAME')
        smtp_password = current_app.config.get('SMTP_PASSWORD')
        sender_email = current_app.config.get('SENDER_EMAIL')
        
        # Check if email configuration is set
        if not all([smtp_server, smtp_port, smtp_username, smtp_password, sender_email]):
            logger.error("Email configuration is incomplete. Cannot send email.")
            return False
        
        # Create a multipart message
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        
        # Add body to email
        message.attach(MIMEText(body, "plain"))
        
        # Connect to SMTP server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        
        logger.info(f"Email sent successfully to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def send_therapist_credentials(email, first_name, last_name, temp_password):
    """
    Send therapist credentials email
    
    Args:
        email (str): Therapist's email address
        first_name (str): Therapist's first name
        last_name (str): Therapist's last name
        temp_password (str): Temporary password
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = "Your Therapist Account for Wellbeing Assistant"
    
    body = f"""
    Hello Dr. {first_name} {last_name},
    
    An account has been created for you on the Wellbeing Assistant platform.
    
    Your login details are:
    Email: {email}
    Temporary Password: {temp_password}
    
    Please log in at {current_app.config.get('SITE_URL', 'our website')} and change your password as soon as possible.
    
    Thank you,
    Wellbeing Assistant Team
    """
    
    return send_email(email, subject, body)

def send_password_reset(email, first_name, last_name, new_password):
    """
    Send password reset email
    
    Args:
        email (str): Therapist's email address
        first_name (str): Therapist's first name
        last_name (str): Therapist's last name
        new_password (str): New temporary password
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = "Your Wellbeing Assistant Password Has Been Reset"
    
    body = f"""
    Hello Dr. {first_name} {last_name},
    
    Your password for the Wellbeing Assistant platform has been reset.
    
    Your new temporary password is: {new_password}
    
    Please log in at {current_app.config.get('SITE_URL', 'our website')} and change your password as soon as possible.
    
    Thank you,
    Wellbeing Assistant Team
    """
    
    return send_email(email, subject, body)