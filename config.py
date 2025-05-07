import os
import secrets
from datetime import timedelta

class Config:
    """Base configuration class."""
    
    # Flask config
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(24))
    DEBUG = os.getenv("FLASK_DEBUG", "True") == "True"
    
    # MongoDB config
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/wellbeing_db")
    
    # Session config
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    
    # File upload config
    UPLOAD_FOLDER = 'static/uploads/videos'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload

    SMTP_SERVER = 'smtp.gmail.com'  # Replace with your SMTP server
    SMTP_PORT = 587  # Common ports: 587 for TLS, 465 for SSL
    SMTP_USERNAME = 'CHATBOT'  # Your SMTP username
    SMTP_PASSWORD = 'zbnb hcnm karj ioyn'  # Your SMTP password
    SENDER_EMAIL = 'toobrian2003@gmail.com'  # The "from" address for emails
    SITE_URL = 'https://127.0.0.1:5001'  # Your application's URL

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False