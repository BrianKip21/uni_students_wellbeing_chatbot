import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, url_for
from wellbeing import logger

def send_email(recipient_email, subject, body_text=None, body_html=None):
    """
    Send an email using SMTP configuration from app config
    
    Args:
        recipient_email (str): Email address of the recipient
        subject (str): Subject of the email
        body_text (str, optional): Plain text body of the email
        body_html (str, optional): HTML body of the email
        
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
        message = MIMEMultipart('alternative')
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        
        # Add plain text body if provided
        if body_text:
            text_part = MIMEText(body_text, "plain")
            message.attach(text_part)
        
        # Add HTML body if provided
        if body_html:
            html_part = MIMEText(body_html, "html")
            message.attach(html_part)
        
        # If neither body is provided, use empty text
        if not body_text and not body_html:
            message.attach(MIMEText("", "plain"))
        
        # Connect to SMTP server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        
        logger.info(f"Email sent successfully to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_email}: {e}")
        return False

def send_password_reset_email(email, token, name):
    """
    Send secure password reset email with token-based reset link
    
    Args:
        email (str): User's email address
        token (str): Secure reset token
        name (str): User's name
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        # Get app configuration
        app_name = current_app.config.get('APP_NAME', 'Wellbeing Assistant')
        support_email = current_app.config.get('SUPPORT_EMAIL')
        
        # Create reset URL
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        
        # Create email content
        subject = f"Reset Your {app_name} Password"
        
        # HTML email content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Password Reset</title>
        </head>
        <body style="font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #8b5cf6, #3b82f6); padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
                <h1 style="color: white; margin: 0; font-size: 28px;">🧠 {app_name}</h1>
                <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 16px;">Password Reset Request</p>
            </div>
            
            <div style="background: #f8fafc; padding: 30px; border-radius: 10px; border-left: 4px solid #8b5cf6;">
                <h2 style="color: #2d3748; margin-top: 0;">Hello {name}! 👋</h2>
                
                <p style="font-size: 16px; margin-bottom: 20px;">
                    We received a request to reset your password for your {app_name} account. 
                    If you made this request, please click the button below to reset your password.
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" 
                       style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); 
                              color: white; 
                              padding: 15px 30px; 
                              text-decoration: none; 
                              border-radius: 8px; 
                              font-weight: 600; 
                              font-size: 16px; 
                              display: inline-block;
                              transition: transform 0.2s ease;">
                        🔐 Reset Password
                    </a>
                </div>
                
                <div style="background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px;">
                        <strong>⚠️ Important:</strong> This link will expire in 30 minutes for security reasons. 
                        If you don't reset your password within this time, you'll need to request a new reset link.
                    </p>
                </div>
                
                <p style="font-size: 14px; color: #666; margin-top: 20px;">
                    If the button doesn't work, copy and paste this link into your browser:<br>
                    <a href="{reset_url}" style="color: #8b5cf6; word-break: break-all;">{reset_url}</a>
                </p>
                
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                
                <p style="font-size: 14px; color: #666;">
                    <strong>Didn't request this?</strong> If you didn't request a password reset, 
                    you can safely ignore this email. Your password will remain unchanged.
                    {f'For support, contact us at {support_email}.' if support_email else ''}
                </p>
                
                <p style="font-size: 14px; color: #666; margin-bottom: 0;">
                    Best regards,<br>
                    <strong>The {app_name} Team</strong> 🌟
                </p>
            </div>
            
            <div style="text-align: center; margin-top: 30px; padding: 20px; color: #666; font-size: 12px;">
                <p style="margin: 0;">
                    This email was sent from an automated system. Please do not reply to this email.
                </p>
            </div>
        </body>
        </html>
        """
        
        # Plain text fallback
        text_content = f"""
        Hello {name}!
        
        We received a request to reset your password for your {app_name} account.
        
        If you made this request, please visit the following link to reset your password:
        {reset_url}
        
        This link will expire in 30 minutes for security reasons.
        
        If you didn't request this password reset, you can safely ignore this email.
        {f'For support, contact us at {support_email}.' if support_email else ''}
        
        Best regards,
        The {app_name} Team
        """
        
        # Send email with both HTML and text
        return send_email(email, subject, text_content, html_content)
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {str(e)}")
        return False

def send_therapist_credentials(email, first_name, last_name, temp_password):
    """
    Send therapist credentials email (for admin-created accounts)
    
    Args:
        email (str): Therapist's email address
        first_name (str): Therapist's first name
        last_name (str): Therapist's last name
        temp_password (str): Temporary password
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    app_name = current_app.config.get('APP_NAME', 'Wellbeing Assistant')
    site_url = current_app.config.get('SITE_URL', 'our website')
    
    subject = f"Your {app_name} Therapist Account"
    
    # HTML email content
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Account Created</title>
    </head>
    <body style="font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #8b5cf6, #3b82f6); padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
            <h1 style="color: white; margin: 0; font-size: 28px;">🧠 {app_name}</h1>
            <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 16px;">Welcome to Our Platform</p>
        </div>
        
        <div style="background: #f8fafc; padding: 30px; border-radius: 10px; border-left: 4px solid #8b5cf6;">
            <h2 style="color: #2d3748; margin-top: 0;">Welcome, Dr. {first_name} {last_name}! 👋</h2>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                An account has been created for you on the {app_name} platform. 
                You can now access the therapist dashboard and manage your patients.
            </p>
            
            <div style="background: #e0f2fe; border: 1px solid #4fc3f7; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #0277bd;">🔑 Your Login Credentials</h3>
                <p style="margin: 10px 0;"><strong>Email:</strong> {email}</p>
                <p style="margin: 10px 0;"><strong>Temporary Password:</strong> <code style="background: #f5f5f5; padding: 2px 8px; border-radius: 4px; font-family: monospace;">{temp_password}</code></p>
            </div>
            
            <div style="background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; font-size: 14px;">
                    <strong>⚠️ Important:</strong> Please change your password immediately after logging in for security reasons.
                </p>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{site_url}/login" 
                   style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); 
                          color: white; 
                          padding: 15px 30px; 
                          text-decoration: none; 
                          border-radius: 8px; 
                          font-weight: 600; 
                          font-size: 16px; 
                          display: inline-block;">
                    🚀 Login to Your Account
                </a>
            </div>
            
            <p style="font-size: 14px; color: #666; margin-bottom: 0;">
                Best regards,<br>
                <strong>The {app_name} Team</strong> 🌟
            </p>
        </div>
    </body>
    </html>
    """
    
    # Plain text fallback
    text_content = f"""
    Hello Dr. {first_name} {last_name},
    
    An account has been created for you on the {app_name} platform.
    
    Your login details are:
    Email: {email}
    Temporary Password: {temp_password}
    
    Please log in at {site_url}/login and change your password as soon as possible.
    
    Thank you,
    {app_name} Team
    """
    
    return send_email(email, subject, text_content, html_content)

def send_welcome_email(email, name, role):
    """
    Send welcome email to new users
    
    Args:
        email (str): User's email address
        name (str): User's name
        role (str): User's role (student, therapist, admin)
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    app_name = current_app.config.get('APP_NAME', 'Wellbeing Assistant')
    site_url = current_app.config.get('SITE_URL', 'our website')
    
    role_emoji = {'student': '🎓', 'therapist': '👨‍⚕️', 'admin': '👑'}.get(role, '👤')
    
    subject = f"Welcome to {app_name}!"
    
    # HTML email content
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Welcome</title>
    </head>
    <body style="font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #8b5cf6, #3b82f6); padding: 30px; border-radius: 10px; text-align: center; margin-bottom: 30px;">
            <h1 style="color: white; margin: 0; font-size: 28px;">🧠 {app_name}</h1>
            <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 16px;">Welcome to the Platform</p>
        </div>
        
        <div style="background: #f8fafc; padding: 30px; border-radius: 10px; border-left: 4px solid #8b5cf6;">
            <h2 style="color: #2d3748; margin-top: 0;">Welcome, {name}! {role_emoji}</h2>
            
            <p style="font-size: 16px; margin-bottom: 20px;">
                Thank you for joining {app_name}! Your account has been successfully created 
                and you're ready to get started.
            </p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{site_url}/login" 
                   style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); 
                          color: white; 
                          padding: 15px 30px; 
                          text-decoration: none; 
                          border-radius: 8px; 
                          font-weight: 600; 
                          font-size: 16px; 
                          display: inline-block;">
                    🚀 Get Started
                </a>
            </div>
            
            <p style="font-size: 14px; color: #666; margin-bottom: 0;">
                Best regards,<br>
                <strong>The {app_name} Team</strong> 🌟
            </p>
        </div>
    </body>
    </html>
    """
    
    # Plain text fallback
    text_content = f"""
    Welcome, {name}!
    
    Thank you for joining {app_name}! Your account has been successfully created 
    and you're ready to get started.
    
    Login at: {site_url}/login
    
    Best regards,
    The {app_name} Team
    """
    
    return send_email(email, subject, text_content, html_content)

# Legacy function - deprecated, use send_password_reset_email instead
def send_password_reset(email, first_name, last_name, new_password):
    """
    DEPRECATED: Send password reset email with new temporary password
    
    This function is deprecated in favor of secure token-based password reset.
    Use send_password_reset_email() instead.
    
    Args:
        email (str): Therapist's email address
        first_name (str): Therapist's first name
        last_name (str): Therapist's last name
        new_password (str): New temporary password
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    logger.warning("send_password_reset() is deprecated. Use send_password_reset_email() instead.")
    
    app_name = current_app.config.get('APP_NAME', 'Wellbeing Assistant')
    site_url = current_app.config.get('SITE_URL', 'our website')
    
    subject = f"Your {app_name} Password Has Been Reset"
    
    body = f"""
    Hello Dr. {first_name} {last_name},
    
    Your password for the {app_name} platform has been reset.
    
    Your new temporary password is: {new_password}
    
    Please log in at {site_url}/login and change your password as soon as possible.
    
    Thank you,
    {app_name} Team
    """
    
    return send_email(email, subject, body)